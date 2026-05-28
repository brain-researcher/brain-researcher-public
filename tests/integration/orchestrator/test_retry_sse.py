import asyncio
import time
import pytest

from brain_researcher.services.orchestrator.worker import JobWorker
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


@pytest.mark.asyncio
async def test_retry_emits_retry_scheduled_sse_event():
    """Ensure scheduling a retry emits a retry_scheduled SSE event."""
    store = MemoryJobStore(total_gpu_slots=2)
    worker = JobWorker(job_store=store, worker_id="sse-worker")

    job = JobRecord(
        job_id="job_sse_retry_001",
        kind="tool",
        user_id="user_test",
        state=JobState.QUEUED,
        priority=5,
        payload_json="{\"tool\": \"test\", \"metadata\": {}}",
        created_at=int(time.time()),
        attempt=1,
        max_attempts=5,
    )
    await store.enqueue(job)

    # Register an SSE queue for this job_id (requires enhanced app context)
    try:
        from brain_researcher.services.orchestrator import main_enhanced
        q = asyncio.Queue()
        main_enhanced.job_updates[job.job_id] = q
    except Exception:
        pytest.skip("enhanced app not available for SSE queue")

    # Trigger a retry by finalizing with a timeout exit code
    await worker._finalize_job(
        job_id=job.job_id,
        exit_code=124,
        error_message="Command timed out",
    )

    # Verify job enters RETRYING state
    updated = await store.get(job.job_id)
    assert updated is not None
    assert updated.state == JobState.RETRYING

    # Collect the SSE event
    event = await asyncio.wait_for(q.get(), timeout=2.0)
    assert event.get("type") == "retry_scheduled"
    assert event.get("job_id") == job.job_id
    assert event.get("status") == "retrying"
    assert event.get("attempt") == 2
    assert isinstance(event.get("delay_seconds"), int) and event.get("delay_seconds") > 0
    assert isinstance(event.get("next_retry_at"), int) or event.get("next_retry_at") is None
