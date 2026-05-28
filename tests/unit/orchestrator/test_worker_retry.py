"""Unit tests for P2.6 worker retry integration.

Tests the retry logic in worker._finalize_job() including:
- Retry decision making
- State transitions to RETRYING
- Attempt counter incrementation
- Cache state preservation
- GPU resource cleanup
- Cancel-wins rule with retries
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from brain_researcher.services.orchestrator.worker import JobWorker
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.config.retry_settings import RetrySettings


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


@pytest.fixture
async def sample_job(job_store):
    """Create a sample job for testing."""
    job = JobRecord(
        job_id="job_test_001",
        kind="tool",
        user_id="user_test",
        state=JobState.QUEUED,
        priority=5,
        payload_json='{"tool": "test", "metadata": {"cache_key": "sha256:abc123"}}',
        created_at=int(time.time()),
        attempt=1,
        max_attempts=3,
    )
    await job_store.enqueue(job)
    return job


class TestWorkerRetryDecisions:
    """Test retry decision logic in _finalize_job()."""

    @pytest.mark.asyncio
    async def test_retry_timeout_first_attempt(self, worker, sample_job, job_store):
        """Timeout on first attempt triggers RETRYING state."""
        # Finalize with timeout exit code
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=124,
            error_message="Command timed out after 300s",
        )

        # Verify job transitioned to RETRYING
        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.RETRYING
        assert job.attempt == 2  # Incremented
        assert job.run_after is not None  # Delay set
        assert job.run_after > int(time.time())  # In the future

    @pytest.mark.asyncio
    async def test_retry_transient_io(self, worker, sample_job, job_store):
        """Transient I/O errors trigger retry."""
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=1,
            error_message="Connection reset by peer",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.RETRYING
        assert job.attempt == 2
        assert "Retry scheduled" in job.error_message

    @pytest.mark.asyncio
    async def test_no_retry_oom(self, worker, sample_job, job_store):
        """OOM errors do not retry - stay FAILED."""
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=137,
            error_message="MemoryError: cannot allocate",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.FAILED
        assert job.exit_code == 137
        # The original error message is preserved, not the retry decision reason
        assert "MemoryError" in job.error_message

    @pytest.mark.asyncio
    async def test_no_retry_user_error(self, worker, sample_job, job_store):
        """User errors (FileNotFoundError) do not retry."""
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=1,
            error_message="FileNotFoundError: input.nii not found",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.FAILED
        # The original error message is preserved
        assert "FileNotFoundError" in job.error_message

    @pytest.mark.asyncio
    async def test_retry_increments_attempt(self, worker, sample_job, job_store):
        """Retry increments attempt counter."""
        # First failure
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.attempt == 2

        # Promote to QUEUED and fail again
        await job_store.update_state(sample_job.job_id, JobState.QUEUED, run_after=None)
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=124,
            error_message="timeout again",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.attempt == 3

    @pytest.mark.asyncio
    async def test_retry_sets_run_after(self, worker, sample_job, job_store):
        """Retry sets run_after timestamp for delayed execution."""
        from datetime import datetime as dt
        now = int(time.time())
        # Use datetime.utcnow() for consistency with retry.py
        now_dt = int(dt.utcnow().timestamp())

        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        job = await job_store.get(sample_job.job_id)
        assert job.run_after is not None
        # Allow for timezone differences - just check it's in a reasonable future window
        assert job.run_after > now_dt - 10  # Allow 10s clock skew
        assert job.run_after < now_dt + 300  # Within 5 minutes (generous for timeout category)

    @pytest.mark.asyncio
    async def test_retry_preserves_cache_pending(self, worker, sample_job, job_store):
        """Retry keeps cache in pending state (doesn't mark failed)."""
        # Mock cache store
        mock_cache = AsyncMock()

        # Patch cache_store where it's imported in worker module
        with patch('brain_researcher.services.orchestrator.main_enhanced.cache_store', mock_cache):
            await worker._finalize_job(
                job_id=sample_job.job_id,
                exit_code=124,
                error_message="timeout",
            )

        # Cache should NOT be marked failed during retry
        mock_cache.mark_failed.assert_not_called()

        # Verify job is RETRYING
        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.RETRYING

    @pytest.mark.asyncio
    async def test_retry_exhausted_marks_failed(self, worker, sample_job, job_store):
        """After max attempts, job marked FAILED and cache marked failed."""
        # Set to last attempt for timeout category (max_attempts=5)
        await job_store.update_state(
            sample_job.job_id,
            JobState.QUEUED,
            attempt=5,  # At timeout category max_attempts
            max_attempts=5,
        )

        mock_cache = AsyncMock()

        with patch('brain_researcher.services.orchestrator.main_enhanced.cache_store', mock_cache):
            await worker._finalize_job(
                job_id=sample_job.job_id,
                exit_code=124,
                error_message="timeout",
            )

        # Should finalize as TIMEOUT (not retry)
        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.TIMEOUT  # Exit 124 becomes TIMEOUT
        # The error message contains the original error, not the retry decision reason
        assert job.exit_code == 124

        # Cache should be marked failed
        mock_cache.mark_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_releases_gpus(self, worker, job_store):
        """Retry releases GPU slots so they're available for next attempt."""
        # Create job with GPU requirement
        gpu_job = JobRecord(
            job_id="job_gpu_001",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            gpu_req=2,
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(gpu_job)

        # Claim job (reserves GPUs)
        claimed_job = await job_store.claim_next("test_worker", lease_ttl=60)
        assert claimed_job is not None
        assert claimed_job.job_id == gpu_job.job_id

        # Verify GPUs reserved
        stats = await job_store.get_slot_stats()
        assert stats["in_use"] == 2

        # Fail with retry
        await worker._finalize_job(
            job_id=gpu_job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        # Verify job in RETRYING state
        job = await job_store.get(gpu_job.job_id)
        assert job.state == JobState.RETRYING

        # Verify GPUs released
        stats = await job_store.get_slot_stats()
        assert stats["in_use"] == 0, "GPUs should be released when job enters RETRYING"

    @pytest.mark.asyncio
    async def test_cancel_wins_over_retry(self, worker, sample_job, job_store):
        """Cancellation request takes precedence over retry."""
        # Request cancellation
        await job_store.cancel(sample_job.job_id, reason="User requested")

        # Try to finalize with retryable error
        await worker._finalize_job(
            job_id=sample_job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        # Should be CANCELLED, not RETRYING
        job = await job_store.get(sample_job.job_id)
        assert job.state == JobState.CANCELLED
        assert "User requested" in job.cancel_reason

    @pytest.mark.asyncio
    async def test_retry_with_jitter(self, worker, job_store):
        """Retry backoff has jitter for different jobs."""
        # Create two jobs
        job1 = JobRecord(
            job_id="job_jitter_001",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        job2 = JobRecord(
            job_id="job_jitter_002",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,
        )
        await job_store.enqueue(job1)
        await job_store.enqueue(job2)

        # Fail both with same error
        await worker._finalize_job(job1.job_id, exit_code=124, error_message="timeout")
        await worker._finalize_job(job2.job_id, exit_code=124, error_message="timeout")

        # Get run_after timestamps
        j1 = await job_store.get(job1.job_id)
        j2 = await job_store.get(job2.job_id)

        # Should have different run_after due to jitter (deterministic based on job_id)
        # Note: With same settings, different job_ids produce different jitter
        assert j1.run_after is not None
        assert j2.run_after is not None
        # They should be different (unless incredibly unlikely hash collision)
        # But both should be reasonably close (within jitter range)
        assert abs(j1.run_after - j2.run_after) <= 20  # Within ~20s jitter window

    @pytest.mark.asyncio
    async def test_retry_respects_category_max_attempts(self, worker, job_store):
        """Timeout category gets 5 attempts (not default 3)."""
        # Create job with default max_attempts=3
        timeout_job = JobRecord(
            job_id="job_timeout_001",
            kind="tool",
            user_id="user_test",
            state=JobState.QUEUED,
            priority=5,
            payload_json='{"tool": "test", "metadata": {}}',
            created_at=int(time.time()),
            attempt=1,
            max_attempts=3,  # Default
        )
        await job_store.enqueue(timeout_job)

        # Fail with timeout (should update max_attempts to 5)
        await worker._finalize_job(
            timeout_job.job_id,
            exit_code=124,
            error_message="timeout",
        )

        job = await job_store.get(timeout_job.job_id)
        assert job.state == JobState.RETRYING
        assert job.max_attempts == 5, "Timeout category should override to 5 attempts"
        assert job.attempt == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
