"""Unit tests for append-only job events endpoints.

These endpoints are backed by JobStore.append_event/list_events and are used to
support replayable SSE/WS streams.
"""

from __future__ import annotations

import json

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
async def test_list_job_events(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    await job_store.enqueue(
        JobRecord(
            job_id="job_test_events_001",
            kind="test",
            payload_json="{}",
            state=JobState.QUEUED,
        )
    )
    await job_store.append_event(
        "job_test_events_001",
        "custom_event",
        payload={"hello": "world"},
        created_at=123,
    )

    with TestClient(app) as client:
        resp = client.get("/api/jobs/job_test_events_001/events?since=0")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["job_id"] == "job_test_events_001"
    assert payload["events"]
    assert any(e["type"] == "custom_event" for e in payload["events"])

    custom = next(e for e in payload["events"] if e["type"] == "custom_event")
    assert custom["ts"] == 123
    assert custom["payload"]["hello"] == "world"


@pytest.mark.asyncio
async def test_list_job_events_404(app_with_job_store):
    app = app_with_job_store
    with TestClient(app) as client:
        resp = client.get("/api/jobs/job_does_not_exist/events")
    assert resp.status_code == 404

