"""Regression tests for contract-first /api/jobs endpoints (T6)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.job_management_endpoints import (
    CreateJobPayload,
    router,
)
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


@pytest.fixture(autouse=True)
def _reset_job_management_globals():
    # The job management router uses module-level globals for legacy progress
    # tracking. Clear them between tests to avoid cross-test interference.
    import brain_researcher.services.orchestrator.job_management_endpoints as endpoints

    endpoints.jobs_db.clear()
    endpoints.progress_queues.clear()
    endpoints.job_queue.clear()
    endpoints.running_jobs.clear()
    endpoints.job_history.clear()
    endpoints.job_subscribers.clear()
    endpoints.execution_history.clear()


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(router)
    app.state.job_store = MemoryJobStore(total_gpu_slots=0)
    return app


def test_create_get_list_jobs_contract(app_with_job_store):
    app = app_with_job_store

    with TestClient(app) as client:
        create = client.post(
            "/api/jobs",
            json={"prompt": "Run a quick smoke test", "pipeline": "chat"},
        )
        assert create.status_code == 200, create.text
        created = create.json()

        job_id = created.get("job_id")
        assert isinstance(job_id, str) and job_id
        assert created.get("schema_version") == "job-record-v1"
        assert created.get("status") in {"queued", "pending"}

        fetched = client.get(f"/api/jobs/{job_id}")
        assert fetched.status_code == 200, fetched.text
        fetched_payload = fetched.json()
        assert fetched_payload.get("job_id") == job_id
        assert fetched_payload.get("schema_version") == "job-record-v1"

        listed = client.get("/api/jobs?limit=50&offset=0")
        assert listed.status_code == 200, listed.text
        payload = listed.json()

        assert isinstance(payload.get("jobs"), list)
        job_ids = [item.get("job_id") for item in payload["jobs"]]
        assert job_id in job_ids
        assert payload.get("total") >= 1


def test_create_job_payload_normalizes_legacy_resume_checkpoint_id():
    payload = CreateJobPayload.model_validate(
        {
            "prompt": "Resume this job",
            "pipeline": "chat",
            "resume_checkpoint_id": "ck-job-1",
        }
    )

    assert payload.checkpoint_id == "ck-job-1"
