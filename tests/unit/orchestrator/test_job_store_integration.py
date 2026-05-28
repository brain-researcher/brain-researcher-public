"""
Integration tests for JobStore P1.1 components.

Tests:
- JobStore protocol implementation (MemoryJobStore)
- JobAdapter conversion (Job ↔ JobRecord)
- Factory initialization
- Atomic claim+GPU reservation
- Recovery sweeper
"""

import pytest
import asyncio
import time
from datetime import datetime

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.job_store_factory import get_job_store
from brain_researcher.services.orchestrator.job_adapter import JobStoreAdapter
from brain_researcher.services.orchestrator.main_enhanced import (
    EnhancedJobManager,
    RunRequest,
    PipelineType,
    JobStatus,
    app,
    jobs_db,
    job_queue,
)


class TestMemoryJobStore:
    """Test MemoryJobStore implementation."""

    @pytest.mark.asyncio
    async def test_enqueue_and_get(self):
        """Test basic enqueue and retrieval."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Create job
        job = JobRecord(
            job_id="test-job-1",
            kind="tool",
            payload_json='{"command": "echo test"}',
            state=JobState.QUEUED,
            priority=5
        )

        # Enqueue
        job_id = await store.enqueue(job)
        assert job_id == "test-job-1"

        # Retrieve
        retrieved = await store.get(job_id)
        assert retrieved is not None
        assert retrieved.job_id == "test-job-1"
        assert retrieved.state == JobState.QUEUED

    @pytest.mark.asyncio
    async def test_atomic_claim_single_worker(self):
        """Test single worker claiming jobs."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue 5 jobs with different priorities
        for i in range(5):
            job = JobRecord(
                job_id=f"job-{i}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=i  # 0, 1, 2, 3, 4
            )
            await store.enqueue(job)

        # Claim jobs (should get highest priority first)
        claimed_ids = []
        for _ in range(5):
            job = await store.claim_next(worker_id="worker-1", lease_ttl=60)
            assert job is not None
            assert job.state == JobState.CLAIMED
            assert job.worker_id == "worker-1"
            claimed_ids.append(job.job_id)

        # Verify order (highest priority first: 4, 3, 2, 1, 0)
        expected_order = ["job-4", "job-3", "job-2", "job-1", "job-0"]
        assert claimed_ids == expected_order

        # No more jobs
        job = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert job is None


