"""
Stress tests for ToolExecutor to verify resource cleanup and high-volume streaming.

Tests:
1. Thread leak detection - verify background loop cleanup
2. High-volume streaming - test with >100MB output
3. Concurrent job streaming - multiple jobs running simultaneously
"""

import asyncio
import pytest
import threading
import time
import gc
from pathlib import Path

from brain_researcher.services.agent.tool_executor import (
    ToolExecutor,
    ToolExecutionRequest,
    ExecutionMode,
)
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState


class TestToolExecutorThreadLeaks:
    """Test that ToolExecutor doesn't leak threads or event loops."""

    def test_background_loop_cleanup(self):
        """Test that background loop thread is cleaned up on shutdown."""
        # Create and shutdown executor multiple times
        for i in range(5):
            # Get thread count before creating executor
            threads_before = {t.name for t in threading.enumerate()}

            executor = ToolExecutor()

            # Verify background loop thread exists
            threads_during = {t.name for t in threading.enumerate()}
            assert "ToolExecutor-AsyncLoop" in threads_during, \
                f"Iteration {i}: Background loop thread not found"

            # Execute a simple command to ensure loop is working
            request = ToolExecutionRequest(
                tool_name="test",
                parameters={"command": "echo 'test'"},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True
            )
            result = executor.execute(request)
            assert result.status == "success"

            # Shutdown executor
            executor.shutdown()

            # Wait for thread to stop
            time.sleep(0.3)

            # Verify ToolExecutor thread is gone
            threads_after = {t.name for t in threading.enumerate()}
            assert "ToolExecutor-AsyncLoop" not in threads_after, \
                f"Iteration {i}: Background loop thread not cleaned up"

            # Verify no ToolExecutor-related threads remain (exclude pytest threads)
            tool_threads = [t for t in threads_after if "ToolExecutor" in t and not t.startswith("pytest_")]
            assert len(tool_threads) == 0, \
                f"Iteration {i}: Found {len(tool_threads)} ToolExecutor threads after shutdown: {tool_threads}"

        print(f"✓ Thread leak test passed: background loop properly cleaned up in all {i+1} iterations")

    def test_event_loop_no_leak(self):
        """Test that event loops are not leaked across multiple executor instances."""
        executors = []

        # Create 10 executors
        for i in range(10):
            executor = ToolExecutor()
            executors.append(executor)

        # Verify each has its own loop
        loops = [e._bg_loop for e in executors]
        assert len(set(loops)) == 10, "Executors should have distinct event loops"

        # Shutdown all
        for executor in executors:
            executor.shutdown()

        time.sleep(1.0)

        # Verify all loops are stopped
        for i, loop in enumerate(loops):
            assert not loop.is_running(), f"Loop {i} still running after shutdown"

        print(f"✓ Event loop leak test passed: created and cleaned up 10 executors")


class TestHighVolumeStreaming:
    """Test streaming with very large outputs."""

    def test_stream_100mb_output(self):
        """Test streaming 100MB+ of output data."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            job = JobRecord(
                job_id="large_stream_100mb",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            asyncio.run(job_store.enqueue(job))

            # Generate 100MB of output (100 lines of 1MB each)
            # Use Python's sys.stdout.buffer.write for fast binary output
            cmd = """python -c "
import sys
data = b'X' * (1024 * 1024)  # 1MB chunk
for i in range(100):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
"
            """.strip()

            request = ToolExecutionRequest(
                tool_name="large_output_100mb",
                parameters={"command": cmd},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                timeout=60.0,
                context={
                    'job_store': job_store,
                    'job_id': 'large_stream_100mb'
                }
            )

            start_time = time.time()
            result = executor.execute(request)
            elapsed = time.time() - start_time

            assert result.status == "success"

            # Wait for background log persistence
            time.sleep(2.0)

            # Verify logs were persisted in chunks
            logs = asyncio.run(job_store.iter_logs("large_stream_100mb"))
            total_size = sum(len(log.data) for log in logs)

            # Should have ~100MB of data
            expected_size = 100 * 1024 * 1024
            assert total_size >= expected_size * 0.95, \
                f"Expected ~{expected_size} bytes, got {total_size}"

            # Should have multiple chunks (not one giant chunk)
            assert len(logs) > 10, \
                f"Expected multiple chunks for 100MB, got {len(logs)}"

            print(f"✓ 100MB streaming test passed: {len(logs)} chunks, "
                  f"{total_size:,} bytes in {elapsed:.2f}s "
                  f"({total_size / elapsed / 1024 / 1024:.2f} MB/s)")

        finally:
            executor.shutdown()

    @pytest.mark.asyncio
    async def test_stream_large_to_sqlite(self, tmp_path):
        """Test streaming large output to SQLite persists correctly."""
        db_path = tmp_path / "large_stream.db"
        job_store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await job_store.initialize()

        executor = ToolExecutor()

        try:
            job = JobRecord(
                job_id="sqlite_large_stream",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            await job_store.enqueue(job)

            # Generate 50MB to SQLite
            cmd = """python -c "
