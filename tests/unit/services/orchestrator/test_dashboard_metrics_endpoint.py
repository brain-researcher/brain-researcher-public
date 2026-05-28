from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import dashboard_endpoints as dashboard_module
from brain_researcher.services.orchestrator import websocket_endpoints
from brain_researcher.services.orchestrator.dashboard_endpoints import (
    DashboardMetricsResponse,
    QueueStatusModel,
    StorageStatus,
    _collect_gpu_metrics,
    _collect_storage_metrics,
    router,
)
from brain_researcher.services.orchestrator.job_store import JobState
from brain_researcher.services.orchestrator.job_state import jobs_db
from brain_researcher.services.orchestrator.models import (
    ArtifactType,
    Job,
    JobArtifact,
    JobStatus,
    TimingInfo,
    User,
    UserRole,
)
from brain_researcher.services.orchestrator.websocket_endpoints import router as ws_router


@pytest.fixture(autouse=True)
def preserve_job_store():
    """Ensure mutating the shared job store does not leak across tests."""
    original = dict(jobs_db)
    try:
        jobs_db.clear()
        yield
    finally:
        jobs_db.clear()
        jobs_db.update(original)


@pytest.fixture
def client() -> TestClient:
    """Spin up an isolated FastAPI app with the dashboard router."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ws_client() -> TestClient:
    """Provide a TestClient with both API and WebSocket routes."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(ws_router)
    with TestClient(app) as test_client:
        yield test_client


def _make_job(
    job_id: str,
    status: JobStatus,
    start_offset: timedelta = timedelta(),
    end_offset: timedelta | None = None,
    with_artifact: bool = False,
) -> Job:
    """Helper to build a Job record for the in-memory store."""
    start_time = datetime.utcnow() - start_offset
    end_time = None
    if end_offset is not None:
        end_time = datetime.utcnow() - end_offset

    artifacts: list[JobArtifact] = []
    if with_artifact:
        artifacts.append(
            JobArtifact(
                id=f"artifact_{job_id}",
                type=ArtifactType.REPORT,
                name=f"{job_id}.html",
                url=f"/api/jobs/{job_id}/artifacts/report",
                size_bytes=5120,
            )
        )

    return Job(
        id=job_id,
        status=status,
        prompt=f"Run {job_id}",
        steps=[],
        artifacts=artifacts,
        timing=TimingInfo(
            start_time=start_time,
            end_time=end_time,
        ),
        metadata={"pipeline": "glmfitlins"},
    )


def test_dashboard_metrics_merges_orchestrator_state(client: TestClient):
    """Coordinator data should be enriched with local queue and artifact state."""
    jobs_db["job_running"] = _make_job("job_running", JobStatus.RUNNING)
    jobs_db["job_done"] = _make_job(
        "job_done",
        JobStatus.COMPLETED,
        start_offset=timedelta(minutes=10),
        end_offset=timedelta(minutes=1),
        with_artifact=True,
    )

    remote_payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "gpuUtilization": [
            {"timestamp": datetime.utcnow().isoformat(), "gpu1": 10, "gpu2": 20, "gpu3": 30, "gpu4": 40},
        ],
        "queueStatus": {"running": 0, "queued": 99, "completed": 0, "failed": 0},
        "projects": [
            {
                "id": "proj-1",
                "name": "Remote Project",
                "progress": 42.0,
                "subjects": 12,
                "status": "active",
            }
        ],
        "teamActivity": [],
        "storage": {"primary": {"used": 123, "total": 256}},
        "outputs": [
            {
                "id": "upstream",
                "name": "remote_output",
                "type": "report",
                "size": "1 MB",
                "created": datetime.utcnow().isoformat(),
            }
        ],
    }

    mock_response = SimpleNamespace(json=lambda: remote_payload)

    with patch.object(
        dashboard_module, "service_coordinator", autospec=True
    ) as mock_coordinator:
        mock_coordinator.make_request = AsyncMock(return_value=mock_response)

        response = client.get("/api/dashboard/metrics")

    assert response.status_code == 200
    body = response.json()

    # Queue counts should reflect orchestrator jobs, not the upstream stub.
    assert body["jobMetrics"]["queue"]["running"] == 1
    assert body["jobMetrics"]["queue"]["completed"] == 1

    # Outputs should include the orchestrator artifact rather than the upstream placeholder.
    output_ids = {item["id"] for item in body["outputs"]}
    assert "artifact_job_done" in output_ids
    assert "upstream" not in output_ids

    # Metadata tracks provenance.
    assert body["metadata"]["source"] == "neurokg"
    status = body["metadata"].get("status")
    if body["metadata"].get("errors"):
        assert status == "degraded"
    else:
        assert status == "healthy"


