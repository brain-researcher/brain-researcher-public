"""
Unit tests for GET /api/jobs/{id}/plan endpoint (P4.9 Planner Explainability).

Tests cover:
- Plan retrieval from job metadata (fast path)
- Plan retrieval from provenance.json (persistent path)
- Hybrid fallback (metadata → provenance)
- Error handling (job not found, plan not available, invalid JSON)
- Path security validation
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, patch, mock_open
from fastapi import HTTPException
from types import SimpleNamespace

from brain_researcher.services.orchestrator.job_management_endpoints import (
    get_job_plan,
    get_job_plan_of_record,
    get_job_plan_events,
    _hydrate_plan_metadata,
    search_jobs,
    JobSearchRequest,
    Job,
    jobs_db,
)
from brain_researcher.services.orchestrator.job_state import jobs_db as core_jobs_db


# Sample plan data for testing
SAMPLE_PLAN = {
    "intent": "skull strip",
    "candidates": [
        {
            "tool_id": "fsl.bet",
            "tool_name": "bet",
            "score": 0.85,
            "image": "/cvmfs/fsl/bet.simg",
            "preflight_ok": True,
            "preflight_report": None,
            "reason": "All checks passed"
        },
        {
            "tool_id": "afni.3dSkullStrip",
            "tool_name": "3dSkullStrip",
            "score": 0.79,
            "image": "/cvmfs/afni/3dSkullStrip.simg",
            "preflight_ok": False,
            "preflight_report": {"ok": False, "blockers": [{"check": "image", "ok": False}]},
            "reason": "Container image not found"
        }
    ],
    "chosen": {
        "tool_id": "fsl.bet",
        "tool_name": "bet",
        "score": 0.85,
        "image": "/cvmfs/fsl/bet.simg",
        "preflight_ok": True,
        "preflight_report": None,
        "reason": "All checks passed"
    },
    "plan_id": "plan_abc123",
    "constraints": {"input": "/data/brain.nii.gz"}
}


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object with app state."""
    request = Mock()
    request.app.state.job_store = Mock()
    # Make get() async-compatible
    request.app.state.job_store.get = AsyncMock()
    return request


@pytest.fixture
def mock_job_with_plan():
    """Mock Job object with planner trace in metadata."""
    job = Mock(spec=Job)
    job.metadata = {"planner_trace": SAMPLE_PLAN}
    return job


@pytest.fixture
def mock_job_without_plan():
    """Mock Job object without planner trace."""
    job = Mock(spec=Job)
    job.metadata = {}
    return job


@pytest.fixture
def mock_job_record_with_provenance(tmp_path):
    """Mock JobRecord with provenance_path."""
    # Create a temporary provenance file
    provenance_file = tmp_path / "provenance.json"
    provenance_data = {
        "run_id": "run_123",
        "state": "succeeded",
        "plan": SAMPLE_PLAN
    }
    provenance_file.write_text(json.dumps(provenance_data))

    job_record = Mock()
    job_record.provenance_path = str(provenance_file)
    return job_record


@pytest.fixture
def mock_job_record_without_provenance():
    """Mock JobRecord without provenance_path."""
    job_record = Mock()
    job_record.provenance_path = None
    return job_record


class TestGetJobPlanFromMetadata:
    """Test plan retrieval from job metadata (fast path)."""

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    async def test_plan_available_from_metadata(
        self, mock_get_job, mock_request, mock_job_with_plan
    ):
        """Test successful plan retrieval from job metadata."""
        mock_get_job.return_value = mock_job_with_plan

        result = await get_job_plan("job_123", mock_request)

        assert result == SAMPLE_PLAN
        assert result["intent"] == "skull strip"
        assert len(result["candidates"]) == 2
        assert result["chosen"]["tool_id"] == "fsl.bet"
        mock_get_job.assert_called_once_with("job_123")
        # Should not access job_store if found in metadata
        mock_request.app.state.job_store.get.assert_not_called()

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    async def test_metadata_exists_but_no_planner_trace(
        self, mock_get_job, mock_request, mock_job_without_plan
    ):
        """Test fallback when metadata exists but no planner_trace."""
        mock_get_job.return_value = mock_job_without_plan
        mock_request.app.state.job_store.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert exc_info.value.status_code == 404
        assert "Job not found" in exc_info.value.detail


