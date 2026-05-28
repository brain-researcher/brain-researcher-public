"""Unit tests for Jobs management tools."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from brain_researcher.services.tools.jobs_tool import (
    ListUserJobsTool,
    GetJobStatusTool,
    GetJobLogsTool,
    SubmitJobTool,
    CancelJobTool,
    JobsTools,
    _timestamp_to_iso,
    _detect_queue_backend,
)


class TestHelperFunctions:
    """Test helper functions."""

    def test_timestamp_to_iso_none(self):
        assert _timestamp_to_iso(None) is None

    def test_timestamp_to_iso_valid(self):
        ts = 1700000000
        result = _timestamp_to_iso(ts)
        assert result.endswith("Z")
        assert "2023" in result

    def test_detect_queue_backend_with_env_override(self):
        with patch.dict("os.environ", {"BR_JOB_BACKEND": "slurm"}):
            assert _detect_queue_backend() == "slurm"

    def test_detect_queue_backend_auto(self):
        with patch.dict("os.environ", {"BR_JOB_BACKEND": "auto"}):
            with patch("shutil.which") as mock_which:
                mock_which.return_value = None
                assert _detect_queue_backend() == "local"


class TestListUserJobsTool:
    """Test list user jobs functionality."""

    @pytest.fixture
    def tool(self):
        return ListUserJobsTool()

    @pytest.fixture
    def mock_job_store(self):
        """Create a mock job store."""
        mock_store = MagicMock()
        mock_store.list_all = AsyncMock(return_value=[])
        mock_store.list_by_state = AsyncMock(return_value=[])
        return mock_store

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "jobs.list_user_jobs"
        assert "jobs" in tool.TAGS
        assert not getattr(tool, "DANGEROUS", False)

    def test_list_jobs_empty(self, tool, mock_job_store):
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_job_store
            result = tool._run()
            assert result.status == "success"
            assert result.data["items"] == []
            assert result.data["total"] == 0

    def test_list_jobs_with_state_filter(self, tool, mock_job_store):
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_job_store
            result = tool._run(state="running")
            mock_job_store.list_by_state.assert_called_once()

    def test_args_schema(self, tool):
        schema = tool.get_args_schema()
        assert schema.__name__ == "ListUserJobsArgs"


class TestGetJobStatusTool:
    """Test get job status functionality."""

    @pytest.fixture
    def tool(self):
        return GetJobStatusTool()

    @pytest.fixture
    def mock_job_record(self):
        """Create a mock job record."""
        record = MagicMock()
        record.job_id = "test-job-123"
        record.kind = "fmriprep"
        record.state = "running"
        record.priority = 5
        record.attempt = 1
        record.max_attempts = 3
        record.exit_code = None
        record.error_message = None
        record.worker_id = "worker-1"
        record.user_id = "user-1"
        record.run_id = "run-123"
        record.run_dir = "/runs/run-123"
        record.created_at = 1700000000
        record.queued_at = 1700000100
        record.claimed_at = 1700000200
        record.started_at = 1700000300
        record.finished_at = None
        record.gpu_req = 0
        record.gpu_type = None
        record.cancellation_requested = False
        record.cancel_reason = None
        return record

    @pytest.fixture
    def mock_job_store(self, mock_job_record):
        mock_store = MagicMock()
        mock_store.get = AsyncMock(return_value=mock_job_record)
        return mock_store

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "jobs.get_job_status"
        assert "jobs" in tool.TAGS

    def test_get_status_success(self, tool, mock_job_store):
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_job_store
            result = tool._run(job_id="test-job-123")
            assert result.status == "success"
            assert result.data["job_id"] == "test-job-123"
            assert result.data["state"] == "running"

    def test_get_status_not_found(self, tool):
        mock_store = MagicMock()
        mock_store.get = AsyncMock(return_value=None)
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_store
            result = tool._run(job_id="nonexistent")
            assert result.status == "error"
            assert "not found" in result.error.lower()

    def test_get_status_with_timing(self, tool, mock_job_store):
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_job_store
            result = tool._run(job_id="test-job-123", include_timing=True)
            assert "timing" in result.data
            assert "created_at" in result.data["timing"]


class TestGetJobLogsTool:
    """Test get job logs functionality."""

    @pytest.fixture
    def tool(self):
        return GetJobLogsTool()

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "jobs.get_job_logs"
        assert "debugging" in tool.TAGS

    def test_args_schema(self, tool):
        schema = tool.get_args_schema()
        assert schema.__name__ == "GetJobLogsArgs"


class TestSubmitJobTool:
    """Test job submission functionality."""

    @pytest.fixture
    def tool(self):
        return SubmitJobTool()

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "jobs.submit"
        assert tool.DANGEROUS is True
        assert tool.COST_HINT == "expensive"

    def test_dry_run(self, tool):
        result = tool._run(
            pipeline="fmriprep",
            dataset_id="ds000001",
            dry_run=True,
        )
        assert result.status == "success"
        assert result.data["dry_run"] is True
        assert "job_id" in result.data
        assert result.data["message"] == "Dry run - job not actually submitted"

    def test_dry_run_with_resources(self, tool):
        result = tool._run(
            pipeline="fmriprep",
            dataset_id="ds000001",
            cpus=4,
            memory_gb=16.0,
            gpus=1,
            walltime_minutes=120,
            dry_run=True,
        )
        assert result.status == "success"
        assert result.data["payload"]["resources"]["cpus"] == 4
        assert result.data["payload"]["resources"]["memory_gb"] == 16.0
        assert result.data["payload"]["resources"]["gpus"] == 1


class TestCancelJobTool:
    """Test job cancellation functionality."""

    @pytest.fixture
    def tool(self):
        return CancelJobTool()

    @pytest.fixture
    def mock_job_store(self):
        mock_store = MagicMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job"
        mock_store.get = AsyncMock(return_value=mock_job)
        mock_store.cancel = AsyncMock(return_value=True)
        return mock_store

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "jobs.cancel"
        assert tool.DANGEROUS is True

    def test_cancel_success(self, tool, mock_job_store):
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_job_store
            result = tool._run(job_id="test-job", reason="Testing")
            assert result.status == "success"
            assert result.data["cancelled"] is True

    def test_cancel_not_found(self, tool):
        mock_store = MagicMock()
        mock_store.get = AsyncMock(return_value=None)
        with patch(
            "brain_researcher.services.orchestrator.job_store_factory.get_job_store"
        ) as mock_get:
            mock_get.return_value = mock_store
            result = tool._run(job_id="nonexistent")
            assert result.status == "error"
            assert "not found" in result.error.lower()


class TestJobsToolsFactory:
    """Test the tools factory."""

    def test_get_all_tools(self):
        factory = JobsTools()
        tools = factory.get_all_tools()
        assert len(tools) == 5

        tool_names = [t.get_tool_name() for t in tools]
        assert "jobs.list_user_jobs" in tool_names
        assert "jobs.get_job_status" in tool_names
        assert "jobs.get_job_logs" in tool_names
        assert "jobs.submit" in tool_names
        assert "jobs.cancel" in tool_names

    def test_dangerous_tools_flagged(self):
        factory = JobsTools()
        tools = factory.get_all_tools()

        dangerous_count = sum(1 for t in tools if getattr(t, "DANGEROUS", False))
        assert dangerous_count == 2  # submit and cancel
