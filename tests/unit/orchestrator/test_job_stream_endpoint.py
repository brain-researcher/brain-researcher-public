"""Unit tests for replayable job SSE endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(router)
    app.state.job_store = MemoryJobStore(total_gpu_slots=0)
    return app


@pytest.mark.asyncio
async def test_job_stream_replays_events_and_terminates(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    await job_store.enqueue(
        JobRecord(
            job_id="job_test_stream_001",
            kind="test",
            payload_json="{}",
            state=JobState.QUEUED,
        )
    )
    await job_store.append_event(
        "job_test_stream_001", "job.started", payload={"status": "running"}
    )
    await job_store.append_event(
        "job_test_stream_001",
        "analysis.completed",
        payload={"status": "succeeded"},
    )

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/jobs/job_test_stream_001/stream?since=0&include_initial_state=false",
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    assert "event: job.started" in content
    assert "event: analysis.completed" in content
    assert "event: progress_update" in content
    assert "event: job_complete" in content
    assert '"job_id": "job_test_stream_001"' in content