@pytest.mark.asyncio
async def test_demo_pipeline_completes_immediately(monkeypatch):
    """Demo runs should complete without hitting external agent services."""
    store = MemoryJobStore(total_gpu_slots=0)
    app.state.job_store = store
    app.state.job_adapter = JobStoreAdapter(store)

    jobs_db.clear()
    job_queue.clear()

    request = RunRequest(
        prompt="demo connectivity replay",
        pipeline=PipelineType.DEMO,
        parameters={"demo_id": "connectivity"},
    )

    job = await EnhancedJobManager.create_job(request)

    assert job.status == JobStatus.COMPLETED
    assert job.steps, "Demo job should contain synthesized steps"
    assert job.artifacts, "Demo job should include precomputed artifacts"

    record = await store.get(job.id)
    assert record is not None
    assert record.state == JobState.SUCCEEDED
    @pytest.mark.asyncio
    async def test_atomic_claim_concurrent_workers(self):
        """Test concurrent workers claiming jobs (no double-booking)."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue 100 jobs
        for i in range(100):
            job = JobRecord(
                job_id=f"job-{i}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=0
            )
            await store.enqueue(job)

        # 10 workers claim concurrently
        async def worker_claim(worker_id):
            claimed = []
            while True:
                job = await store.claim_next(worker_id=worker_id, lease_ttl=60)
                if job is None:
                    break
                claimed.append(job.job_id)
                await asyncio.sleep(0.001)  # Small delay
            return claimed

        results = await asyncio.gather(*[
            worker_claim(f"worker-{i}") for i in range(10)
        ])

        # Verify no double-booking
        all_claimed = [job_id for worker_jobs in results for job_id in worker_jobs]
        assert len(all_claimed) == len(set(all_claimed)), "Duplicate claims detected!"
        assert len(all_claimed) == 100, f"Expected 100 claims, got {len(all_claimed)}"

    @pytest.mark.asyncio
    async def test_gpu_reservation(self):
        """Test GPU slot reservation during claim."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue 3 GPU jobs (2 slots each)
        for i in range(3):
            job = JobRecord(
                job_id=f"gpu-job-{i}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=0,
                gpu_req=2  # Each job needs 2 GPUs
            )
            await store.enqueue(job)

        # First job should claim
        job1 = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert job1 is not None
        assert job1.job_id == "gpu-job-0"

        # Check GPU stats
        stats = await store.get_slot_stats()
        assert stats['total'] == 2
        assert stats['in_use'] == 2
        assert stats['available'] == 0

        # Second job should NOT claim (no GPUs available)
        job2 = await store.claim_next(worker_id="worker-2", lease_ttl=60)
        assert job2 is None

        # Release GPU slots by marking job1 as succeeded
        await store.update_state(job1.job_id, state=JobState.SUCCEEDED)

        # Check GPU stats (should be freed)
        stats = await store.get_slot_stats()
        assert stats['in_use'] == 0
        assert stats['available'] == 2

        # Now second job can claim
        job2 = await store.claim_next(worker_id="worker-2", lease_ttl=60)
        assert job2 is not None
        assert job2.job_id == "gpu-job-1"

    @pytest.mark.asyncio
    async def test_heartbeat_extends_lease(self):
        """Test heartbeat extends job lease."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue and claim job
        job = JobRecord(
            job_id="test-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0
        )
        await store.enqueue(job)

        claimed = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert claimed is not None
        original_lease = claimed.lease_expires_at

        # Wait 2 seconds
        await asyncio.sleep(2)

        # Update to running
        await store.update_state(claimed.job_id, state=JobState.RUNNING)

        # Send heartbeat
        await store.heartbeat(worker_id="worker-1", job_id=claimed.job_id)

        # Get job and verify lease extended
        refreshed = await store.get(claimed.job_id)
        assert refreshed.lease_expires_at > original_lease

    @pytest.mark.asyncio
    async def test_recovery_sweeper(self):
        """Test stale job recovery."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue and claim job
        job = JobRecord(
            job_id="stale-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0,
            gpu_req=1
        )
        await store.enqueue(job)

        claimed = await store.claim_next(worker_id="worker-1", lease_ttl=1)  # 1 second lease
        assert claimed is not None

        # Update to running
        await store.update_state(claimed.job_id, state=JobState.RUNNING)

        # Check GPU in use
        stats = await store.get_slot_stats()
        assert stats['in_use'] == 1

        # Wait for lease to expire
        await asyncio.sleep(2)

        # Run recovery
        recovery_stats = await store.recover_stale(lease_timeout=1)

        assert recovery_stats['jobs_requeued'] == 1
        assert recovery_stats['gpu_slots_freed'] == 1

        # Verify job is back in queue
        refreshed = await store.get(claimed.job_id)
        assert refreshed.state == JobState.QUEUED
        assert refreshed.attempt == 1  # Incremented
        assert refreshed.worker_id is None

        # Verify GPU freed
        stats = await store.get_slot_stats()
        assert stats['in_use'] == 0

    @pytest.mark.asyncio
    async def test_cancellation(self):
        """Test job cancellation."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Test 1: Cancel queued job (immediate)
        job1 = JobRecord(
            job_id="queued-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0
        )
        await store.enqueue(job1)

        success = await store.cancel(job1.job_id, reason="Test cancel")
        assert success is True

        refreshed = await store.get(job1.job_id)
        assert refreshed.state == JobState.CANCELLED
        assert refreshed.cancel_reason == "Test cancel"

        # Test 2: Cancel running job (mark as cancelling)
        job2 = JobRecord(
            job_id="running-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0
        )
        await store.enqueue(job2)
        await store.claim_next(worker_id="worker-1", lease_ttl=60)
        await store.update_state(job2.job_id, state=JobState.RUNNING)

        success = await store.cancel(job2.job_id, reason="User abort")
        assert success is True

        refreshed = await store.get(job2.job_id)
        assert refreshed.state == JobState.CANCELLING
        assert refreshed.cancellation_requested is True

    @pytest.mark.asyncio
    async def test_queue_stats(self):
        """Test queue statistics."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue jobs in different states
        states = [JobState.QUEUED, JobState.QUEUED, JobState.RUNNING, JobState.SUCCEEDED, JobState.FAILED]
        for i, state in enumerate(states):
            job = JobRecord(
                job_id=f"job-{i}",
                kind="tool",
                payload_json='{}',
                state=state,
                priority=0
            )
            await store.enqueue(job)

        stats = await store.get_queue_stats()
        assert stats[JobState.QUEUED] == 2
        assert stats[JobState.RUNNING] == 1
        assert stats[JobState.SUCCEEDED] == 1
        assert stats[JobState.FAILED] == 1


