"""Unit tests for JobStore append-only events."""

from __future__ import annotations

import pytest

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore


@pytest.mark.asyncio
async def test_memory_job_store_events_round_trip():
    store = MemoryJobStore(total_gpu_slots=0)
    await store.enqueue(
        JobRecord(job_id="job-1", kind="tool", payload_json="{}", state=JobState.QUEUED)
    )

    event_id = await store.append_event(
        "job-1", "custom", payload={"a": 1}, created_at=123
    )
    assert event_id >= 1

    events = await store.list_events("job-1", after_event_id=0)
    assert any(e.event_type == "custom" for e in events)
    custom = next(e for e in events if e.event_type == "custom")
    assert custom.created_at == 123
    assert custom.payload == {"a": 1}

    assert await store.list_events("job-1", after_event_id=event_id) == []


@pytest.mark.asyncio
async def test_sqlite_job_store_events_round_trip(tmp_path):
    store = SqliteJobStore(db_path=str(tmp_path / "jobs.sqlite"))
    await store.initialize()

    await store.enqueue(
        JobRecord(job_id="job-1", kind="tool", payload_json="{}", state=JobState.QUEUED)
    )

    event_id = await store.append_event(
        "job-1", "custom", payload={"a": 1}, created_at=123
    )
    assert event_id > 0

    events = await store.list_events("job-1", after_event_id=0)
    assert any(e.event_type == "custom" for e in events)
    custom = next(e for e in events if e.event_type == "custom")
    assert custom.created_at == 123
    assert custom.payload == {"a": 1}

