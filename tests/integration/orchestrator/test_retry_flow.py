"""Integration tests for P2.6 full retry flow.

Tests complete end-to-end retry scenarios including:
- Job execution → failure → retry decision → delayed execution → re-execution
- Different error categories and their retry behavior
- Worker + retry logic + job store integration
"""

import pytest
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from brain_researcher.services.orchestrator.worker import JobWorker
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


@pytest.fixture
def job_store():
    """Create memory job store for testing."""
    return MemoryJobStore(total_gpu_slots=4)


@pytest.fixture
def worker(job_store):
    """Create worker instance."""
    return JobWorker(
        worker_id="test_worker",
        job_store=job_store,
        lease_ttl=60,
    )


class TestTimeoutRetryFlow:
    """Test timeout errors with retry and eventual success."""

    @pytest.mark.asyncio
    async def test_timeout_retry_succeeds_second_attempt(self, worker, job_store):
        """Job times out on first attempt, retries, succeeds on second attempt."""
        # Create job
        job = JobRecord(
            job_id="job_timeout_success",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=5,
        )
        await job_store.enqueue(job)

        # First execution: timeout (exit 124)
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=124,
            error_message="Command timed out after 300s",
        )

        # Verify job in RETRYING state
        job = await job_store.get(job.job_id)
        assert job.state == JobState.RETRYING
        assert job.attempt == 2
        assert job.run_after is not None

        # Simulate time passing and promote to QUEUED
        await job_store.update_state(job.job_id, JobState.QUEUED, run_after=None)

        # Second execution: success (exit 0)
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=0,
            error_message=None,
        )

        # Verify job succeeded
        job = await job_store.get(job.job_id)
        assert job.state == JobState.SUCCEEDED
        # Attempt is 3: started at 1, incremented to 2 on first failure, incremented to 3 on success
        assert job.attempt == 3
        assert job.exit_code == 0


class TestTransientIORetryFlow:
    """Test transient I/O errors with multiple retries."""

    @pytest.mark.asyncio
    async def test_transient_io_retry_three_times(self, worker, job_store):
        """Connection error retries twice (max_attempts=3 means 3 total attempts)."""
        # Create job with transient_io max_attempts=3
        job = JobRecord(
            job_id="job_io_retry",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job)

        # First attempt: I/O error (increments to 2, retries)
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=1,
            error_message="Connection reset by peer",
        )

        job = await job_store.get(job.job_id)
        assert job.state == JobState.RETRYING
        assert job.attempt == 2

        # Second attempt: Same I/O error (increments to 3, exhausted)
        await job_store.update_state(job.job_id, JobState.QUEUED, run_after=None)
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=1,
            error_message="Connection reset by peer",
        )

        job = await job_store.get(job.job_id)
        assert job.state == JobState.FAILED
        assert job.attempt == 3  # Exhausted at max_attempts
        assert "Connection reset" in job.error_message


class TestNonRetryableErrors:
    """Test errors that should not trigger retries."""

    @pytest.mark.asyncio
    async def test_oom_no_retry_immediate_fail(self, worker, job_store):
        """OOM error fails immediately without retry."""
        job = JobRecord(
            job_id="job_oom",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job)

        # Fail with OOM (exit 137)
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=137,
            error_message="MemoryError: cannot allocate memory",
        )

        # Should fail immediately (attempt incremented but no retry)
        job = await job_store.get(job.job_id)
        assert job.state == JobState.FAILED
        assert job.attempt == 2  # Incremented during finalization
        assert job.exit_code == 137
        assert "MemoryError" in job.error_message

    @pytest.mark.asyncio
    async def test_user_error_no_retry(self, worker, job_store):
        """User errors (file not found) do not retry."""
        job = JobRecord(
            job_id="job_user_error",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job)

        # Fail with user error
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=1,
            error_message="FileNotFoundError: input.nii not found",
        )

        # Should fail immediately (attempt incremented but no retry)
        job = await job_store.get(job.job_id)
        assert job.state == JobState.FAILED
        assert job.attempt == 2  # Incremented during finalization
        assert "FileNotFoundError" in job.error_message


class TestRetryWithPromotion:
    """Test retry with delayed execution and promotion."""

    @pytest.mark.asyncio
    async def test_opportunistic_promotion_and_retry(self, worker, job_store):
        """Job retries after delayed execution via opportunistic promotion."""
        # Create job
        job = JobRecord(
            job_id="job_promotion",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job)

        # First attempt: timeout
        await worker._finalize_job(
            job_id=job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        job = await job_store.get(job.job_id)
        assert job.state == JobState.RETRYING
        original_run_after = job.run_after

        # Set run_after to past (ready to retry)
        now = int(time.time())
        await job_store.update_state(
            job.job_id,
            JobState.RETRYING,
            run_after=now - 10  # 10 seconds ago
        )

        # Claim next should opportunistically promote
        claimed = await job_store.claim_next("worker_1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == job.job_id
        assert claimed.state == JobState.CLAIMED
        assert claimed.run_after is None  # Cleared on promotion
        assert claimed.attempt == 2


class TestMixedRetryScenarios:
    """Test multiple jobs with different retry outcomes."""

    @pytest.mark.asyncio
    async def test_mixed_retry_scenarios(self, worker, job_store):
        """Multiple jobs: some retry and succeed, some fail, some no retry."""
        # Job 1: Timeout → Retry → Success
        job1 = JobRecord(
            job_id="job_mixed_1",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=5,
        )
        await job_store.enqueue(job1)

        # Job 2: OOM → Immediate Fail
        job2 = JobRecord(
            job_id="job_mixed_2",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job2)

        # Job 3: I/O Error → Retry → Success
        job3 = JobRecord(
            job_id="job_mixed_3",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job3)

        # Execute Job 1: Timeout
        await worker._finalize_job(job1.job_id, exit_code=124, error_message="timeout")
        j1 = await job_store.get(job1.job_id)
        assert j1.state == JobState.RETRYING

        # Execute Job 2: OOM
        await worker._finalize_job(job2.job_id, exit_code=137, error_message="OOM")
        j2 = await job_store.get(job2.job_id)
        assert j2.state == JobState.FAILED

        # Execute Job 3: I/O Error
        await worker._finalize_job(job3.job_id, exit_code=1, error_message="Connection reset")
        j3 = await job_store.get(job3.job_id)
        assert j3.state == JobState.RETRYING

        # Promote Job 1 and retry successfully
        await job_store.update_state(job1.job_id, JobState.QUEUED, run_after=None)
        await worker._finalize_job(job1.job_id, exit_code=0, error_message=None)
        j1 = await job_store.get(job1.job_id)
        assert j1.state == JobState.SUCCEEDED
        assert j1.attempt == 3  # Incremented on first failure and on success

        # Promote Job 3 and retry successfully
        await job_store.update_state(job3.job_id, JobState.QUEUED, run_after=None)
        await worker._finalize_job(job3.job_id, exit_code=0, error_message=None)
        j3 = await job_store.get(job3.job_id)
        assert j3.state == JobState.SUCCEEDED
        assert j3.attempt == 3  # Incremented on first failure and on success

        # Verify final states
        final_jobs = {
            job1.job_id: await job_store.get(job1.job_id),
            job2.job_id: await job_store.get(job2.job_id),
            job3.job_id: await job_store.get(job3.job_id),
        }

        assert final_jobs[job1.job_id].state == JobState.SUCCEEDED
        assert final_jobs[job2.job_id].state == JobState.FAILED
        assert final_jobs[job3.job_id].state == JobState.SUCCEEDED


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
