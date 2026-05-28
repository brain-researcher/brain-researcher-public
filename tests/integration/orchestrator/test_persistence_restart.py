"""
Integration test for persistence and restart behavior.

Tests that jobs persist across orchestrator restarts and that
the sweeper resumes correctly.
"""

import asyncio
import pytest
from pathlib import Path

from brain_researcher.services.orchestrator.job_store_factory import get_job_store
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.background_tasks import start_sqlite_sweeper


@pytest.mark.asyncio
async def test_persistence_across_restart(tmp_path, caplog):
    """
    Test that jobs persist across orchestrator restart.

    Scenario:
    1. Start orchestrator with SQLite backend
    2. Enqueue a job
    3. Simulate restart by closing and reopening store
    4. Verify job persists
    5. Verify sweeper resumes
    """
    import logging
    caplog.set_level(logging.INFO)

    db_path = tmp_path / "restart_test.db"

    # ========== Phase 1: Initial startup ==========
    print("\n=== Phase 1: Initial startup ===")

    # Create job store (simulate first startup)
    store1 = get_job_store(
        backend='sqlite',
        db_path=str(db_path),
        total_gpu_slots=2
    )
    await store1.initialize()

    # Enqueue a job
    job = JobRecord(
        job_id="persistent_job_001",
        kind="persistence_test",
        payload_json='{"data": "important"}',
        state=JobState.QUEUED,
        priority=10,
        gpu_req=0
    )
    await store1.enqueue(job)

    # Verify job exists
    retrieved = await store1.get("persistent_job_001")
    assert retrieved is not None
    assert retrieved.job_id == "persistent_job_001"
    print(f"✓ Job enqueued: {retrieved.job_id}")

    # Start sweeper (simulating orchestrator lifespan)
    stop_event1 = asyncio.Event()
    sweeper_task1 = await start_sqlite_sweeper(
        job_store=store1,
        backend='sqlite',
        stop_event=stop_event1
    )

    # Verify sweeper started (task should be created)
    assert sweeper_task1 is not None, "Sweeper task not created"
    print("✓ Sweeper started")

    await asyncio.sleep(0.1)  # Let sweeper initialize

    # ========== Phase 2: Simulate shutdown ==========
    print("\n=== Phase 2: Simulating shutdown ===")

    # Stop sweeper
    stop_event1.set()
    if sweeper_task1:
        try:
            await asyncio.wait_for(sweeper_task1, timeout=5.0)
        except asyncio.TimeoutError:
            sweeper_task1.cancel()
            try:
                await sweeper_task1
            except asyncio.CancelledError:
                pass

    # Close store (simulate orchestrator shutdown)
    await store1.close()
    print("✓ Orchestrator shutdown complete")

    # ========== Phase 3: Restart ==========
    print("\n=== Phase 3: Restarting orchestrator ===")

    # Reopen database (simulate restart)
    store2 = get_job_store(
        backend='sqlite',
        db_path=str(db_path),
        total_gpu_slots=2
    )
    await store2.initialize()

    # Verify job persisted
    persisted_job = await store2.get("persistent_job_001")
    assert persisted_job is not None, "Job did not persist across restart"
    assert persisted_job.job_id == "persistent_job_001"
    assert persisted_job.state == JobState.QUEUED
    print(f"✓ Job persisted: {persisted_job.job_id}")

    # Restart sweeper
    stop_event2 = asyncio.Event()
    sweeper_task2 = await start_sqlite_sweeper(
        job_store=store2,
        backend='sqlite',
        stop_event=stop_event2
    )

    # Verify sweeper restarted (task should be created)
    assert sweeper_task2 is not None, "Sweeper task not created on restart"
    print("✓ Sweeper resumed after restart")

    await asyncio.sleep(0.1)

    # ========== Phase 4: Verify job can be processed ==========
    print("\n=== Phase 4: Processing persisted job ===")

    # Claim the persisted job
    claimed = await store2.claim_next(worker_id="test-worker", lease_ttl=60)
    assert claimed is not None
    assert claimed.job_id == "persistent_job_001"
    print(f"✓ Persisted job claimed: {claimed.job_id}")

    # Complete it
    await store2.update_state(
        "persistent_job_001",
        JobState.SUCCEEDED,
        exit_code=0
    )

    # Verify completion persisted
    final_job = await store2.get("persistent_job_001")
    assert final_job.state == JobState.SUCCEEDED
    print(f"✓ Job completed: {final_job.state}")

    # Cleanup
    stop_event2.set()
    if sweeper_task2:
        try:
            await asyncio.wait_for(sweeper_task2, timeout=5.0)
        except asyncio.TimeoutError:
            sweeper_task2.cancel()
            try:
                await sweeper_task2
            except asyncio.CancelledError:
                pass

    await store2.close()

    print("\n✅ Persistence & restart test PASSED:")
    print("   - Job persisted across restart")
    print("   - Sweeper resumed correctly")
    print("   - Persisted job can be claimed and completed")


