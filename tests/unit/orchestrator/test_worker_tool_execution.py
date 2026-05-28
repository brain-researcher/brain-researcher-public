"""
Unit tests for JobWorker tool execution with provenance tracking.

Tests that the worker correctly:
1. Executes tools via ToolExecutor
2. Extracts provenance metadata (run_id, run_dir, provenance_path)
3. Maps ToolExecutionResult.status to exit codes
4. Persists provenance fields to JobStore
5. Respects cancel-wins finalization rule
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from brain_researcher.config.retry_settings import clear_settings_cache
from brain_researcher.core.gates.engine import GateEngine
from brain_researcher.services.orchestrator import worker as worker_module
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker


class MockToolExecutor:
    """Mock ToolExecutor for testing."""

    def __init__(self, result_status="success", include_provenance=True):
        """
        Initialize mock executor.

        Args:
            result_status: Status to return ("success", "error", "timeout", "cancelled")
            include_provenance: Whether to include provenance metadata
        """
        self.result_status = result_status
        self.include_provenance = include_provenance
        self.executed_requests = []

    def execute(self, request):
        """Mock execute method."""
        self.executed_requests.append(request)

        # Create mock result
        from brain_researcher.services.agent.tool_executor import ToolExecutionResult

        metadata = {}
        if self.include_provenance:
            metadata = {
                "run_id": f"run_{request.execution_id}",
                "run_dir": f"/tmp/runs/{request.execution_id}",
                "provenance_path": f"/tmp/runs/{request.execution_id}/provenance.json",
                "mode": "direct_execution",
            }

        error = (
            None
            if self.result_status == "success"
            else f"Mock {self.result_status} error"
        )

        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status=self.result_status,
            result={"mock": "result"},
            error=error,
            execution_time=0.1,
            metadata=metadata,
        )


class TestWorkerToolExecution:
    """Test worker tool execution with provenance."""

    @pytest.mark.asyncio
    async def test_worker_executes_shell_command_with_provenance(self):
        """Test worker executes shell command and captures provenance."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-1", tool_executor=mock_executor
        )

        # Create job with shell command
        payload = {
            "command": 'echo "test"',
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_shell_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify execution
        assert len(mock_executor.executed_requests) == 1
        request = mock_executor.executed_requests[0]
        assert request.execution_id == "job_shell_001"
        assert request.parameters["command"] == 'echo "test"'
        assert request.context["job_store"] == job_store
        assert request.context["job_id"] == "job_shell_001"

        # Verify job state and provenance
        final_job = await job_store.get("job_shell_001")
        assert final_job.state == JobState.SUCCEEDED
        assert final_job.run_id == "run_job_shell_001"
        assert final_job.run_dir == "/tmp/runs/job_shell_001"
        assert final_job.provenance_path == "/tmp/runs/job_shell_001/provenance.json"
        assert final_job.exit_code == 0

        print("✓ Shell command execution with provenance works")

    @pytest.mark.asyncio
    async def test_worker_emits_artifact_written_events_for_tool_runs(
        self, tmp_path: Path
    ):
        job_store = MemoryJobStore(total_gpu_slots=2)

        run_dir = tmp_path / "runs" / "job_artifacts_001"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stdout.txt").write_text("stdout", encoding="utf-8")
        (run_dir / "stderr.txt").write_text("stderr", encoding="utf-8")
        (run_dir / "provenance.json").write_text("{}", encoding="utf-8")
        (run_dir / "hash.json").write_text("{}", encoding="utf-8")

        class MockToolExecutorWithRunDir(MockToolExecutor):
            def execute(self, request):
                res = super().execute(request)
                res.metadata["run_dir"] = str(run_dir)
                res.metadata["provenance_path"] = str(run_dir / "provenance.json")
                return res

        worker = JobWorker(
            job_store,
            worker_id="test-worker-artifacts",
            tool_executor=MockToolExecutorWithRunDir(result_status="success"),
        )

        payload = {
            "command": 'echo "test"',
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_artifacts_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        await worker._execute_job(job)

        events = await job_store.list_events("job_artifacts_001")
        artifact_events = [ev for ev in events if ev.event_type == "artifact.written"]
        assert artifact_events

        artifact_uris = {
            (ev.payload.get("artifact") or {}).get("uri")
            for ev in artifact_events
            if isinstance(ev.payload, dict)
        }
        assert {"stdout.txt", "stderr.txt", "provenance.json", "hash.json"}.issubset(
            artifact_uris
        )

        trace_path = run_dir / "trace.jsonl"
        assert trace_path.exists()
        trace_lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        assert trace_lines

        from pydantic import TypeAdapter

        from brain_researcher.core.contracts.analysis_stream import (
            AnalysisStreamEventV1,
        )

        adapter = TypeAdapter(AnalysisStreamEventV1)
        parsed = [adapter.validate_python(json.loads(line)) for line in trace_lines]
        assert any(e.event_type == "artifact.written" for e in parsed)

    @pytest.mark.asyncio
    async def test_worker_maps_error_status_correctly(self, monkeypatch):
        """Test worker maps error status to exit_code=1."""
        # Disable retry system for this test (P2.6)
        monkeypatch.setenv("BR_RETRY_ENABLED", "false")
        clear_settings_cache()  # Clear cache to pick up new env var

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="error")
        worker = JobWorker(
            job_store, worker_id="test-worker-2", tool_executor=mock_executor
        )

        # Create job
        payload = {
            "command": "invalid_command",
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_error_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify job state
        final_job = await job_store.get("job_error_001")
        assert final_job.state == JobState.FAILED
        assert final_job.exit_code == 1
        assert "error" in final_job.error_message.lower()
        # Provenance should still be captured even on error
        assert final_job.run_id == "run_job_error_001"

        print("✓ Error status mapping works")

    @pytest.mark.asyncio
    async def test_worker_maps_timeout_status_correctly(self, monkeypatch):
        """Test worker maps timeout status to exit_code=124."""
        # Disable retry system for this test (P2.6)
        monkeypatch.setenv("BR_RETRY_ENABLED", "false")
        clear_settings_cache()  # Clear cache to pick up new env var

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="timeout")
        worker = JobWorker(
            job_store, worker_id="test-worker-3", tool_executor=mock_executor
        )

        # Create job
        payload = {
            "command": "sleep 1000",
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_timeout_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify job state
        final_job = await job_store.get("job_timeout_001")
        assert final_job.state == JobState.TIMEOUT
        assert final_job.exit_code == 124
        assert "timeout" in final_job.error_message.lower()

        print("✓ Timeout status mapping works")

    @pytest.mark.asyncio
    async def test_worker_executes_tool_by_name(self):
        """Test worker executes registered tool by name."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-4", tool_executor=mock_executor
        )

        # Create job with tool name
        payload = {
            "tool_name": "example_tool",
            "parameters": {"arg1": "value1", "arg2": "value2"},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_tool_001",
            kind="tool_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify execution
        assert len(mock_executor.executed_requests) == 1
        request = mock_executor.executed_requests[0]
        assert request.tool_name == "example_tool"
        assert request.parameters == {"arg1": "value1", "arg2": "value2"}

        # Verify success
        final_job = await job_store.get("job_tool_001")
        assert final_job.state == JobState.SUCCEEDED

        print("✓ Tool execution by name works")

    @pytest.mark.asyncio
    async def test_worker_blocks_on_existing_metadata_violation(
        self, monkeypatch, tmp_path: Path
    ):
        """Blocking violations in tool metadata should fail the job."""
        monkeypatch.setenv("BR_RETRY_ENABLED", "true")
        clear_settings_cache()

        class ViolationExecutor(MockToolExecutor):
            def execute(self, request):
                from brain_researcher.services.agent.tool_executor import (
                    ToolExecutionResult,
                )

                run_dir = tmp_path / request.execution_id
                run_dir.mkdir(parents=True, exist_ok=True)
                metadata = {
                    "run_id": f"run_{request.execution_id}",
                    "run_dir": str(run_dir),
                    "provenance_path": str(run_dir / "provenance.json"),
                    "mode": "direct_execution",
                    "violations": [
                        {"code": "V_BLOCK", "message": "blocked", "blocking": True}
                    ],
                }
                return ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name,
                    status="success",
                    result={"mock": "result"},
                    error=None,
                    execution_time=0.1,
                    metadata=metadata,
                )

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = ViolationExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-block", tool_executor=mock_executor
        )

        payload = {
            "tool_name": "example_tool",
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_block_001",
            kind="tool_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        await worker._execute_job(job)

        final_job = await job_store.get("job_block_001")
        assert final_job.state == JobState.FAILED
        assert final_job.exit_code == 1
        assert "Postcheck blocked" in (final_job.error_message or "")

    @pytest.mark.asyncio
    async def test_worker_blocks_on_gate_violation(self, monkeypatch, tmp_path: Path):
        """Blocking gate rules at postcheck should fail single-tool jobs."""
        monkeypatch.setenv("BR_RETRY_ENABLED", "true")
        clear_settings_cache()

        class GateViolationExecutor(MockToolExecutor):
            def execute(self, request):
                from brain_researcher.services.agent.tool_executor import (
                    ToolExecutionResult,
                )

                run_dir = tmp_path / request.execution_id
                run_dir.mkdir(parents=True, exist_ok=True)
                metadata = {
                    "run_id": f"run_{request.execution_id}",
                    "run_dir": str(run_dir),
                    "provenance_path": str(run_dir / "provenance.json"),
                    "mode": "direct_execution",
                    # Triggers QC_MEAN_FD_HIGH in configs/gates.yaml
                    "qc": {"motion": {"mean_fd": 0.8}},
                }
                return ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name,
                    status="success",
                    result={"mock": "result"},
                    error=None,
                    execution_time=0.1,
                    metadata=metadata,
                )

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = GateViolationExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-gate-block", tool_executor=mock_executor
        )
        gate_path = worker_module._resolve_gate_config_path()
        assert gate_path is not None and gate_path.exists()
        worker.gate_engine = GateEngine.from_yaml(gate_path)

        payload = {
            "tool_name": "example_tool",
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_block_gate_001",
            kind="tool_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        await worker._execute_job(job)

        final_job = await job_store.get("job_block_gate_001")
        assert final_job.state == JobState.FAILED
        assert final_job.exit_code == 1
        assert "Postcheck blocked" in (final_job.error_message or "")
        data = json.loads(final_job.payload_json or "{}")
        violations = (data.get("metadata") or {}).get("violations") or []
        assert any(v.get("code") == "QC_MEAN_FD_HIGH" for v in violations)

    @pytest.mark.asyncio
    async def test_worker_runs_tool_executor_off_thread(self):
        """Worker should dispatch ToolExecutor.execute via run_in_executor."""
        job_store = MemoryJobStore(total_gpu_slots=2)

        class StubExecutor:
            def __init__(self):
                self.execute = Mock(name="execute")

            def cancel(self, execution_id: str):
                pass

        stub_executor = StubExecutor()
        worker = JobWorker(
            job_store,
            worker_id="test-worker-thread",
            tool_executor=stub_executor,
        )

        payload = {
            "command": 'echo "async test"',
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_async_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        from brain_researcher.services.agent.tool_executor import ToolExecutionResult

        tool_result = ToolExecutionResult(
            execution_id=job.job_id,
            tool_name="shell_command",
            status="success",
            result={"mock": "result"},
            execution_time=0.05,
            metadata={
                "run_id": f"run_{job.job_id}",
                "run_dir": f"/tmp/runs/{job.job_id}",
                "provenance_path": f"/tmp/runs/{job.job_id}/provenance.json",
            },
        )

        run_in_executor_mock = AsyncMock(return_value=tool_result)
        loop_namespace = SimpleNamespace(run_in_executor=run_in_executor_mock)

        with patch(
            "brain_researcher.services.orchestrator.worker.asyncio.get_running_loop",
            return_value=loop_namespace,
        ) as get_loop_mock:
            await worker._execute_job(job)

        get_loop_mock.assert_called_once()
        run_in_executor_mock.assert_awaited_once()
        args, kwargs = run_in_executor_mock.await_args
        assert args[0] is None
        assert args[1] is stub_executor.execute

        final_job = await job_store.get("job_async_001")
        assert final_job.state == JobState.SUCCEEDED
        assert final_job.run_id == f"run_{job.job_id}"
        assert final_job.provenance_path == f"/tmp/runs/{job.job_id}/provenance.json"

        print("✓ Worker dispatches ToolExecutor via run_in_executor")

    @pytest.mark.asyncio
    async def test_worker_handles_cancel_during_execution(self):
        """Test worker detects cancellation and stops before execution."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-5", tool_executor=mock_executor
        )

        # Create job
        payload = {
            "command": 'echo "test"',
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_cancel_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Get the job for execution (simulating worker claiming it)
        job = await job_store.get("job_cancel_001")

        # Mark job as running
        await job_store.update_state("job_cancel_001", JobState.RUNNING)

        # Request cancellation before finalization
        await job_store.cancel("job_cancel_001", "User cancelled")

        # Execute job (will detect cancellation and stop before execution)
        await worker._execute_job(job)

        # Verify cancellation was detected
        final_job = await job_store.get("job_cancel_001")
        # State may be CANCELLED or CANCELLING depending on timing
        assert final_job.state in [JobState.CANCELLED, JobState.CANCELLING]
        assert final_job.cancellation_requested or final_job.cancel_reason is not None
        # Tool should not have been executed (early detection)
        assert len(mock_executor.executed_requests) == 0

        print("✓ Early cancellation detection works")

    @pytest.mark.asyncio
    async def test_worker_cancel_wins_after_execution(self):
        """Test cancel-wins rule when cancellation happens after execution completes."""
        job_store = MemoryJobStore(total_gpu_slots=2)

        # Use a mock that doesn't immediately execute
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-5b", tool_executor=mock_executor
        )

        # Create job
        payload = {
            "command": 'echo "test"',
            "parameters": {},
            "execution_mode": "direct_execution",
        }
        job = JobRecord(
            job_id="job_cancel_002",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.RUNNING,  # Already running
            priority=5,
        )
        await job_store.enqueue(job)

        # Get the job
        job = await job_store.get("job_cancel_002")

        # Manually patch the finalize to simulate race condition
        original_finalize = worker._finalize_job

        async def finalize_with_cancel(*args, **kwargs):
            # Request cancel BEFORE finalization completes
            await job_store.cancel(
                "job_cancel_002", "User cancelled during finalization"
            )
            # Continue with original finalization
            return await original_finalize(*args, **kwargs)

        worker._finalize_job = finalize_with_cancel

        # Execute job
        await worker._execute_job(job)

        # Verify cancel-wins applied
        final_job = await job_store.get("job_cancel_002")
        assert final_job.state == JobState.CANCELLED
        # Exit code and provenance should be preserved
        assert final_job.exit_code == 0
        assert final_job.run_id == "run_job_cancel_002"

        print("✓ Cancel-wins rule after execution works")

    @pytest.mark.asyncio
    async def test_worker_handles_invalid_payload(self, monkeypatch):
        """Test worker handles invalid JSON payload gracefully."""
        # Disable retry system for this test (P2.6)
        monkeypatch.setenv("BR_RETRY_ENABLED", "false")
        clear_settings_cache()  # Clear cache to pick up new env var

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-6", tool_executor=mock_executor
        )

        # Create job with invalid JSON
        job = JobRecord(
            job_id="job_invalid_001",
            kind="shell_command",
            payload_json="invalid json {",
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify error handling
        final_job = await job_store.get("job_invalid_001")
        assert final_job.state == JobState.FAILED
        assert final_job.exit_code == 1
        assert "Invalid job payload JSON" in final_job.error_message

        print("✓ Invalid payload handling works")

    @pytest.mark.asyncio
    async def test_worker_handles_missing_tool_name(self, monkeypatch):
        """Test worker handles missing tool_name/command gracefully."""
        # Disable retry system for this test (P2.6)
        monkeypatch.setenv("BR_RETRY_ENABLED", "false")
        clear_settings_cache()  # Clear cache to pick up new env var

        job_store = MemoryJobStore(total_gpu_slots=2)
        mock_executor = MockToolExecutor(result_status="success")
        worker = JobWorker(
            job_store, worker_id="test-worker-7", tool_executor=mock_executor
        )

        # Create job without tool_name or command
        payload = {"parameters": {}, "execution_mode": "direct_execution"}
        job = JobRecord(
            job_id="job_missing_001",
            kind="shell_command",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            priority=5,
        )
        await job_store.enqueue(job)

        # Execute job
        await worker._execute_job(job)

        # Verify error handling
        final_job = await job_store.get("job_missing_001")
        assert final_job.state == JobState.FAILED
        assert final_job.exit_code == 1
        assert "Missing tool_name or command" in final_job.error_message

        print("✓ Missing tool_name handling works")

    @pytest.mark.asyncio
    async def test_worker_without_tool_executor_uses_stub(self):
        """Test worker falls back to stub execution when ToolExecutor unavailable."""
        job_store = MemoryJobStore(total_gpu_slots=2)

        # Patch TOOL_EXECUTOR_AVAILABLE to False to simulate unavailable executor
        with patch(
            "brain_researcher.services.orchestrator.worker.TOOL_EXECUTOR_AVAILABLE",
            False,
        ):
            worker = JobWorker(job_store, worker_id="test-worker-8", tool_executor=None)

            # Create job
            payload = {
                "command": 'echo "test"',
                "parameters": {},
                "execution_mode": "direct_execution",
            }
            job = JobRecord(
                job_id="job_stub_001",
                kind="shell_command",
                payload_json=json.dumps(payload),
                state=JobState.QUEUED,
                priority=5,
            )
            await job_store.enqueue(job)

            # Get the job for execution
            job = await job_store.get("job_stub_001")

            # Execute job (should use stub)
            await worker._execute_job(job)

            # Verify stub execution completed
            final_job = await job_store.get("job_stub_001")
            assert final_job.state == JobState.SUCCEEDED
            assert final_job.exit_code == 0
            # No provenance from stub
            assert final_job.run_id is None

            print("✓ Stub execution fallback works")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
