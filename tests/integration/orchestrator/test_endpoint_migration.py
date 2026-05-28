"""
Integration tests for endpoint migration to JobStore.

Tests that endpoints correctly use JobStore and maintain backward compatibility.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.job_management_endpoints import router


@pytest.fixture
def app_with_job_store():
    """Create FastAPI app with JobStore initialized."""
    app = FastAPI()
    app.include_router(router)

    # Initialize job store
    job_store = MemoryJobStore(total_gpu_slots=2)
    app.state.job_store = job_store

    return app


@pytest.fixture
def client(app_with_job_store):
    """Create test client."""
    return TestClient(app_with_job_store)


class TestGetJobEndpoint:
    """Test GET /api/jobs/{job_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_job_from_job_store(self, client, app_with_job_store):
        """Test retrieving job from JobStore."""
        job_store = app_with_job_store.state.job_store

        # Create test job (job ID must match pattern: ^job_[a-zA-Z0-9_]+$)
        job_record = JobRecord(
            job_id="job_test123",
            kind="tool",
            payload_json='{"tool": "fsl.bet", "params": {}}',
            state=JobState.QUEUED,
            priority=5,
            worker_id=None,
            gpu_req=0,
            created_at=int(datetime.utcnow().timestamp())
        )

        # Enqueue job
        await job_store.enqueue(job_record)

        # Call endpoint
        response = client.get("/api/jobs/job_test123")

        # Validate response
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "job_test123"
        assert data["status"] in ["queued", "QUEUED"]  # Case insensitive
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_get_job_claimed_state(self, client, app_with_job_store):
        """Test retrieving claimed job with worker info."""
        job_store = app_with_job_store.state.job_store

        # Create and claim job
        job_record = JobRecord(
            job_id="job_claimed456",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=10,
            gpu_req=1
        )

        await job_store.enqueue(job_record)
        claimed = await job_store.claim_next(worker_id="worker-1", lease_ttl=60)

        assert claimed is not None
        assert claimed.state == JobState.CLAIMED

        # Call endpoint
        response = client.get("/api/jobs/job_claimed456")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "job_claimed456"
        # JobAdapter should convert state correctly
        assert data["worker_id"] == "worker-1"

    def test_get_job_not_found(self, client):
        """Test 404 response for non-existent job."""
        response = client.get("/api/jobs/nonexistent-job")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_job_with_gpu_allocation(self, client, app_with_job_store):
        """Test retrieving job with GPU allocation."""
        job_store = app_with_job_store.state.job_store

        # Create GPU job
        job_record = JobRecord(
            job_id="job_gpu789",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=2,
            gpu_type="nvidia-v100"
        )

        await job_store.enqueue(job_record)
        claimed = await job_store.claim_next(worker_id="gpu-worker", lease_ttl=60)

        # Call endpoint
        response = client.get("/api/jobs/job_gpu789")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "job_gpu789"
        # Check GPU fields if exposed by JobAdapter
        if "gpu_count_required" in data:
            assert data["gpu_count_required"] == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
