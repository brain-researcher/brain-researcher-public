"""
Global pytest configuration and fixtures for Brain Researcher integration tests.

Provides common fixtures for service connections, mock data, and test utilities
across all integration test modules.
"""

import asyncio
import inspect
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import httpx
import numpy as np
import pytest
import pytest_asyncio
import redis.asyncio as redis_asyncio

# Explicitly ignore problematic integration test that pulls MNE/numba and
# crashes collection in unit-only runs.
collect_ignore = globals().get("collect_ignore", [])
collect_ignore_glob = globals().get("collect_ignore_glob", [])
collect_ignore_glob.append("*test_advanced_tools.py*")
_adv_tools = Path(__file__).parent / "integration" / "test_advanced_tools.py"
if _adv_tools.exists():
    collect_ignore.append(str(_adv_tools))

# Ensure this repo root wins over any installed brain_researcher package.
# This must happen before importing brain_researcher modules below.
ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# Ensure TMPDIR exists and is writable. Some environments in CI/sandboxes have a
# non-writable system temp dir; tests also pass --basetemp which may clear dirs.
def _ensure_tmpdir() -> Path:
    candidate = os.environ.get("TMPDIR")
    if candidate:
        path = Path(candidate)
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            pass

    fallback = ROOT / ".pytest_tmp" / "tmp"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(fallback)
    return fallback


_ensure_tmpdir()

# Work around anyio.start_blocking_portal hanging in this environment by
# providing a minimal portal implementation for TestClient.
try:
    import anyio.from_thread as _anyio_from_thread
except Exception:
    _anyio_from_thread = None  # pragma: no cover

if _anyio_from_thread is not None:

    class _InlinePortal:
        @staticmethod
        def _run_awaitable(awaitable):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(awaitable)

            result_box = {}
            error_box = {}

            def _runner():
                try:
                    result_box["value"] = asyncio.run(awaitable)
                except Exception as exc:
                    error_box["exc"] = exc

            thread = threading.Thread(target=_runner)
            thread.start()
            thread.join()
            if error_box:
                raise error_box["exc"]
            return result_box.get("value")

        def call(self, func, *args, **kwargs):
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                return self._run_awaitable(result)
            return result

        def start_task_soon(self, func, *args, name=None):
            future: Future = Future()
            try:
                result = func(*args)
                if inspect.isawaitable(result):
                    result = self._run_awaitable(result)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            return future

        def stop(self, cancel_remaining: bool = False) -> None:
            return None

    @contextmanager
    def _patched_start_blocking_portal(*args, **kwargs):
        portal = _InlinePortal()
        yield portal

    _anyio_from_thread.start_blocking_portal = _patched_start_blocking_portal

    try:
        import starlette.testclient as _starlette_testclient
    except Exception:
        _starlette_testclient = None

    if _starlette_testclient is not None:

        async def _noop_lifespan(self):
            return None

        async def _noop_wait_startup(self):
            return None

        async def _noop_wait_shutdown(self):
            return None

        _starlette_testclient.TestClient.lifespan = _noop_lifespan
        _starlette_testclient.TestClient.wait_startup = _noop_wait_startup
        _starlette_testclient.TestClient.wait_shutdown = _noop_wait_shutdown


# Test configuration
os.environ.setdefault("TOOL_DISCOVERY_MODE", "light")
os.environ.setdefault("NUMBA_DISABLE_JIT", "1")
joblib_temp = Path(tempfile.gettempdir()) / "brain_researcher_joblib"
joblib_temp.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("JOBLIB_TEMP_FOLDER", str(joblib_temp))
os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")

from brain_researcher.services.tools.dl_pytorch_tool import DLPyTorchTools
from brain_researcher.services.tools.gnn_connectivity_tool import GNNConnectivityTools
from brain_researcher.services.tools.multimodal_integration_tool import (
    MultimodalIntegrationTools,
)