def test_dashboard_metrics_fallback_when_upstream_unavailable(client: TestClient):
    """If upstream services fail, fallback metrics are still returned."""
    jobs_db["job_pending"] = _make_job("job_pending", JobStatus.QUEUED)

    request = httpx.Request("GET", "http://neurokg.local/api/dashboard/metrics")

    with patch.object(
        dashboard_module, "service_coordinator", autospec=True
    ) as mock_coordinator, patch.object(
        dashboard_module,
        "_fetch_metrics_direct",
        new=AsyncMock(side_effect=httpx.RequestError("boom", request=request)),
    ):
        mock_coordinator.make_request = AsyncMock(
            side_effect=dashboard_module.ServiceUnavailableError("offline")
        )

        response = client.get("/api/dashboard/metrics")

    assert response.status_code == 200
    body = response.json()

    # Fallback keeps queue data from orchestrator memory.
    assert body["jobMetrics"]["queue"]["queued"] == 1
    assert body["metadata"]["source"] == "fallback"
    assert "errors" in body["metadata"]


def test_dashboard_metrics_use_job_store_queue_stats(client: TestClient):
    """Queue status should prefer the configured job store when available."""

    class FakeJobStore:
        async def get_queue_stats(self):
            return {
                JobState.RUNNING.value: 2,
                JobState.QUEUED.value: 3,
                JobState.SUCCEEDED.value: 4,
                JobState.FAILED.value: 1,
            }

    with patch(
        "brain_researcher.services.orchestrator.dashboard_endpoints._get_job_store",
        return_value=FakeJobStore(),
    ):
        response = client.get("/api/dashboard/metrics")

    assert response.status_code == 200

    body = response.json()
    assert body["jobMetrics"]["queue"]["running"] == 2
    assert body["jobMetrics"]["queue"]["queued"] == 3
    assert body["jobMetrics"]["queue"]["completed"] == 4
    assert body["jobMetrics"]["queue"]["failed"] == 1
    assert body["jobMetrics"]["queueSource"] == "job_store"


def test_dashboard_websocket_emits_snapshot(ws_client: TestClient):
    """Dashboard WebSocket should stream an initial snapshot."""
    metrics = DashboardMetricsResponse(
        timestamp=datetime.utcnow(),
        jobMetrics=dashboard_module.JobMetricsModel(
            queue=QueueStatusModel(running=2, queued=1, completed=5, failed=0)
        ),
        resourceMetrics=dashboard_module.ResourceMetricsModel(gpuSamples=[]),
        projects=[],
        activity=[],
        storageMetrics=StorageStatus(
            primary={"used": 10, "total": 100},
            archive={"used": 0, "total": 100},
            scratch={"used": 0, "total": 50},
        ),
        outputs=[],
        metadata={"source": "test-suite"},
    )

    with patch.object(
        websocket_endpoints,
        "build_dashboard_metrics_response",
        new=AsyncMock(return_value=metrics),
    ):
        try:
            with ws_client.websocket_connect("/ws/dashboard") as websocket:
                connection_info = websocket.receive_json()
                assert connection_info["type"] == "connection_info"

                payload = None
                for _ in range(4):
                    message = websocket.receive_json()
                    if message["type"] == "data" and message.get("channel") == "dashboard":
                        assert message["data"]["type"] == "snapshot"
                        payload = message["data"]["data"]
                        break

                assert payload is not None
                assert payload["jobMetrics"]["queue"]["running"] == 2
                assert payload["metadata"]["source"] == "test-suite"
        except AttributeError as exc:
            # Some dependency combinations (starlette/anyio) break websocket_connect().
            if "start_task" in str(exc):
                pytest.skip(f"WebSocket TestClient unsupported in this env: {exc}")
            raise


