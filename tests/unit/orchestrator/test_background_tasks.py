"""
Unit tests for background_tasks module.

Tests the SQLite sweeper loop for recovering stale jobs.
"""

import asyncio
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.orchestrator.background_tasks import (
    sqlite_sweeper_loop,
    should_enable_sweeper,
    start_sqlite_sweeper
)


class TestSweeperConfiguration:
    """Test sweeper configuration and helper functions."""

    def test_should_enable_sweeper_memory(self):
        """Memory backend should not enable sweeper."""
        assert should_enable_sweeper('memory') is False
        assert should_enable_sweeper('MEMORY') is False

    def test_should_enable_sweeper_sqlite(self):
        """SQLite backend should enable sweeper."""
        assert should_enable_sweeper('sqlite') is True
        assert should_enable_sweeper('SQLITE') is True

    def test_should_enable_sweeper_dual(self):
        """Dual backend should enable sweeper."""
        assert should_enable_sweeper('dual') is True
        assert should_enable_sweeper('DUAL') is True


class TestSweeperLoop:
    """Test the sweeper loop functionality."""

    @pytest.mark.asyncio
    async def test_sweeper_calls_recover_stale_jobs(self):
        """Test that sweeper periodically calls recover_stale_jobs."""
        # Create mock job store
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {
            'recovered': 2,
            'gpus_freed': 1
        }

        # Create stop event to control loop
        stop_event = asyncio.Event()

        # Start sweeper with short interval
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=mock_store,
                interval_secs=1,
                stop_event=stop_event
            )
        )

        # Let it run for a bit (should do 2-3 sweeps)
        await asyncio.sleep(2.5)

        # Stop sweeper
        stop_event.set()
        await sweeper_task

        # Verify recover_stale_jobs was called multiple times
        assert mock_store.recover_stale_jobs.call_count >= 2
        # Verify it was called with timestamps
        for call in mock_store.recover_stale_jobs.call_args_list:
            assert 'now_ts' in call.kwargs
            assert isinstance(call.kwargs['now_ts'], int)

    @pytest.mark.asyncio
    async def test_sweeper_stops_gracefully(self):
        """Test that sweeper stops when stop_event is set."""
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {'recovered': 0, 'gpus_freed': 0}

        stop_event = asyncio.Event()

        # Start sweeper with long interval
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=mock_store,
                interval_secs=60,
                stop_event=stop_event
            )
        )

        # Let it run briefly
        await asyncio.sleep(0.1)

        # Stop sweeper
        stop_start = time.time()
        stop_event.set()
        await sweeper_task
        stop_duration = time.time() - stop_start

        # Should stop within one sleep interval (< 6 seconds)
        # The sweeper sleeps for min(interval, 5) = 5 seconds between checks
        assert stop_duration < 6.0

    @pytest.mark.asyncio
    async def test_sweeper_handles_cancellation(self):
        """Test that sweeper handles cancellation properly."""
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {'recovered': 0, 'gpus_freed': 0}

        # Start sweeper
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=mock_store,
                interval_secs=60,
                stop_event=None
            )
        )

        await asyncio.sleep(0.1)

        # Cancel task
        sweeper_task.cancel()

        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await sweeper_task

    @pytest.mark.asyncio
    async def test_sweeper_error_handling(self):
        """Test that sweeper continues after errors."""
        mock_store = AsyncMock()

        # First call succeeds, second fails, third succeeds
        mock_store.recover_stale_jobs.side_effect = [
            {'recovered': 1, 'gpus_freed': 0},
            Exception("Database connection lost"),
            {'recovered': 0, 'gpus_freed': 0}
        ]

        stop_event = asyncio.Event()

        # Start sweeper
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=mock_store,
                interval_secs=0.5,
                stop_event=stop_event
            )
        )

        # Let it run for at least 3 sweeps
        await asyncio.sleep(2.0)

        # Stop sweeper
        stop_event.set()
        await sweeper_task

        # Verify at least 3 calls were attempted (timing may allow 4)
        assert mock_store.recover_stale_jobs.call_count >= 3

    @pytest.mark.asyncio
    async def test_sweeper_logs_recoveries(self, caplog):
        """Test that sweeper logs when jobs are recovered."""
        import logging
        caplog.set_level(logging.WARNING)

        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {
            'recovered': 5,
            'gpus_freed': 2
        }

        stop_event = asyncio.Event()

        # Start sweeper
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=mock_store,
                interval_secs=0.5,
                stop_event=stop_event
            )
        )

        # Let it run one sweep
        await asyncio.sleep(0.8)

        # Stop sweeper
        stop_event.set()
        await sweeper_task

        # Verify warning log for recovered jobs
        assert any('recovered 5 stale jobs' in record.message for record in caplog.records)
        assert any('freed 2 GPU slots' in record.message for record in caplog.records)


