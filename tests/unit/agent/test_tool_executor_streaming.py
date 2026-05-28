"""
Unit tests for ToolExecutor log streaming functionality.

Tests that ToolExecutor properly streams stdout/stderr to JobStore
when job_store and job_id are provided in execution context.
"""

import asyncio
import pytest
import time
from pathlib import Path

from brain_researcher.services.agent.tool_executor import (
    ToolExecutor,
    ToolExecutionRequest,
    ExecutionMode,
)
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState


class TestToolExecutorStreaming:
    """Test ToolExecutor streaming to JobStore."""

    def test_streaming_with_memory_job_store(self):
        """Test streaming stdout/stderr to MemoryJobStore."""
        # Setup
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            # Enqueue a job
            job = JobRecord(
                job_id="stream_test_001",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            asyncio.run(job_store.enqueue(job))

            # Execute command with streaming context
            request = ToolExecutionRequest(
                tool_name="test_stream",
                parameters={"command": "echo 'Hello from stdout' && echo 'Error from stderr' >&2"},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                context={
                    'job_store': job_store,
                    'job_id': 'stream_test_001'
                }
            )

            result = executor.execute(request)

            # Debug: print error if failed
            if result.status != "success":
                print(f"Execution failed: {result.error}")
                print(f"Result: {result.result}")

            # Verify execution succeeded
            assert result.status == "success"
            assert "Hello from stdout" in result.result["stdout"]
            assert "Error from stderr" in result.result["stderr"]

            # Wait for background log persistence to complete
            time.sleep(0.5)

            # Verify logs were persisted to job store
            logs = asyncio.run(job_store.iter_logs("stream_test_001"))
            assert len(logs) > 0

            # Check stdout logs
            stdout_logs = [log for log in logs if log.stream == "stdout"]
            assert len(stdout_logs) > 0
            stdout_data = b"".join([log.data for log in stdout_logs])
            assert b"Hello from stdout" in stdout_data

            # Check stderr logs
            stderr_logs = [log for log in logs if log.stream == "stderr"]
            assert len(stderr_logs) > 0
            stderr_data = b"".join([log.data for log in stderr_logs])
            assert b"Error from stderr" in stderr_data

            print(f"✓ Streaming test passed: {len(logs)} log chunks persisted")
        finally:
            executor.shutdown()

    def test_streaming_large_output(self):
        """Test streaming with large output (>64KB)."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            job = JobRecord(
                job_id="large_stream_test",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            asyncio.run(job_store.enqueue(job))

            # Generate 100KB of output
            request = ToolExecutionRequest(
                tool_name="large_output",
                parameters={"command": "python -c \"print('X' * 102400)\""},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                context={
                    'job_store': job_store,
                    'job_id': 'large_stream_test'
                }
            )

            result = executor.execute(request)

            assert result.status == "success"

            # Wait for background log persistence
            time.sleep(0.5)

            # Verify multiple chunks were created
            logs = asyncio.run(job_store.iter_logs("large_stream_test"))
            assert len(logs) > 1, "Large output should create multiple chunks"

            # Verify total size is correct
            total_size = sum(len(log.data) for log in logs)
            assert total_size >= 100000, f"Expected >=100KB, got {total_size} bytes"

            print(f"✓ Large output test passed: {len(logs)} chunks, {total_size} bytes total")
        finally:
            executor.shutdown()

    def test_streaming_incremental_output(self):
        """Test that logs are streamed incrementally, not all at once."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            job = JobRecord(
                job_id="incremental_test",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            asyncio.run(job_store.enqueue(job))

            # Command that outputs in stages with delays
            cmd = """python -c "
import time, sys
for i in range(5):
    print(f'Line {i}', flush=True)
    time.sleep(0.1)
"
            """.strip()

            request = ToolExecutionRequest(
                tool_name="incremental",
                parameters={"command": cmd},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                timeout=10.0,
                context={
                    'job_store': job_store,
                    'job_id': 'incremental_test'
                }
            )

            result = executor.execute(request)

            assert result.status == "success"

            # Wait for background log persistence
            time.sleep(0.5)

            # Verify logs exist
            logs = asyncio.run(job_store.iter_logs("incremental_test"))
            assert len(logs) > 0

            # Verify offsets are sequential
            stdout_logs = sorted([log for log in logs if log.stream == "stdout"], key=lambda x: x.offset)
            if len(stdout_logs) > 1:
                for i in range(1, len(stdout_logs)):
                    prev_log = stdout_logs[i-1]
                    curr_log = stdout_logs[i]
                    # Current offset should start where previous ended
                    assert curr_log.offset == prev_log.offset + len(prev_log.data), \
                        f"Offset mismatch: {prev_log.offset} + {len(prev_log.data)} != {curr_log.offset}"

            print(f"✓ Incremental streaming test passed: {len(logs)} chunks with sequential offsets")
        finally:
            executor.shutdown()

    def test_no_streaming_without_context(self):
        """Test that execution works normally when no job_store context is provided."""
        executor = ToolExecutor()

        try:
            # Execute without job_store context
            request = ToolExecutionRequest(
                tool_name="no_stream",
                parameters={"command": "echo 'No streaming'"},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True
            )

            result = executor.execute(request)

            assert result.status == "success"
            assert "No streaming" in result.result["stdout"]

            print("✓ Non-streaming execution test passed")
        finally:
            executor.shutdown()

    def test_streaming_with_empty_output(self):
        """Test streaming when command produces no output."""
        job_store = MemoryJobStore(total_gpu_slots=2)
        executor = ToolExecutor()

        try:
            job = JobRecord(
                job_id="empty_output_test",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            asyncio.run(job_store.enqueue(job))

            # Command with no output
            request = ToolExecutionRequest(
                tool_name="empty",
                parameters={"command": "true"},  # Exit 0 with no output
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                context={
                    'job_store': job_store,
                    'job_id': 'empty_output_test'
                }
            )

            result = executor.execute(request)

            assert result.status == "success"

            # Wait for background log persistence
            time.sleep(0.5)

            # Should have no logs (or empty logs)
            logs = asyncio.run(job_store.iter_logs("empty_output_test"))
            total_data = b"".join([log.data for log in logs])
            assert len(total_data) == 0 or total_data.strip() == b""

            print("✓ Empty output test passed")
        finally:
            executor.shutdown()


class TestToolExecutorStreamingSqlite:
    """Test streaming with SqliteJobStore."""

    @pytest.mark.asyncio
    async def test_streaming_persists_to_sqlite(self, tmp_path):
        """Test that streamed logs persist in SQLite."""
        db_path = tmp_path / "streaming_test.db"
        job_store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await job_store.initialize()

        try:
            executor = ToolExecutor()

            job = JobRecord(
                job_id="sqlite_stream_test",
                kind="test",
                payload_json='{}',
                state=JobState.RUNNING,
                priority=5
            )
            await job_store.enqueue(job)

            # Execute with streaming
            request = ToolExecutionRequest(
                tool_name="sqlite_stream",
                parameters={"command": "echo 'SQLite streaming test' && echo 'stderr test' >&2"},
                mode=ExecutionMode.DIRECT_EXECUTION,
                execute_directly=True,
                context={
                    'job_store': job_store,
                    'job_id': 'sqlite_stream_test'
                }
            )

            result = executor.execute(request)

            assert result.status == "success"

            # Wait for background log persistence
            await asyncio.sleep(0.5)

            # Verify logs persisted
            logs = await job_store.iter_logs("sqlite_stream_test")
            assert len(logs) > 0

            # Verify data
            stdout_data = b"".join([log.data for log in logs if log.stream == "stdout"])
            assert b"SQLite streaming test" in stdout_data

            print(f"✓ SQLite streaming test passed: {len(logs)} chunks persisted")

        finally:
            executor.shutdown()
            await job_store.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
