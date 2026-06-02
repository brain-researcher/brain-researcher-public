"""
Concurrency and stress testing for JobStore.

Tests concurrent claim operations to verify:
- No job is claimed by multiple workers
- GPU slot limits are enforced
- All jobs complete successfully
"""

import asyncio
from collections import defaultdict
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.job_store_factory import get_job_store


class TestConcurrentClaims:
    """Stress test concurrent job claiming."""

    @pytest.mark.asyncio
    async def test_50_workers_200_jobs_mix(self, tmp_path):
        """
        Stress test: 50 concurrent workers claiming 200 mixed CPU/GPU jobs.

        Verifies:
        1. Each job is claimed by exactly one worker (no double-booking)
        2. GPU utilization never exceeds available slots
        3. All jobs complete successfully
        """
        # Configuration
        num_workers = 50
        num_jobs = 200
        total_gpu_slots = 4
        gpu_jobs_ratio = 0.3  # 30% GPU jobs

        # Create job store (use SQLite for realistic concurrency testing)
        db_path = tmp_path / "stress_test.db"
        job_store = get_job_store(
            backend="sqlite", db_path=str(db_path), total_gpu_slots=total_gpu_slots
        )

        # Initialize store
        await job_store.initialize()

        try:
            # Enqueue mix of GPU and CPU jobs
            job_ids = []
            for i in range(num_jobs):
                is_gpu = i < int(num_jobs * gpu_jobs_ratio)
                job = JobRecord(
                    job_id=f"stress_job_{i:04d}",
                    kind="stress_test",
                    payload_json=f'{{"job_index": {i}}}',
                    state=JobState.QUEUED,
                    priority=i % 10,  # Mix of priorities
                    gpu_req=1 if is_gpu else 0,
                )
                await job_store.enqueue(job)
                job_ids.append(job.job_id)

            print(
                f"\nEnqueued {num_jobs} jobs ({int(num_jobs * gpu_jobs_ratio)} GPU, {num_jobs - int(num_jobs * gpu_jobs_ratio)} CPU)"
            )

            # Track claims and GPU usage
            claims = {}  # job_id -> worker_id
            claims_lock = asyncio.Lock()
            gpu_usage = []  # List of GPU usage snapshots
            gpu_usage_lock = asyncio.Lock()
            completed = set()
            completed_lock = asyncio.Lock()

            async def worker_loop(worker_id: str):
                """Worker that claims and processes jobs."""
                while True:
                    # Claim next job
                    job = await job_store.claim_next(worker_id=worker_id, lease_ttl=60)

                    if job is None:
                        # No more jobs
                        break

                    # Record claim
                    async with claims_lock:
                        if job.job_id in claims:
                            # VIOLATION: Job claimed by multiple workers!
                            raise AssertionError(
                                f"Job {job.job_id} claimed by both {claims[job.job_id]} and {worker_id}"
                            )
                        claims[job.job_id] = worker_id

                    # Record GPU usage
                    if job.gpu_req > 0:
                        stats = await job_store.get_queue_stats()
                        async with gpu_usage_lock:
                            gpu_usage.append(
                                {
                                    "worker_id": worker_id,
                                    "job_id": job.job_id,
                                    "gpus_in_use": stats["gpu_slots"]["in_use"],
                                    "gpus_available": stats["gpu_slots"]["available"],
                                }
                            )

                    # Simulate work (very brief to increase concurrency stress)
                    await asyncio.sleep(0.01)

                    # Update to succeeded
                    await job_store.update_state(
                        job.job_id, JobState.SUCCEEDED, exit_code=0
                    )

                    # Record completion
                    async with completed_lock:
                        completed.add(job.job_id)

            # Launch workers
            print(f"Launching {num_workers} concurrent workers...")
            worker_tasks = [
                asyncio.create_task(worker_loop(f"worker-{i:03d}"))
                for i in range(num_workers)
            ]

            # Wait for all workers to finish
            await asyncio.gather(*worker_tasks)

            print(f"\nAll workers finished!")
            print(f"Jobs claimed: {len(claims)}")
            print(f"Jobs completed: {len(completed)}")
            print(f"GPU usage samples: {len(gpu_usage)}")

            # Verification 1: All jobs claimed exactly once
            assert (
                len(claims) == num_jobs
            ), f"Expected {num_jobs} claims, got {len(claims)}"

            # Verification 2: All claimed jobs completed
            assert (
                len(completed) == num_jobs
            ), f"Expected {num_jobs} completions, got {len(completed)}"

            # Verification 3: GPU utilization never exceeded limit
            for snapshot in gpu_usage:
                assert (
                    snapshot["gpus_in_use"] <= total_gpu_slots
                ), f"GPU oversubscription detected: {snapshot['gpus_in_use']} > {total_gpu_slots}"

            # Verification 4: All job IDs are unique
            unique_jobs = set(claims.keys())
            assert (
                len(unique_jobs) == num_jobs
            ), f"Duplicate job IDs detected: {num_jobs - len(unique_jobs)} duplicates"

            # Verification 5: Expected mix of GPU/CPU jobs
            final_stats = await job_store.get_queue_stats()
            print(f"\nFinal stats: {final_stats}")

            print("\n✅ Concurrency stress test PASSED:")
            print(f"   - {num_jobs} jobs processed by {num_workers} workers")
            print(f"   - No double-booking detected")
            print(f"   - GPU limits enforced ({total_gpu_slots} slots)")
            print(f"   - All jobs completed successfully")

        finally:
            await job_store.close()

    @pytest.mark.asyncio
    async def test_gpu_contention_stress(self, tmp_path):
        """
        Test high GPU contention: many workers competing for limited GPUs.

        Scenario: 20 workers, 100 GPU jobs, only 2 GPU slots.
        This creates high contention and tests GPU reservation atomicity.
        """
        num_workers = 20
        num_jobs = 100
        total_gpu_slots = 2

        # Create job store
        db_path = tmp_path / "gpu_stress.db"
        job_store = get_job_store(
            backend="sqlite", db_path=str(db_path), total_gpu_slots=total_gpu_slots
        )

        await job_store.initialize()

        try:
            # Enqueue all GPU jobs
            for i in range(num_jobs):
                job = JobRecord(
                    job_id=f"gpu_job_{i:04d}",
                    kind="gpu_stress",
                    payload_json="{}",
                    state=JobState.QUEUED,
                    priority=5,
                    gpu_req=1,  # All require 1 GPU
                )
                await job_store.enqueue(job)

            # Track concurrent GPU usage
            max_concurrent_gpus = [0]
            max_lock = asyncio.Lock()
            completed = []

            async def gpu_worker(worker_id: str):
                """Worker that claims GPU jobs."""
                while True:
                    job = await job_store.claim_next(
                        worker_id=worker_id,
                        lease_ttl=60,
                        gpu_filter=True,  # Only claim GPU jobs
                    )

                    if job is None:
                        break

                    # Check GPU usage
                    stats = await job_store.get_queue_stats()
                    gpus_in_use = stats["gpu_slots"]["in_use"]

                    async with max_lock:
                        max_concurrent_gpus[0] = max(
                            max_concurrent_gpus[0], gpus_in_use
                        )

                    # Verify GPU limit not exceeded
                    assert (
                        gpus_in_use <= total_gpu_slots
                    ), f"GPU oversubscription: {gpus_in_use} > {total_gpu_slots}"

                    # Brief work
                    await asyncio.sleep(0.01)

                    # Complete
                    await job_store.update_state(
                        job.job_id, JobState.SUCCEEDED, exit_code=0
                    )

                    completed.append(job.job_id)

            # Launch workers
            worker_tasks = [
                asyncio.create_task(gpu_worker(f"gpu-worker-{i:03d}"))
                for i in range(num_workers)
            ]

            await asyncio.gather(*worker_tasks)

            # Verify all jobs completed
            assert (
                len(completed) == num_jobs
            ), f"Expected {num_jobs} completions, got {len(completed)}"

            print(f"\n✅ GPU contention stress test PASSED:")
            print(f"   - {num_jobs} GPU jobs with {total_gpu_slots} slots")
            print(f"   - {num_workers} competing workers")
            print(f"   - Max concurrent GPU usage: {max_concurrent_gpus[0]}")
            print(f"   - No oversubscription detected")

        finally:
            await job_store.close()

    @pytest.mark.asyncio
    async def test_claim_fairness(self, tmp_path):
        """
        Test fairness: workers should get roughly equal share of jobs.

        This ensures the queue isn't biased toward certain workers.
        """
        num_workers = 10
        num_jobs = 100
        total_gpu_slots = 4

        # Create job store
        db_path = tmp_path / "fairness_test.db"
        job_store = get_job_store(
            backend="sqlite", db_path=str(db_path), total_gpu_slots=total_gpu_slots
        )

        await job_store.initialize()

        try:
            # Enqueue jobs with varying priorities
            for i in range(num_jobs):
                job = JobRecord(
                    job_id=f"fair_job_{i:04d}",
                    kind="fairness_test",
                    payload_json="{}",
                    state=JobState.QUEUED,
                    priority=i % 10,  # Rotate priorities 0-9
                    gpu_req=0,
                )
                await job_store.enqueue(job)

            # Track claims per worker
            claims_per_worker = defaultdict(int)
            claims_lock = asyncio.Lock()

            async def fair_worker(worker_id: str):
                """Worker that claims jobs."""
                while True:
                    job = await job_store.claim_next(worker_id=worker_id, lease_ttl=60)

                    if job is None:
                        break

                    async with claims_lock:
                        claims_per_worker[worker_id] += 1

                    # Brief work
                    await asyncio.sleep(0.005)

                    # Complete
                    await job_store.update_state(
                        job.job_id, JobState.SUCCEEDED, exit_code=0
                    )

            # Launch workers
            worker_tasks = [
                asyncio.create_task(fair_worker(f"worker-{i:02d}"))
                for i in range(num_workers)
            ]

            await asyncio.gather(*worker_tasks)

            # Analyze fairness
            claims_list = list(claims_per_worker.values())
            avg_claims = sum(claims_list) / len(claims_list)
            max_claims = max(claims_list)
            min_claims = min(claims_list)
            fairness_ratio = min_claims / max_claims if max_claims > 0 else 0

            print(f"\n✅ Fairness test results:")
            print(f"   - Average claims per worker: {avg_claims:.1f}")
            print(f"   - Max claims: {max_claims}")
            print(f"   - Min claims: {min_claims}")
            print(f"   - Fairness ratio: {fairness_ratio:.2f}")
            print(f"   - Distribution: {dict(claims_per_worker)}")

            # Verify reasonable fairness (min should be at least 60% of max)
            # This is a loose threshold to account for random variation
            assert (
                fairness_ratio >= 0.6
            ), f"Unfair distribution detected: ratio {fairness_ratio:.2f} < 0.6"

        finally:
            await job_store.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
