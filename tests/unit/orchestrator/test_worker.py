"""
Unit tests for JobWorker.

Tests that the worker correctly integrates with JobStore API:
- claim_next()
- heartbeat()
- update_state()
- cancel-wins flow
"""

import asyncio
import json
import time
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from brain_researcher.services.agent.tool_executor import ToolExecutionResult
from brain_researcher.services.orchestrator import worker as worker_module
from brain_researcher.services.orchestrator.dag_runtime import (
    WorkflowResult,
    WorkflowState,
)
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import (
    JobWorker,
    _anchor_plan_step_output_dirs,
    start_worker_pool,
)
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState


@pytest.fixture
def mock_job_store():
    """Create mock JobStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def sample_job():
    """Create sample job record."""
    payload = {
        "command": 'echo "test"',
        "parameters": {},
        "execution_mode": "direct_execution",
    }
    return JobRecord(
        job_id="test_job_001",
        kind="tool",
        payload_json=json.dumps(payload),
        state=JobState.CLAIMED,
        priority=5,
        gpu_req=0,
        worker_id="worker-test",
    )


class StubToolExecutor:
    """Lightweight ToolExecutor stub for worker tests."""

    def __init__(self, status: str = "success", sleep: float = 0.1):
        self.status = status
        self.sleep = sleep
        self.executions = []

    def execute(self, request):
        self.executions.append(request)
        if self.sleep:
            time.sleep(self.sleep)

        metadata = {
            "run_id": f"run_{request.execution_id}",
            "run_dir": f"/tmp/runs/{request.execution_id}",
            "provenance_path": f"/tmp/runs/{request.execution_id}/provenance.json",
        }
        error = None if self.status == "success" else f"Stub {self.status}"

        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name or "stub_tool",
            status=self.status,
            result={"stdout": "", "stderr": "", "returncode": 0},
            error=error,
            execution_time=self.sleep or 0.01,
            metadata=metadata,
        )

    def cancel(self, execution_id: str):
        self.status = "cancelled"


def test_anchor_plan_step_output_dirs_uses_job_run_dir(tmp_path: Path):
    step_defs = [
        {
            "id": "connectome",
            "tool": "workflow_rest_connectome_e2e",
            "params": {
                "bids_dir": "/app/data/OpenNeuro/ds000114",
                "output_dir": "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e",
                "output_file": (
                    "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e/"
                    "connectivity_matrix.npy"
                ),
                "report_file": (
                    "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e/"
                    "reports/connectivity.html"
                ),
            },
        },
        {
            "id": "workflow_without_output_dir",
            "tool": "workflow_rest_connectome_e2e",
            "params": {"bids_dir": "/app/data/OpenNeuro/ds000114"},
        },
        {
            "id": "search",
            "tool": "literature_search",
            "params": {"query": "connectome"},
        },
    ]

    changed = _anchor_plan_step_output_dirs(step_defs, run_dir=tmp_path)

    assert changed is True
    assert step_defs[0]["params"]["output_dir"] == str(tmp_path)
    assert step_defs[0]["params"]["output_file"] == str(
        (tmp_path / "connectivity_matrix.npy").resolve()
    )
    assert step_defs[0]["params"]["report_file"] == str(
        (tmp_path / "reports" / "connectivity.html").resolve()
    )
    assert step_defs[0]["params"]["bids_dir"] == "/app/data/OpenNeuro/ds000114"
    assert step_defs[1]["params"]["output_dir"] == str(tmp_path)
    assert "output_dir" not in step_defs[2]["params"]


@pytest.mark.asyncio
async def test_plan_worker_persists_job_run_id_and_anchored_output_dir(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    monkeypatch.setattr("brain_researcher.config.run_artifacts._config", None)

    def fake_execute(self, workflow):
        return WorkflowResult(
            state=WorkflowState.SUCCEEDED,
            error=None,
            run_dir=str(tmp_path / "workflow-run"),
            step_results=[{"step_id": "s1", "tool": "workflow_rest_connectome_e2e"}],
        )

    monkeypatch.setattr(worker_module.DAGExecutor, "execute", fake_execute)

    old_output_dir = "/app/jobstore/runs/ds000114/workflow_rest_connectome_e2e"
    payload = {
        "type": "plan_execution",
        "plan_id": "plan-connectome",
        "plan": {
            "plan_id": "plan-connectome",
            "dag": {
                "steps": [
                    {
                        "id": "s1",
                        "tool": "workflow_rest_connectome_e2e",
                        "params": {
                            "output_dir": old_output_dir,
                            "output_file": f"{old_output_dir}/connectivity_matrix.npy",
                        },
                    }
                ],
                "artifacts": [],
            },
        },
    }
    job = JobRecord(
        job_id="job-plan-output-dir",
        kind="plan_execution",
        payload_json=json.dumps(payload),
        state=JobState.QUEUED,
        priority=5,
        gpu_req=0,
        worker_id="worker-test",
    )
    job_store = MemoryJobStore(total_gpu_slots=1)
    await job_store.enqueue(job)

    worker = JobWorker(
        job_store=job_store,
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=MagicMock(),
    )
    worker.gate_engine = None

    await worker._execute_job(job)

    final_job = await job_store.get(job.job_id)
    assert final_job is not None
    assert final_job.run_id == job.job_id
    assert final_job.run_dir is not None
    assert Path(final_job.run_dir).name == job.job_id
    persisted_payload = json.loads(final_job.payload_json or "{}")
    params = persisted_payload["plan"]["dag"]["steps"][0]["params"]
    assert params["output_dir"] == final_job.run_dir
    assert params["output_file"] == str(Path(final_job.run_dir) / "connectivity_matrix.npy")


def setup_claim_next_once(mock_job_store, job):
    """Configure claim_next to return job once, then None without raising."""

    async def _claim_next(*args, **kwargs):
        if not getattr(_claim_next, "called", False):
            _claim_next.called = True
            return job
        return None

    _claim_next.called = False
    mock_job_store.claim_next.side_effect = _claim_next


class TestJobWorkerBasics:
    """Test basic worker lifecycle."""

    @pytest.mark.asyncio
    async def test_worker_initialization(self, mock_job_store):
        """Test worker can be initialized."""
        worker = JobWorker(
            job_store=mock_job_store,
            worker_id="worker-test",
            lease_ttl=60,
            heartbeat_interval=30,
        )

        assert worker.worker_id == "worker-test"
        assert worker.lease_ttl == 60
        assert worker.heartbeat_interval == 30
        assert worker.running is False
        assert worker.current_job_id is None

    @pytest.mark.asyncio
    async def test_worker_starts_and_stops_gracefully(self, mock_job_store):
        """Test worker can start and stop without errors."""
        # No jobs available
        mock_job_store.claim_next.return_value = None

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.2),
        )

        # Start worker in background
        worker_task = asyncio.create_task(worker.start())

        # Let it run briefly
        await asyncio.sleep(0.1)

        # Stop worker
        await worker.stop()

        # Wait for worker to finish
        await worker_task

        # Verify claim_next was called
        assert mock_job_store.claim_next.called

    def test_sort_steps_by_dependencies_orders_depends_on(self, mock_job_store):
        worker = JobWorker(
            job_store=mock_job_store,
            worker_id="worker-test",
            lease_ttl=60,
            heartbeat_interval=30,
        )

        steps = [
            {"id": "b", "depends_on": ["a"]},
            {"id": "a"},
        ]
        ordered = worker._sort_steps_by_dependencies(steps)
        assert [s.get("id") for s in ordered] == ["a", "b"]

    def test_sort_steps_by_dependencies_orders_by_artifact_flow(self, mock_job_store):
        worker = JobWorker(
            job_store=mock_job_store,
            worker_id="worker-test",
            lease_ttl=60,
            heartbeat_interval=30,
        )

        steps = [
            {"id": "consume", "consumes": {"in": "artifact-1"}},
            {"id": "produce", "produces": {"out": "artifact-1"}},
        ]
        ordered = worker._sort_steps_by_dependencies(steps)
        assert [s.get("id") for s in ordered] == ["produce", "consume"]


class TestJobWorkerClaiming:
    """Test job claiming behavior."""

    @pytest.mark.asyncio
    async def test_worker_claims_job_using_claim_next(self, mock_job_store, sample_job):
        """Test worker uses claim_next() to get jobs."""
        # Return job once, then None
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        stub_executor = StubToolExecutor(sleep=0.2)
        worker = JobWorker(
            mock_job_store,
            "worker-test",
            heartbeat_interval=1,
            tool_executor=stub_executor,
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it process the job
        await asyncio.sleep(6)  # Longer than execution time

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify claim_next was called with correct parameters
        assert mock_job_store.claim_next.called
        claim_calls = mock_job_store.claim_next.call_args_list
        assert any(
            call_args.kwargs.get("worker_id") == "worker-test"
            and call_args.kwargs.get("lease_ttl") == 60
            for call_args in claim_calls
        )

    @pytest.mark.asyncio
    async def test_worker_waits_when_no_jobs_available(self, mock_job_store):
        """Test worker sleeps when queue is empty."""
        # No jobs available
        mock_job_store.claim_next.return_value = None

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.2),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it run for a short time
        await asyncio.sleep(0.2)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify claim_next was called multiple times (polling)
        assert mock_job_store.claim_next.call_count >= 1


class TestJobWorkerHeartbeat:
    """Test heartbeat functionality."""

    @pytest.mark.asyncio
    async def test_worker_sends_heartbeats_during_execution(
        self, mock_job_store, sample_job
    ):
        """Test worker sends periodic heartbeats using heartbeat()."""
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        stub_executor = StubToolExecutor(sleep=3.0)
        worker = JobWorker(
            mock_job_store,
            "worker-test",
            heartbeat_interval=1,  # Fast heartbeats for testing
            tool_executor=stub_executor,
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it execute (job takes ~5 seconds)
        await asyncio.sleep(6)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify heartbeat was called multiple times
        assert mock_job_store.heartbeat.call_count >= 2

        # Verify heartbeat was called with correct parameters
        heartbeat_calls = mock_job_store.heartbeat.call_args_list
        assert any(
            call_args.kwargs.get("worker_id") == "worker-test"
            and call_args.kwargs.get("job_id") == "test_job_001"
            for call_args in heartbeat_calls
        )

    @pytest.mark.asyncio
    async def test_worker_stops_on_heartbeat_failure(self, mock_job_store, sample_job):
        """Test worker detects heartbeat failure and stops."""
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True

        # Heartbeat succeeds once, then fails
        mock_job_store.heartbeat.side_effect = [1, 0]

        stub_executor = StubToolExecutor(sleep=3.0)
        worker = JobWorker(
            mock_job_store,
            "worker-test",
            heartbeat_interval=1,
            tool_executor=stub_executor,
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it run
        await asyncio.sleep(3)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify heartbeat was attempted
        assert mock_job_store.heartbeat.called


class TestJobWorkerStateUpdates:
    """Test job state update behavior."""

    @pytest.mark.asyncio
    async def test_worker_updates_state_to_running(self, mock_job_store, sample_job):
        """Test worker updates job to RUNNING state using update_state()."""
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.1),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it start execution
        await asyncio.sleep(6)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify update_state was called to set RUNNING
        update_calls = mock_job_store.update_state.call_args_list
        running_call = next(
            (c for c in update_calls if c.args[1] == JobState.RUNNING), None
        )
        assert running_call is not None
        assert running_call.args[0] == "test_job_001"

    @pytest.mark.asyncio
    async def test_worker_updates_state_to_succeeded(self, mock_job_store, sample_job):
        """Test worker updates job to SUCCEEDED on completion."""
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.2),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it complete execution (5 seconds + buffer)
        await asyncio.sleep(6)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify update_state was called to set SUCCEEDED
        update_calls = mock_job_store.update_state.call_args_list
        succeeded_call = next(
            (c for c in update_calls if c.args[1] == JobState.SUCCEEDED), None
        )
        assert succeeded_call is not None
        assert succeeded_call.args[0] == "test_job_001"

    @pytest.mark.asyncio
    async def test_worker_updates_state_to_failed_on_error(
        self, mock_job_store, sample_job
    ):
        """Test worker updates job to FAILED on execution error."""
        setup_claim_next_once(mock_job_store, sample_job)
        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(status="error", sleep=0.2),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it fail
        await asyncio.sleep(2)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify update_state was called to set RETRYING (with P2.6 retry logic)
        update_calls = mock_job_store.update_state.call_args_list
        retrying_call = next(
            (c for c in update_calls if c.args[1] == JobState.RETRYING), None
        )
        assert retrying_call is not None, (
            f"Expected RETRYING call, got: {[c.args[1] for c in update_calls]}"
        )
        # Error jobs are retryable, so they go to RETRYING state
        assert retrying_call.kwargs.get("run_after") is not None

    @pytest.mark.asyncio
    async def test_worker_persists_output_paths_as_artifacts(
        self, mock_job_store, sample_job, tmp_path
    ):
        run_dir = tmp_path / "runs" / sample_job.job_id
        output_path = (
            run_dir / "outputs" / "nilearn_connectivity" / "connectivity_matrix.npy"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"matrix")

        class ArtifactStubExecutor:
            def execute(self, request):
                return ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name or "stub_tool",
                    status="success",
                    result={
                        "status": "success",
                        "data": {
                            "outputs": {
                                "connectivity_matrix": "outputs/nilearn_connectivity/connectivity_matrix.npy"
                            }
                        },
                    },
                    error=None,
                    execution_time=0.01,
                    metadata={
                        "run_id": f"run_{request.execution_id}",
                        "run_dir": str(run_dir),
                        "provenance_path": str(run_dir / "provenance.json"),
                    },
                )

            def cancel(
                self, execution_id: str
            ):  # pragma: no cover - parity with interface
                return None

        mock_job_store.get.return_value = sample_job
        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=ArtifactStubExecutor(),
        )

        await worker._execute_job(sample_job)

        payload = json.loads(sample_job.payload_json)
        artifacts = payload.get("artifacts")
        assert isinstance(artifacts, list) and artifacts

        matched = next(
            (
                artifact
                for artifact in artifacts
                if isinstance(artifact, dict)
                and artifact.get("name") == "connectivity_matrix.npy"
            ),
            None,
        )
        assert matched is not None
        assert (
            str(matched.get("path"))
            == "outputs/nilearn_connectivity/connectivity_matrix.npy"
        )
        assert str(matched.get("url", "")).endswith(
            "/artifacts/files/outputs/nilearn_connectivity/connectivity_matrix.npy"
        )


class TestJobWorkerCancellation:
    """Test cancel-wins flow."""

    @pytest.mark.asyncio
    async def test_worker_handles_cancellation_request(
        self, mock_job_store, sample_job
    ):
        """Test worker respects cancellation_requested flag."""
        setup_claim_next_once(mock_job_store, sample_job)

        # Job is marked for cancellation
        cancelled_job = sample_job
        cancelled_job.cancellation_requested = True
        mock_job_store.get.return_value = cancelled_job

        mock_job_store.update_state.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.2),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it process cancellation
        await asyncio.sleep(2)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify cancel() was called
        assert mock_job_store.cancel.called
        cancel_call = mock_job_store.cancel.call_args
        assert cancel_call.args[0] == "test_job_001"

    @pytest.mark.asyncio
    async def test_cancel_wins_over_completion(self, mock_job_store, sample_job):
        """Test that cancellation takes precedence over success."""
        setup_claim_next_once(mock_job_store, sample_job)

        # Job gets cancelled mid-execution
        call_count = [0]

        def get_with_cancellation(job_id):
            call_count[0] += 1
            job = JobRecord(**sample_job.__dict__)
            # Cancel after first few calls
            job.cancellation_requested = call_count[0] >= 2
            return job

        mock_job_store.get.side_effect = get_with_cancellation
        mock_job_store.update_state.return_value = True
        mock_job_store.cancel.return_value = True
        mock_job_store.heartbeat.return_value = 1

        worker = JobWorker(
            mock_job_store,
            "worker-test",
            tool_executor=StubToolExecutor(sleep=0.5),
        )

        # Start worker
        worker_task = asyncio.create_task(worker.start())

        # Let it detect cancellation
        await asyncio.sleep(4)

        # Stop worker
        await worker.stop()
        await worker_task

        # Verify job finalized as CANCELLED
        update_calls = mock_job_store.update_state.call_args_list
        cancelled_call = next(
            (c for c in update_calls if c.args[1] == JobState.CANCELLED), None
        )
        assert cancelled_call is not None

        # Verify SUCCEEDED was NOT set after cancellation
        succeeded_after_cancel = any(
            c.args[1] == JobState.SUCCEEDED for c in update_calls
        )
        assert not succeeded_after_cancel, (
            "Job should not be marked SUCCEEDED after cancellation"
        )


class TestWorkerPool:
    """Test worker pool functionality."""

    @pytest.mark.asyncio
    async def test_start_worker_pool(self, mock_job_store):
        """Test starting multiple workers."""
        mock_job_store.claim_next.return_value = None

        stop_event = asyncio.Event()

        # Start pool in background
        pool_task = asyncio.create_task(
            start_worker_pool(mock_job_store, num_workers=3, stop_event=stop_event)
        )

        # Let workers start
        await asyncio.sleep(0.2)

        # Stop pool
        stop_event.set()

        # Wait for completion
        tasks = await pool_task

        assert len(tasks) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
