"""
Unit tests for provenance API endpoints.

Tests the following endpoints:
- GET /api/jobs/{job_id}/provenance
- GET /api/jobs/{job_id}/artifacts/files
- GET /api/jobs/{job_id}/artifacts/files/{filename}

Verifies:
- Provenance retrieval from run_dir
- File listing and download
- Path traversal protection
- Error handling (404, 403, 500)
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState, JobStore
from brain_researcher.config.run_artifacts import RecorderConfig


class TestJobStore(JobStore):
    """Simple test job store without asyncio locks for cross-event-loop testing."""

    __test__ = False

    def __init__(self):
        self._jobs = {}

    async def enqueue(self, job: JobRecord) -> bool:
        self._jobs[job.job_id] = job
        return True

    async def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def claim_next(self, worker_id: str, lease_ttl: int) -> JobRecord | None:
        return None

    async def update_state(self, job_id: str, state: JobState, **kwargs) -> bool:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.state = state
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            return True
        return False

    async def cancel(self, job_id: str, reason: str) -> bool:
        if job_id in self._jobs:
            self._jobs[job_id].cancel_reason = reason
            self._jobs[job_id].state = JobState.CANCELLED
            return True
        return False

    async def heartbeat(self, worker_id: str, job_id: str, lease_ttl: int) -> int | None:
        return 1


@pytest.fixture
def app_with_job_store():
    """Create FastAPI app with job store and test data."""
    app = FastAPI()
    app.include_router(router)

    # Use simple test job store without asyncio locks
    job_store = TestJobStore()
    app.state.job_store = job_store

    yield app, job_store


@pytest.fixture
def test_run_directory(tmp_path: Path):
    """Create a temporary run directory with test files."""
    # Create a nested structure: tmp_path is the "run store root"
    # and run_dir is a subdirectory within it
    base_dir = tmp_path
    run_dir = base_dir / "test_run_001"
    run_dir.mkdir()

    # Create provenance.json
    provenance_data = {
        "run_id": "test_run_001",
        "command": "echo 'test'",
        "exit_code": 0,
        "started_at": "2025-01-01T00:00:00Z",
        "finished_at": "2025-01-01T00:00:05Z",
        "environment": {"PATH": "/usr/bin"},
        "outputs": [],
    }
    provenance_path = run_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance_data), encoding="utf-8")

    # Create some artifact files
    (run_dir / "output.txt").write_text("Test output", encoding="utf-8")
    (run_dir / "result.json").write_text('{"result": "success"}', encoding="utf-8")
    (run_dir / "data.nii.gz").write_bytes(b"fake nifti data")

    yield base_dir, run_dir, provenance_path


class TestProvenanceEndpoints:
    """Test provenance API endpoints."""

    @pytest.mark.asyncio
    async def test_get_provenance_success(self, app_with_job_store, test_run_directory):
        """Test successful provenance retrieval."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job with provenance
        job = JobRecord(
            job_id="job_prov_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path)
        )
        await job_store.enqueue(job)


        # Mock recorder config to use base_dir as root
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_prov_001/provenance")

                assert response.status_code == 200
                data = response.json()
                assert data["run_id"] == "test_run_001"
                assert data["command"] == "echo 'test'"
                assert data["exit_code"] == 0

        print("✓ Provenance retrieval works")

    @pytest.mark.asyncio
    async def test_get_provenance_job_not_found(self, app_with_job_store):
        """Test provenance endpoint with non-existent job."""
        app, job_store = app_with_job_store

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/jobs/nonexistent_job/provenance")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

        print("✓ Provenance 404 handling works")

    @pytest.mark.asyncio
    async def test_get_provenance_not_available(self, app_with_job_store):
        """Test provenance endpoint when provenance not available."""
        app, job_store = app_with_job_store

        # Create job without provenance
        job = JobRecord(
            job_id="job_no_prov_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5
        )
        await job_store.enqueue(job)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/jobs/job_no_prov_001/provenance")

            assert response.status_code == 404
            assert "provenance not available" in response.json()["detail"].lower()

        print("✓ Provenance not available handling works")

    @pytest.mark.asyncio
    async def test_list_artifact_files_success(self, app_with_job_store, test_run_directory):
        """Test successful file listing."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_list_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_list_001/artifacts/files")

                assert response.status_code == 200
                data = response.json()
                assert data["run_id"] == "test_run_001"
                assert data["file_count"] == 3  # Excludes provenance.json

                # Check files are listed
                file_names = [f["name"] for f in data["files"]]
                assert "output.txt" in file_names
                assert "result.json" in file_names
                assert "data.nii.gz" in file_names
                assert "provenance.json" not in file_names  # Excluded

                # Check file metadata
                output_file = next(f for f in data["files"] if f["name"] == "output.txt")
                assert output_file["size"] > 0
                assert "modified" in output_file

        print("✓ File listing works")

    @pytest.mark.asyncio
    async def test_list_artifact_files_empty_dir(self, app_with_job_store, tmp_path: Path):
        """Test file listing with empty run directory."""
        app, job_store = app_with_job_store

        base_dir = tmp_path
        run_dir = base_dir / "empty_run"
        run_dir.mkdir()

        # Create job
        job = JobRecord(
            job_id="job_list_empty_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_002",
            run_dir=str(run_dir),
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/jobs/job_list_empty_001/artifacts/files"
                )

                assert response.status_code == 200
                data = response.json()
                assert data["file_count"] == 0
                assert data["files"] == []

        print("✓ Empty directory listing works")

    @pytest.mark.asyncio
    async def test_get_job_artifacts_returns_ui_ready_entries(self, app_with_job_store, test_run_directory):
        """Test /api/jobs/{job_id}/artifacts returns run artifacts from observation/run_dir."""
        app, job_store = app_with_job_store
        base_dir, run_dir, _provenance_path = test_run_directory

        job = JobRecord(
            job_id="job_artifacts_001",
            kind="test",
            payload_json="{}",
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/jobs/job_artifacts_001/artifacts")
                assert response.status_code == 200
                data = response.json()
                assert isinstance(data.get("artifacts"), list)
                names = {item.get("name") for item in data["artifacts"] if isinstance(item, dict)}
                assert "output.txt" in names
                assert "result.json" in names
                assert "data.nii.gz" in names

        print("✓ Job artifacts endpoint returns UI-ready artifacts")

    @pytest.mark.asyncio
    async def test_download_artifact_file_success(self, app_with_job_store, test_run_directory):
        """Test successful file download."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_download_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_download_001/artifacts/files/output.txt")

                assert response.status_code == 200
                assert response.text == "Test output"
                assert "text/plain" in response.headers["content-type"]

        print("✓ File download works")

    @pytest.mark.asyncio
    async def test_download_artifact_file_supports_legacy_run_root_alias(
        self,
        app_with_job_store,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Legacy data/runs paths should resolve to the canonical shared run root."""
        app, job_store = app_with_job_store
        canonical_root = tmp_path / "shared" / "runs"
        legacy_root = tmp_path / "data" / "runs"
        run_dir = canonical_root / "20260223" / "job_download_legacy_001"
        run_dir.mkdir(parents=True)
        (run_dir / "output.txt").write_text("legacy output", encoding="utf-8")

        job = JobRecord(
            job_id="job_download_legacy_001",
            kind="test",
            payload_json="{}",
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="job_download_legacy_001",
            run_dir=str(legacy_root / "20260223" / "job_download_legacy_001"),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = canonical_root
        monkeypatch.setenv("BR_RUN_STORE_ROOT_ALIASES", str(legacy_root))

        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/jobs/job_download_legacy_001/artifacts/files/output.txt"
                )

                assert response.status_code == 200
                assert response.text == "legacy output"

        print("✓ Legacy run-root alias resolves for artifact downloads")

    @pytest.mark.asyncio
    async def test_download_artifact_file_not_found(self, app_with_job_store, test_run_directory):
        """Test file download with non-existent file."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_download_404_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_download_404_001/artifacts/files/nonexistent.txt")

                assert response.status_code == 404
                assert "not found" in response.json()["detail"].lower()

        print("✓ File not found handling works")

    @pytest.mark.asyncio
    async def test_download_provenance_via_files_blocked(self, app_with_job_store, test_run_directory):
        """Test that provenance.json cannot be downloaded via files endpoint."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_download_prov_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_download_prov_001/artifacts/files/provenance.json")

                assert response.status_code == 403
                assert "provenance endpoint" in response.json()["detail"].lower()

        print("✓ Provenance.json download blocking works")

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_in_filename(self, app_with_job_store, test_run_directory):
        """Test path traversal protection in filename."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_traversal_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                # Try path traversal with encoded slashes
                response = await client.get("/api/jobs/job_traversal_001/artifacts/files/..%2F..%2F..%2Fetc%2Fpasswd")
                assert response.status_code in [400, 403, 404]

                # Try '..' encoded so httpx does not normalize the path.
                response = await client.get("/api/jobs/job_traversal_001/artifacts/files/%2e%2e")
                assert response.status_code in [400, 403, 404]

        print("✓ Path traversal protection works")

    @pytest.mark.asyncio
    async def test_json_file_content_type(self, app_with_job_store, test_run_directory):
        """Test correct content type for JSON files."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_json_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_json_001/artifacts/files/result.json")

                assert response.status_code == 200
                assert "application/json" in response.headers["content-type"]
                assert response.json() == {"result": "success"}

        print("✓ JSON content type works")

    @pytest.mark.asyncio
    async def test_nifti_file_content_type(self, app_with_job_store, test_run_directory):
        """Test correct content type for NIfTI files."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Create job
        job = JobRecord(
            job_id="job_nifti_001",
            kind="test",
            payload_json='{}',
            state=JobState.SUCCEEDED,
            priority=5,
            run_id="test_run_001",
            run_dir=str(run_dir)
        )
        await job_store.enqueue(job)

        # Mock recorder config
        mock_config = RecorderConfig()
        mock_config.root = base_dir

        with patch('brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config', return_value=mock_config):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/jobs/job_nifti_001/artifacts/files/data.nii.gz")

                assert response.status_code == 200
                assert "application/x-nifti" in response.headers["content-type"]
                assert response.content == b"fake nifti data"

        print("✓ NIfTI content type works")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