TEST_CONFIG = {
    "services": {
        "br_kg": {"host": "localhost", "port": 5000, "timeout": 30.0},
        "orchestrator": {"host": "localhost", "port": 3001, "timeout": 30.0},
        "agent": {"host": "localhost", "port": 8000, "timeout": 60.0},
        "web_ui": {"host": "localhost", "port": 3000, "timeout": 10.0},
    },
    "redis": {
        "url": os.getenv("REDIS_URL", "redis://localhost:6379"),
        "use_fake": os.getenv("USE_FAKE_REDIS", "true").lower() == "true",
    },
    "demo_timeouts": {"short": 30, "medium": 120, "long": 300},
    "max_concurrent_demos": 5,
    "test_data_dir": Path(__file__).parent / "fixtures",
}


# Pytest markers for test categorization
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session", autouse=True)
def _ensure_tmpdir_exists():
    """Re-create TMPDIR after pytest basetemp cleanup."""
    _ensure_tmpdir()
    return None


@pytest.fixture
def coding_workflow_test_routes():
    """Register test-only coding workflow endpoints on the enhanced orchestrator app."""
    from fastapi import APIRouter, Body, HTTPException
    from pydantic import BaseModel

    from brain_researcher.services.orchestrator import coding_agent, main_enhanced
    from brain_researcher.services.orchestrator.models import (
        ErrorCode,
        ErrorResponse,
        JobStatus,
        JobStep,
        StepStatus,
    )

    app = main_enhanced.app
    if getattr(app.state, "_test_coding_routes", False):
        return app

    router = APIRouter()

    class CodePatchRequest(BaseModel):
        patch: Optional[str] = None
        description: Optional[str] = None

    class CodeTestRequest(BaseModel):
        targets: Optional[List[str]] = None
        marker: Optional[str] = None
        extra_args: Optional[List[str]] = None

    def _repo_root() -> Path:
        return Path(os.environ.get("WORKSPACE_ROOT", Path.cwd()))

    def _truncate(text: Optional[str], limit: int = 2000) -> Optional[str]:
        if text is None:
            return None
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    @router.post("/jobs/{job_id}/apply_patch")
    async def apply_patch(
        job_id: str, request: CodePatchRequest | None = Body(default=None)
    ):
        if job_id not in main_enhanced.jobs_db:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse.create(
                    ErrorCode.NOT_FOUND, "Job not found"
                ).model_dump(),
            )

        patch_text = request.patch if request else None
        if not patch_text:
            raise HTTPException(status_code=400, detail="No patch provided or pending")

        result = await coding_agent.run_in_executor(
            coding_agent.apply_patch,
            patch_text,
            _repo_root(),
        )
        if not result.get("applied"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error") or "Patch application failed",
            )

        job = main_enhanced.jobs_db[job_id]
        step = JobStep(
            id=f"step_coding_patch_{main_enhanced.uuid.uuid4().hex[:8]}",
            name="Apply patch",
            tool="coding.patch.apply",
            status=StepStatus.COMPLETED,
            preview=result.get("summary"),
            args={
                "stdout": _truncate(result.get("stdout")),
                "stderr": _truncate(result.get("stderr")),
            },
        )
        job.steps.append(step)
        job.status = JobStatus.RUNNING
        await main_enhanced.notify_job_update(
            job_id, {"type": "step", "step": step.model_dump()}
        )
        await main_enhanced.notify_job_update(
            job_id, {"type": "status", "status": job.status}
        )
        await main_enhanced.EnhancedJobManager._sync_job_in_store(job)
        return result

    @router.post("/jobs/{job_id}/run_tests")
    async def run_tests(job_id: str, request: CodeTestRequest):
        if job_id not in main_enhanced.jobs_db:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse.create(
                    ErrorCode.NOT_FOUND, "Job not found"
                ).model_dump(),
            )

        result = await coding_agent.run_in_executor(
            coding_agent.run_tests,
            request.targets,
            request.marker,
            request.extra_args,
            _repo_root(),
        )

        success = result.get("returncode") == 0
        job = main_enhanced.jobs_db[job_id]
        step = JobStep(
            id=f"step_coding_tests_{main_enhanced.uuid.uuid4().hex[:8]}",
            name="Run tests",
            tool="coding.tests.pytest",
            status=StepStatus.COMPLETED if success else StepStatus.FAILED,
            preview=f"{result.get('command')} -> {result.get('returncode')}",
            args={
                "stdout": _truncate(result.get("stdout")),
                "stderr": _truncate(result.get("stderr")),
            },
        )
        job.steps.append(step)

        if success:
            job.status = JobStatus.COMPLETED
            job.error = None
        else:
            job.status = JobStatus.FAILED
            job.error = ErrorResponse.create(ErrorCode.PROCESSING_ERROR, "Tests failed")

        await main_enhanced.notify_job_update(
            job_id, {"type": "step", "step": step.model_dump()}
        )
        await main_enhanced.notify_job_update(
            job_id, {"type": "status", "status": job.status}
        )
        await main_enhanced.EnhancedJobManager._sync_job_in_store(job)
        return result

    app.include_router(router)
    app.state._test_coding_routes = True
    return app


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def http_session() -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client session for all tests."""
    timeout = httpx.Timeout(30.0, read=60.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def redis_session():
    """Redis client session for caching tests."""
    if TEST_CONFIG["redis"]["use_fake"]:
        # Use fake redis for testing
        client = fakeredis.aioredis.FakeRedis()
    else:
        try:
            # Try to connect to real Redis
            client = redis_asyncio.from_url(TEST_CONFIG["redis"]["url"])
            # Test connection
            await client.ping()
        except Exception:
            # Fall back to fake redis
            client = fakeredis.aioredis.FakeRedis()

    yield client

    try:
        if hasattr(client, "aclose"):
            await client.aclose()
        elif hasattr(client, "close"):
            maybe_coro = client.close()
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
    except Exception:
        pass


@pytest.fixture
def service_urls():
    """Service URLs for testing."""
    services = TEST_CONFIG["services"]
    return {
        name: f"http://{config['host']}:{config['port']}"
        for name, config in services.items()
    }


@pytest_asyncio.fixture
async def check_service_health(http_session, service_urls):
    """Check if services are running and healthy."""

    async def _check_health(service_name: str) -> bool:
        if service_name not in service_urls:
            return False

        url = f"{service_urls[service_name]}/health"
        try:
            response = await http_session.get(url, timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    return _check_health


@pytest.fixture
def mock_demo_data():
    """Mock demo data for testing."""
    return {
        "scenarios": [
            {
                "id": "glm_motor_task",
                "name": "Motor Task GLM Analysis",
                "title": "First-Level GLM Analysis: Motor Cortex Activation",
                "description": "Demonstrates statistical analysis of fMRI data during finger-tapping task",
                "type": "glm_motor_task",
                "complexity": "beginner",
                "duration": 85,
                "estimated_real_duration": "8-12 minutes",
                "tags": ["fMRI", "GLM", "Motor", "FSL", "Statistics", "Beginner"],
                "popularity": 5,
                "thumbnail": "/demo/thumbnails/glm_motor_card.png",
            },
            {
                "id": "connectivity_dmn",
                "name": "Default Mode Network Connectivity",
                "title": "Resting-State Connectivity Analysis: Default Mode Network",
                "description": "Investigates functional connectivity within the default mode network",
                "type": "connectivity_dmn",
                "complexity": "intermediate",
                "duration": 120,
                "estimated_real_duration": "15-20 minutes",
                "tags": ["Resting State", "Connectivity", "DMN", "Networks"],
                "popularity": 4,
                "thumbnail": "/demo/thumbnails/connectivity_dmn_card.png",
            },
        ],
        "artifacts": {
            "glm_motor_task": [
                {
                    "id": "zstat_map",
                    "name": "zstat1.nii.gz",
                    "type": "brain_map",
                    "size_bytes": 2847392,
                    "url": "/api/demo/artifacts/glm_motor/zstat1.nii.gz",
                    "meta": {"threshold": 3.1, "max_z": 8.42},
                },
                {
                    "id": "design_matrix",
                    "name": "design_matrix.png",
                    "type": "image",
                    "size_bytes": 156432,
                    "url": "/api/demo/artifacts/glm_motor/design_matrix.png",
                    "meta": {"format": "PNG", "dimensions": [800, 600]},
                },
            ]
        },
        "visualizations": {
            "glm_motor_task": [
                {
                    "id": "motor_activation_map",
                    "title": "Motor Cortex Activation",
                    "type": "brain_map_3d",
                    "description": "Interactive 3D brain showing motor task activation",
                    "url": "/viz/demo/glm_motor/brain_map",
                    "interactive": True,
                    "thumbnail": "/demo/thumbnails/motor_activation_thumb.png",
                }
            ]
        },
    }


@pytest.fixture
def mock_service_responses():
    """Mock responses for service endpoints."""
    return {
        "health_responses": {
            "br_kg": {
                "status": "healthy",
                "service": "br_kg",
                "version": "1.0.0",
                "database": "connected",
            },
            "orchestrator": {
                "status": "healthy",
                "service": "orchestrator",
                "demos_available": 5,
                "active_demos": 2,
            },
            "agent": {
                "status": "healthy",
                "service": "agent",
                "active_tools": 25,
                "langgraph_status": "ready",
            },
        },
        "demo_responses": {
            "start_demo": {
                "demo_id": "test_demo_123",
                "status": "started",
                "estimated_duration": 85,
                "queue_position": 1,
            },
            "demo_progress": {
                "demo_id": "test_demo_123",
                "status": "running",
                "progress": 45,
                "current_step": "Running GLM analysis",
                "steps_completed": ["Data loading", "Preprocessing"],
                "estimated_time_remaining": 40,
            },
            "demo_result": {
                "demo_id": "test_demo_123",
                "status": "completed",
                "duration": 85,
                "outputs": [
                    {"name": "zmap.nii.gz", "type": "nifti", "size": "12.3 MB"}
                ],
                "visualizations": [
                    {
                        "type": "3d_brain",
                        "url": "/api/landing/demos/test_demo_123/viz/brain",
                    }
                ],
                "run_card": {
                    "reproducibility_score": 0.95,
                    "parameters": {"smoothing": "6mm", "threshold": "p<0.001"},
                },
            },
        },
    }


@pytest.fixture
def registry():
    """Instantiate the tool registry for tests that need it."""
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    reg = ToolRegistry(auto_discover=False, light_mode=True)

    for tool in DLPyTorchTools().get_all_tools():
        reg.register_tool(tool)
    for tool in GNNConnectivityTools().get_all_tools():
        reg.register_tool(tool)
    for tool in MultimodalIntegrationTools().get_all_tools():
        reg.register_tool(tool)

    return reg


@pytest.fixture
def output_dir(tmp_path):
    """Provide a temporary output directory for tool runs."""
    out_path = tmp_path / "tool_outputs"
    out_path.mkdir(parents=True, exist_ok=True)
    return out_path


@pytest.fixture
def test_data(tmp_path):
    """Synthesize lightweight neuroimaging test data used across integration suites."""

    rng = np.random.default_rng(42)

    def _save(name: str, array: np.ndarray) -> str:
        path = tmp_path / f"{name}.npy"
        np.save(path, array)
        return str(path)

    t1 = rng.normal(size=(32, 32, 16)).astype(np.float32)
    flair = (t1 * 1.2).astype(np.float32)
    phase = (t1 * np.pi).astype(np.float32)
    magnitude = np.abs(t1).astype(np.float32) * 1000
    asl = rng.normal(size=(32, 32, 16, 20)).astype(np.float32)
    fmri = rng.normal(size=(32, 32, 16, 40)).astype(np.float32)
    mask = t1 > t1.mean()

    data = {
        "t1": _save("test_t1", t1),
        "flair": _save("test_flair", flair),
        "phase": _save("test_phase", phase),
        "magnitude": _save("test_magnitude", magnitude),
        "asl": _save("test_asl", asl),
        "fmri": _save("test_fmri", fmri),
        "mask": _save("test_mask", mask.astype(np.bool_)),
    }

    return data


@pytest.fixture
def temp_data_dir():
    """Temporary directory for test data files."""
    with tempfile.TemporaryDirectory(prefix="br_test_") as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def demo_executor_mock():
    """Mock demo executor for testing."""
    mock_executor = MagicMock()

    # Mock methods
    async def mock_execute_demo(demo_id, scenario_id, user_id=None):
        return demo_id

    def mock_get_progress(demo_id):
        return {
            "demo_id": demo_id,
            "status": "completed",
            "progress": 100,
            "scenario_id": "glm_motor_task",
        }

    def mock_list_scenarios():
        return [
            {
                "id": "glm_motor_task",
                "name": "Motor Task GLM",
                "complexity": "beginner",
                "duration": 85,
            }
        ]

    mock_executor.execute_demo = mock_execute_demo
    mock_executor.get_demo_progress = mock_get_progress
    mock_executor.list_available_scenarios = mock_list_scenarios

    return mock_executor


@pytest.fixture
def websocket_mock():
    """Mock WebSocket connection for testing."""
    mock_ws = AsyncMock()

    # Mock WebSocket methods
    async def mock_send(data):
        pass

    async def mock_recv():
        return json.dumps(
            {
                "type": "progress_update",
                "demo_id": "test_demo_123",
                "progress": 50,
                "status": "running",
            }
        )

    mock_ws.send = mock_send
    mock_ws.recv = mock_recv

    return mock_ws


@pytest.fixture
def integration_test_markers():
    """Helper for marking integration tests."""

    def marker_helper(test_type: str):
        markers = {
            "demo_scenarios": pytest.mark.demo_scenarios,
            "service_connections": pytest.mark.service_connections,
            "e2e_workflow": pytest.mark.e2e_workflow,
            "demo_gallery": pytest.mark.demo_gallery,
            "slow": pytest.mark.slow_integration,
            "requires_services": pytest.mark.requires_services,
            "websockets": pytest.mark.websockets,
        }
        return markers.get(test_type, lambda x: x)

    return marker_helper


# Utility functions for tests
@pytest.fixture
def test_utilities():
    """Utility functions for integration tests."""

    class TestUtils:
        @staticmethod
        async def wait_for_condition(condition_func, timeout=30, interval=1):
            """Wait for a condition to be true."""
            import time

            start_time = time.time()

            while (time.time() - start_time) < timeout:
                if (
                    await condition_func()
                    if asyncio.iscoroutinefunction(condition_func)
                    else condition_func()
                ):
                    return True
                await asyncio.sleep(interval)
            return False

        @staticmethod
        async def wait_for_demo_completion(client, base_url, demo_id, timeout=120):
            """Wait for demo to complete."""

            async def check_completed():
                try:
                    response = await client.get(
                        f"{base_url}/api/landing/demos/{demo_id}/progress"
                    )
                    if response.status_code == 200:
                        progress = response.json()
                        return progress["status"] in ["completed", "failed", "timeout"]
                except Exception:
                    pass
                return False

            return await TestUtils.wait_for_condition(check_completed, timeout)

        @staticmethod
        def validate_demo_result_structure(result_data):
            """Validate demo result has required structure."""
            required_fields = ["demo_id", "status", "duration"]
            for field in required_fields:
                assert field in result_data, f"Missing required field: {field}"

            # Validate status
            assert result_data["status"] in ["completed", "failed", "timeout"]

            # Validate artifacts if present
            if "outputs" in result_data:
                for output in result_data["outputs"]:
                    assert "name" in output
                    assert "type" in output

        @staticmethod
        def validate_service_health_response(health_data, service_name):
            """Validate service health response structure."""
            assert "status" in health_data
            assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
            assert "service" in health_data
            assert health_data["service"] == service_name

    return TestUtils


# Skip markers for unavailable services
@pytest.fixture
def skip_if_service_unavailable(check_service_health):
    """Skip test if required service is unavailable."""

    async def _skip_if_unavailable(service_name: str):
        if not await check_service_health(service_name):
            pytest.skip(f"{service_name} service not available")

    return _skip_if_unavailable


# Cleanup fixture
@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_data(redis_session):
    """Cleanup test data after each test."""
    yield  # Run the test

    # Cleanup Redis test keys
    try:
        test_keys = await redis_session.keys("test:*")
        if test_keys:
            await redis_session.delete(*test_keys)
    except Exception:
        pass  # Ignore cleanup errors

    # Avoid pytest-asyncio hanging on default executor shutdown.
    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None:
        executor.shutdown(wait=False)
        loop._default_executor = None


# Performance monitoring
@pytest.fixture
def performance_monitor():
    """Monitor test performance metrics."""
    import time

    class PerformanceMonitor:
        def __init__(self):
            self.start_time = None
            self.metrics = {}

        def start(self):
            self.start_time = time.time()

        def record(self, metric_name: str, value: float = None):
            if value is None and self.start_time:
                value = time.time() - self.start_time
            self.metrics[metric_name] = value

        def get_metrics(self):
            return self.metrics.copy()

        def assert_performance(self, metric_name: str, max_value: float):
            if metric_name in self.metrics:
                actual = self.metrics[metric_name]
                assert (
                    actual <= max_value
                ), f"{metric_name} was {actual}, expected <= {max_value}"

    return PerformanceMonitor()


# Test data fixtures for specific scenarios
@pytest.fixture
def sample_fmri_data():
    """Sample fMRI data for testing."""
    return {
        "shape": [64, 64, 30, 200],  # 4D: x, y, z, time
        "tr": 2.5,
        "n_volumes": 200,
        "voxel_size": [2.0, 2.0, 2.0],
        "tasks": ["motor"],
        "conditions": ["left_hand", "right_hand", "rest"],
    }


@pytest.fixture
def sample_coordinates():
    """Sample brain coordinates for testing."""
    return {
        "motor_cortex": [42, -22, 62],
        "visual_cortex": [18, -94, -12],
        "auditory_cortex": [52, -26, 8],
        "frontal_cortex": [36, 42, 28],
    }


# Error simulation fixtures
@pytest.fixture
def simulate_service_errors():
    """Simulate various service error conditions."""

    class ErrorSimulator:
        @staticmethod
        def connection_error():
            return httpx.ConnectError("Connection failed")

        @staticmethod
        def timeout_error():
            return httpx.TimeoutException("Request timeout")

        @staticmethod
        def server_error_response():
            response = MagicMock()
            response.status_code = 500
            response.json.return_value = {
                "error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}
            }
            return response

        @staticmethod
        def service_unavailable_response():
            response = MagicMock()
            response.status_code = 503
            response.json.return_value = {
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Service temporarily unavailable",
                }
            }
            return response

    return ErrorSimulator


# Istio-specific fixtures
def add_istio_markers(config):
    """Configure Istio-specific pytest markers."""
    istio_markers = [
        "istio: Tests related to Istio service mesh functionality",
        "migration: Tests related to Istio migration functionality",
        "canary: Tests related to canary deployments",
        "circuit_breaking: Tests related to circuit breaking functionality",
        "multi_cluster: Tests related to multi-cluster functionality",
        "traffic_management: Tests related to traffic management",
        "security: Tests related to security functionality",
        "observability: Tests related to observability features",
        "performance: Tests related to performance characteristics",
        "scalability: Tests related to scalability features",
        "production: Tests that simulate production conditions",
    ]

    for marker in istio_markers:
        config.addinivalue_line("markers", marker)


# Override pytest_configure to add all markers
def pytest_configure(config):
    """Configure pytest with custom markers including Istio markers."""
    # Add basic markers
    markers = [
        "demo_scenarios: Tests for demo scenario execution",
        "service_connections: Tests for inter-service communication",
        "e2e_workflow: End-to-end workflow tests",
        "demo_gallery: Tests for demo gallery functionality",
        "slow_integration: Integration tests that take >30s",
        "requires_services: Tests that require external services running",
        "websockets: Tests that use WebSocket connections",
    ]

    for marker in markers:
        config.addinivalue_line("markers", marker)

    # Add Istio markers
    add_istio_markers(config)


@pytest.fixture(scope="session")
def istio_test_environment():
    """Provide Istio test environment configuration."""
    return {
        "CI": os.getenv("CI", "false").lower() == "true",
        "ISTIO_AVAILABLE": os.getenv("ISTIO_AVAILABLE", "false").lower() == "true",
        "K8S_CLUSTER_AVAILABLE": os.getenv("K8S_CLUSTER_AVAILABLE", "false").lower()
        == "true",
        "LOAD_TESTING_ENABLED": os.getenv("LOAD_TESTING_ENABLED", "false").lower()
        == "true",
        "TEST_TIMEOUT": int(os.getenv("TEST_TIMEOUT", "300")),  # 5 minutes default
    }


@pytest.fixture
def skip_if_no_istio(istio_test_environment):
    """Skip test if Istio is not available."""
    if not istio_test_environment["ISTIO_AVAILABLE"]:
        pytest.skip("Istio not available in test environment")


@pytest.fixture
def skip_if_no_k8s(istio_test_environment):
    """Skip test if Kubernetes cluster is not available."""
    if not istio_test_environment["K8S_CLUSTER_AVAILABLE"]:
        pytest.skip("Kubernetes cluster not available in test environment")


@pytest.fixture
def skip_if_no_load_testing(istio_test_environment):
    """Skip test if load testing is not enabled."""
    if not istio_test_environment["LOAD_TESTING_ENABLED"]:
        pytest.skip("Load testing not enabled in test environment")


@pytest.fixture
def mock_k8s_config():
    """Provide mock Kubernetes configuration."""
    return {
        "clusters": [
            {
                "cluster": {
                    "certificate-authority-data": "LS0tLS1CRUdJTi...",
                    "server": "https://kubernetes.example.com",
                },
                "name": "test-cluster",
            }
        ],
        "contexts": [
            {
                "context": {"cluster": "test-cluster", "user": "test-user"},
                "name": "test-context",
            }
        ],
        "current-context": "test-context",
        "users": [{"name": "test-user", "user": {"token": "test-token"}}],
    }


@pytest.fixture
def istio_test_namespace():
    """Provide Istio test namespace configuration."""
    return {
        "name": "brain-researcher-test",
        "labels": {"istio-injection": "enabled", "test-environment": "true"},
    }


@pytest.fixture
def sample_service_config():
    """Provide sample service configuration for testing."""
    return {
        "br_kg": {
            "image": "brain-researcher/br_kg:test",
            "port": 5000,
            "replicas": 2,
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "500m", "memory": "1Gi"},
            },
            "health_check": "/health",
            "readiness_check": "/ready",
        },
        "agent": {
            "image": "brain-researcher/agent:test",
            "port": 8000,
            "replicas": 1,
            "resources": {
                "requests": {"cpu": "200m", "memory": "512Mi"},
                "limits": {"cpu": "1000m", "memory": "2Gi"},
            },
            "health_check": "/health",
            "readiness_check": "/ready",
        },
        "orchestrator": {
            "image": "brain-researcher/orchestrator:test",
            "port": 3001,
            "replicas": 2,
            "resources": {
                "requests": {"cpu": "150m", "memory": "384Mi"},
                "limits": {"cpu": "750m", "memory": "1.5Gi"},
            },
            "health_check": "/health",
            "readiness_check": "/ready",
        },
    }


@pytest.fixture
def mock_prometheus_metrics():
    """Provide mock Prometheus metrics data."""
    return {
        "istio_requests_total": [
            {
                "metric": {
                    "__name__": "istio_requests_total",
                    "destination_service_name": "br_kg-service",
                    "response_code": "200",
                },
                "value": [1640995200, "1500"],
            },
            {
                "metric": {
                    "__name__": "istio_requests_total",
                    "destination_service_name": "agent-service",
                    "response_code": "200",
                },
                "value": [1640995200, "800"],
            },
        ],
        "istio_request_duration_milliseconds": [
            {
                "metric": {
                    "__name__": "istio_request_duration_milliseconds",
                    "destination_service_name": "br_kg-service",
                },
                "value": [1640995200, "45.5"],
            }
        ],
    }


@pytest.fixture
def mock_jaeger_traces():
    """Provide mock Jaeger trace data."""
    return {
        "data": [
            {
                "traceID": "1234567890abcdef",
                "spans": [
                    {
                        "spanID": "abcdef1234567890",
                        "operationName": "GET /health",
                        "startTime": 1640995200000000,
                        "duration": 45500,
                        "tags": [
                            {"key": "http.method", "value": "GET"},
                            {"key": "http.url", "value": "/health"},
                        ],
                        "process": {
                            "serviceName": "br_kg-service",
                            "tags": [{"key": "version", "value": "v1.0.0"}],
                        },
                    }
                ],
                "processes": {
                    "p1": {
                        "serviceName": "br_kg-service",
                        "tags": [{"key": "version", "value": "v1.0.0"}],
                    }
                },
            }
        ]
    }


class IstioTestConfig:
    """Configuration class for Istio tests."""

    def __init__(self):
        self.namespace = "brain-researcher-istio-test"
        self.gateway_name = "brain-researcher-gateway"
        self.mesh_config = {
            "default_config": {
                "proxy_stats_matcher": {
                    "inclusion_regexps": [
                        ".*outlier_detection.*",
                        ".*circuit_breaker.*",
                    ],
                    "exclusion_regexps": [".*_bucket"],
                }
            }
        }
        self.security_config = {
            "mtls_mode": "STRICT",
            "authorization_enabled": True,
            "jwt_validation_enabled": True,
        }


@pytest.fixture
def istio_config():
    """Provide Istio test configuration."""
    return IstioTestConfig()


# Performance testing fixtures
@pytest.fixture
def performance_thresholds():
    """Define performance thresholds for testing."""
    return {
        "max_response_time_ms": 1000,
        "max_p95_response_time_ms": 2000,
        "max_p99_response_time_ms": 5000,
        "min_success_rate": 0.95,
        "max_error_rate": 0.05,
        "min_throughput_rps": 100,
        "max_cpu_utilization": 0.8,
        "max_memory_utilization": 0.8,
    }


@pytest.fixture
def load_test_config():
    """Configuration for load tests."""
    return {
        "concurrent_users": [10, 50, 100],
        "test_duration_seconds": 60,
        "ramp_up_duration_seconds": 30,
        "ramp_down_duration_seconds": 30,
        "request_timeout_seconds": 30,
        "think_time_seconds": 1,
    }


# Error simulation fixtures for Istio
@pytest.fixture
def istio_error_scenarios():
    """Define Istio-specific error scenarios for testing."""
    return {
        "network_timeout": {"type": "timeout", "duration": 30},
        "connection_refused": {"type": "connection_error", "errno": 61},
        "server_error": {"type": "http_error", "status_code": 500},
        "service_unavailable": {"type": "http_error", "status_code": 503},
        "rate_limited": {"type": "http_error", "status_code": 429},
        "unauthorized": {"type": "http_error", "status_code": 401},
        "forbidden": {"type": "http_error", "status_code": 403},
        "circuit_breaker_open": {
            "type": "http_error",
            "status_code": 503,
            "headers": {"x-envoy-overloaded": "true"},
        },
        "mtls_failure": {"type": "ssl_error", "reason": "certificate_verify_failed"},
        "mesh_config_error": {
            "type": "istio_error",
            "reason": "virtual_service_invalid",
        },
    }


# Auto-added to block flaky integration test that fails numba/MNE caching
import pathlib as _pathlib

_collect_ignore_entry = (
    _pathlib.Path(__file__).parent / "integration" / "test_advanced_tools.py"
)
collect_ignore = globals().get("collect_ignore", [])
if _collect_ignore_entry.exists():
    collect_ignore.append(str(_collect_ignore_entry))