def test_collect_gpu_metrics_when_nvidia_smi_available():
    """Test GPU metrics collection with nvidia-smi available."""
    mock_nvidia_output = "0, 65.5, 8192, 16384\n1, 45.2, 4096, 16384\n2, 80.0, 12288, 16384\n3, 30.5, 2048, 16384"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = mock_nvidia_output

    with patch('shutil.which', return_value='/usr/bin/nvidia-smi'), \
         patch('subprocess.run', return_value=mock_result):

        metrics = _collect_gpu_metrics()

        assert len(metrics) == 1
        assert 'timestamp' in metrics[0]
        assert metrics[0]['gpu1'] == 65.5
        assert metrics[0]['gpu2'] == 45.2
        assert metrics[0]['gpu3'] == 80.0
        assert metrics[0]['gpu4'] == 30.5


def test_collect_gpu_metrics_when_nvidia_smi_unavailable():
    """Test GPU metrics collection when nvidia-smi is not available."""
    with patch('shutil.which', return_value=None):
        metrics = _collect_gpu_metrics()

        assert metrics == []


def test_collect_gpu_metrics_when_nvidia_smi_fails():
    """Test GPU metrics collection when nvidia-smi command fails."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch('shutil.which', return_value='/usr/bin/nvidia-smi'), \
         patch('subprocess.run', return_value=mock_result):

        metrics = _collect_gpu_metrics()

        assert metrics == []


def test_collect_gpu_metrics_timeout():
    """Test GPU metrics collection handles subprocess timeout."""
    import subprocess

    with patch('shutil.which', return_value='/usr/bin/nvidia-smi'), \
         patch('subprocess.run', side_effect=subprocess.TimeoutExpired('nvidia-smi', 2.0)):

        metrics = _collect_gpu_metrics()

        assert metrics == []


def test_collect_storage_metrics_success():
    """Test storage metrics collection with valid paths."""
    import os
    from unittest.mock import MagicMock

    mock_usage = MagicMock()
    mock_usage.used = 100 * 1024**3  # 100 GB
    mock_usage.total = 500 * 1024**3  # 500 GB

    with patch('shutil.disk_usage', return_value=mock_usage), \
         patch.dict(os.environ, {
             'PRIMARY_STORAGE_PATH': '/tmp/test/primary',
             'ARCHIVE_STORAGE_PATH': '/tmp/test/archive',
             'SCRATCH_STORAGE_PATH': '/tmp/test/scratch'
         }):

        metrics = _collect_storage_metrics()

        assert 'primary' in metrics
        assert 'archive' in metrics
        assert 'scratch' in metrics

        assert metrics['primary']['used'] == 100.0
        assert metrics['primary']['total'] == 500.0
        assert metrics['archive']['used'] == 100.0
        assert metrics['scratch']['total'] == 500.0


def test_collect_storage_metrics_with_defaults():
    """Test storage metrics collection uses default paths when env vars not set."""
    import os
    from unittest.mock import MagicMock

    mock_usage = MagicMock()
    mock_usage.used = 50 * 1024**3
    mock_usage.total = 1000 * 1024**3

    with patch('shutil.disk_usage', return_value=mock_usage), \
         patch.dict(os.environ, {}, clear=True):

        metrics = _collect_storage_metrics()

        assert 'primary' in metrics
        assert 'archive' in metrics
        assert 'scratch' in metrics


def test_collect_storage_metrics_handles_errors():
    """Test storage metrics collection handles filesystem errors gracefully."""
    import os

    def mock_disk_usage(path):
        if 'primary' in path:
            raise PermissionError("Access denied")
        return MagicMock(used=10*1024**3, total=100*1024**3)

    with patch('shutil.disk_usage', side_effect=mock_disk_usage), \
         patch.dict(os.environ, {
             'PRIMARY_STORAGE_PATH': '/tmp/test/primary',
             'ARCHIVE_STORAGE_PATH': '/tmp/test/archive',
             'SCRATCH_STORAGE_PATH': '/tmp/test/scratch'
         }):

        metrics = _collect_storage_metrics()

        # Primary should use default values due to error
        assert metrics['primary']['used'] == 0.0
        assert metrics['primary']['total'] == 0.0

        # Archive and scratch should work
        assert metrics['archive']['used'] == 10.0
        assert metrics['scratch']['total'] == 100.0


def test_dashboard_metrics_includes_gpu_and_storage(client: TestClient):
    """Test that dashboard metrics response includes GPU and storage data."""
    jobs_db["job_test"] = _make_job("job_test", JobStatus.RUNNING)

    mock_gpu_data = [{
        'timestamp': datetime.utcnow(),
        'gpu1': 75.0,
        'gpu2': 60.0,
        'gpu3': 85.0,
        'gpu4': 50.0
    }]

    mock_storage_data = {
        'primary': {'used': 150.0, 'total': 500.0},
        'archive': {'used': 300.0, 'total': 1000.0},
        'scratch': {'used': 20.0, 'total': 100.0}
    }

    with patch.object(dashboard_module, '_collect_gpu_metrics', return_value=mock_gpu_data), \
         patch.object(dashboard_module, '_collect_storage_metrics', return_value=mock_storage_data), \
         patch.object(dashboard_module, 'service_coordinator', None):

        response = client.get("/api/dashboard/metrics")

    assert response.status_code == 200
    body = response.json()

    # Verify GPU metrics are included
    assert 'resourceMetrics' in body
    assert 'gpuSamples' in body['resourceMetrics']
    assert len(body['resourceMetrics']['gpuSamples']) == 1
    assert body['resourceMetrics']['gpuSamples'][0]['gpu1'] == 75.0
    assert body['resourceMetrics']['gpuSamples'][0]['gpu4'] == 50.0

    # Verify storage metrics are included
    assert 'storageMetrics' in body
    assert body['storageMetrics']['primary']['used'] == 150.0
    assert body['storageMetrics']['archive']['total'] == 1000.0
    assert body['storageMetrics']['scratch']['used'] == 20.0

@pytest.mark.asyncio
async def test_dashboard_metrics_prefers_job_store_queue(monkeypatch):
    """Ensure queue stats originate from the job store when available."""

    queue_stats = {
        'by_state': {
            JobState.RUNNING: 3,
            JobState.QUEUED: 4,
            JobState.SUCCEEDED: 7,
            JobState.FAILED: 1,
        },
        'oldest_pending_age_sec': 42,
    }
    job_store = SimpleNamespace(get_queue_stats=AsyncMock(return_value=queue_stats))

    payload = {'projects': [], 'metadata': {}}
    gpu_samples: list[dict[str, float]] = []
    storage_snapshot = {
        'primary': {'used': 10.0, 'total': 100.0},
        'archive': {'used': 5.0, 'total': 50.0},
        'scratch': {'used': 1.0, 'total': 10.0},
    }

    monkeypatch.setattr(dashboard_module, '_get_job_store', lambda: job_store)
    monkeypatch.setattr(
        dashboard_module,
        '_load_dashboard_metrics',
        AsyncMock(return_value=(payload, 'neurokg', [])),
    )
    monkeypatch.setattr(dashboard_module, '_collect_gpu_metrics', lambda: gpu_samples)
    monkeypatch.setattr(dashboard_module, '_collect_storage_metrics', lambda: storage_snapshot)
    monkeypatch.setattr(dashboard_module, '_build_team_activity_snapshot', lambda: [])
    monkeypatch.setattr(dashboard_module, '_collect_recent_outputs', lambda: [])

    response = await dashboard_module.build_dashboard_metrics_response()

    assert response.jobMetrics.queueSource == 'job_store'
    assert response.jobMetrics.queue.running == 3
    assert response.jobMetrics.queue.queued == 4
    assert response.jobMetrics.queue.completed == 7
    assert response.jobMetrics.queue.failed == 1
    assert response.jobMetrics.oldestPendingSeconds == 42
    assert response.metadata.get('errors') is None


@pytest.mark.asyncio
async def test_dashboard_metrics_marks_job_store_unavailable(monkeypatch):
    """Metadata should reflect degraded mode when the job store is missing."""

    payload = {'projects': [], 'metadata': {}}
    gpu_samples: list[dict[str, float]] = []
    storage_snapshot = {
        'primary': {'used': 5.0, 'total': 50.0},
        'archive': {'used': 3.0, 'total': 30.0},
        'scratch': {'used': 1.0, 'total': 10.0},
    }

    monkeypatch.setattr(dashboard_module, '_get_job_store', lambda: None)
    monkeypatch.setattr(
        dashboard_module,
        '_load_dashboard_metrics',
        AsyncMock(return_value=(payload, 'fallback', [])),
    )
    monkeypatch.setattr(dashboard_module, '_collect_gpu_metrics', lambda: gpu_samples)
    monkeypatch.setattr(dashboard_module, '_collect_storage_metrics', lambda: storage_snapshot)
    monkeypatch.setattr(dashboard_module, '_build_team_activity_snapshot', lambda: [])
    monkeypatch.setattr(dashboard_module, '_collect_recent_outputs', lambda: [])

    response = await dashboard_module.build_dashboard_metrics_response()

    assert response.jobMetrics.queueSource == 'in_memory'
    assert response.metadata['status'] == 'degraded'
    assert 'job_store_unavailable' in response.metadata['errors']


@pytest.mark.asyncio
async def test_build_mcp_adoption_metrics_summarizes_user_statuses(monkeypatch):
    """MCP adoption rollups should distinguish used, token-never-used, and no-token users."""

    class FakeRedis:
        def __init__(self):
            self.token_records = {
                'mcp_token:kid:kid_used': {
                    'user_id': 'user_used',
                    'last_used_at': '2026-03-23T12:00:00Z',
                },
                'mcp_token:kid:kid_unused': {
                    'user_id': 'user_tokenneverused',
                    'last_used_at': '',
                },
            }
            self.active_user_keys = [
                'mcp_token:user:user_used',
                'mcp_token:user:user_tokenneverused',
            ]

        async def scan_iter(self, match: str):
            if match == 'mcp_token:kid:*':
                for key in self.token_records:
                    yield key
            elif match == 'mcp_token:user:*':
                for key in self.active_user_keys:
                    yield key

        async def hgetall(self, key: str):
            return self.token_records.get(key, {})

    users = [
        User(
            id='user_used',
            username='used_user',
            email='used@example.com',
            full_name='Used User',
            role=UserRole.RESEARCHER,
            created_at=datetime.utcnow() - timedelta(days=3),
        ),
        User(
            id='user_tokenneverused',
            username='token_only_user',
            email='token@example.com',
            full_name='Token Only',
            role=UserRole.RESEARCHER,
            created_at=datetime.utcnow() - timedelta(days=2),
        ),
        User(
            id='user_notoken',
            username='no_token_user',
            email='notoken@example.com',
            full_name='No Token',
            role=UserRole.RESEARCHER,
            created_at=datetime.utcnow() - timedelta(days=1),
        ),
        User(
            id='user_demo',
            username='demo',
            email='demo@brain-researcher.ai',
            full_name='Demo User',
            role=UserRole.RESEARCHER,
        ),
    ]

    monkeypatch.setattr(dashboard_module.UserStore, 'list_all', AsyncMock(return_value=users))
    monkeypatch.setattr(
        dashboard_module,
        '_get_userstore_redis',
        AsyncMock(return_value=FakeRedis()),
    )

    metrics = await dashboard_module._build_mcp_adoption_metrics()

    assert metrics.summary.totalUsers == 3
    assert metrics.summary.usedUsers == 1
    assert metrics.summary.unusedUsers == 2
    assert metrics.summary.tokenNeverUsedUsers == 1
    assert metrics.summary.noTokenUsers == 1

    by_user = {entry.userId: entry for entry in metrics.users}
    assert by_user['user_used'].mcpStatus == 'used'
    assert by_user['user_used'].usedMcp is True
    assert by_user['user_used'].hasActiveToken is True
    assert by_user['user_tokenneverused'].mcpStatus == 'token_never_used'
    assert by_user['user_notoken'].mcpStatus == 'no_token'


@pytest.mark.asyncio
async def test_dashboard_metrics_includes_mcp_adoption_for_admin_request(monkeypatch):
    """Admin requests should receive MCP adoption metrics in the dashboard payload."""

    payload = {'projects': [], 'metadata': {}}
    storage_snapshot = {
        'primary': {'used': 5.0, 'total': 50.0},
        'archive': {'used': 3.0, 'total': 30.0},
        'scratch': {'used': 1.0, 'total': 10.0},
    }
    adoption = dashboard_module.McpAdoptionMetricsModel(
        summary=dashboard_module.McpAdoptionSummaryModel(
            totalUsers=10,
            usedUsers=4,
            unusedUsers=6,
            tokenNeverUsedUsers=2,
            noTokenUsers=4,
            adoptionRatePct=40.0,
        ),
        users=[],
    )

    monkeypatch.setattr(
        dashboard_module,
        '_load_dashboard_metrics',
        AsyncMock(return_value=(payload, 'fallback', [])),
    )
    monkeypatch.setattr(dashboard_module, '_collect_gpu_metrics', lambda: [])
    monkeypatch.setattr(dashboard_module, '_collect_storage_metrics', lambda: storage_snapshot)
    monkeypatch.setattr(dashboard_module, '_build_team_activity_snapshot', lambda: [])
    monkeypatch.setattr(dashboard_module, '_collect_recent_outputs', lambda: [])
    monkeypatch.setattr(
        dashboard_module,
        '_should_include_mcp_adoption',
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        dashboard_module,
        '_build_mcp_adoption_metrics',
        AsyncMock(return_value=adoption),
    )

    response = await dashboard_module.build_dashboard_metrics_response(request=MagicMock())

    assert response.mcpAdoption is not None
    assert response.mcpAdoption.summary.totalUsers == 10
    assert response.metadata['status'] == 'degraded'


@pytest.mark.asyncio
async def test_should_include_mcp_adoption_for_allowlisted_email(monkeypatch):
    """Allowlisted internal emails should be able to view MCP adoption analytics."""

    monkeypatch.setenv(
        'BR_MCP_ADOPTION_DASHBOARD_ALLOWLIST',
        'ops@brain-researcher.com, founder@brain-researcher.com',
    )
    monkeypatch.setattr(dashboard_module, '_extract_bearer_token', lambda request: 'jwt-token')
    monkeypatch.setattr(
        dashboard_module,
        '_decode_auth_token',
        lambda token: {'email': 'ops@brain-researcher.com', 'role': 'researcher'},
    )
    monkeypatch.setattr(
        dashboard_module,
        '_resolve_authenticated_user',
        AsyncMock(side_effect=AssertionError('should not need user lookup when JWT email is allowlisted')),
    )

    allowed = await dashboard_module._should_include_mcp_adoption(MagicMock())

    assert allowed is True