class TestGetJobPlanFromProvenance:
    """Test plan retrieval from provenance.json (persistent path)."""

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_plan_available_from_provenance(
        self, mock_config, mock_validate, mock_get_job,
        mock_request, mock_job_record_with_provenance
    ):
        """Test successful plan retrieval from provenance.json."""
        mock_get_job.return_value = None  # Not in memory
        mock_request.app.state.job_store.get.return_value = mock_job_record_with_provenance
        mock_config.return_value.root.resolve.return_value = Path("/tmp")

        result = await get_job_plan("job_123", mock_request)

        assert result == SAMPLE_PLAN
        assert result["intent"] == "skull strip"
        mock_validate.assert_called_once()

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    async def test_job_not_found(self, mock_get_job, mock_request):
        """Test 404 when job doesn't exist."""
        mock_get_job.return_value = None
        mock_request.app.state.job_store.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("nonexistent_job", mock_request)

        assert exc_info.value.status_code == 404
        assert "Job not found" in exc_info.value.detail

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    async def test_plan_not_available_no_provenance_path(
        self, mock_get_job, mock_request, mock_job_record_without_provenance
    ):
        """Test 404 when job has no provenance_path."""
        mock_get_job.return_value = None
        mock_request.app.state.job_store.get.return_value = mock_job_record_without_provenance

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert exc_info.value.status_code == 404
        assert "Plan not available" in exc_info.value.detail
        assert "not have used planner or has not completed" in exc_info.value.detail


class TestPlanOfRecordEndpoints:
    """Tests for plan-of-record and event endpoints."""

    @pytest.mark.asyncio
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_job_with_store")
    async def test_plan_of_record_success(self, mock_get_job, mock_request):
        plan = {"plan_id": "plan_stub"}
        job = SimpleNamespace(plan_of_record=plan, plan_events=[{"event": "step_started"}], por_token="token", metadata={})
        mock_get_job.return_value = job

        result = await get_job_plan_of_record("job_123", mock_request)

        assert result.plan == plan
        assert result.por_token == "token"
        mock_get_job.assert_called_once()

    @pytest.mark.asyncio
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_job_with_store")
    async def test_plan_of_record_missing(self, mock_get_job, mock_request):
        job = SimpleNamespace(plan_of_record=None, plan_events=[], por_token=None, metadata={})
        mock_get_job.return_value = job

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan_of_record("job_123", mock_request)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_job_with_store")
    async def test_plan_events_success(self, mock_get_job, mock_request):
        plan = {"plan_id": "plan_stub"}
        events = [{"event": "step_started", "data": {"step_id": "s1"}}]
        job = SimpleNamespace(plan_of_record=plan, plan_events=events, por_token=None, metadata={})
        mock_get_job.return_value = job

        result = await get_job_plan_events("job_123", mock_request)

        assert result.plan_id == "plan_stub"
        assert result.events == events

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_provenance_file_not_found(
        self, mock_config, mock_validate, mock_get_job, mock_request, tmp_path
    ):
        """Test 404 when provenance file doesn't exist."""
        mock_get_job.return_value = None

        # Create job record with non-existent provenance path
        job_record = Mock()
        job_record.provenance_path = str(tmp_path / "nonexistent.json")
        mock_request.app.state.job_store.get.return_value = job_record
        mock_config.return_value.root.resolve.return_value = tmp_path

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert exc_info.value.status_code == 404
        assert "Provenance file not found" in exc_info.value.detail


class TestSearchJobsPlanSummary:
    """Verify job search payloads surface plan summary metadata."""

    @pytest.mark.asyncio
    async def test_search_jobs_includes_plan_summary(self):
        job_id = "job_plan_summary"
        jobs_db.clear()
        core_jobs_db.clear()
        job = Job(
            id=job_id,
            prompt="an fmri connectivity run",
            plan_of_record={
                "plan_id": "plan_stub",
                "version": 1,
                "resolvable": True,
                "dag": {"steps": [{"id": "s1"}, {"id": "s2"}]},
            },
            plan_events=[{"event": "step_completed", "data": {"id": "s2"}}],
            metadata={},
        )
        jobs_db[job_id] = job

        try:
            response = await search_jobs(JobSearchRequest(limit=10, offset=0))
        finally:
            jobs_db.pop(job_id, None)

        assert response["total"] == 1
        job_payload = response["jobs"][0]
        summary = job_payload["plan_summary"]
        assert summary["plan_id"] == "plan_stub"
        assert summary["plan_status"] == "step_completed"
        assert summary["step_count"] == 2
        assert summary["por_token_set"] is False

    @pytest.mark.asyncio
    async def test_search_jobs_without_plan_summary(self):
        job_id = "job_without_plan"
        jobs_db.clear()
        core_jobs_db.clear()
        job = Job(
            id=job_id,
            prompt="legacy run",
            metadata={},
        )
        jobs_db[job_id] = job

        try:
            response = await search_jobs(JobSearchRequest(limit=10, offset=0))
        finally:
            jobs_db.pop(job_id, None)

        job_payload = response["jobs"][0]
        assert "plan_summary" not in job_payload
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_provenance_missing_plan_key(
        self, mock_config, mock_validate, mock_get_job, mock_request, tmp_path
    ):
        """Test 404 when provenance.json exists but has no plan key."""
        mock_get_job.return_value = None

        # Create provenance file without plan key
        provenance_file = tmp_path / "provenance.json"
        provenance_file.write_text(json.dumps({"run_id": "run_123", "state": "succeeded"}))

        job_record = Mock()
        job_record.provenance_path = str(provenance_file)
        mock_request.app.state.job_store.get.return_value = job_record
        mock_config.return_value.root.resolve.return_value = tmp_path

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert exc_info.value.status_code == 404
        assert "Plan not available" in exc_info.value.detail
        assert "planner was not used" in exc_info.value.detail

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_invalid_provenance_json(
        self, mock_config, mock_validate, mock_get_job, mock_request, tmp_path
    ):
        """Test 500 when provenance.json contains invalid JSON."""
        mock_get_job.return_value = None

        # Create provenance file with invalid JSON
        provenance_file = tmp_path / "provenance.json"
        provenance_file.write_text("{ invalid json }")

        job_record = Mock()
        job_record.provenance_path = str(provenance_file)
        mock_request.app.state.job_store.get.return_value = job_record
        mock_config.return_value.root.resolve.return_value = tmp_path

        with pytest.raises(HTTPException) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert exc_info.value.status_code == 500
        assert "invalid JSON" in exc_info.value.detail


