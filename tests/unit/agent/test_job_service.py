"""Unit tests for job service module."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunAsync:
    """Tests for the _run_async helper function."""

    def test_run_async_no_event_loop(self):
        """_run_async should work when no event loop exists."""
        from brain_researcher.services.agent.job_service import _run_async

        async def simple_coro():
            return "result"

        result = _run_async(simple_coro())
        assert result == "result"

    def test_run_async_with_value(self):
        """_run_async should return the coroutine result."""
        from brain_researcher.services.agent.job_service import _run_async

        async def return_value(val):
            return val * 2

        result = _run_async(return_value(21))
        assert result == 42


class TestAgentJobService:
    """Tests for AgentJobService class."""

    @pytest.fixture
    def mock_job_store(self):
        """Create a mock JobStore."""
        store = MagicMock()
        store.initialize = AsyncMock(return_value=None)
        store.enqueue = AsyncMock(return_value=None)
        store.get = AsyncMock(return_value=None)
        store.list_all = AsyncMock(return_value=[])
        store.cancel = AsyncMock(return_value=True)
        store.iter_logs = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def job_service(self, mock_job_store):
        """Create an AgentJobService with mocked store."""
        from brain_researcher.services.agent.job_service import AgentJobService

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=mock_job_store,
        ):
            service = AgentJobService()
            return service

    def test_create_run_returns_api_format(self, job_service, mock_job_store):
        """create_run should return API-formatted response."""
        result = job_service.create_run(
            plan={"steps": [{"tool": "test"}]},
            user_id="user-123",
            thread_id="thread-abc",
        )

        assert "run_id" in result
        assert result["status"] == "queued"
        assert result["user_id"] == "user-123"
        assert result["thread_id"] == "thread-abc"
        assert result["plan"] == {"steps": [{"tool": "test"}]}

        # Verify enqueue was called
        mock_job_store.enqueue.assert_called_once()

    def test_create_run_rejects_nonexistent_project(self, job_service):
        """create_run should reject explicit non-default projects that do not exist."""
        with pytest.raises(ValueError, match="does not exist"):
            job_service.create_run(
                plan={"steps": []},
                user_id="user-123",
                project_id="missing-project",
            )

    def test_create_run_accepts_existing_project(self, job_service):
        """create_run should accept explicit projects that already exist."""
        project = job_service.create_project(
            user_id="user-123",
            project_id="project-existing",
            name="Existing Project",
        )
        assert project["project_id"] == "project-existing"

        result = job_service.create_run(
            plan={"steps": []},
            user_id="user-123",
            project_id="project-existing",
        )

        assert result["project_id"] == "project-existing"

    def test_create_run_generates_job_id(self, job_service):
        """create_run should generate normalized job IDs for run_id."""
        result = job_service.create_run(plan={}, user_id="user-1")

        # Current format is job_<12 chars>
        run_id = result["run_id"]
        assert run_id.startswith("job_")
        suffix = run_id[len("job_") :]
        assert len(suffix) == 12
        assert suffix.isalnum()

    def test_get_run_existing(self, job_service, mock_job_store):
        """get_run should return API-formatted run for existing job."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        mock_record = JobRecord(
            job_id="run-456",
            kind="plan",
            payload_json='{"test": true}',
            state=JobState.RUNNING,
            user_id="user-789",
            session_id="thread-xyz",
            created_at=1704067200,  # 2024-01-01 00:00:00 UTC
            started_at=1704067210,
        )
        mock_job_store.get = AsyncMock(return_value=mock_record)

        result = job_service.get_run("run-456")

        assert result is not None
        assert result["run_id"] == "run-456"
        assert result["status"] == "running"
        assert result["user_id"] == "user-789"
        assert result["plan"] == {"test": True}

    def test_get_run_not_found(self, job_service, mock_job_store):
        """get_run should return None for nonexistent job."""
        mock_job_store.get = AsyncMock(return_value=None)

        result = job_service.get_run("nonexistent")

        assert result is None

    def test_list_runs_returns_formatted_list(self, job_service, mock_job_store):
        """list_runs should return list of API-formatted runs."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        mock_records = [
            JobRecord(
                job_id="run-1",
                kind="plan",
                payload_json="{}",
                state=JobState.SUCCEEDED,
                user_id="user-1",
                created_at=1704067200,
            ),
            JobRecord(
                job_id="run-2",
                kind="plan",
                payload_json="{}",
                state=JobState.FAILED,
                user_id="user-1",
                created_at=1704067300,
                error_message="Test error",
            ),
        ]
        mock_job_store.list_all = AsyncMock(return_value=mock_records)

        results = job_service.list_runs("user-1", limit=10)

        assert len(results) == 2
        assert results[0]["run_id"] == "run-1"
        assert results[0]["status"] == "completed"
        assert results[1]["run_id"] == "run-2"
        assert results[1]["status"] == "failed"
        assert results[1]["error_message"] == "Test error"

    def test_cancel_run_success(self, job_service, mock_job_store):
        """cancel_run should return True on success."""
        mock_job_store.cancel = AsyncMock(return_value=True)

        result = job_service.cancel_run("run-to-cancel", "User requested")

        assert result is True
        mock_job_store.cancel.assert_called_once_with("run-to-cancel", "User requested")

    def test_cancel_run_failure(self, job_service, mock_job_store):
        """cancel_run should return False on failure."""
        mock_job_store.cancel = AsyncMock(return_value=False)

        result = job_service.cancel_run("invalid-run")

        assert result is False

    def test_get_logs_formats_chunks(self, job_service, mock_job_store):
        """get_logs should format log chunks properly."""
        from brain_researcher.services.orchestrator.job_store import LogChunk

        mock_chunks = [
            LogChunk(
                job_id="run-with-logs",
                stream="stdout",
                offset=0,
                data=b"Line 1\n",
                created_at=1704067200,
            ),
            LogChunk(
                job_id="run-with-logs",
                stream="stderr",
                offset=7,
                data=b"Error!\n",
                created_at=1704067201,
            ),
        ]
        mock_job_store.iter_logs = AsyncMock(return_value=mock_chunks)

        logs = job_service.get_logs("run-with-logs", start_offset=0)

        assert len(logs) == 2
        assert logs[0]["stream"] == "stdout"
        assert logs[0]["offset"] == 0
        assert logs[0]["data"] == "Line 1\n"
        assert logs[1]["stream"] == "stderr"
        assert logs[1]["data"] == "Error!\n"

    def test_get_logs_handles_binary_data(self, job_service, mock_job_store):
        """get_logs should handle non-UTF8 binary data."""
        from brain_researcher.services.orchestrator.job_store import LogChunk

        mock_chunks = [
            LogChunk(
                job_id="binary-run",
                stream="stdout",
                offset=0,
                data=b"\xff\xfe Binary data",
                created_at=1704067200,
            ),
        ]
        mock_job_store.iter_logs = AsyncMock(return_value=mock_chunks)

        logs = job_service.get_logs("binary-run")

        assert len(logs) == 1
        # Should decode with errors='replace'
        assert "Binary data" in logs[0]["data"]


class TestStatusMapping:
    """Tests for JobState to API status mapping."""

    @pytest.fixture
    def job_service(self):
        """Create a job service with mocked store."""
        from brain_researcher.services.agent.job_service import AgentJobService

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=MagicMock(),
        ):
            return AgentJobService()

    def test_pending_maps_to_pending(self, job_service):
        """PENDING state should map to 'pending'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.PENDING, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "pending"

    def test_queued_maps_to_queued(self, job_service):
        """QUEUED state should map to 'queued'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.QUEUED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "queued"

    def test_claimed_maps_to_running(self, job_service):
        """CLAIMED state should map to 'running'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.CLAIMED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "running"

    def test_running_maps_to_running(self, job_service):
        """RUNNING state should map to 'running'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.RUNNING, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "running"

    def test_succeeded_maps_to_completed(self, job_service):
        """SUCCEEDED state should map to 'completed'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.SUCCEEDED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "completed"

    def test_failed_maps_to_failed(self, job_service):
        """FAILED state should map to 'failed'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.FAILED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "failed"

    def test_cancelled_maps_to_cancelled(self, job_service):
        """CANCELLED state should map to 'cancelled'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.CANCELLED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "cancelled"

    def test_timeout_maps_to_timeout(self, job_service):
        """TIMEOUT state should map to 'timeout'."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.TIMEOUT, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["status"] == "timeout"


class TestProgressMapping:
    """Tests for status to progress mapping."""

    @pytest.fixture
    def job_service(self):
        """Create a job service with mocked store."""
        from brain_researcher.services.agent.job_service import AgentJobService

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=MagicMock(),
        ):
            return AgentJobService()

    def test_pending_progress_is_zero(self, job_service):
        """Pending status should have 0.0 progress."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.PENDING, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["progress"] == 0.0

    def test_running_progress_is_half(self, job_service):
        """Running status should have 0.5 progress."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.RUNNING, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["progress"] == 0.5

    def test_completed_progress_is_one(self, job_service):
        """Completed status should have 1.0 progress."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="test", kind="plan", payload_json="{}",
            state=JobState.SUCCEEDED, created_at=0
        )
        result = job_service._to_api_format(record)
        assert result["progress"] == 1.0


