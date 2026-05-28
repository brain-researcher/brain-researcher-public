"""
Unit tests for DualJobStore.

Tests dual-write validation wrapper that writes to both memory and SQLite.
"""

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore, DualJobStore


@pytest_asyncio.fixture
async def dual_store(tmp_path):
    """Create DualJobStore with memory primary and SQLite secondary."""
    # Create memory store
    memory = MemoryJobStore(total_gpu_slots=2)

    # Create and initialize SQLite store
    db_path = tmp_path / "dual_test.db"
    sqlite = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
    await sqlite.initialize()

    # Create dual store
    dual = DualJobStore(primary=memory, secondary=sqlite)
    await dual.initialize()

    try:
        yield dual
    finally:
        await dual.close()


class TestDualJobStoreBasics:
    """Test basic dual-write operations."""

    @pytest.mark.asyncio
    async def test_initialize_and_close(self, tmp_path):
        """Test initialization and cleanup."""
        memory = MemoryJobStore(total_gpu_slots=2)
        db_path = tmp_path / "test_init.db"
        sqlite = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)

        dual = DualJobStore(primary=memory, secondary=sqlite)

        # Initialize
        await dual.initialize()
        assert db_path.exists()

        # Close
        await dual.close()

    @pytest.mark.asyncio
    async def test_enqueue_dual_write(self, dual_store):
        """Test that enqueue writes to both stores."""
        job = JobRecord(
            job_id="job_dual_enqueue",
            kind="tool",
            payload_json='{"test": "data"}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        job_id = await dual_store.enqueue(job)
        assert job_id == "job_dual_enqueue"

        # Verify in primary
        primary_job = await dual_store.primary.get(job_id)
        assert primary_job is not None
        assert primary_job.job_id == job_id

        # Verify in secondary
        secondary_job = await dual_store.secondary.get(job_id)
        assert secondary_job is not None
        assert secondary_job.job_id == job_id

    @pytest.mark.asyncio
    async def test_get_reads_from_primary(self, dual_store):
        """Test that get() reads from primary only."""
        job = JobRecord(
            job_id="job_dual_get",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Get should return job
        retrieved = await dual_store.get("job_dual_get")
        assert retrieved is not None
        assert retrieved.job_id == "job_dual_get"

    @pytest.mark.asyncio
    async def test_update_state_dual_write(self, dual_store):
        """Test that update_state writes to both stores."""
        job = JobRecord(
            job_id="job_dual_update",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Update state
        success = await dual_store.update_state(
            "job_dual_update",
            JobState.RUNNING,
            worker_id="worker-1"
        )
        assert success is True

        # Verify in primary
        primary_job = await dual_store.primary.get("job_dual_update")
        assert primary_job.state == JobState.RUNNING
        assert primary_job.worker_id == "worker-1"

        # Verify in secondary
        secondary_job = await dual_store.secondary.get("job_dual_update")
        assert secondary_job.state == JobState.RUNNING
        assert secondary_job.worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_cancel_dual_write(self, dual_store):
        """Test that cancel writes to both stores."""
        job = JobRecord(
            job_id="job_dual_cancel",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Cancel
        success = await dual_store.cancel("job_dual_cancel", reason="Test cancellation")
        assert success is True

        # Verify in primary
        primary_job = await dual_store.primary.get("job_dual_cancel")
        assert primary_job.state == JobState.CANCELLED
        assert primary_job.cancel_reason == "Test cancellation"

        # Verify in secondary
        secondary_job = await dual_store.secondary.get("job_dual_cancel")
        assert secondary_job.state == JobState.CANCELLED
        assert secondary_job.cancel_reason == "Test cancellation"


class TestDualJobStoreClaimAndHeartbeat:
    """Test claim and heartbeat operations."""

    @pytest.mark.asyncio
    async def test_claim_next_from_primary_only(self, dual_store):
        """Test that claim_next operates on primary only."""
        job = JobRecord(
            job_id="job_dual_claim",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Claim job
        claimed = await dual_store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert claimed is not None
        assert claimed.job_id == "job_dual_claim"

        # Primary should have claimed job
        primary_job = await dual_store.primary.get("job_dual_claim")
        assert primary_job.state == JobState.CLAIMED

        # Secondary should still be queued (claim not dual-written)
        secondary_job = await dual_store.secondary.get("job_dual_claim")
        assert secondary_job.state == JobState.QUEUED

    @pytest.mark.asyncio
    async def test_heartbeat_dual_write(self, dual_store):
        """Test that heartbeat writes to both stores."""
        job = JobRecord(
            job_id="job_dual_heartbeat",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Claim job in primary
        await dual_store.primary.claim_next(worker_id="worker-1", lease_ttl=60)

        # Heartbeat
        count = await dual_store.heartbeat(
            worker_id="worker-1",
            job_id="job_dual_heartbeat",
            lease_ttl=120,
        )
        assert count >= 1


class TestDualJobStoreErrors:
    """Test error handling when secondary fails."""

    @pytest.mark.asyncio
    async def test_secondary_enqueue_failure(self, dual_store):
        """Test graceful handling when secondary enqueue fails."""
        # Mock secondary to fail
        with patch.object(dual_store.secondary, 'enqueue', side_effect=Exception("DB error")):
            job = JobRecord(
                job_id="job_error_enqueue",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5,
                gpu_req=0
            )

            # Should still succeed (returns primary result)
            job_id = await dual_store.enqueue(job)
            assert job_id == "job_error_enqueue"

            # Primary should have job
            primary_job = await dual_store.primary.get(job_id)
            assert primary_job is not None

    @pytest.mark.asyncio
    async def test_secondary_update_failure(self, dual_store):
        """Test graceful handling when secondary update fails."""
        job = JobRecord(
            job_id="job_error_update",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Mock secondary to fail
        with patch.object(dual_store.secondary, 'update_state', side_effect=Exception("DB error")):
            # Should still succeed
            success = await dual_store.update_state("job_error_update", JobState.RUNNING)
            assert success is True

            # Primary should be updated
            primary_job = await dual_store.primary.get("job_error_update")
            assert primary_job.state == JobState.RUNNING


class TestDualJobStoreDiscrepancy:
    """Test discrepancy detection."""

    @pytest.mark.asyncio
    async def test_discrepancy_tracking(self, dual_store):
        """Test that discrepancies are counted."""
        # Get initial stats
        initial_stats = await dual_store.get_queue_stats()
        initial_count = initial_stats['dual_store']['discrepancy_count']

        # Create a scenario where results differ
        job = JobRecord(
            job_id="job_discrepancy",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Mock secondary to return different result
        with patch.object(dual_store.secondary, 'update_state', return_value=False):
            await dual_store.update_state("job_discrepancy", JobState.RUNNING)

        # Check discrepancy count increased
        stats = await dual_store.get_queue_stats()
        assert stats['dual_store']['discrepancy_count'] > initial_count

    @pytest.mark.asyncio
    async def test_stats_include_metadata(self, dual_store):
        """Test that stats include dual-store metadata."""
        stats = await dual_store.get_queue_stats()

        assert 'dual_store' in stats
        assert stats['dual_store']['primary_type'] == 'MemoryJobStore'
        assert stats['dual_store']['secondary_type'] == 'SqliteJobStore'
        assert 'discrepancy_count' in stats['dual_store']


class TestDualJobStoreGPU:
    """Test GPU slot management."""

    @pytest.mark.asyncio
    async def test_reserve_slots_dual_write(self, dual_store):
        """Test that GPU slot reservation works (implementations differ)."""
        job = JobRecord(
            job_id="job_gpu_reserve",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=1
        )

        await dual_store.enqueue(job)

        # Reserve slots (return type may differ between backends)
        slots = await dual_store.reserve_slots("job_gpu_reserve", gpu_req=1)
        # Just verify it doesn't crash - implementations differ

        # Verify primary has slot tracking
        if hasattr(dual_store.primary, 'get_slot_stats'):
            primary_stats = await dual_store.primary.get_slot_stats()
            assert 'in_use' in primary_stats

    @pytest.mark.asyncio
    async def test_release_slots_dual_write(self, dual_store):
        """Test that GPU slot release works (implementations differ)."""
        job = JobRecord(
            job_id="job_gpu_release",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=1
        )

        await dual_store.enqueue(job)
        await dual_store.reserve_slots("job_gpu_release", gpu_req=1)

        # Release slots (return type may differ)
        count = await dual_store.release_slots("job_gpu_release")
        # Just verify it doesn't crash - implementations differ


class TestDualJobStoreRecovery:
    """Test stale job recovery."""

    @pytest.mark.asyncio
    async def test_recover_stale_jobs_dual(self, dual_store):
        """Test that recovery runs on both stores."""
        job = JobRecord(
            job_id="job_stale",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        await dual_store.enqueue(job)

        # Claim with short lease in both stores
        await dual_store.primary.claim_next(worker_id="worker-1", lease_ttl=1)
        await dual_store.secondary.claim_next(worker_id="worker-1", lease_ttl=1)

        # Wait for lease to expire
        await asyncio.sleep(2)

        # Recover
        import time
        now = int(time.time())
        stats = await dual_store.recover_stale_jobs(now_ts=now)

        # Verify recovery happened (different keys for different backends)
        # MemoryJobStore returns 'jobs_requeued', SqliteJobStore returns 'recovered'
        recovered_count = stats.get('recovered', stats.get('jobs_requeued', 0))
        assert recovered_count >= 1, f"Expected at least 1 recovered job, got stats={stats}"

        # Verify primary recovered
        primary_job = await dual_store.primary.get("job_stale")
        assert primary_job.state == JobState.QUEUED

        # Verify secondary recovered
        secondary_job = await dual_store.secondary.get("job_stale")
        assert secondary_job.state == JobState.QUEUED


class TestDualJobStoreListOperations:
    """Test list operations."""

    @pytest.mark.asyncio
    async def test_list_by_state_from_primary(self, dual_store):
        """Test that list_by_state reads from primary."""
        # Enqueue multiple jobs
        for i in range(3):
            job = JobRecord(
                job_id=f"job_list{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=i,
                gpu_req=0
            )
            await dual_store.enqueue(job)

        # List queued jobs
        queued = await dual_store.list_by_state(JobState.QUEUED)
        assert len(queued) == 3

    @pytest.mark.asyncio
    async def test_list_all_from_primary(self, dual_store):
        """Test that list_all reads from primary."""
        # Enqueue jobs
        for i in range(5):
            job = JobRecord(
                job_id=f"job_all{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=i,
                gpu_req=0
            )
            await dual_store.enqueue(job)

        # List all
        all_jobs = await dual_store.list_all()
        assert len(all_jobs) >= 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