class TestHybridFallback:
    """Test hybrid approach (metadata → provenance fallback)."""

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_hybrid_fallback_metadata_empty_reads_provenance(
        self, mock_config, mock_validate, mock_get_job,
        mock_request, mock_job_without_plan, mock_job_record_with_provenance
    ):
        """Test fallback from empty metadata to provenance.json."""
        # Step 1: _get_router_job returns job with empty metadata
        mock_get_job.return_value = mock_job_without_plan

        # Step 2: JobStore returns job_record with provenance
        mock_request.app.state.job_store.get.return_value = mock_job_record_with_provenance
        mock_config.return_value.root.resolve.return_value = Path("/tmp")

        result = await get_job_plan("job_123", mock_request)

        assert result == SAMPLE_PLAN
        # Should try memory first, then fall back to provenance
        mock_get_job.assert_called_once_with("job_123")
        mock_request.app.state.job_store.get.assert_called_once_with("job_123")

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_hybrid_no_metadata_reads_provenance(
        self, mock_config, mock_validate, mock_get_job,
        mock_request, mock_job_record_with_provenance
    ):
        """Test fallback when job has None metadata."""
        # Job exists but has no metadata field
        job_no_metadata = Mock(spec=Job)
        job_no_metadata.metadata = None
        mock_get_job.return_value = job_no_metadata

        mock_request.app.state.job_store.get.return_value = mock_job_record_with_provenance
        mock_config.return_value.root.resolve.return_value = Path("/tmp")

        result = await get_job_plan("job_123", mock_request)

        assert result == SAMPLE_PLAN


class TestPathSecurity:
    """Test path security validation."""

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_path_validation_called(
        self, mock_config, mock_validate, mock_get_job,
        mock_request, mock_job_record_with_provenance
    ):
        """Test that path security validation is called."""
        mock_get_job.return_value = None
        mock_request.app.state.job_store.get.return_value = mock_job_record_with_provenance
        mock_config.return_value.root.resolve.return_value = Path("/tmp")

        result = await get_job_plan("job_123", mock_request)

        # Verify _validate_path_security was called
        assert mock_validate.called
        call_args = mock_validate.call_args
        assert isinstance(call_args[0][0], Path)  # First arg is provenance_path

    @patch("brain_researcher.services.orchestrator.job_management_endpoints._get_router_job")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints._validate_path_security")
    @patch("brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config")
    async def test_path_traversal_blocked(
        self, mock_config, mock_validate, mock_get_job, mock_request, tmp_path
    ):
        """Test that path traversal attempts are blocked."""
        mock_get_job.return_value = None

        # Simulate path traversal attempt
        job_record = Mock()
        job_record.provenance_path = "../../../etc/passwd"
        mock_request.app.state.job_store.get.return_value = job_record
        mock_config.return_value.root.resolve.return_value = tmp_path

        # Mock _validate_path_security to raise exception for path traversal
        mock_validate.side_effect = ValueError("Path traversal detected")

        with pytest.raises(ValueError) as exc_info:
            await get_job_plan("job_123", mock_request)

        assert "Path traversal" in str(exc_info.value)


class TestHydratePlanMetadata:
    """Unit tests for plan metadata hydration helper."""

    def test_hydrate_populates_from_metadata(self):
        job = SimpleNamespace(
            metadata={
                "plan_of_record": {"plan_id": "plan_stub"},
                "plan_events": [{"event": "step_started"}],
                "por_token": "por-123",
            },
            plan_of_record=None,
            plan_events=[],
            por_token=None,
        )

        result = _hydrate_plan_metadata(job)

        assert result.plan_of_record == {"plan_id": "plan_stub"}
        assert result.plan_events == [{"event": "step_started"}]
        assert result.por_token == "por-123"

    def test_hydrate_defaults_events_to_empty(self):
        job = SimpleNamespace(metadata={}, plan_of_record=None, plan_events=None, por_token=None)

        result = _hydrate_plan_metadata(job)

        assert result.plan_of_record is None
        assert result.plan_events == []
        assert result.por_token is None
