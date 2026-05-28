"""
Unit tests for JobStore log persistence.

Tests log append and retrieval operations for MemoryJobStore,
SqliteJobStore, and DualJobStore implementations.
"""

import pytest
import asyncio
from pathlib import Path

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState, LogChunk
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore


class TestLogStorageMemory:
    """Test log storage in MemoryJobStore."""

    @pytest.mark.asyncio
    async def test_append_and_retrieve_single_chunk(self):
        """Test appending and retrieving a single log chunk."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue a job first
        job = JobRecord(
            job_id="test_job_001",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await store.enqueue(job)

        # Append log chunk
        log_data = b"Starting task execution..."
        await store.append_log("test_job_001", "stdout", log_data, offset=0)

        # Retrieve logs
        chunks = await store.iter_logs("test_job_001")

        assert len(chunks) == 1
        assert chunks[0].job_id == "test_job_001"
        assert chunks[0].stream == "stdout"
        assert chunks[0].data == log_data
        assert chunks[0].offset == 0

    @pytest.mark.asyncio
    async def test_append_multiple_chunks_stdout_stderr(self):
        """Test appending multiple chunks to stdout and stderr."""
        store = MemoryJobStore(total_gpu_slots=2)

        # Enqueue job
        job = JobRecord(
            job_id="test_job_002",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await store.enqueue(job)

        # Append multiple chunks
        await store.append_log("test_job_002", "stdout", b"Line 1\n", offset=0)
        await store.append_log("test_job_002", "stdout", b"Line 2\n", offset=7)
        await store.append_log("test_job_002", "stderr", b"Warning!\n", offset=0)
        await store.append_log("test_job_002", "stdout", b"Line 3\n", offset=14)

        # Retrieve all logs
        all_chunks = await store.iter_logs("test_job_002")
        assert len(all_chunks) == 4

        # Retrieve stdout only
        stdout_chunks = await store.iter_logs("test_job_002", stream="stdout")
        assert len(stdout_chunks) == 3
        assert all(c.stream == "stdout" for c in stdout_chunks)

        # Retrieve stderr only
        stderr_chunks = await store.iter_logs("test_job_002", stream="stderr")
        assert len(stderr_chunks) == 1
        assert stderr_chunks[0].stream == "stderr"
        assert stderr_chunks[0].data == b"Warning!\n"

    @pytest.mark.asyncio
    async def test_iter_logs_with_start_offset(self):
        """Test retrieving logs from specific offset."""
        store = MemoryJobStore(total_gpu_slots=2)

        job = JobRecord(
            job_id="test_job_003",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await store.enqueue(job)

        # Append chunks with offsets
        await store.append_log("test_job_003", "stdout", b"Chunk 0", offset=0)
        await store.append_log("test_job_003", "stdout", b"Chunk 100", offset=100)
        await store.append_log("test_job_003", "stdout", b"Chunk 200", offset=200)
        await store.append_log("test_job_003", "stdout", b"Chunk 300", offset=300)

        # Get logs from offset 150
        chunks = await store.iter_logs("test_job_003", start_offset=150)
        assert len(chunks) == 2
        assert chunks[0].offset == 200
        assert chunks[1].offset == 300

        # Get logs from offset 0 (all)
        chunks_all = await store.iter_logs("test_job_003", start_offset=0)
        assert len(chunks_all) == 4

    @pytest.mark.asyncio
    async def test_iter_logs_nonexistent_job(self):
        """Test retrieving logs for nonexistent job returns empty list."""
        store = MemoryJobStore(total_gpu_slots=2)

        chunks = await store.iter_logs("nonexistent_job")
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_append_log_sorts_by_offset(self):
        """Test that chunks are returned sorted by offset."""
        store = MemoryJobStore(total_gpu_slots=2)

        job = JobRecord(
            job_id="test_job_004",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await store.enqueue(job)

        # Append chunks out of order
        await store.append_log("test_job_004", "stdout", b"Third", offset=300)
        await store.append_log("test_job_004", "stdout", b"First", offset=0)
        await store.append_log("test_job_004", "stdout", b"Second", offset=100)

        # Should be returned in offset order
        chunks = await store.iter_logs("test_job_004")
        assert len(chunks) == 3
        assert chunks[0].offset == 0
        assert chunks[0].data == b"First"
        assert chunks[1].offset == 100
        assert chunks[1].data == b"Second"
        assert chunks[2].offset == 300
        assert chunks[2].data == b"Third"


class TestLogStorageSqlite:
    """Test log storage in SqliteJobStore."""

    @pytest.mark.asyncio
    async def test_append_and_retrieve_single_chunk(self, tmp_path):
        """Test appending and retrieving a single log chunk."""
        db_path = tmp_path / "logs_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        try:
            # Enqueue a job
            job = JobRecord(
                job_id="sqlite_job_001",
                kind="test",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5
            )
            await store.enqueue(job)

            # Append log chunk
            log_data = b"SQLite test log"
            await store.append_log("sqlite_job_001", "stdout", log_data, offset=0)

            # Retrieve logs
            chunks = await store.iter_logs("sqlite_job_001")

            assert len(chunks) == 1
            assert chunks[0].job_id == "sqlite_job_001"
            assert chunks[0].stream == "stdout"
            assert chunks[0].data == log_data
            assert chunks[0].offset == 0

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_append_large_log_chunk(self, tmp_path):
        """Test appending large binary log chunk (>64KB)."""
        db_path = tmp_path / "large_logs_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        try:
            job = JobRecord(
                job_id="large_log_job",
                kind="test",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5
            )
            await store.enqueue(job)

            # Create 100KB log chunk
            large_data = b"X" * (100 * 1024)
            await store.append_log("large_log_job", "stdout", large_data, offset=0)

            # Retrieve and verify
            chunks = await store.iter_logs("large_log_job")
            assert len(chunks) == 1
            assert len(chunks[0].data) == 100 * 1024
            assert chunks[0].data == large_data

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_append_duplicate_offset_replaces(self, tmp_path):
        """Test that INSERT OR REPLACE works for duplicate offsets."""
        db_path = tmp_path / "replace_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        try:
            job = JobRecord(
                job_id="replace_job",
                kind="test",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5
            )
            await store.enqueue(job)

            # Append chunk at offset 0
            await store.append_log("replace_job", "stdout", b"Original", offset=0)

            # Append different data at same offset (should replace)
            await store.append_log("replace_job", "stdout", b"Updated", offset=0)

            # Should have only one chunk with updated data
            chunks = await store.iter_logs("replace_job")
            assert len(chunks) == 1
            assert chunks[0].data == b"Updated"

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_iter_logs_with_filters(self, tmp_path):
        """Test iter_logs with stream filter and offset."""
        db_path = tmp_path / "filters_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        try:
            job = JobRecord(
                job_id="filter_job",
                kind="test",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5
            )
            await store.enqueue(job)

            # Append mixed stdout/stderr at various offsets
            await store.append_log("filter_job", "stdout", b"Out 0", offset=0)
            await store.append_log("filter_job", "stderr", b"Err 0", offset=0)
            await store.append_log("filter_job", "stdout", b"Out 100", offset=100)
            await store.append_log("filter_job", "stderr", b"Err 100", offset=100)
            await store.append_log("filter_job", "stdout", b"Out 200", offset=200)

            # Get all logs
            all_chunks = await store.iter_logs("filter_job")
            assert len(all_chunks) == 5

            # Get stdout only
            stdout_chunks = await store.iter_logs("filter_job", stream="stdout")
            assert len(stdout_chunks) == 3
            assert all(c.stream == "stdout" for c in stdout_chunks)

            # Get stderr only from offset 50
            stderr_chunks = await store.iter_logs("filter_job", start_offset=50, stream="stderr")
            assert len(stderr_chunks) == 1
            assert stderr_chunks[0].offset == 100

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_logs_persist_across_restart(self, tmp_path):
        """Test that logs persist across store restart."""
        db_path = tmp_path / "persist_logs.db"

        # Phase 1: Create store and append logs
        store1 = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store1.initialize()

        job = JobRecord(
            job_id="persist_job",
            kind="test",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5
        )
        await store1.enqueue(job)

        await store1.append_log("persist_job", "stdout", b"Before restart", offset=0)
        await store1.close()

        # Phase 2: Reopen and verify logs
        store2 = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store2.initialize()

        try:
            chunks = await store2.iter_logs("persist_job")
            assert len(chunks) == 1
            assert chunks[0].data == b"Before restart"
        finally:
            await store2.close()


class TestLogStorageConcurrency:
    """Test concurrent log appends."""

    @pytest.mark.asyncio
    async def test_concurrent_log_appends(self, tmp_path):
        """Test concurrent log appends from multiple tasks."""
        db_path = tmp_path / "concurrent_logs.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        try:
            job = JobRecord(
                job_id="concurrent_job",
                kind="test",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5
            )
            await store.enqueue(job)

            # Append logs concurrently
            async def append_chunk(offset: int):
                data = f"Chunk {offset}\n".encode()
                await store.append_log("concurrent_job", "stdout", data, offset=offset)

            # Launch 50 concurrent appends
            tasks = [append_chunk(i * 10) for i in range(50)]
            await asyncio.gather(*tasks)

            # Verify all chunks persisted
            chunks = await store.iter_logs("concurrent_job")
            assert len(chunks) == 50

            # Verify order is correct
            for i, chunk in enumerate(chunks):
                assert chunk.offset == i * 10

        finally:
            await store.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
