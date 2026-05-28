"""Tests for /api/jobs/{id}/progress endpoint with plan_summary and plan_events."""

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from brain_researcher.services.orchestrator.job_management_endpoints import (
    get_job_progress,
    stream_job_progress,
    jobs_db,
    Job,
    JobStatus,
)


@pytest.mark.asyncio
async def test_progress_endpoint_includes_plan_summary():
    """Verify progress endpoint includes plan_summary when job has POR."""
    job_id = "job_progress_summary"
    jobs_db.clear()

    job = Job(
        id=job_id,
        prompt="connectivity analysis",
        status=JobStatus.RUNNING,
        created_at=datetime.utcnow(),
        plan_of_record={
            "plan_id": "plan_progress_test",
            "version": 1,
            "resolvable": True,
            "dag": {"steps": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]},
        },
        plan_events=[
            {"event": "plan_approved", "timestamp": "2025-01-01T10:00:00"},
            {"event": "step_started", "data": {"id": "s1"}},
            {"event": "step_completed", "data": {"id": "s1"}},
        ],
        por_token="token-progress",
        steps=[],
        artifacts=[],
        metadata={},
    )
    jobs_db[job_id] = job

    try:
        response = await get_job_progress(job_id)

        # Verify basic progress fields
        assert response["job_id"] == job_id
        assert response["status"] == JobStatus.RUNNING

        # Verify plan_summary is included
        assert "plan_summary" in response
        summary = response["plan_summary"]
        assert summary["plan_id"] == "plan_progress_test"
        assert summary["step_count"] == 3
        assert summary["plan_status"] == "step_completed"
        assert summary["por_token_set"] is True

        # Verify plan_events are included and truncated
        assert "plan_events" in response
        assert len(response["plan_events"]) == 3

    finally:
        jobs_db.pop(job_id, None)


@pytest.mark.asyncio
async def test_progress_endpoint_omits_plan_summary_when_no_por():
    """Verify progress endpoint omits plan_summary when job has no POR."""
    job_id = "job_progress_no_plan"
    jobs_db.clear()

    job = Job(
        id=job_id,
        prompt="simple analysis",
        status=JobStatus.RUNNING,
        created_at=datetime.utcnow(),
        steps=[],
        artifacts=[],
        metadata={},
    )
    jobs_db[job_id] = job

    try:
        response = await get_job_progress(job_id)

        # Verify basic progress fields
        assert response["job_id"] == job_id
        assert response["status"] == JobStatus.RUNNING

        # Verify plan_summary is NOT included
        assert "plan_summary" not in response
        assert "plan_events" not in response

    finally:
        jobs_db.pop(job_id, None)


@pytest.mark.asyncio
async def test_progress_endpoint_truncates_many_plan_events():
    """Verify progress endpoint truncates plan_events to 25 most recent."""
    job_id = "job_progress_many_events"
    jobs_db.clear()

    # Create 50 events
    events = [{"event": f"event_{i}", "data": {}} for i in range(50)]

    job = Job(
        id=job_id,
        prompt="long running analysis",
        status=JobStatus.RUNNING,
        created_at=datetime.utcnow(),
        plan_of_record={
            "plan_id": "plan_many_events",
            "version": 1,
            "resolvable": True,
            "dag": {"steps": [{"id": "s1"}]},
        },
        plan_events=events,
        por_token="token-many",
        steps=[],
        artifacts=[],
        metadata={},
    )
    jobs_db[job_id] = job

    try:
        response = await get_job_progress(job_id)

        # Verify plan_events are truncated to 25
        assert "plan_events" in response
        assert len(response["plan_events"]) == 25

        # Verify we got the LAST 25 events
        assert response["plan_events"][0]["event"] == "event_25"
        assert response["plan_events"][-1]["event"] == "event_49"

    finally:
        jobs_db.pop(job_id, None)


@pytest.mark.asyncio
async def test_sse_initial_state_includes_plan_summary():
    """Verify SSE endpoint includes plan_summary in initial_state event."""
    job_id = "job_sse_summary"
    jobs_db.clear()
    from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
    from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore

    job_store = MemoryJobStore(total_gpu_slots=0)
    payload = {
        "prompt": "sse test",
        "plan_of_record": {
            "plan_id": "plan_sse_test",
            "version": 1,
            "resolvable": True,
            "dag": {"steps": [{"id": "s1"}, {"id": "s2"}]},
        },
        "plan_events": [{"event": "step_started", "data": {"id": "s1"}}],
        "por_token": "token-sse",
        "steps": [],
        "artifacts": [],
        "metadata": {},
    }
    await job_store.enqueue(
        JobRecord(
            job_id=job_id,
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.RUNNING,
        )
    )
    # Ensure the generator terminates.
    await job_store.append_event(
        job_id, "analysis.completed", payload={"status": "succeeded"}
    )

    try:
        request = MagicMock()
        request.app.state.job_store = job_store

        response = await stream_job_progress(
            job_id,
            request=request,
            since=0,
            since_event_id=None,
            include_initial_state=True,
        )
        event_generator = response.body_iterator

        first_event = None
        async for event_dict in event_generator:
            if event_dict.get("event") == "initial_state":
                data_str = event_dict.get("data", "{}")
                first_event = json.loads(data_str)
            if event_dict.get("event") in {"job_finalized", "analysis.completed"}:
                break

        # Verify initial_state includes plan_summary
        assert first_event is not None
        assert "plan_summary" in first_event
        summary = first_event["plan_summary"]
        assert summary["plan_id"] == "plan_sse_test"
        assert summary["step_count"] == 2
        assert summary["plan_status"] == "step_started"

    finally:
        jobs_db.pop(job_id, None)


@pytest.mark.asyncio
async def test_sse_omits_plan_summary_when_no_por():
    """Verify SSE endpoint omits plan_summary when job has no POR."""
    job_id = "job_sse_no_plan"
    jobs_db.clear()
    from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
    from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore

    job_store = MemoryJobStore(total_gpu_slots=0)
    payload = {
        "prompt": "sse no plan test",
        "steps": [],
        "artifacts": [],
        "metadata": {},
    }
    await job_store.enqueue(
        JobRecord(
            job_id=job_id,
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.RUNNING,
        )
    )
    await job_store.append_event(
        job_id, "analysis.completed", payload={"status": "succeeded"}
    )

    try:
        request = MagicMock()
        request.app.state.job_store = job_store

        response = await stream_job_progress(
            job_id,
            request=request,
            since=0,
            since_event_id=None,
            include_initial_state=True,
        )
        event_generator = response.body_iterator

        first_event = None
        async for event_dict in event_generator:
            if event_dict.get("event") == "initial_state":
                data_str = event_dict.get("data", "{}")
                first_event = json.loads(data_str)
            if event_dict.get("event") in {"job_finalized", "analysis.completed"}:
                break

        # Verify initial_state does NOT include plan_summary
        assert first_event is not None
        assert "plan_summary" not in first_event

    finally:
        jobs_db.pop(job_id, None)