class TestJobLifecycles:
    """Test job state transition lifecycles."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_happy_path(self):
        """Test complete job lifecycle: QUEUED → CLAIMED → RUNNING → SUCCEEDED."""
        store = MemoryJobStore(total_gpu_slots=2)

        # 1. Enqueue
        job = JobRecord(
            job_id="lifecycle-1",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        job_id = await store.enqueue(job)
        assert job_id == "lifecycle-1"

        # Verify queued state
        job = await store.get(job_id)
        assert job.state == JobState.QUEUED
        assert job.queued_at is not None

        # 2. Claim
        claimed = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert claimed is not None
        assert claimed.job_id == job_id
        assert claimed.state == JobState.CLAIMED
        assert claimed.worker_id == "worker-1"
        assert claimed.claimed_at is not None
        assert claimed.lease_expires_at is not None

        # 3. Start running
        await store.update_state(
            claimed.job_id,
            state=JobState.RUNNING,
            started_at=int(time.time())
        )
        job = await store.get(claimed.job_id)
        assert job.state == JobState.RUNNING
        assert job.started_at is not None

        # 4. Complete successfully
        await store.update_state(
            claimed.job_id,
            state=JobState.SUCCEEDED,
            exit_code=0,
            finished_at=int(time.time())
        )
        job = await store.get(claimed.job_id)
        assert job.state == JobState.SUCCEEDED
        assert job.exit_code == 0
        assert job.finished_at is not None

    @pytest.mark.asyncio
    async def test_cancel_flow_from_running(self):
        """Test cancellation workflow: RUNNING → CANCELLING → CANCELLED."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Setup: start a running job
        job = JobRecord(
            job_id="cancel-test",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0
        )
        await store.enqueue(job)

        # Claim and start
        claimed = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        await store.update_state(claimed.job_id, state=JobState.RUNNING)

        # Verify running
        job = await store.get(claimed.job_id)
        assert job.state == JobState.RUNNING

        # Request cancellation
        success = await store.cancel(claimed.job_id, reason="User requested")
        assert success is True

        # Verify intermediate CANCELLING state
        job = await store.get(claimed.job_id)
        assert job.state == JobState.CANCELLING
        assert job.cancel_reason == "User requested"
        assert job.cancellation_requested is True

        # Worker finalizes (cancel wins even if exit_code=0)
        await store.update_state(
            claimed.job_id,
            state=JobState.CANCELLED,
            exit_code=0,  # Exit 0 but still cancelled!
            finished_at=int(time.time())
        )
        job = await store.get(claimed.job_id)
        assert job.state == JobState.CANCELLED  # Not SUCCEEDED!
        assert job.exit_code == 0  # Exit code preserved but state is cancelled

    @pytest.mark.asyncio
    async def test_skip_for_dag_child(self):
        """Test SKIPPED state for DAG nodes when upstream fails."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Parent and child jobs
        parent = JobRecord(
            job_id="parent-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=10
        )
        child = JobRecord(
            job_id="child-job",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )

        await store.enqueue(parent)
        await store.enqueue(child)

        # Parent executes and fails
        claimed_parent = await store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert claimed_parent.job_id == "parent-job"  # Higher priority claimed first

        await store.update_state(claimed_parent.job_id, state=JobState.RUNNING)
        await store.update_state(
            claimed_parent.job_id,
            state=JobState.FAILED,
            exit_code=1,
            error_message="Parent failed"
        )

        # Skip child due to upstream failure
        await store.update_state(
            child.job_id,
            state=JobState.SKIPPED,
            skip_reason=f"Upstream failed: {parent.job_id}"
        )

        child_job = await store.get(child.job_id)
        assert child_job.state == JobState.SKIPPED
        assert "Upstream failed" in child_job.skip_reason
        assert child_job.finished_at is None  # Skipped jobs never started

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Test timeout handling and TIMEOUT state."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Job with short lease
        job = JobRecord(
            job_id="timeout-test",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=0
        )
        await store.enqueue(job)

        # Claim with 1-second lease
        claimed = await store.claim_next(worker_id="worker-1", lease_ttl=1)
        await store.update_state(claimed.job_id, state=JobState.RUNNING)

        # Verify running
        job = await store.get(claimed.job_id)
        assert job.state == JobState.RUNNING

        # Simulate timeout by manually marking
        # (In production, this would be set by the executor when timeout is detected)
        await store.update_state(
            claimed.job_id,
            state=JobState.TIMEOUT,
            exit_code=124,  # Standard timeout exit code
            error_message="Execution timed out",
            finished_at=int(time.time())
        )

        job = await store.get(claimed.job_id)
        assert job.state == JobState.TIMEOUT
        assert job.exit_code == 124
        assert "timed out" in job.error_message.lower()


class TestJobStoreFactory:
    """Test JobStore factory."""

    def test_factory_memory_backend(self):
        """Test factory creates MemoryJobStore."""
        import os
        os.environ['BR_QUEUE_BACKEND'] = 'memory'

        store = get_job_store()
        assert isinstance(store, MemoryJobStore)

    def test_factory_invalid_backend(self):
        """Test factory raises error for invalid backend."""
        with pytest.raises(ValueError):
            get_job_store(backend='invalid')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
