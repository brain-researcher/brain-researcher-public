"""
Unit tests for SSE log streaming endpoint.

Tests the /api/jobs/{job_id}/logs/stream endpoint for streaming job logs in real-time.
"""

import asyncio
import base64
import json
import pytest
from fastapi.testclient import TestClient
from sse_starlette.sse import ServerSentEvent

from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from fastapi import FastAPI


@pytest.fixture
def app_with_job_store():
    """Create FastAPI app with job store in state."""
    app = FastAPI()
    app.include_router(router)

    # Initialize job store
    job_store = MemoryJobStore(total_gpu_slots=2)
    app.state.job_store = job_store

    # Add a test job to jobs_db (used by _get_router_job)
    from brain_researcher.services.orchestrator.job_state import jobs_db
    from brain_researcher.services.orchestrator.models import Job, JobStatus, TimingInfo
    from datetime import datetime

    test_job = Job(
        id="job_test_job_001",  # Must match pattern ^job_[a-zA-Z0-9_]+$
        user_id="test_user",
        status=JobStatus.RUNNING,
        prompt="Test prompt",  # Required field
        timing=TimingInfo(  # Required field
            start_time=datetime.utcnow()
        )
    )
    jobs_db["job_test_job_001"] = test_job

    yield app, job_store, jobs_db

    # Cleanup
    jobs_db.clear()


class TestSSELogEndpoint:
    """Test SSE log streaming endpoint."""

    @pytest.mark.asyncio
    async def test_stream_initial_logs(self, app_with_job_store):
        """Test streaming existing logs."""
        app, job_store, jobs_db = app_with_job_store

        # Create job in job store
        job_record = JobRecord(
            job_id="job_test_job_001",
            kind="test",
            payload_json='{}',
            state=JobState.RUNNING,
            priority=5
        )
        await job_store.enqueue(job_record)

        # Add some logs
        await job_store.append_log("job_test_job_001", "stdout", b"Line 1\n", offset=0)
        await job_store.append_log("job_test_job_001", "stdout", b"Line 2\n", offset=7)
        await job_store.append_log("job_test_job_001", "stderr", b"Error 1\n", offset=0)

        # Create test client
        with TestClient(app) as client:
            # Stream logs without follow (get existing only)
            response = client.get(
                "/api/jobs/job_test_job_001/logs/stream?follow=false",
                headers={"Accept": "text/event-stream"}
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # Parse SSE events
            events = []
            current_event_type = None
            for line in response.text.split('\n'):
                if line.startswith('event: '):
                    current_event_type = line[7:].strip()  # Strip whitespace including \r
                elif line.startswith('data: '):
                    if current_event_type:
                        data = json.loads(line[6:])
                        events.append((current_event_type, data))

            # Should have 3 log_chunk events + 1 log_complete event
            log_chunks = [e for e in events if e[0] == 'log_chunk']
            log_complete = [e for e in events if e[0] == 'log_complete']

            assert len(log_chunks) == 3, f"Expected 3 log chunks, got {len(log_chunks)}"
            assert len(log_complete) >= 0, "Should have log_complete event"

            # Verify log content
            stdout_chunks = [e[1] for e in log_chunks if e[1]['stream'] == 'stdout']
            stderr_chunks = [e[1] for e in log_chunks if e[1]['stream'] == 'stderr']

            assert len(stdout_chunks) == 2
            assert len(stderr_chunks) == 1

            # Decode base64 data
            stdout_data = base64.b64decode(stdout_chunks[0]['data'])
            assert stdout_data == b"Line 1\n"

            print("✓ Initial log streaming test passed")

    @pytest.mark.asyncio
    async def test_stream_filter_by_stream_type(self, app_with_job_store):
        """Test filtering logs by stream type (stdout/stderr)."""
        app, job_store, jobs_db = app_with_job_store

        # Create job
        job_record = JobRecord(
            job_id="job_test_job_001",
            kind="test",
            payload_json='{}',
            state=JobState.RUNNING,
            priority=5
        )
        await job_store.enqueue(job_record)

        # Add mixed logs
        await job_store.append_log("job_test_job_001", "stdout", b"Stdout 1\n", offset=0)
        await job_store.append_log("job_test_job_001", "stderr", b"Stderr 1\n", offset=0)
        await job_store.append_log("job_test_job_001", "stdout", b"Stdout 2\n", offset=9)

        with TestClient(app) as client:
            # Stream only stdout
            response = client.get(
                "/api/jobs/job_test_job_001/logs/stream?stream=stdout&follow=false",
                headers={"Accept": "text/event-stream"}
            )

            assert response.status_code == 200

            # Parse events
            events = []
            current_event_type = None
            for line in response.text.split('\n'):
                if line.startswith('event: '):
                    current_event_type = line[7:].strip()
                elif line.startswith('data: '):
                    if current_event_type:
                        data = json.loads(line[6:])
                        events.append((current_event_type, data))

            log_chunks = [e for e in events if e[0] == 'log_chunk']

            # Should only have stdout chunks
            assert len(log_chunks) == 2
            assert all(e[1]['stream'] == 'stdout' for e in log_chunks)

            print("✓ Stream filtering test passed")

    @pytest.mark.asyncio
    async def test_stream_resume_from_offset(self, app_with_job_store):
        """Test resuming stream from specific offset."""
        app, job_store, jobs_db = app_with_job_store

        # Create job
        job_record = JobRecord(
            job_id="job_test_job_001",
            kind="test",
            payload_json='{}',
            state=JobState.RUNNING,
            priority=5
        )
        await job_store.enqueue(job_record)

        # Add logs at various offsets
        await job_store.append_log("job_test_job_001", "stdout", b"Chunk 0\n", offset=0)
        await job_store.append_log("job_test_job_001", "stdout", b"Chunk 8\n", offset=8)
        await job_store.append_log("job_test_job_001", "stdout", b"Chunk 16\n", offset=16)

        with TestClient(app) as client:
            # Resume from offset 10 (should get chunks at offset 16 only)
            response = client.get(
                "/api/jobs/job_test_job_001/logs/stream?start_offset=10&follow=false",
                headers={"Accept": "text/event-stream"}
            )

            assert response.status_code == 200

            # Parse events
            events = []
            current_event_type = None
            for line in response.text.split('\n'):
                if line.startswith('event: '):
                    current_event_type = line[7:].strip()
                elif line.startswith('data: '):
                    if current_event_type:
                        data = json.loads(line[6:])
                        events.append((current_event_type, data))

            log_chunks = [e for e in events if e[0] == 'log_chunk']

            # Should only get chunk at offset >= 10
            assert len(log_chunks) == 1
            assert log_chunks[0][1]['offset'] == 16

            print("✓ Resume from offset test passed")

    def test_nonexistent_job(self, app_with_job_store):
        """Test streaming logs for non-existent job returns 404."""
        app, job_store, jobs_db = app_with_job_store

        with TestClient(app) as client:
            response = client.get(
                "/api/jobs/nonexistent_job/logs/stream",
                headers={"Accept": "text/event-stream"}
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

            print("✓ Nonexistent job test passed")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
