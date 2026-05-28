import json
from datetime import datetime

import pytest

from brain_researcher.services.orchestrator.job_adapter import JobAdapter, JobStoreAdapter
from brain_researcher.services.orchestrator.job_management_endpoints import Job, JobStatus
from brain_researcher.services.orchestrator.job_store import JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def _make_job() -> Job:
    return Job(
        id="job_plan_test",
        name="plan test",
        prompt="run connectivity",
        status=JobStatus.PENDING,
        created_at=datetime.utcnow(),
        steps=[],
        artifacts=[],
        metadata={},
    )


def test_job_adapter_to_record_includes_plan_fields():
    job = _make_job()
    job.plan_of_record = {"plan_id": "plan_stub", "dag": {"steps": []}}
    job.plan_events = [{"event": "step_started", "data": {"id": "s1"}}]
    job.por_token = "token-123"

    record = JobAdapter.to_record(job)
    payload = json.loads(record.payload_json)

    assert payload["plan_of_record"] == job.plan_of_record
    assert payload["plan_events"] == job.plan_events
    assert payload["por_token"] == job.por_token


def test_job_adapter_from_record_restores_plan_fields():
    job = _make_job()
    job.plan_of_record = {"plan_id": "plan_stub", "dag": {"steps": []}}
    job.plan_events = [{"event": "step_completed", "data": {"id": "s1"}}]
    job.por_token = "token-abc"

    record = JobAdapter.to_record(job)
    restored = JobAdapter.from_record(record)

    assert restored.plan_of_record == job.plan_of_record
    assert restored.plan_events == job.plan_events
    assert restored.por_token == job.por_token


def test_job_adapter_caches_plan_summary():
    """Verify that JobAdapter.to_record caches plan_summary in payload_json."""
    job = _make_job()
    job.plan_of_record = {
        "plan_id": "plan_cached",
        "version": 1,
        "resolvable": True,
        "dag": {"steps": [{"id": "s1"}, {"id": "s2"}]},
    }
    job.plan_events = [{"event": "step_completed", "data": {"id": "s2"}}]
    job.por_token = "token-cached"

    record = JobAdapter.to_record(job)
    payload = json.loads(record.payload_json)

    # Verify plan_summary is cached
    assert "plan_summary" in payload
    assert payload["plan_summary"] is not None
    assert payload["plan_summary"]["plan_id"] == "plan_cached"
    assert payload["plan_summary"]["version"] == 1
    assert payload["plan_summary"]["step_count"] == 2
    assert payload["plan_summary"]["plan_status"] == "step_completed"
    assert payload["plan_summary"]["por_token_set"] is True


def test_job_adapter_restores_cached_plan_summary():
    """Verify that JobAdapter.from_record restores cached plan_summary."""
    job = _make_job()
    job.plan_of_record = {
        "plan_id": "plan_restore",
        "version": 2,
        "resolvable": True,
        "dag": {"steps": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]},
    }
    job.plan_events = [{"event": "plan_approved", "data": {}}]
    job.por_token = "token-restore"

    record = JobAdapter.to_record(job)
    restored = JobAdapter.from_record(record)

    # Verify plan_summary is restored to metadata
    assert "plan_summary" in restored.metadata
    summary = restored.metadata["plan_summary"]
    assert summary["plan_id"] == "plan_restore"
    assert summary["version"] == 2
    assert summary["step_count"] == 3
    assert summary["plan_status"] == "plan_approved"


def test_job_adapter_plan_summary_omitted_when_no_plan():
    """Verify that plan_summary is None when job has no plan_of_record."""
    job = _make_job()
    # No plan_of_record set

    record = JobAdapter.to_record(job)
    payload = json.loads(record.payload_json)

    # Verify plan_summary is None
    assert payload.get("plan_summary") is None


def test_job_adapter_sync_fields_persists_error_message():
    job = _make_job()
    record = JobAdapter.to_record(job)

    job.status = JobStatus.FAILED
    job.error = "Agent plan execution failed with 500"
    JobAdapter.sync_fields(job, record)

    assert record.state == JobState.FAILED
    assert record.error_message == "Agent plan execution failed with 500"


@pytest.mark.asyncio
async def test_job_store_adapter_update_job_forwards_error_message():
    store = MemoryJobStore()
    adapter = JobStoreAdapter(store)
    job = _make_job()
    await adapter.create_job(job)

    job.status = JobStatus.FAILED
    job.error = "Direct tool run failed"
    assert await adapter.update_job(job)

    record = await store.get(job.id)
    assert record is not None
    assert record.state == JobState.FAILED
    assert record.error_message == "Direct tool run failed"
