from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from brain_researcher.services.orchestrator import enhanced_job_manager as mod


@pytest.mark.asyncio
async def test_parallel_batch_enforces_max_concurrent_jobs(monkeypatch) -> None:
    monkeypatch.setattr(mod, "broadcast_job_update", AsyncMock())

    manager = mod.EnhancedJobManager()
    request = mod.BatchJobRequest(
        jobs=[{"id": f"job_{i}"} for i in range(5)],
        dependency_mode="parallel",
        max_concurrent_jobs=2,
    )
    result = await manager.create_batch_jobs(request)
    job_ids = result["job_ids"]

    queued = [job_id for job_id in job_ids if manager.jobs[job_id]["status"] == mod.JobStatus.QUEUED]
    pending = [job_id for job_id in job_ids if manager.jobs[job_id]["status"] == mod.JobStatus.PENDING]
    assert len(queued) == 2
    assert len(pending) == 3

    # Sliding-window dependency chain.
    dep_job_2 = manager.job_dependencies[job_ids[2]][0]
    assert dep_job_2.depends_on_job_id == job_ids[0]
    assert dep_job_2.required_statuses and mod.JobStatus.FAILED in dep_job_2.required_statuses

    # A failure in the gate job should still unlock the next job (parallel batches are independent).
    manager.jobs[job_ids[0]]["status"] = mod.JobStatus.FAILED
    assert await manager._check_dependencies_satisfied(job_ids[2]) is True

