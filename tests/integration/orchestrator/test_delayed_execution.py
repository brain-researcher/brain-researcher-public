"""Integration tests for P2.6 delayed execution (retry scheduling).

Tests the retry poller and opportunistic promotion logic that schedules
delayed job execution after failures.
"""

import pytest
import asyncio
import time
from pathlib import Path

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore


@pytest.fixture
def memory_store():
    """Create memory job store."""
    return MemoryJobStore(total_gpu_slots=4)


@pytest.fixture
async def sqlite_store(tmp_path):
    """Create SQLite job store."""
    db_path = tmp_path / "test_delayed.db"
    store = SqliteJobStore(db_path=db_path, total_gpu_slots=4)
    await store.initialize()
    return store


async def create_retrying_job(store, job_id: str, run_after: int, priority: int = 5):
    """Helper to create a job in RETRYING state."""
    job = JobRecord(
        job_id=job_id,
        kind="tool",
        user_id="user_test",
        state=JobState.RETRYING,
        priority=priority,
        payload_json='{"tool": "test"}',
        created_at=int(time.time()),
        run_after=run_after,
        attempt=2,
        max_attempts=5,
    )
    await store.enqueue(job)
    # Manually transition to RETRYING (enqueue puts it in QUEUED)
    await store.update_state(job_id, JobState.RETRYING, run_after=run_after)
    return job


class TestBackgroundPoller:
    """Test the retry_poller background task promotion logic."""

    @pytest.mark.asyncio
    async def test_poller_promotes_ready_jobs_memory(self, memory_store):
        """Background poller promotes RETRYING jobs when run_after <= now."""
        now = int(time.time())

        # Create job ready to retry (run_after in the past)
        ready_job = await create_retrying_job(
            memory_store,
            job_id="job_ready",
            run_after=now - 10,  # 10 seconds ago
        )

        # Create job not ready yet
        future_job = await create_retrying_job(
            memory_store,
            job_id="job_future",
            run_after=now + 60,  # 60 seconds in future
        )

        # Simulate poller logic
        retrying_jobs = await memory_store.list_by_state(JobState.RETRYING)
        assert len(retrying_jobs) == 2

        promoted_count = 0
        for job in retrying_jobs:
            if job.run_after and job.run_after <= now:
                await memory_store.update_state(job.job_id, JobState.QUEUED, run_after=None)
                promoted_count += 1

        assert promoted_count == 1

        # Verify ready job promoted
        ready = await memory_store.get("job_ready")
        assert ready.state == JobState.QUEUED
        assert ready.run_after is None

        # Verify future job still RETRYING
        future = await memory_store.get("job_future")
        assert future.state == JobState.RETRYING
        assert future.run_after is not None

    @pytest.mark.asyncio
    async def test_poller_promotes_ready_jobs_sqlite(self, sqlite_store):
        """Background poller promotes RETRYING jobs in SQLite."""
        now = int(time.time())

        # Create job ready to retry
        await create_retrying_job(
            sqlite_store,
            job_id="job_ready_sql",
            run_after=now - 5,
        )

        # Create job not ready
        await create_retrying_job(
            sqlite_store,
            job_id="job_future_sql",
            run_after=now + 120,
        )

        # Simulate poller logic
        retrying_jobs = await sqlite_store.list_by_state(JobState.RETRYING)
        assert len(retrying_jobs) == 2

        promoted_count = 0
        for job in retrying_jobs:
            if job.run_after and job.run_after <= now:
                await sqlite_store.update_state(job.job_id, JobState.QUEUED, run_after=None)
                promoted_count += 1

        assert promoted_count == 1

        # Verify promotion
        ready = await sqlite_store.get("job_ready_sql")
        assert ready.state == JobState.QUEUED


class TestOpportunisticPromotion:
    """Test opportunistic promotion in claim_next()."""

    @pytest.mark.asyncio
    async def test_opportunistic_promotion_memory(self, memory_store):
        """claim_next() promotes RETRYING jobs ready to retry (memory store)."""
        now = int(time.time())

        # Create RETRYING job ready to retry
        await create_retrying_job(
            memory_store,
            job_id="job_opportunistic",
            run_after=now - 1,  # Ready now
        )

        # Verify it's in RETRYING state
        job = await memory_store.get("job_opportunistic")
        assert job.state == JobState.RETRYING

        # Try to claim next job (should promote and claim)
        claimed = await memory_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == "job_opportunistic"
        assert claimed.state == JobState.CLAIMED

    @pytest.mark.asyncio
    async def test_opportunistic_promotion_sqlite(self, sqlite_store):
        """claim_next() promotes RETRYING jobs ready to retry (SQLite store)."""
        now = int(time.time())

        # Create RETRYING job ready to retry
        await create_retrying_job(
            sqlite_store,
            job_id="job_opp_sql",
            run_after=now - 2,
        )

        # Verify RETRYING state
        job = await sqlite_store.get("job_opp_sql")
        assert job.state == JobState.RETRYING

        # Claim next (should opportunistically promote)
        claimed = await sqlite_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == "job_opp_sql"
        assert claimed.state == JobState.CLAIMED

    @pytest.mark.asyncio
    async def test_run_after_blocks_early_claim_memory(self, memory_store):
        """Jobs with run_after in the future are not claimed early."""
        now = int(time.time())

        # Create job not ready yet
        await create_retrying_job(
            memory_store,
            job_id="job_not_ready",
            run_after=now + 300,  # 5 minutes in future
        )

        # Try to claim (should return None)
        claimed = await memory_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is None

        # Verify still RETRYING
        job = await memory_store.get("job_not_ready")
        assert job.state == JobState.RETRYING

    @pytest.mark.asyncio
    async def test_run_after_blocks_early_claim_sqlite(self, sqlite_store):
        """Jobs with run_after in the future are not claimed early (SQLite)."""
        now = int(time.time())

        # Create job not ready
        await create_retrying_job(
            sqlite_store,
            job_id="job_not_ready_sql",
            run_after=now + 180,
        )

        # Try to claim
        claimed = await sqlite_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is None

        # Verify still RETRYING
        job = await sqlite_store.get("job_not_ready_sql")
        assert job.state == JobState.RETRYING


class TestRetryPriorityHandling:
    """Test that priority is respected during retry promotion."""

    @pytest.mark.asyncio
    async def test_poller_respects_priority_memory(self, memory_store):
        """Higher priority RETRYING jobs promoted first."""
        now = int(time.time())

        # Create high priority job
        await create_retrying_job(
            memory_store,
            job_id="job_high_priority",
            run_after=now - 1,
            priority=10,
        )

        # Create low priority job
        await create_retrying_job(
            memory_store,
            job_id="job_low_priority",
            run_after=now - 1,
            priority=1,
        )

        # Both ready, claim should get high priority first
        claimed = await memory_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == "job_high_priority"

    @pytest.mark.asyncio
    async def test_poller_respects_priority_sqlite(self, sqlite_store):
        """Higher priority RETRYING jobs promoted first (SQLite)."""
        now = int(time.time())

        # Create jobs with different priorities
        await create_retrying_job(
            sqlite_store,
            job_id="job_priority_10",
            run_after=now - 1,
            priority=10,
        )

        await create_retrying_job(
            sqlite_store,
            job_id="job_priority_5",
            run_after=now - 1,
            priority=5,
        )

        # Claim should get highest priority
        claimed = await sqlite_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == "job_priority_10"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