class TestStartSqliteSweeper:
    """Test the start_sqlite_sweeper helper function."""

    @pytest.mark.asyncio
    async def test_start_sweeper_sqlite_backend(self):
        """Test starting sweeper with sqlite backend."""
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {'recovered': 0, 'gpus_freed': 0}

        # Start sweeper
        task = await start_sqlite_sweeper(
            job_store=mock_store,
            backend='sqlite',
            stop_event=asyncio.Event()
        )

        # Should return a task
        assert task is not None
        assert isinstance(task, asyncio.Task)

        # Clean up
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_start_sweeper_memory_backend(self):
        """Test that sweeper is not started for memory backend."""
        mock_store = AsyncMock()

        # Start sweeper with memory backend
        task = await start_sqlite_sweeper(
            job_store=mock_store,
            backend='memory',
            stop_event=asyncio.Event()
        )

        # Should return None
        assert task is None

        # Should not have called recover
        mock_store.recover_stale_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_sweeper_dual_backend(self):
        """Test starting sweeper with dual backend."""
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {'recovered': 0, 'gpus_freed': 0}

        # Start sweeper with dual backend
        task = await start_sqlite_sweeper(
            job_store=mock_store,
            backend='dual',
            stop_event=asyncio.Event()
        )

        # Should return a task
        assert task is not None
        assert isinstance(task, asyncio.Task)

        # Clean up
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_start_sweeper_respects_interval(self):
        """Test that sweeper respects BR_QUEUE_SWEEP_INTERVAL_SECS."""
        mock_store = AsyncMock()
        mock_store.recover_stale_jobs.return_value = {'recovered': 0, 'gpus_freed': 0}

        stop_event = asyncio.Event()

        # Mock environment variable
        with patch.dict('os.environ', {'BR_QUEUE_SWEEP_INTERVAL_SECS': '10'}):
            task = await start_sqlite_sweeper(
                job_store=mock_store,
                backend='sqlite',
                stop_event=stop_event
            )

            # Let it run briefly
            await asyncio.sleep(0.1)

            # Stop immediately
            stop_event.set()
            await task

            # Should not have completed even one sweep (interval is 10s)
            # Note: It might have done one immediate sweep at start
            assert mock_store.recover_stale_jobs.call_count <= 1


class TestSweeperIntegration:
    """Integration tests with real SqliteJobStore."""

    @pytest.mark.asyncio
    async def test_sweeper_with_real_store(self, tmp_path):
        """Test sweeper with actual SqliteJobStore."""
        from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore
        from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

        # Create and initialize store
        db_path = tmp_path / "sweeper_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        # Enqueue a job and claim it with short lease
        job = JobRecord(
            job_id="job_sweeper_test",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )
        await store.enqueue(job)

        # Claim with 1 second lease
        claimed = await store.claim_next(worker_id="worker-test", lease_ttl=1)
        assert claimed is not None

        # Start sweeper with short interval
        stop_event = asyncio.Event()
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(
                job_store=store,
                interval_secs=2,
                stop_event=stop_event
            )
        )

        # Wait for lease to expire and sweeper to recover
        await asyncio.sleep(3)

        # Stop sweeper
        stop_event.set()
        await sweeper_task

        # Verify job was recovered
        recovered_job = await store.get("job_sweeper_test")
        assert recovered_job is not None
        assert recovered_job.state == JobState.QUEUED
        assert recovered_job.worker_id is None

        await store.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