@pytest.mark.asyncio
async def test_recovery_after_crash(tmp_path):
    """
    Test that jobs with expired leases are recovered after restart.

    Scenario:
    1. Claim a job with short lease
    2. Simulate crash (don't complete job, just close store)
    3. Restart
    4. Verify sweeper recovers the stale job
    """
    db_path = tmp_path / "recovery_test.db"

    # ========== Phase 1: Claim job with short lease ==========
    print("\n=== Phase 1: Claiming job with short lease ===")

    store1 = get_job_store(backend='sqlite', db_path=str(db_path), total_gpu_slots=2)
    await store1.initialize()

    # Enqueue job
    job = JobRecord(
        job_id="crash_recovery_job",
        kind="recovery_test",
        payload_json='{}',
        state=JobState.QUEUED,
        priority=5,
        gpu_req=0
    )
    await store1.enqueue(job)

    # Claim with 1 second lease
    claimed = await store1.claim_next(worker_id="crash-worker", lease_ttl=1)
    assert claimed is not None
    print(f"✓ Job claimed with 1s lease: {claimed.job_id}")

    # Simulate crash - close without completing job
    await store1.close()
    print("✓ Simulated crash")

    # Wait for lease to expire
    await asyncio.sleep(2)

    # ========== Phase 2: Restart and recover ==========
    print("\n=== Phase 2: Restarting and recovering ===")

    store2 = get_job_store(backend='sqlite', db_path=str(db_path), total_gpu_slots=2)
    await store2.initialize()

    # Job should still exist but with expired lease
    recovered_job = await store2.get("crash_recovery_job")
    assert recovered_job is not None
    print(f"✓ Job exists after restart: {recovered_job.job_id}")

    # Start sweeper to recover stale jobs
    stop_event = asyncio.Event()
    sweeper_task = await start_sqlite_sweeper(
        job_store=store2,
        backend='sqlite',
        stop_event=stop_event
    )

    # Wait for sweeper to run recovery
    await asyncio.sleep(3)

    # Verify job was recovered (requeued)
    recovered_job = await store2.get("crash_recovery_job")
    assert recovered_job.state == JobState.QUEUED, \
        f"Expected QUEUED after recovery, got {recovered_job.state}"
    assert recovered_job.worker_id is None, \
        "Worker ID should be cleared after recovery"
    print(f"✓ Job recovered to QUEUED state")

    # Verify job can be claimed again
    reclaimed = await store2.claim_next(worker_id="recovery-worker", lease_ttl=60)
    assert reclaimed is not None
    assert reclaimed.job_id == "crash_recovery_job"
    print(f"✓ Recovered job can be reclaimed")

    # Cleanup
    stop_event.set()
    if sweeper_task:
        try:
            await asyncio.wait_for(sweeper_task, timeout=5.0)
        except asyncio.TimeoutError:
            sweeper_task.cancel()
            try:
                await sweeper_task
            except asyncio.CancelledError:
                pass

    await store2.close()

    print("\n✅ Recovery after crash test PASSED:")
    print("   - Job persisted after simulated crash")
    print("   - Sweeper recovered stale job")
    print("   - Recovered job can be reclaimed")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