class TestSingletonInstance:
    """Tests for singleton get_job_service() function."""

    def test_get_job_service_returns_instance(self):
        """get_job_service should return an AgentJobService instance."""
        from brain_researcher.services.agent.job_service import get_job_service

        # Reset singleton for test isolation
        import brain_researcher.services.agent.job_service as module
        module._job_service = None

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=MagicMock(),
        ):
            service = get_job_service()

        assert service is not None

    def test_get_job_service_is_singleton(self):
        """Multiple calls should return the same instance."""
        from brain_researcher.services.agent.job_service import get_job_service

        # Reset singleton for test isolation
        import brain_researcher.services.agent.job_service as module
        module._job_service = None

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=MagicMock(),
        ):
            service1 = get_job_service()
            service2 = get_job_service()

        assert service1 is service2


class TestAPIFormatFields:
    """Tests for complete API format fields."""

    @pytest.fixture
    def job_service(self):
        """Create a job service with mocked store."""
        from brain_researcher.services.agent.job_service import AgentJobService

        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_initialized_job_store",
            return_value=MagicMock(),
        ):
            return AgentJobService()

    def test_all_fields_present(self, job_service):
        """API format should include all required fields."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="complete-run",
            kind="plan",
            payload_json='{"workflow": "test"}',
            state=JobState.SUCCEEDED,
            user_id="test-user",
            session_id="test-session",
            created_at=1704067200,
            queued_at=1704067201,
            started_at=1704067202,
            finished_at=1704067300,
            error_message=None,
        )

        result = job_service._to_api_format(record)

        # Required fields
        assert "run_id" in result
        assert "status" in result
        assert "progress" in result
        assert "plan" in result
        assert "user_id" in result
        assert "thread_id" in result
        assert "created_at" in result
        assert "started_at" in result
        assert "finished_at" in result
        assert "error_message" in result

        # Values
        assert result["run_id"] == "complete-run"
        assert result["plan"] == {"workflow": "test"}
        assert result["thread_id"] == "test-session"

    def test_empty_payload_json_returns_empty_dict(self, job_service):
        """Empty payload_json should return empty dict for plan."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="no-plan",
            kind="plan",
            payload_json="",  # Empty string
            state=JobState.QUEUED,
            created_at=0,
        )

        result = job_service._to_api_format(record)
        assert result["plan"] == {}

    def test_null_payload_json_returns_empty_dict(self, job_service):
        """Null payload_json should return empty dict for plan."""
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        record = JobRecord(
            job_id="null-plan",
            kind="plan",
            payload_json=None,
            state=JobState.QUEUED,
            created_at=0,
        )

        result = job_service._to_api_format(record)
        assert result["plan"] == {}
