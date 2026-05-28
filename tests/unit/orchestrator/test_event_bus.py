import asyncio
import json
from datetime import datetime

import pytest

from brain_researcher.services.orchestrator.main_enhanced import (
    jobs_db,
    job_updates,
    stream_job_updates,
    notify_job_update,
)
from brain_researcher.services.orchestrator.models import Job, JobStatus, TimingInfo


@pytest.fixture
def registered_job():
    job_id = "job_test_event_bus"
    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        prompt="event-bus-test",
        timing=TimingInfo(start_time=datetime.utcnow()),
    )
    jobs_db[job_id] = job
    queue = asyncio.Queue()
    job_updates[job_id] = queue
    try:
        yield job_id, queue
    finally:
        jobs_db.pop(job_id, None)
        job_updates.pop(job_id, None)


def _decode_sse_chunk(chunk: bytes) -> tuple[str, dict]:
    if isinstance(chunk, dict):
        event = chunk.get("event", "")
        data = chunk.get("data")
        payload = json.loads(data) if isinstance(data, str) else (data or {})
        return event, payload

    text = chunk.decode("utf-8")
    event = None
    data_line = None
    for line in text.splitlines():
        if line.startswith("event: "):
            event = line.split(": ", 1)[1]
        if line.startswith("data: "):
            data_line = line.split(": ", 1)[1]
    payload = json.loads(data_line) if data_line else {}
    return event or "", payload


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe_order(registered_job):
    job_id, queue = registered_job

    response = await stream_job_updates(job_id)
    generator = response.body_iterator

    # Initial chunk is the init payload
    await generator.__anext__()

    await queue.put({"type": "step_started", "order": 1})
    await queue.put({"type": "step_completed", "order": 2})

    first_chunk = await generator.__anext__()
    second_chunk = await generator.__anext__()

    event1, payload1 = _decode_sse_chunk(first_chunk)
    event2, payload2 = _decode_sse_chunk(second_chunk)

    assert event1 == "step_started"
    assert event2 == "step_completed"
    assert payload1["order"] == 1
    assert payload2["order"] == 2


@pytest.mark.asyncio
async def test_stream_disconnect_does_not_crash_publish(registered_job):
    job_id, _queue = registered_job

    # Remove queue to simulate disconnect
    job_updates.pop(job_id, None)

    # Should not raise even if there is no subscriber
    await notify_job_update(job_id, {"type": "step_update", "status": "done"})


@pytest.mark.asyncio
async def test_stream_includes_init_snapshot(registered_job):
    job_id, _ = registered_job

    response = await stream_job_updates(job_id)
    generator = response.body_iterator

    init_chunk = await generator.__anext__()
    event, payload = _decode_sse_chunk(init_chunk)

    assert event == "init"
    snapshot = json.loads(payload.get("data", "{}")) if isinstance(payload.get("data"), str) else payload
    assert snapshot["id"] == job_id


@pytest.mark.asyncio
async def test_notify_job_update_pushes_to_queue(registered_job):
    job_id, queue = registered_job

    await notify_job_update(job_id, {"type": "status", "status": "running"})

    message = await queue.get()
    assert message["type"] == "status"
    assert message["status"] == "running"