import sys
data = b'X' * (1024 * 1024)
for i in range(50):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
"
            """.strip()

            request = ToolExecutionRequest(
                tool_name="sqlite_large",
                parameters={"command": cmd},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                timeout=60.0,
                context={
                    'job_store': job_store,
                    'job_id': 'sqlite_large_stream'
                }
            )

            result = executor.execute(request)
            assert result.status == "success"

            # Wait for persistence
            await asyncio.sleep(2.0)

            # Verify persistence
            logs = await job_store.iter_logs("sqlite_large_stream")
            total_size = sum(len(log.data) for log in logs)

            assert total_size >= 50 * 1024 * 1024 * 0.95
            assert len(logs) > 5

            print(f"✓ SQLite large streaming test passed: {len(logs)} chunks, "
                  f"{total_size:,} bytes persisted")

        finally:
            executor.shutdown()
            await job_store.close()


class TestConcurrentJobStreaming:
    """Test multiple jobs streaming simultaneously."""

    def test_concurrent_streaming_jobs(self):
        """Test 5 jobs streaming concurrently."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            # Create 5 jobs
            job_ids = [f"concurrent_job_{i}" for i in range(5)]
            for job_id in job_ids:
                job = JobRecord(
                    job_id=job_id,
                    kind="test",
                    payload_json='{}',
                    state=JobState.RUNNING,
                    priority=5
                )
                asyncio.run(job_store.enqueue(job))

            # Run all jobs concurrently
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = []
                for i, job_id in enumerate(job_ids):
                    # Each job outputs 10MB
                    cmd = f"""python -c "
import sys, time
for i in range(10):
    sys.stdout.buffer.write(b'Job{i}' * (1024 * 1024 // 4))
    sys.stdout.buffer.flush()
    time.sleep(0.1)
print('Job{i} complete')
"
                    """.strip()

                    request = ToolExecutionRequest(
                        tool_name=f"concurrent_{i}",
                        parameters={"command": cmd},
                        mode=ExecutionMode.DIRECT_EXECUTION,
                        execute_directly=True,
                        timeout=30.0,
                        context={
                            'job_store': job_store,
                            'job_id': job_id
                        }
                    )

                    future = pool.submit(executor.execute, request)
                    futures.append(future)

                # Wait for all to complete
                results = [f.result() for f in futures]

            # Verify all succeeded
            assert all(r.status == "success" for r in results)

            # Wait for log persistence
            time.sleep(2.0)

            # Verify logs for each job
            for job_id in job_ids:
                logs = asyncio.run(job_store.iter_logs(job_id))
                total_size = sum(len(log.data) for log in logs)

                # Each job should have ~10MB
                assert total_size >= 10 * 1024 * 1024 * 0.9, \
                    f"Job {job_id}: expected ~10MB, got {total_size:,} bytes"
                assert len(logs) > 0

            print(f"✓ Concurrent streaming test passed: {len(job_ids)} jobs completed")

        finally:
            executor.shutdown()


class TestStressShutdown:
    """Test shutdown under various stress conditions."""

    def test_shutdown_during_streaming(self):
        """Test that shutdown works even when jobs are actively streaming."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        job = JobRecord(
            job_id="shutdown_test",
            kind="test",
            payload_json='{}',
            state=JobState.RUNNING,
            priority=5
        )
        asyncio.run(job_store.enqueue(job))

        # Start a long-running streaming job
        cmd = """python -c "
import sys, time
for i in range(1000):
    sys.stdout.buffer.write(b'X' * 1024)
    sys.stdout.buffer.flush()
    time.sleep(0.01)
"
        """.strip()

        request = ToolExecutionRequest(
            tool_name="long_stream",
            parameters={"command": cmd},
            mode=ExecutionMode.DIRECT_EXECUTION,
            execute_directly=True,
            timeout=60.0,
            context={
                'job_store': job_store,
                'job_id': 'shutdown_test'
            }
        )

        # Start execution in background thread
        import threading
        result_holder = {}
        def run_job():
            try:
                result = executor.execute(request)
                result_holder['result'] = result
            except Exception as e:
                result_holder['error'] = e

        job_thread = threading.Thread(target=run_job)
        job_thread.start()

        # Wait a bit for streaming to start
        time.sleep(1.0)

        # Shutdown executor while job is running
        start_shutdown = time.time()
        executor.shutdown()
        shutdown_time = time.time() - start_shutdown

        # Verify shutdown completes within reasonable time
        assert shutdown_time < 10.0, \
            f"Shutdown took {shutdown_time:.2f}s, expected <10s"

        # Wait for job thread
        job_thread.join(timeout=5.0)

        print(f"✓ Shutdown during streaming test passed: shutdown in {shutdown_time:.2f}s")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
