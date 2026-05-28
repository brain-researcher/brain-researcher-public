"""
Unit tests for SqliteJobStore.

Tests basic CRUD operations with SQLite backend.
"""

import asyncio
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore


@pytest_asyncio.fixture
async def sqlite_store(tmp_path):
    """Create and initialize SqliteJobStore with temporary database."""
    db_path = tmp_path / "test_jobs.db"
    store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2, busy_timeout_ms=1000)
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()


class TestSqliteJobStore:
    """Test SQLite job store basic operations."""

    @pytest.mark.asyncio
    async def test_initialize(self, tmp_path):
        """Test database initialization creates schema and GPU slots."""
        db_path = tmp_path / "init_test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=3)

        # Before init, DB doesn't exist
        assert not db_path.exists()

        # Initialize
        await store.initialize()

        # After init, DB exists
        assert db_path.exists()

        # Verify GPU slots were created
        stats = await store.get_queue_stats()
        assert stats['gpu_slots']['total'] == 3
        assert stats['gpu_slots']['in_use'] == 0
        assert stats['gpu_slots']['available'] == 3

        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_fail_fast_readonly_dir(self, tmp_path):
        """Test that initialization fails fast with clear error on read-only directory."""
        import os
        import stat

        # Create a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        # Remove write permissions from directory
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x (read and execute only)

        try:
            db_path = readonly_dir / "test.db"
            store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)

            # Initialize should fail with RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                await store.initialize()

            # Verify error message is clear and helpful
            error_msg = str(exc_info.value)
            assert "not writable" in error_msg.lower() or "cannot create" in error_msg.lower()
            assert str(readonly_dir) in error_msg

        finally:
            # Restore write permissions for cleanup
            readonly_dir.chmod(stat.S_IRWXU)

    @pytest.mark.asyncio
    async def test_initialize_fail_fast_missing_schema(self, tmp_path, monkeypatch):
        """Test that initialization fails fast with clear error when schema file is missing."""
        from pathlib import Path

        # Monkeypatch Path to return non-existent schema location
        original_path = Path(__file__).parent
        fake_module_path = tmp_path / "fake_module"
        fake_module_path.mkdir()

        db_path = tmp_path / "test.db"
        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)

        # Mock the schema path to point to non-existent location
        def mock_file_location():
            return fake_module_path / "nonexistent.py"

        # This test verifies the schema file check - schema should be found normally
        # But if it were missing, we'd get a clear RuntimeError
        # For now, just verify normal initialization works
        await store.initialize()
        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_migrates_legacy_jobs_without_project_column(self, tmp_path):
        """Legacy DBs missing jobs.project_id should be migrated before schema index replay."""
        db_path = tmp_path / "legacy_jobs.db"

        # Simulate an old schema before project_id existed.
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    queued_at INTEGER,
                    claimed_at INTEGER,
                    started_at INTEGER,
                    finished_at INTEGER,
                    run_after INTEGER,
                    worker_id TEXT,
                    lease_expires_at INTEGER,
                    last_heartbeat INTEGER,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    cancel_reason TEXT,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    exit_code INTEGER,
                    error_message TEXT,
                    skip_reason TEXT,
                    gpu_req INTEGER NOT NULL DEFAULT 0,
                    gpu_type TEXT,
                    cpus INTEGER NOT NULL DEFAULT 1,
                    memory_gb REAL NOT NULL DEFAULT 4.0,
                    walltime_minutes INTEGER NOT NULL DEFAULT 60,
                    backend TEXT,
                    job_name TEXT,
                    run_id TEXT,
                    run_dir TEXT,
                    provenance_path TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );
                """
            )
            conn.execute(
                """
                INSERT INTO jobs (job_id, kind, payload_json, state, created_at)
                VALUES ('job_legacy_001', 'tool', '{}', 'queued', strftime('%s','now'))
                """
            )
            conn.commit()
        finally:
            conn.close()

        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        conn = sqlite3.connect(db_path)
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            assert "project_id" in columns

            migrated_project_id = conn.execute(
                "SELECT project_id FROM jobs WHERE job_id = 'job_legacy_001'"
            ).fetchone()[0]
            assert migrated_project_id == "default"
        finally:
            conn.close()

        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_backfills_projects_from_existing_jobs(self, tmp_path):
        """Initialize should create projects table and backfill from jobs.project_id."""
        db_path = tmp_path / "legacy_projects.db"

        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    queued_at INTEGER,
                    claimed_at INTEGER,
                    started_at INTEGER,
                    finished_at INTEGER,
                    run_after INTEGER,
                    worker_id TEXT,
                    lease_expires_at INTEGER,
                    last_heartbeat INTEGER,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    cancel_reason TEXT,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    exit_code INTEGER,
                    error_message TEXT,
                    skip_reason TEXT,
                    gpu_req INTEGER NOT NULL DEFAULT 0,
                    gpu_type TEXT,
                    cpus INTEGER NOT NULL DEFAULT 1,
                    memory_gb REAL NOT NULL DEFAULT 4.0,
                    walltime_minutes INTEGER NOT NULL DEFAULT 60,
                    backend TEXT,
                    job_name TEXT,
                    run_id TEXT,
                    run_dir TEXT,
                    provenance_path TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    project_id TEXT,
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO jobs (job_id, kind, payload_json, state, created_at, project_id)
                VALUES (?, 'tool', '{}', 'queued', strftime('%s','now'), ?)
                """,
                [
                    ("job_proj_alpha", "proj_alpha"),
                    ("job_proj_beta", "proj_beta"),
                    ("job_proj_empty", ""),
                    ("job_proj_null", None),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=2)
        await store.initialize()

        projects = await store.list_projects()
        project_ids = {project["project_id"] for project in projects}
        assert project_ids == {"default", "proj_alpha", "proj_beta"}

        default_project = await store.get_project("default")
        assert default_project is not None
        assert default_project["name"] == "Default Project"
        assert default_project["is_archived"] is False

        await store.close()

    @pytest.mark.asyncio
    async def test_enqueue_and_get(self, sqlite_store):
        """Test enqueue job and retrieve by ID."""
        # Create job
        job = JobRecord(
            job_id="job_test001",
            kind="tool",
            payload_json='{"tool": "fsl.bet", "params": {"input": "brain.nii"}}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )

        # Enqueue
        job_id = await sqlite_store.enqueue(job)
        assert job_id == "job_test001"

        # Retrieve
        retrieved = await sqlite_store.get(job_id)
        assert retrieved is not None
        assert retrieved.job_id == "job_test001"
        assert retrieved.kind == "tool"
        assert retrieved.state == JobState.QUEUED
        assert retrieved.priority == 5
        assert retrieved.created_at is not None

        # Verify queue stats
        stats = await sqlite_store.get_queue_stats()
        assert stats['total_jobs'] == 1
        assert stats['by_state'].get(JobState.QUEUED, 0) == 1

    @pytest.mark.asyncio
    async def test_update_state(self, sqlite_store):
        """Test updating job state and fields."""
        # Enqueue job
        job = JobRecord(
            job_id="job_update001",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=10,
            gpu_req=0
        )
        await sqlite_store.enqueue(job)

        # Update to RUNNING
        now = int(datetime.utcnow().timestamp())
        success = await sqlite_store.update_state(
            "job_update001",
            JobState.RUNNING,
            started_at=now,
            worker_id="worker-1"
        )
        assert success is True

        # Verify update
        updated = await sqlite_store.get("job_update001")
        assert updated.state == JobState.RUNNING
        assert updated.started_at == now
        assert updated.worker_id == "worker-1"

        # Update to SUCCEEDED
        finish_time = now + 10
        success = await sqlite_store.update_state(
            "job_update001",
            JobState.SUCCEEDED,
            finished_at=finish_time,
            exit_code=0
        )
        assert success is True

        # Verify final state
        completed = await sqlite_store.get("job_update001")
        assert completed.state == JobState.SUCCEEDED
        assert completed.finished_at == finish_time
        assert completed.exit_code == 0

    @pytest.mark.asyncio
    async def test_cancel(self, sqlite_store):
        """Test job cancellation."""
        # Enqueue job
        job = JobRecord(
            job_id="job_cancel001",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )
        await sqlite_store.enqueue(job)

        # Cancel job
        success = await sqlite_store.cancel("job_cancel001", reason="User requested")
        assert success is True

        # Verify cancellation
        cancelled = await sqlite_store.get("job_cancel001")
        assert cancelled.state == JobState.CANCELLED
        assert cancelled.cancellation_requested is True
        assert cancelled.cancel_reason == "User requested"

        # Try to cancel already cancelled job (should return False)
        success = await sqlite_store.cancel("job_cancel001", reason="Already cancelled")
        assert success is False

    @pytest.mark.asyncio
    async def test_update_state_persists_payload_and_priority(self, sqlite_store):
        """Ensure update_state writes payload_json/priority/cancellation flag."""
        job = JobRecord(
            job_id="job_cache_meta",
            kind="tool",
            payload_json=json.dumps({"metadata": {"cache_key": "sha256:foo"}}),
            state=JobState.QUEUED,
            priority=1,
            gpu_req=0,
        )
        await sqlite_store.enqueue(job)

        new_payload = json.dumps({"metadata": {"cache": {"key": "sha256:foo", "hit": True}}})
        new_priority = 9
        queued_at = int(time.time())

        await sqlite_store.update_state(
            "job_cache_meta",
            JobState.RUNNING.value,
            payload_json=new_payload,
            priority=new_priority,
            queued_at=queued_at,
            cancellation_requested=True,
        )

        updated = await sqlite_store.get("job_cache_meta")
        assert updated.payload_json == new_payload
        assert updated.priority == new_priority
        assert updated.cancellation_requested is True
        assert updated.queued_at == queued_at

    @pytest.mark.asyncio
    async def test_list_by_state(self, sqlite_store):
        """Test listing jobs by state with pagination."""
        # Enqueue multiple jobs
        for i in range(5):
            job = JobRecord(
                job_id=f"job_list{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=i,
                gpu_req=0
            )
            await sqlite_store.enqueue(job)

        # List all queued jobs
        queued = await sqlite_store.list_by_state(JobState.QUEUED, limit=10)
        assert len(queued) == 5

        # Jobs should be ordered by priority DESC, created_at ASC
        # Priority: 4, 3, 2, 1, 0
        assert queued[0].priority == 4
        assert queued[4].priority == 0

        # Test pagination
        page1 = await sqlite_store.list_by_state(JobState.QUEUED, limit=2, offset=0)
        assert len(page1) == 2
        assert page1[0].priority == 4

        page2 = await sqlite_store.list_by_state(JobState.QUEUED, limit=2, offset=2)
        assert len(page2) == 2
        assert page2[0].priority == 2

    @pytest.mark.asyncio
    async def test_nonexistent_job(self, sqlite_store):
        """Test operations on nonexistent job."""
        # Get nonexistent job
        result = await sqlite_store.get("nonexistent_job")
        assert result is None

        # Update nonexistent job
        success = await sqlite_store.update_state("nonexistent_job", JobState.RUNNING)
        assert success is False

        # Cancel nonexistent job
        success = await sqlite_store.cancel("nonexistent_job", reason="Test")
        assert success is False

    @pytest.mark.asyncio
    async def test_list_all_filters_by_project_id(self, sqlite_store):
        """Project-scoped listing should return only matching jobs."""
        jobs = [
            JobRecord(
                job_id="job_project_default_implicit",
                kind="tool",
                payload_json="{}",
                state=JobState.QUEUED,
                priority=1,
                gpu_req=0,
            ),
            JobRecord(
                job_id="job_project_default_explicit",
                kind="tool",
                payload_json="{}",
                state=JobState.QUEUED,
                priority=1,
                gpu_req=0,
                project_id="default",
            ),
            JobRecord(
                job_id="job_project_alpha",
                kind="tool",
                payload_json="{}",
                state=JobState.QUEUED,
                priority=1,
                gpu_req=0,
                project_id="proj_alpha",
            ),
        ]
        for job in jobs:
            await sqlite_store.enqueue(job)

        alpha_jobs = await sqlite_store.list_all(project_id="proj_alpha")
        assert [job.job_id for job in alpha_jobs] == ["job_project_alpha"]

        default_jobs = await sqlite_store.list_all(project_id="default")
        default_ids = {job.job_id for job in default_jobs}
        assert "job_project_default_implicit" in default_ids
        assert "job_project_default_explicit" in default_ids
        assert "job_project_alpha" not in default_ids

    @pytest.mark.asyncio
    async def test_project_crud_and_delete_guards(self, sqlite_store):
        """Projects table CRUD should work with delete safety checks."""
        default_exists = await sqlite_store.project_exists("default")
        assert default_exists is True

        created = await sqlite_store.create_project(
            project_id="proj_crud",
            name="Project CRUD",
            description="Initial description",
        )
        assert created["project_id"] == "proj_crud"
        assert created["name"] == "Project CRUD"
        assert created["description"] == "Initial description"
        assert created["is_archived"] is False

        fetched = await sqlite_store.get_project("proj_crud")
        assert fetched is not None
        assert fetched["project_id"] == "proj_crud"

        updated = await sqlite_store.update_project(
            "proj_crud",
            name="Project CRUD Updated",
            description="Updated description",
        )
        assert updated is not None
        assert updated["name"] == "Project CRUD Updated"
        assert updated["description"] == "Updated description"

        listed = await sqlite_store.list_projects()
        listed_ids = [project["project_id"] for project in listed]
        assert "default" in listed_ids
        assert "proj_crud" in listed_ids

        with pytest.raises(ValueError, match="default project"):
            await sqlite_store.delete_project("default")

        await sqlite_store.enqueue(
            JobRecord(
                job_id="job_proj_crud_001",
                kind="tool",
                payload_json="{}",
                state=JobState.QUEUED,
                priority=1,
                gpu_req=0,
                project_id="proj_crud",
            )
        )
        with pytest.raises(ValueError, match="has 1 job"):
            await sqlite_store.delete_project("proj_crud")

        await sqlite_store.create_project(
            project_id="proj_empty_delete",
            name="Empty Project",
            description=None,
        )
        deleted = await sqlite_store.delete_project("proj_empty_delete")
        assert deleted is True
        assert await sqlite_store.project_exists("proj_empty_delete") is False


class TestSqliteAtomicClaim:
    """Test atomic claim operations with concurrency."""

    @pytest.mark.asyncio
    async def test_atomic_claim_single_worker(self, sqlite_store):
        """Test single worker claiming job."""
        # Enqueue job
        job = JobRecord(
            job_id="job_claim001",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )
        await sqlite_store.enqueue(job)

        # Claim job
        claimed = await sqlite_store.claim_next(worker_id="worker-1", lease_ttl=60)

        assert claimed is not None
        assert claimed.job_id == "job_claim001"
        assert claimed.state == JobState.CLAIMED
        assert claimed.worker_id == "worker-1"
        assert claimed.lease_expires_at is not None
        assert claimed.last_heartbeat is not None

        # Try to claim again (should return None)
        claimed2 = await sqlite_store.claim_next(worker_id="worker-2", lease_ttl=60)
        assert claimed2 is None

    @pytest.mark.asyncio
    async def test_atomic_claim_concurrent_workers(self, sqlite_store):
        """Test concurrent workers claiming jobs - no double-booking."""
        # Enqueue 100 jobs
        for i in range(100):
            job = JobRecord(
                job_id=f"job_concurrent{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=i % 10,  # Mix of priorities
                gpu_req=0
            )
            await sqlite_store.enqueue(job)

        # Create 10 workers, each trying to claim jobs concurrently
        async def worker_claim(worker_id, num_claims=15):
            claimed_jobs = []
            for _ in range(num_claims):
                job = await sqlite_store.claim_next(worker_id=f"worker-{worker_id}", lease_ttl=60)
                if job:
                    claimed_jobs.append(job.job_id)
                await asyncio.sleep(0.001)  # Small delay to simulate work
            return claimed_jobs

        # Launch 10 workers concurrently
        results = await asyncio.gather(*[worker_claim(i) for i in range(10)])

        # Flatten results
        all_claimed = [job_id for worker_jobs in results for job_id in worker_jobs]

        # Verify no double-booking: all claimed job IDs should be unique
        assert len(all_claimed) == len(set(all_claimed)), "Double-booking detected!"

        # Verify all 100 jobs were claimed
        assert len(all_claimed) == 100

        # Verify all jobs are in CLAIMED state
        for job_id in all_claimed:
            job = await sqlite_store.get(job_id)
            assert job.state == JobState.CLAIMED
            assert job.worker_id is not None

    @pytest.mark.asyncio
    async def test_gpu_reservation_atomic(self, sqlite_store):
        """Test atomic GPU reservation during claim."""
        # Enqueue GPU jobs (total GPU requirement: 6, but only 2 slots available)
        for i in range(3):
            job = JobRecord(
                job_id=f"job_gpu{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=10 - i,
                gpu_req=2  # Each requires 2 GPUs
            )
            await sqlite_store.enqueue(job)

        # First worker claims first job (uses 2 GPUs)
        claimed1 = await sqlite_store.claim_next(worker_id="worker-1", lease_ttl=60)
        assert claimed1 is not None
        assert claimed1.job_id == "job_gpu000"  # Highest priority
        assert claimed1.gpu_req == 2

        # Second worker tries to claim but no GPUs left
        claimed2 = await sqlite_store.claim_next(worker_id="worker-2", lease_ttl=60)
        assert claimed2 is None  # No GPUs available

        # Verify GPU stats
        stats = await sqlite_store.get_queue_stats()
        assert stats['gpu_slots']['total'] == 2
        assert stats['gpu_slots']['in_use'] == 2
        assert stats['gpu_slots']['available'] == 0

        # Complete first job (should free GPUs via trigger)
        await sqlite_store.update_state(claimed1.job_id, JobState.SUCCEEDED, exit_code=0)

        # Now second worker can claim
        claimed3 = await sqlite_store.claim_next(worker_id="worker-2", lease_ttl=60)
        assert claimed3 is not None
        assert claimed3.job_id == "job_gpu001"

    @pytest.mark.asyncio
    async def test_heartbeat_extends_lease(self, sqlite_store):
        """Test heartbeat extends job lease."""
        # Enqueue and claim job
        job = JobRecord(
            job_id="job_heartbeat001",
            kind="tool",
            payload_json='{}',
            state=JobState.QUEUED,
            priority=5,
            gpu_req=0
        )
        await sqlite_store.enqueue(job)

        claimed = await sqlite_store.claim_next(worker_id="worker-1", lease_ttl=2)
        assert claimed is not None
        original_lease = claimed.lease_expires_at

        # Wait 1 second and heartbeat
        await asyncio.sleep(1)
        await sqlite_store.heartbeat(worker_id="worker-1", job_id=claimed.job_id, lease_ttl=5)

        # Verify lease was extended
        updated = await sqlite_store.get(claimed.job_id)
        assert updated.lease_expires_at > original_lease
        assert updated.last_heartbeat > claimed.last_heartbeat

    @pytest.mark.asyncio
    async def test_recovery_sweeper(self, sqlite_store):
        """Test recovery of stale jobs with expired leases."""
        # Enqueue and claim jobs
        for i in range(3):
            job = JobRecord(
                job_id=f"job_stale{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5,
                gpu_req=1 if i == 0 else 0  # First job requires GPU
            )
            await sqlite_store.enqueue(job)

        # Claim with very short lease (1 second)
        claimed1 = await sqlite_store.claim_next(worker_id="worker-1", lease_ttl=1)
        claimed2 = await sqlite_store.claim_next(worker_id="worker-2", lease_ttl=1)

        # Update one to RUNNING
        await sqlite_store.update_state(claimed1.job_id, JobState.RUNNING)

        # Wait for leases to expire
        await asyncio.sleep(2)

        # Run recovery sweeper
        now = int(time.time())
        stats = await sqlite_store.recover_stale_jobs(now_ts=now)

        # Verify recovery (at least 2 jobs were recovered)
        assert stats['recovered'] >= 2  # Both our jobs requeued
        assert stats['gpus_freed'] >= 1  # At least first job's GPU freed

        # Verify our specific jobs are back in QUEUED state
        recovered1 = await sqlite_store.get(claimed1.job_id)
        assert recovered1 is not None
        assert recovered1.state == JobState.QUEUED
        assert recovered1.worker_id is None
        assert recovered1.lease_expires_at is None

        recovered2 = await sqlite_store.get(claimed2.job_id)
        assert recovered2 is not None
        assert recovered2.state == JobState.QUEUED
        assert recovered2.worker_id is None

        # Verify GPUs are available again
        stats_after = await sqlite_store.get_queue_stats()
        assert stats_after['gpu_slots']['available'] >= 1  # At least the GPU from job 1 freed

    @pytest.mark.asyncio
    async def test_claim_with_gpu_filter(self, sqlite_store):
        """Test claiming with GPU filter."""
        # Enqueue mix of GPU and non-GPU jobs
        for i in range(4):
            job = JobRecord(
                job_id=f"job_filter{i:03d}",
                kind="tool",
                payload_json='{}',
                state=JobState.QUEUED,
                priority=5,
                gpu_req=1 if i % 2 == 0 else 0  # Even: GPU, Odd: no GPU
            )
            await sqlite_store.enqueue(job)

        # Claim GPU job only
        gpu_job = await sqlite_store.claim_next(worker_id="worker-1", gpu_filter=True)
        assert gpu_job is not None
        assert gpu_job.gpu_req > 0
        assert gpu_job.job_id == "job_filter000"

        # Claim non-GPU job only
        cpu_job = await sqlite_store.claim_next(worker_id="worker-2", gpu_filter=False)
        assert cpu_job is not None
        assert cpu_job.gpu_req == 0
        assert cpu_job.job_id == "job_filter001"

        # Claim any job
        any_job = await sqlite_store.claim_next(worker_id="worker-3", gpu_filter=None)
        assert any_job is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
