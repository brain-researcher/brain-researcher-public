"""
Unit tests for cancel-wins finalization rule (CF-4).

Tests that cancellation always takes precedence over completion,
preventing race conditions where a job completes successfully
but cancellation was requested during execution.
"""

import asyncio
import pytest
import time
from brain_researcher.services.orchestrator.worker import JobWorker
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState


class TestCancelWinsFinalization:
    """Test cancel-wins finalization rule."""

    @pytest.mark.asyncio
    async def test_cancel_wins_over_success(self):
        """Test that cancellation wins over successful exit code 0."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-1")

        # Create job
        job = JobRecord(
            job_id="cancel_wins_test_1",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await job_store.enqueue(job)

        # Simulate: job completes successfully but cancellation was requested
        # This tests the race condition where cancel is requested after execution
        # but before finalization

        # First, mark as running
        await job_store.update_state("cancel_wins_test_1", JobState.RUNNING)

        # Request cancellation
        await job_store.cancel("cancel_wins_test_1", "User requested cancellation")

        # Now finalize with exit_code=0 (would normally be SUCCESS)
        await worker._finalize_job(
            job_id="cancel_wins_test_1",
            exit_code=0
        )

        # Verify: State should be CANCELLED (cancel wins)
        final_job = await job_store.get("cancel_wins_test_1")
        assert final_job.state == JobState.CANCELLED
        assert "Cancelled:" in final_job.error_message
        assert final_job.exit_code == 0  # Exit code preserved for audit

        print("✓ Cancel wins over successful exit code")

    @pytest.mark.asyncio
    async def test_cancel_wins_over_failure(self):
        """Test that cancellation wins over failed exit code."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-2")

        # Create job
        job = JobRecord(
            job_id="cancel_wins_test_2",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await job_store.enqueue(job)

        # Mark as running and request cancellation
        await job_store.update_state("cancel_wins_test_2", JobState.RUNNING)
        await job_store.cancel("cancel_wins_test_2", "User cancelled")

        # Finalize with exit_code=1 (would normally be FAILED)
        await worker._finalize_job(
            job_id="cancel_wins_test_2",
            exit_code=1,
            error_message="Process failed"
        )

        # Verify: State should be CANCELLED (cancel wins)
        final_job = await job_store.get("cancel_wins_test_2")
        assert final_job.state == JobState.CANCELLED
        assert "Cancelled:" in final_job.error_message
        assert final_job.exit_code == 1

        print("✓ Cancel wins over failed exit code")

    @pytest.mark.asyncio
    async def test_cancel_wins_over_timeout(self):
        """Test that cancellation wins over timeout exit code 124."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-3")

        # Create job
        job = JobRecord(
            job_id="cancel_wins_test_3",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await job_store.enqueue(job)

        # Mark as running and request cancellation
        await job_store.update_state("cancel_wins_test_3", JobState.RUNNING)
        await job_store.cancel("cancel_wins_test_3", "Timeout triggered but also cancelled")

        # Finalize with exit_code=124 (would normally be TIMEOUT)
        await worker._finalize_job(
            job_id="cancel_wins_test_3",
            exit_code=124,
            error_message="Execution timed out"
        )

        # Verify: State should be CANCELLED (cancel wins)
        final_job = await job_store.get("cancel_wins_test_3")
        assert final_job.state == JobState.CANCELLED
        assert "Cancelled:" in final_job.error_message
        assert final_job.exit_code == 124

        print("✓ Cancel wins over timeout")

    @pytest.mark.asyncio
    async def test_success_when_no_cancellation(self):
        """Test normal success path when no cancellation requested."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-4")

        # Create job
        job = JobRecord(
            job_id="normal_success_test",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await job_store.enqueue(job)

        # Mark as running (no cancellation)
        await job_store.update_state("normal_success_test", JobState.RUNNING)

        # Finalize with exit_code=0
        await worker._finalize_job(
            job_id="normal_success_test",
            exit_code=0
        )

        # Verify: State should be SUCCEEDED
        final_job = await job_store.get("normal_success_test")
        assert final_job.state == JobState.SUCCEEDED
        assert final_job.error_message is None
        assert final_job.exit_code == 0

        print("✓ Normal success path works")

    @pytest.mark.asyncio
    async def test_timeout_when_no_cancellation(self):
        """Test timeout handling when no cancellation requested."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-5")

        # Create job
        job = JobRecord(
            job_id="timeout_test",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            attempt=5,
            max_attempts=5  # At max attempts for timeout category
        )
        await job_store.enqueue(job)

        # Mark as running (no cancellation)
        await job_store.update_state("timeout_test", JobState.RUNNING)

        # Finalize with exit_code=124 (timeout)
        await worker._finalize_job(
            job_id="timeout_test",
            exit_code=124,
            error_message="Command timed out"
        )

        # Verify: State should be TIMEOUT
        final_job = await job_store.get("timeout_test")
        assert final_job.state == JobState.TIMEOUT
        assert "timed out" in final_job.error_message.lower()
        assert final_job.exit_code == 124

        print("✓ Timeout handling works")

    @pytest.mark.asyncio
    async def test_failure_when_no_cancellation(self):
        """Test failure handling when no cancellation requested."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-6")

        # Create job
        job = JobRecord(
            job_id="failure_test",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            attempt=1,
            max_attempts=1  # Disable retry for this test
        )
        await job_store.enqueue(job)

        # Mark as running (no cancellation)
        await job_store.update_state("failure_test", JobState.RUNNING)

        # Finalize with exit_code=1 (failure)
        await worker._finalize_job(
            job_id="failure_test",
            exit_code=1,
            error_message="Command failed"
        )

        # Verify: State should be FAILED
        final_job = await job_store.get("failure_test")
        assert final_job.state == JobState.FAILED
        assert "Command failed" in final_job.error_message
        assert final_job.exit_code == 1

        print("✓ Failure handling works")

    @pytest.mark.asyncio
    async def test_provenance_fields_preserved(self):
        """Test that provenance fields are preserved during finalization."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        worker = JobWorker(job_store, worker_id="test-worker-7")

        # Create job
        job = JobRecord(
            job_id="provenance_test",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await job_store.enqueue(job)

        # Mark as running
        await job_store.update_state("provenance_test", JobState.RUNNING)

        # Finalize with provenance fields
        await worker._finalize_job(
            job_id="provenance_test",
            exit_code=0,
            run_id="run_123",
            run_dir="/tmp/runs/run_123",
            provenance_path="provenance.json"
        )

        # Verify: Provenance fields preserved
        final_job = await job_store.get("provenance_test")
        assert final_job.state == JobState.SUCCEEDED
        assert final_job.run_id == "run_123"
        assert final_job.run_dir == "/tmp/runs/run_123"
        assert final_job.provenance_path == "provenance.json"

        print("✓ Provenance fields preserved")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
