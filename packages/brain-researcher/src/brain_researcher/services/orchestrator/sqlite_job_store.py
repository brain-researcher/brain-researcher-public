"""
SQLite-based job store implementation with WAL mode for durability.

Provides crash-safe, persistent job queue with:
- Atomic claim with GPU reservation
- Lease-based heartbeats
- Auto-recovery of stale jobs
- Audit logging
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
import threading

import sqlite3

try:
    import aiosqlite
except ImportError:
    raise ImportError("aiosqlite is required for SQLite backend. Install with: pip install aiosqlite")

from .job_store import JobEvent, JobRecord, JobState, JobStore

logger = logging.getLogger(__name__)


def _should_use_sync_sqlite() -> bool:
    """Decide whether to use sync sqlite3 connections instead of aiosqlite."""
    env = os.getenv("BR_SQLITE_SYNC")
    if env is not None:
        return env.lower() in {"1", "true", "yes", "y", "on"}
    # Prefer sync in pytest to avoid aiosqlite thread hangs.
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


class _SyncCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int:
        return self._cursor.lastrowid

    def __await__(self):
        async def _noop():
            return self
        return _noop().__await__()

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    async def close(self):
        self._cursor.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._cursor.close()
        return False


class _SyncConnection:
    """Async-compatible wrapper around sqlite3.Connection."""

    def __init__(self, path: Path, lock: Optional[threading.Lock] = None, timeout_s: Optional[float] = None):
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = lock
        self._timeout_s = timeout_s

    async def __aenter__(self):
        if self._lock is not None:
            self._lock.acquire()
        try:
            timeout = self._timeout_s if self._timeout_s is not None else 5.0
            # check_same_thread=False to allow safe use across background loop thread in tests
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self._path,
                timeout=timeout,
                check_same_thread=False,
            )
            return self
        except Exception:
            # If connect fails, __aexit__ won't run; avoid leaking the lock.
            if self._lock is not None:
                self._lock.release()
            raise

    async def __aexit__(self, exc_type, exc, tb):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._lock is not None:
            self._lock.release()
        return False

    @property
    def total_changes(self) -> int:
        return self._conn.total_changes if self._conn is not None else 0

    @property
    def row_factory(self):
        return self._conn.row_factory if self._conn is not None else None

    @row_factory.setter
    def row_factory(self, value):
        if self._conn is not None:
            self._conn.row_factory = value

    def execute(self, *args, **kwargs) -> _SyncCursor:
        cursor = self._conn.execute(*args, **kwargs)
        return _SyncCursor(cursor)

    async def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    async def commit(self) -> None:
        self._conn.commit()

    async def rollback(self) -> None:
        self._conn.rollback()


class SqliteJobStore(JobStore):
    """
    SQLite-based job store with WAL mode and atomic operations.

    Features:
    - WAL mode for concurrent reads during writes
    - Atomic claim with CTE-based SELECT FOR UPDATE
    - Automatic GPU slot management via triggers
    - Recovery sweeper for crashed workers

    Args:
        db_path: Path to SQLite database file
        total_gpu_slots: Total number of GPU slots available
        busy_timeout_ms: SQLite busy timeout in milliseconds (default: 5000)
    """

    def __init__(
        self,
        db_path: str,
        total_gpu_slots: int = 2,
        busy_timeout_ms: int = 5000
    ):
        self._db_path = Path(db_path)
        self._total_gpu_slots = total_gpu_slots
        self._busy_timeout_ms = busy_timeout_ms
        self._lock = asyncio.Lock()  # Serialize claim operations within process
        self._initialized = False
        self._use_sync = _should_use_sync_sqlite()
        self._sync_lock = threading.Lock() if self._use_sync else None

    def _connect(self):
        """Return an async context manager for SQLite connections."""
        if self._use_sync:
            timeout_s = self._busy_timeout_ms / 1000.0
            return _SyncConnection(self._db_path, self._sync_lock, timeout_s)
        return aiosqlite.connect(self._db_path)

    def _row_factory(self):
        return sqlite3.Row if self._use_sync else aiosqlite.Row

    async def initialize(self) -> None:
        """
        Initialize database, create schema, populate GPU slots.

        Raises:
            RuntimeError: If database directory is not writable or database cannot be created
        """
        if self._initialized:
            return

        # Create parent directory if needed
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            raise RuntimeError(
                f"Cannot create database directory {self._db_path.parent}: {e}. "
                f"Check directory permissions and disk space."
            ) from e

        # Check directory writability before attempting database creation
        if not os.access(self._db_path.parent, os.W_OK):
            raise RuntimeError(
                f"Database directory {self._db_path.parent} is not writable. "
                f"Check directory permissions (current permissions: {oct(self._db_path.parent.stat().st_mode)})"
            )

        # Read schema SQL
        schema_path = Path(__file__).parent / "sqlite_schema" / "schema.sql"
        try:
            with open(schema_path, 'r') as f:
                schema_sql = f.read()
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Cannot find schema file at {schema_path}. "
                f"Ensure brain_researcher package is installed correctly."
            ) from e

        # Apply schema and verify writability
        try:
            async with self._connect() as db:
                await self._configure_connection(db)
                # Legacy databases may predate jobs.project_id while schema.sql
                # now declares indexes on project_id. Ensure the column exists
                # before replaying schema DDL so CREATE INDEX does not fail.
                await self._ensure_jobs_project_column(db)
                await db.executescript(schema_sql)
                await self._ensure_jobs_project_column(db)
                await self._ensure_projects_table_and_backfill(db)
                await self._ensure_gpu_slots(db)
                await db.commit()

                # Verify database is actually writable by performing a test write
                await db.execute(
                    "INSERT INTO job_audit (job_id, event_type, payload_json) VALUES (?, ?, ?)",
                    ("_writability_test", "init", '{}')
                )
                await db.execute("DELETE FROM job_audit WHERE job_id = ?", ("_writability_test",))
                await db.commit()
        except (OSError, PermissionError) as e:
            raise RuntimeError(
                f"Cannot create or write to database at {self._db_path}: {e}. "
                f"Check file permissions and disk space."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize SQLite database at {self._db_path}: {e}"
            ) from e

        self._initialized = True
        logger.info(f"SQLite job store initialized at {self._db_path}")

    async def _configure_connection(self, db: aiosqlite.Connection) -> None:
        """Apply connection-level pragmas."""
        await db.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms};")
        await db.execute("PRAGMA synchronous=NORMAL;")
        cursor = await db.execute("PRAGMA journal_mode=WAL;")
        await cursor.fetchone()
        await cursor.close()

    async def _ensure_gpu_slots(self, db: aiosqlite.Connection) -> None:
        """Populate GPU slots table if empty."""
        async with db.execute("SELECT COUNT(*) FROM gpu_slots") as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 0:
                # Insert GPU slots
                for slot_id in range(1, self._total_gpu_slots + 1):
                    await db.execute(
                        "INSERT INTO gpu_slots (id, in_use) VALUES (?, 0)",
                        (slot_id,)
                    )
                logger.info(f"Initialized {self._total_gpu_slots} GPU slots")

    async def _table_exists(self, db: aiosqlite.Connection, table_name: str) -> bool:
        async with db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ) as cursor:
            row = await cursor.fetchone()
        return bool(row)

    async def _ensure_jobs_project_column(self, db: aiosqlite.Connection) -> None:
        """Backfill jobs.project_id for existing DBs and ensure index exists."""
        if not await self._table_exists(db, "jobs"):
            return

        async with db.execute("PRAGMA table_info(jobs)") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row[1]) for row in rows}
        if "project_id" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN project_id TEXT")

        # Keep legacy rows queryable under the default project.
        await db.execute(
            "UPDATE jobs SET project_id = 'default' WHERE project_id IS NULL OR TRIM(project_id) = ''"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON jobs(project_id) WHERE project_id IS NOT NULL"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_project_created ON jobs(user_id, project_id, created_at DESC)"
        )

    async def _ensure_projects_table_and_backfill(self, db: aiosqlite.Connection) -> None:
        """Ensure projects table exists and register project IDs seen in jobs."""
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_projects_archived
                ON projects(is_archived, updated_at DESC)
            """
        )

        now = int(time.time())
        # Always keep the default project present and active.
        await db.execute(
            """
            INSERT INTO projects (project_id, name, description, created_at, updated_at, is_archived)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(project_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                is_archived = 0
            """,
            ("default", "Default Project", "System default project", now, now),
        )

        if await self._table_exists(db, "jobs"):
            await db.execute(
                """
                INSERT INTO projects (project_id, name, description, created_at, updated_at, is_archived)
                SELECT DISTINCT TRIM(project_id), TRIM(project_id), NULL, ?, ?, 0
                FROM jobs
                WHERE project_id IS NOT NULL
                  AND TRIM(project_id) != ''
                ON CONFLICT(project_id) DO NOTHING
                """,
                (now, now),
            )

    @staticmethod
    def _normalize_project_id(project_id: str) -> str:
        normalized = str(project_id).strip()
        if not normalized:
            raise ValueError("project_id must be a non-empty string")
        return normalized

    def _project_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "project_id": row["project_id"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_archived": bool(row["is_archived"]),
        }

    async def enqueue(self, job: JobRecord) -> str:
        """
        Enqueue a job for execution.

        Args:
            job: JobRecord to enqueue

        Returns:
            job_id of enqueued job
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            # Set state to QUEUED if not already set
            if not job.state or job.state == JobState.PENDING:
                job.state = JobState.QUEUED

            # Set created_at if not set
            if job.created_at is None:
                job.created_at = int(time.time())

            # Insert job
            await db.execute("""
                INSERT INTO jobs (
                    job_id, kind, payload_json, state, priority,
                    created_at, queued_at, claimed_at, started_at, finished_at, run_after,
                    worker_id, lease_expires_at, last_heartbeat,
                    attempt, max_attempts,
                    cancel_reason, cancellation_requested,
                    exit_code, error_message, skip_reason,
                    gpu_req, gpu_type,
                    cpus, memory_gb, walltime_minutes, backend, job_name,
                    run_id, run_dir, provenance_path,
                    user_id, session_id, project_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.job_id,
                job.kind,
                job.payload_json,
                job.state,
                job.priority,
                job.created_at,
                job.queued_at,
                job.claimed_at,
                job.started_at,
                job.finished_at,
                job.run_after,
                job.worker_id,
                job.lease_expires_at,
                job.last_heartbeat,
                job.attempt,
                job.max_attempts,
                job.cancel_reason,
                1 if job.cancellation_requested else 0,
                job.exit_code,
                job.error_message,
                job.skip_reason,
                job.gpu_req,
                job.gpu_type,
                job.cpus,
                job.memory_gb,
                job.walltime_minutes,
                job.backend,
                job.job_name,
                job.run_id,
                job.run_dir,
                job.provenance_path,
                job.user_id,
                job.session_id,
                job.project_id or "default",
            ))

            await db.commit()

            # Audit log
            await self._audit_log(db, job.job_id, "enqueued", {"priority": job.priority})
            await db.commit()

        logger.debug(f"Enqueued job {job.job_id} with priority {job.priority}")
        return job.job_id

    async def get(self, job_id: str) -> Optional[JobRecord]:
        """
        Retrieve a job by ID.

        Args:
            job_id: Job identifier

        Returns:
            JobRecord or None if not found
        """
        # In some CI/dev environments (notably when using sync sqlite in pytest),
        # sqlite can transiently fail to open the DB (WAL/shm file race, flaky FS).
        # A short retry makes reads robust without masking persistent failures.
        for attempt in range(2):
            try:
                async with self._connect() as db:
                    await self._configure_connection(db)
                    db.row_factory = self._row_factory()

                    async with db.execute(
                        "SELECT * FROM jobs WHERE job_id = ?",
                        (job_id,),
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            return self._row_to_record(row)
                        return None
            except sqlite3.OperationalError as e:
                if "unable to open database file" in str(e).lower() and attempt == 0:
                    await asyncio.sleep(0.05)
                    continue
                raise
        return None

    async def claim_next(
        self,
        worker_id: str,
        lease_ttl: int = 60,
        gpu_filter: Optional[bool] = None
    ) -> Optional[JobRecord]:
        """
        Atomically claim next available job with GPU reservation.

        Uses CTE-based SELECT FOR UPDATE to prevent race conditions.
        Two-phase commit: claim job → reserve GPUs → commit or rollback.

        Args:
            worker_id: Worker identifier
            lease_ttl: Lease duration in seconds
            gpu_filter: If True, only claim jobs requiring GPU; if False, only non-GPU jobs; if None, any

        Returns:
            Claimed JobRecord or None if no eligible jobs
        """
        # Serialize claim operations within process (cross-process serialization via DB locks)
        async with self._lock:
            async with self._connect() as db:
                await self._configure_connection(db)

                now = int(time.time())
                lease_expires_at = now + lease_ttl

                try:
                    # BEGIN IMMEDIATE gets exclusive write lock
                    await db.execute("BEGIN IMMEDIATE")

                    # Phase 1: Find and lock eligible job using CTE
                    # The ORDER BY ensures highest priority job is selected first
                    sql = """
                        WITH picked AS (
                            SELECT job_id, gpu_req, priority, created_at
                            FROM jobs
                            WHERE state = ?
                              AND (run_after IS NULL OR run_after <= ?)
                              AND (? IS NULL OR (CASE WHEN ? = 1 THEN gpu_req > 0 ELSE gpu_req = 0 END))
                            ORDER BY priority DESC, created_at ASC
                            LIMIT 1
                        )
                        SELECT job_id, gpu_req FROM picked
                    """

                    async with db.execute(sql, (
                        JobState.QUEUED,
                        now,
                        1 if gpu_filter is not None else None,
                        1 if gpu_filter else 0
                    )) as cursor:
                        picked_row = await cursor.fetchone()

                    # P2.6: Opportunistic retry check - if no QUEUED jobs, check RETRYING
                    if not picked_row:
                        # Try to find a RETRYING job ready to retry
                        retry_sql = """
                            WITH picked AS (
                                SELECT job_id, gpu_req, priority, created_at
                                FROM jobs
                                WHERE state = ?
                                  AND run_after IS NOT NULL
                                  AND run_after <= ?
                                  AND (? IS NULL OR (CASE WHEN ? = 1 THEN gpu_req > 0 ELSE gpu_req = 0 END))
                                ORDER BY priority DESC, created_at ASC
                                LIMIT 1
                            )
                            SELECT job_id, gpu_req FROM picked
                        """

                        async with db.execute(retry_sql, (
                            JobState.RETRYING,
                            now,
                            1 if gpu_filter is not None else None,
                            1 if gpu_filter else 0
                        )) as cursor:
                            picked_row = await cursor.fetchone()

                        if picked_row:
                            # Found a RETRYING job ready to retry - promote to QUEUED
                            job_id_to_promote = picked_row[0]
                            await db.execute("""
                                UPDATE jobs
                                SET state = ?,
                                    run_after = NULL
                                WHERE job_id = ?
                            """, (JobState.QUEUED, job_id_to_promote))

                            logger.info(
                                f"Opportunistically promoted job {job_id_to_promote} "
                                f"from RETRYING to QUEUED in claim_next()"
                            )
                            # Now proceed to claim this job below
                        else:
                            # No jobs available at all
                            await db.rollback()
                            return None

                    job_id_to_claim = picked_row[0]
                    gpu_required = picked_row[1]

                    # Phase 2: Check GPU availability if needed
                    if gpu_required > 0:
                        async with db.execute("""
                            SELECT COUNT(*) FROM gpu_slots WHERE in_use = 0
                        """) as cursor:
                            available_row = await cursor.fetchone()
                            available_gpus = available_row[0] if available_row else 0

                        if available_gpus < gpu_required:
                            # Not enough GPUs available
                            await db.rollback()
                            logger.debug(
                                f"Cannot claim {job_id_to_claim}: requires {gpu_required} GPUs, "
                                f"only {available_gpus} available"
                            )
                            return None

                    # Phase 3: Claim the job
                    await db.execute("""
                        UPDATE jobs
                        SET state = ?,
                            claimed_at = ?,
                            worker_id = ?,
                            lease_expires_at = ?,
                            last_heartbeat = ?
                        WHERE job_id = ?
                    """, (
                        JobState.CLAIMED,
                        now,
                        worker_id,
                        lease_expires_at,
                        now,
                        job_id_to_claim
                    ))

                    # Verify update succeeded
                    if db.total_changes == 0:
                        await db.rollback()
                        logger.warning(f"Failed to claim job {job_id_to_claim}")
                        return None

                    # Phase 4: Reserve GPU slots if needed
                    if gpu_required > 0:
                        # First, select the slot IDs to reserve
                        async with db.execute("""
                            SELECT id FROM gpu_slots
                            WHERE in_use = 0
                            ORDER BY id
                            LIMIT ?
                        """, (gpu_required,)) as cursor:
                            slot_ids = [row[0] for row in await cursor.fetchall()]

                        if len(slot_ids) < gpu_required:
                            # Not enough slots (race condition)
                            await db.rollback()
                            logger.warning(
                                f"GPU slot selection failed for {job_id_to_claim}: "
                                f"found {len(slot_ids)}, needed {gpu_required}"
                            )
                            return None

                        # Now update exactly those slots
                        placeholders = ','.join('?' * len(slot_ids))
                        cursor = await db.execute(f"""
                            UPDATE gpu_slots
                            SET in_use = 1,
                                job_id = ?,
                                updated_at = ?
                            WHERE id IN ({placeholders})
                        """, (job_id_to_claim, now, *slot_ids))

                        # Use len(slot_ids) since we know exactly which slots we're updating
                        slots_reserved = len(slot_ids)

                        if slots_reserved != gpu_required:
                            # GPU reservation failed (race condition)
                            await db.rollback()
                            logger.warning(
                                f"GPU reservation failed for {job_id_to_claim}: "
                                f"reserved {slots_reserved}, needed {gpu_required}"
                            )
                            return None

                    # Success! Commit transaction
                    await db.commit()

                    # Audit log
                    await self._audit_log(db, job_id_to_claim, "claimed", {
                        "worker_id": worker_id,
                        "gpu_req": gpu_required
                    })
                    await db.commit()

                    # Fetch and return claimed job
                    db.row_factory = self._row_factory()
                    async with db.execute(
                        "SELECT * FROM jobs WHERE job_id = ?",
                        (job_id_to_claim,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            claimed_job = self._row_to_record(row)
                            logger.info(
                                f"Claimed job {job_id_to_claim} for worker {worker_id} "
                                f"(priority={claimed_job.priority}, gpu_req={gpu_required})"
                            )
                            return claimed_job

                    return None

                except Exception as e:
                    await db.rollback()
                    logger.error(f"Error claiming job: {e}")
                    raise

    async def heartbeat(
        self,
        worker_id: str,
        job_id: Optional[str] = None,
        lease_ttl: int = 60
    ) -> int:
        """
        Send heartbeat to extend job lease.

        Args:
            worker_id: Worker identifier
            job_id: Specific job to heartbeat (if None, heartbeat all jobs for worker)
            lease_ttl: Lease extension duration in seconds
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            now = int(time.time())
            new_lease = now + lease_ttl

            if job_id:
                # Heartbeat specific job
                await db.execute("""
                    UPDATE jobs
                    SET last_heartbeat = ?,
                        lease_expires_at = ?
                    WHERE job_id = ?
                      AND worker_id = ?
                      AND state IN (?, ?)
                """, (now, new_lease, job_id, worker_id, JobState.CLAIMED, JobState.RUNNING))
            else:
                # Heartbeat all jobs for worker
                await db.execute("""
                    UPDATE jobs
                    SET last_heartbeat = ?,
                        lease_expires_at = ?
                    WHERE worker_id = ?
                      AND state IN (?, ?)
                """, (now, new_lease, worker_id, JobState.CLAIMED, JobState.RUNNING))

            await db.commit()
            updated = db.total_changes
            if updated > 0:
                logger.debug(f"Heartbeat from {worker_id}: extended lease for {updated} job(s)")
            return int(updated or 0)

    async def recover_stale_jobs(self, now_ts: Optional[int] = None) -> Dict[str, int]:
        """
        Recover jobs with expired leases (crashed workers).

        Requeues stale jobs and frees their GPU allocations.

        Args:
            now_ts: Current timestamp (defaults to time.time())

        Returns:
            Dictionary with recovery statistics
        """
        if now_ts is None:
            now_ts = int(time.time())

        async with self._connect() as db:
            await self._configure_connection(db)

            try:
                await db.execute("BEGIN IMMEDIATE")

                # Find stale jobs (expired lease)
                async with db.execute("""
                    SELECT job_id, worker_id, state, gpu_req
                    FROM jobs
                    WHERE state IN (?, ?)
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < ?
                """, (JobState.CLAIMED, JobState.RUNNING, now_ts)) as cursor:
                    stale_jobs = await cursor.fetchall()

                if not stale_jobs:
                    await db.rollback()
                    return {"recovered": 0, "gpus_freed": 0}

                stale_job_ids = [row[0] for row in stale_jobs]
                total_gpus_to_free = sum(row[3] for row in stale_jobs)

                # Requeue stale jobs
                await db.execute("""
                    UPDATE jobs
                    SET state = ?,
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        last_heartbeat = NULL,
                        queued_at = COALESCE(queued_at, ?)
                    WHERE job_id IN ({})
                """.format(','.join('?' * len(stale_job_ids))),
                    (JobState.QUEUED, now_ts, *stale_job_ids)
                )

                recovered_count = db.total_changes

                # Free GPU slots
                await db.execute("""
                    UPDATE gpu_slots
                    SET in_use = 0,
                        job_id = NULL,
                        updated_at = ?
                    WHERE job_id IN ({})
                """.format(','.join('?' * len(stale_job_ids))),
                    (now_ts, *stale_job_ids)
                )

                gpus_freed = db.total_changes

                await db.commit()

                # Audit log
                for job_id, worker_id, state, gpu_req in stale_jobs:
                    await self._audit_log(db, job_id, "recovered", {
                        "old_worker": worker_id,
                        "old_state": state,
                        "lease_expired": True
                    })
                await db.commit()

                logger.info(
                    f"Recovery sweep: requeued {recovered_count} stale jobs, "
                    f"freed {gpus_freed} GPU slots"
                )

                return {
                    "recovered": recovered_count,
                    "gpus_freed": gpus_freed
                }

            except Exception as e:
                await db.rollback()
                logger.error(f"Error recovering stale jobs: {e}")
                raise

    async def update_state(
        self,
        job_id: str,
        state: JobState | str | None = None,
        **kwargs
    ) -> bool:
        """
        Update job state and optionally other fields.

        Args:
            job_id: Job to update
            state: New state
            **kwargs: Additional fields to update (started_at, finished_at, exit_code, error_message, etc.)

        Returns:
            True if job was updated, False if not found
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            # Build SET clause dynamically
            set_clauses: list[str] = []
            params: list[Any] = []

            if state is not None:
                set_clauses.append("state = ?")
                params.append(state)

            # Map kwargs to column names
            field_mapping = {
                'started_at': 'started_at',
                'finished_at': 'finished_at',
                'exit_code': 'exit_code',
                'error_message': 'error_message',
                'skip_reason': 'skip_reason',
                'worker_id': 'worker_id',
                'lease_expires_at': 'lease_expires_at',
                'claimed_at': 'claimed_at',
                'queued_at': 'queued_at',
                'priority': 'priority',
                'last_heartbeat': 'last_heartbeat',
                'cancel_reason': 'cancel_reason',
                'cancellation_requested': 'cancellation_requested',
                'run_id': 'run_id',
                'run_dir': 'run_dir',
                'provenance_path': 'provenance_path',
                'run_after': 'run_after',
                'attempt': 'attempt',
                'max_attempts': 'max_attempts',
                'payload_json': 'payload_json',
                'gpu_req': 'gpu_req',
                'gpu_type': 'gpu_type',
                'cpus': 'cpus',
                'memory_gb': 'memory_gb',
                'walltime_minutes': 'walltime_minutes',
                'backend': 'backend',
                'job_name': 'job_name',
                'user_id': 'user_id',
                'session_id': 'session_id',
                'project_id': 'project_id',
            }

            boolean_fields = {'cancellation_requested'}

            for key, col_name in field_mapping.items():
                if key in kwargs:
                    value = kwargs[key]
                    if key in boolean_fields and value is not None:
                        value = 1 if value else 0
                    set_clauses.append(f"{col_name} = ?")
                    params.append(value)

            # Always update updated_at timestamp
            set_clauses.append("updated_at = strftime('%s','now')")

            if not set_clauses:
                return False

            # Add job_id for WHERE clause
            params.append(job_id)

            sql = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE job_id = ?"

            cursor = await db.execute(sql, params)
            await db.commit()

            updated = cursor.rowcount > 0

            if updated:
                # Audit log
                state_label = None
                if state is not None:
                    state_label = state.value if isinstance(state, JobState) else str(state)
                audit_type = (
                    f"state_changed:{state_label}"
                    if state_label is not None
                    else "fields_updated"
                )
                await self._audit_log(db, job_id, audit_type, kwargs)
                await db.commit()
                if state is not None:
                    logger.debug(f"Updated job {job_id} state to {state}")

            return updated

    async def append_event(
        self,
        job_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> int:
        ts = int(created_at if created_at is not None else time.time())
        async with self._connect() as db:
            await self._configure_connection(db)
            cursor = await db.execute(
                """
                INSERT INTO job_audit (job_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(event_type),
                    json.dumps(payload) if payload is not None else None,
                    ts,
                ),
            )
            await db.commit()
            return int(getattr(cursor, "lastrowid", 0) or 0)

    async def list_events(
        self,
        job_id: str,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> List[JobEvent]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            cursor = await db.execute(
                """
                SELECT id, job_id, event_type, payload_json, created_at
                FROM job_audit
                WHERE job_id = ?
                  AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (job_id, int(after_event_id), max(1, int(limit))),
            )
            rows = await cursor.fetchall()
            await cursor.close()

        events: List[JobEvent] = []
        for row in rows or []:
            payload_obj = None
            try:
                raw_payload = row["payload_json"] if row else None
            except Exception:
                raw_payload = None
            if raw_payload:
                try:
                    parsed = json.loads(raw_payload)
                    payload_obj = parsed if isinstance(parsed, dict) else None
                except Exception:
                    payload_obj = None
            events.append(
                JobEvent(
                    event_id=int(row["id"]),
                    job_id=str(row["job_id"]),
                    event_type=str(row["event_type"]),
                    payload=payload_obj,
                    created_at=int(row["created_at"] or 0),
                )
            )
        return events

    async def release_gpus(self, job_id: str) -> None:
        """Release GPU slots associated with a job."""
        async with self._connect() as db:
            await self._configure_connection(db)
            try:
                await db.execute("""
                    UPDATE gpu_slots
                    SET in_use = 0,
                        job_id = NULL,
                        updated_at = strftime('%s','now')
                    WHERE job_id = ?
                """, (job_id,))
                await db.commit()
                if db.total_changes > 0:
                    logger.debug(f"Released {db.total_changes} GPU slot(s) for job {job_id}")
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to release GPU slots for {job_id}: {e}")
                raise

    async def cancel(self, job_id: str, reason: Optional[str] = None) -> bool:
        """
        Request cancellation of a job.

        Args:
            job_id: Job to cancel
            reason: Cancellation reason

        Returns:
            True if job was updated, False if not found or already terminal
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            # Check current state
            async with db.execute(
                "SELECT state FROM jobs WHERE job_id = ?",
                (job_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False

                current_state_value = row[0]
                try:
                    current_state = JobState(current_state_value)
                except ValueError:
                    logger.warning(f"Unknown job state {current_state_value} for job {job_id}; cannot cancel")
                    return False

                # Cannot cancel terminal states
                terminal_states = {
                    JobState.SUCCEEDED,
                    JobState.FAILED,
                    JobState.CANCELLED,
                    JobState.TIMEOUT,
                    JobState.SKIPPED,
                }
                if current_state in terminal_states:
                    logger.warning(f"Cannot cancel job {job_id} in terminal state {current_state.value}")
                    return False

            # Set cancellation flag and state
            new_state = (
                JobState.CANCELLING if current_state == JobState.RUNNING else JobState.CANCELLED
            )

            await db.execute("""
                UPDATE jobs
                SET cancellation_requested = 1,
                    cancel_reason = ?,
                    state = ?
                WHERE job_id = ?
            """, (reason, new_state, job_id))

            await db.commit()

            # Audit log
            await self._audit_log(db, job_id, "cancelled", {"reason": reason})
            await db.commit()

            logger.info(f"Cancelled job {job_id}: {reason}")
            return True

    async def list_by_state(
        self,
        state: JobState,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """
        List jobs by state.

        Args:
            state: Job state to filter by
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip

        Returns:
            List of JobRecords
        """
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()

            query = """
                SELECT * FROM jobs
                WHERE state = ?
            """
            params: List[Any] = [state]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            if project_id:
                if project_id == "default":
                    query += " AND (project_id = ? OR project_id IS NULL OR TRIM(project_id) = '')"
                    params.append(project_id)
                else:
                    query += " AND project_id = ?"
                    params.append(project_id)

            query += " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_record(row) for row in rows]

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """List jobs with optional user filter."""
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()

            query = "SELECT * FROM jobs"
            params: List[Any] = []
            where_clauses: List[str] = []
            if user_id:
                where_clauses.append("user_id = ?")
                params.append(user_id)
            if project_id:
                if project_id == "default":
                    where_clauses.append("(project_id = ? OR project_id IS NULL OR TRIM(project_id) = '')")
                    params.append(project_id)
                else:
                    where_clauses.append("project_id = ?")
                    params.append(project_id)

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            query += " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_record(row) for row in rows]

    async def count_by_state(self, state: str, user_id: Optional[str] = None) -> int:
        async with self._connect() as db:
            await self._configure_connection(db)
            query = "SELECT COUNT(*) FROM jobs WHERE state = ?"
            params: List[Any] = [state]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return int(row[0] if row else 0)

    async def count_all(self, user_id: Optional[str] = None) -> int:
        async with self._connect() as db:
            await self._configure_connection(db)
            query = "SELECT COUNT(*) FROM jobs"
            params: List[Any] = []
            if user_id:
                query += " WHERE user_id = ?"
                params.append(user_id)
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return int(row[0] if row else 0)

    async def list_projects(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List registered projects.

        Note:
            user_id is accepted for API compatibility but currently ignored.
        """
        del user_id  # ACL not implemented yet
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                """
                SELECT project_id, name, description, created_at, updated_at, is_archived
                FROM projects
                ORDER BY
                    CASE WHEN project_id = 'default' THEN 0 ELSE 1 END,
                    created_at ASC,
                    project_id ASC
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return [self._project_row_to_dict(row) for row in rows]

    async def get_project(
        self,
        project_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a single project by ID."""
        del user_id  # ACL not implemented yet
        normalized_project_id = self._normalize_project_id(project_id)
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                """
                SELECT project_id, name, description, created_at, updated_at, is_archived
                FROM projects
                WHERE project_id = ?
                """,
                (normalized_project_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._project_row_to_dict(row)

    async def create_project(
        self,
        project_id: str,
        name: str,
        description: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a project entry."""
        del user_id  # ACL not implemented yet
        normalized_project_id = self._normalize_project_id(project_id)
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("name must be a non-empty string")

        now = int(time.time())
        async with self._connect() as db:
            await self._configure_connection(db)
            try:
                await db.execute(
                    """
                    INSERT INTO projects (project_id, name, description, created_at, updated_at, is_archived)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (
                        normalized_project_id,
                        normalized_name,
                        description,
                        now,
                        now,
                    ),
                )
                await db.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Project '{normalized_project_id}' already exists") from exc

        project = await self.get_project(normalized_project_id)
        if project is None:
            raise RuntimeError(f"Failed to read newly created project '{normalized_project_id}'")
        return project

    async def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update mutable project fields."""
        del user_id  # ACL not implemented yet
        normalized_project_id = self._normalize_project_id(project_id)
        set_clauses: List[str] = []
        params: List[Any] = []

        if name is not None:
            normalized_name = str(name).strip()
            if not normalized_name:
                raise ValueError("name must be a non-empty string when provided")
            set_clauses.append("name = ?")
            params.append(normalized_name)
        if description is not None:
            set_clauses.append("description = ?")
            params.append(description)

        if not set_clauses:
            return await self.get_project(normalized_project_id)

        set_clauses.append("updated_at = ?")
        params.append(int(time.time()))
        params.append(normalized_project_id)

        async with self._connect() as db:
            await self._configure_connection(db)
            cursor = await db.execute(
                f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id = ?",
                params,
            )
            await db.commit()
            if cursor.rowcount <= 0:
                return None

        return await self.get_project(normalized_project_id)

    async def delete_project(
        self,
        project_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Delete project if it is not default and has no jobs.

        Raises:
            ValueError: if attempting to delete default or a project still referenced by jobs.
        """
        del user_id  # ACL not implemented yet
        normalized_project_id = self._normalize_project_id(project_id)
        if normalized_project_id == "default":
            raise ValueError("Cannot delete the default project")

        async with self._connect() as db:
            await self._configure_connection(db)

            async with db.execute(
                "SELECT COUNT(*) FROM jobs WHERE project_id = ?",
                (normalized_project_id,),
            ) as cursor:
                jobs_row = await cursor.fetchone()
                job_count = int(jobs_row[0] if jobs_row else 0)
            if job_count > 0:
                raise ValueError(
                    f"Cannot delete project '{normalized_project_id}' because it has {job_count} job(s)"
                )

            cursor = await db.execute(
                "DELETE FROM projects WHERE project_id = ?",
                (normalized_project_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def project_exists(
        self,
        project_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Check if a project exists."""
        del user_id  # ACL not implemented yet
        normalized_project_id = self._normalize_project_id(project_id)
        async with self._connect() as db:
            await self._configure_connection(db)
            async with db.execute(
                "SELECT 1 FROM projects WHERE project_id = ? LIMIT 1",
                (normalized_project_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row)

    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dictionary with counts by state and GPU stats
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            # Count jobs by state
            async with db.execute("""
                SELECT state, COUNT(*) as count
                FROM jobs
                GROUP BY state
            """) as cursor:
                rows = await cursor.fetchall()
                state_counts = {row[0]: row[1] for row in rows}

            # GPU stats
            async with db.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN in_use = 1 THEN 1 ELSE 0 END) as in_use
                FROM gpu_slots
            """) as cursor:
                row = await cursor.fetchone()
                gpu_stats = {
                    "total": row[0] if row else 0,
                    "in_use": row[1] if row else 0,
                    "available": (row[0] - row[1]) if row else 0
                }

            return {
                "by_state": state_counts,
                "gpu_slots": gpu_stats,
                "total_jobs": sum(state_counts.values())
            }

    async def append_log(
        self,
        job_id: str,
        stream: str,
        data: bytes,
        offset: int
    ) -> None:
        """
        Append log chunk for job.

        Args:
            job_id: Job identifier
            stream: Stream name ('stdout' or 'stderr')
            data: Log data bytes
            offset: Byte offset in stream
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            try:
                await db.execute("""
                    INSERT OR REPLACE INTO job_logs (job_id, stream, offset, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (job_id, stream, offset, data, int(time.time())))
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to append log for job {job_id}: {e}")
                raise

    async def iter_logs(
        self,
        job_id: str,
        start_offset: int = 0,
        stream: Optional[str] = None
    ) -> List['LogChunk']:
        """
        Iterate log chunks for job.

        Args:
            job_id: Job identifier
            start_offset: Start from this byte offset
            stream: Filter by stream ('stdout', 'stderr'), or None for both

        Returns:
            List of LogChunk records sorted by offset
        """
        from .job_store import LogChunk

        for attempt in range(2):
            try:
                async with self._connect() as db:
                    await self._configure_connection(db)
                    db.row_factory = self._row_factory()

                    # Build query with optional stream filter
                    query = """
                        SELECT job_id, stream, offset, payload, created_at
                        FROM job_logs
                        WHERE job_id = ? AND offset >= ?
                    """
                    params = [job_id, start_offset]

                    order_in_sql = stream is not None
                    if stream is not None:
                        query += " AND stream = ?"
                        params.append(stream)

                    if order_in_sql:
                        query += " ORDER BY offset ASC"

                    async with db.execute(query, params) as cursor:
                        rows = await cursor.fetchall()

                        chunks = [
                            LogChunk(
                                job_id=row['job_id'],
                                stream=row['stream'],
                                offset=row['offset'],
                                data=row['payload'],
                                created_at=row['created_at']
                            )
                            for row in rows
                        ]
                        if not order_in_sql:
                            chunks.sort(key=lambda c: c.offset)
                        return chunks
            except sqlite3.OperationalError as e:
                if "unable to open database file" in str(e).lower() and attempt == 0:
                    await asyncio.sleep(0.05)
                    continue
                raise

    async def close(self) -> None:
        """Close database connection and cleanup."""
        # For aiosqlite, connections are created per-operation, so nothing to close
        logger.info("SQLite job store closed")

    def _row_to_record(self, row: aiosqlite.Row) -> JobRecord:
        """Convert SQLite row to JobRecord."""
        return JobRecord(
            job_id=row['job_id'],
            kind=row['kind'],
            payload_json=row['payload_json'],
            state=row['state'],
            priority=row['priority'],
            created_at=row['created_at'],
            queued_at=row['queued_at'],
            claimed_at=row['claimed_at'],
            started_at=row['started_at'],
            finished_at=row['finished_at'],
            run_after=row['run_after'],
            worker_id=row['worker_id'],
            lease_expires_at=row['lease_expires_at'],
            last_heartbeat=row['last_heartbeat'],
            attempt=row['attempt'],
            max_attempts=row['max_attempts'],
            cancel_reason=row['cancel_reason'],
            cancellation_requested=bool(row['cancellation_requested']),
            exit_code=row['exit_code'],
            error_message=row['error_message'],
            skip_reason=row['skip_reason'],
            gpu_req=row['gpu_req'],
            gpu_type=row['gpu_type'],
            run_id=row['run_id'],
            run_dir=row['run_dir'],
            provenance_path=row['provenance_path'],
            user_id=row['user_id'],
            session_id=row['session_id'],
            project_id=row['project_id'] if 'project_id' in row.keys() else None,
            cpus=row['cpus'] if 'cpus' in row.keys() else 1,
            memory_gb=row['memory_gb'] if 'memory_gb' in row.keys() else 4.0,
            walltime_minutes=row['walltime_minutes'] if 'walltime_minutes' in row.keys() else 60,
            backend=row['backend'] if 'backend' in row.keys() else None,
            job_name=row['job_name'] if 'job_name' in row.keys() else None,
        )

    async def _audit_log(
        self,
        db: aiosqlite.Connection,
        job_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Write audit log entry."""
        try:
            await db.execute("""
                INSERT INTO job_audit (job_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
            """, (job_id, event_type, json.dumps(payload) if payload else None, int(time.time())))
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")


class DualJobStore(JobStore):
    """
    Dual-write job store that writes to both primary and secondary stores.

    Used for validating SQLite against Memory backend during development.
    All writes go to both stores, reads come from primary only.
    Discrepancies are logged for analysis.

    Typical usage:
        memory_store = MemoryJobStore(total_gpu_slots=2)
        sqlite_store = SqliteJobStore(db_path="validation.db", total_gpu_slots=2)
        await sqlite_store.initialize()

        dual_store = DualJobStore(primary=memory_store, secondary=sqlite_store)
        # All operations now go to both stores
    """

    def __init__(self, primary: JobStore, secondary: JobStore):
        """
        Initialize dual-write store.

        Args:
            primary: Primary store for reads and writes (typically MemoryJobStore)
            secondary: Secondary store for validation writes (typically SqliteJobStore)
        """
        self.primary = primary
        self.secondary = secondary
        self._discrepancy_count = 0
        logger.info(f"DualJobStore initialized: primary={type(primary).__name__}, secondary={type(secondary).__name__}")

    async def initialize(self) -> None:
        """Initialize both stores if they support it."""
        # Initialize secondary (SqliteJobStore needs this)
        if hasattr(self.secondary, 'initialize'):
            await self.secondary.initialize()
        # Primary (MemoryJobStore) doesn't need initialization
        logger.info("DualJobStore initialized both backends")

    async def close(self) -> None:
        """Close both stores if they support it."""
        if hasattr(self.secondary, 'close'):
            await self.secondary.close()
        logger.info("DualJobStore closed both backends")

    async def _call_heartbeat(
        self,
        store,
        worker_id: str,
        job_id: Optional[str],
        lease_ttl: int
    ) -> Optional[int]:
        """Invoke store.heartbeat with compatible signature."""
        if not hasattr(store, 'heartbeat'):
            return None

        heartbeat_fn = store.heartbeat
        try:
            return await heartbeat_fn(worker_id, job_id, lease_ttl)
        except TypeError:
            # Fallback for stores that don't accept lease_ttl
            return await heartbeat_fn(worker_id, job_id)

    async def enqueue(self, job: JobRecord) -> str:
        """Enqueue job in both stores."""
        job_id = await self.primary.enqueue(job)
        try:
            secondary_id = await self.secondary.enqueue(job)
            if secondary_id != job_id:
                logger.warning(f"Discrepancy in enqueue: primary={job_id}, secondary={secondary_id}")
                self._discrepancy_count += 1
        except Exception as e:
            logger.error(f"Secondary enqueue failed for {job_id}: {e}")
        return job_id

    async def get(self, job_id: str) -> Optional[JobRecord]:
        """
        Get job from primary, optionally validate against secondary.

        Validation is performed periodically (every 100th call) to avoid overhead.
        """
        primary_job = await self.primary.get(job_id)

        # Validate occasionally
        if self._should_validate():
            try:
                secondary_job = await self.secondary.get(job_id)
                self._compare_jobs(job_id, primary_job, secondary_job)
            except Exception as e:
                logger.debug(f"Secondary get validation failed for {job_id}: {e}")

        return primary_job

    async def update_state(
        self, job_id: str, state: JobState | str | None = None, **kwargs
    ) -> bool:
        """Update state in both stores."""
        result = await self.primary.update_state(job_id, state, **kwargs)
        try:
            secondary_result = await self.secondary.update_state(job_id, state, **kwargs)
            if result != secondary_result:
                logger.warning(
                    f"Discrepancy in update_state for {job_id}: "
                    f"primary={result}, secondary={secondary_result}"
                )
                self._discrepancy_count += 1
        except Exception as e:
            logger.error(f"Secondary update_state failed for {job_id}: {e}")
        return result

    async def claim_next(
        self,
        worker_id: str,
        lease_ttl: int = 60,
        gpu_filter: Optional[bool] = None
    ) -> Optional[JobRecord]:
        """
        Claim next job from primary only.

        Note: Claim operations are NOT dual-written to avoid race conditions.
        The secondary store is updated via update_state when the job transitions.
        """
        claimed = await self.primary.claim_next(worker_id, lease_ttl, gpu_filter)
        # Do NOT dual-write claims - they're inherently racy
        return claimed

    async def heartbeat(
        self,
        worker_id: str,
        job_id: Optional[str] = None,
        lease_ttl: int = 60,
    ) -> int:
        """Send heartbeat to both stores."""
        primary_result = await self._call_heartbeat(
            self.primary, worker_id, job_id, lease_ttl
        )

        try:
            secondary_result = await self._call_heartbeat(
                self.secondary, worker_id, job_id, lease_ttl
            )
            if isinstance(primary_result, int) and isinstance(secondary_result, int):
                if primary_result != secondary_result:
                    logger.debug(
                        f"Heartbeat count difference: primary={primary_result}, secondary={secondary_result}"
                    )
        except Exception as e:
            logger.error(f"Secondary heartbeat failed: {e}")

        return int(primary_result or 0)

    async def append_event(
        self,
        job_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> int:
        primary_id = await self.primary.append_event(
            job_id, event_type, payload=payload, created_at=created_at
        )
        try:
            await self.secondary.append_event(
                job_id, event_type, payload=payload, created_at=created_at
            )
        except Exception as e:
            logger.error(f"Secondary append_event failed for {job_id}: {e}")
        return int(primary_id or 0)

    async def list_events(
        self,
        job_id: str,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> List[JobEvent]:
        return await self.primary.list_events(
            job_id, after_event_id=after_event_id, limit=limit
        )

    async def cancel(self, job_id: str, reason: Optional[str] = None) -> bool:
        """Cancel job in both stores."""
        result = await self.primary.cancel(job_id, reason)
        try:
            secondary_result = await self.secondary.cancel(job_id, reason)
            if result != secondary_result:
                logger.warning(
                    f"Discrepancy in cancel for {job_id}: "
                    f"primary={result}, secondary={secondary_result}"
                )
                self._discrepancy_count += 1
        except Exception as e:
            logger.error(f"Secondary cancel failed for {job_id}: {e}")
        return result

    async def list_by_state(
        self,
        state: JobState,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """List jobs from primary."""
        return await self.primary.list_by_state(
            state,
            user_id=user_id,
            limit=limit,
            offset=offset,
            project_id=project_id,
        )

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """List all jobs from primary."""
        return await self.primary.list_all(
            user_id=user_id,
            limit=limit,
            offset=offset,
            project_id=project_id,
        )

    async def count_by_state(self, state: str, user_id: Optional[str] = None) -> int:
        return await self.primary.count_by_state(state, user_id=user_id)

    async def count_all(self, user_id: Optional[str] = None) -> int:
        return await self.primary.count_all(user_id=user_id)

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue stats from primary."""
        stats = await self.primary.get_queue_stats()

        # Add dual-store metadata
        stats['dual_store'] = {
            'primary_type': type(self.primary).__name__,
            'secondary_type': type(self.secondary).__name__,
            'discrepancy_count': self._discrepancy_count
        }

        return stats

    async def recover_stale_jobs(self, now_ts: Optional[int] = None) -> Dict[str, int]:
        """
        Recover stale jobs in both stores.

        Note: MemoryJobStore uses recover_stale(), SqliteJobStore uses recover_stale_jobs().
        This method handles both API signatures.
        """
        # Recover from primary
        primary_stats = {}
        if hasattr(self.primary, 'recover_stale_jobs'):
            primary_stats = await self.primary.recover_stale_jobs(now_ts)
        elif hasattr(self.primary, 'recover_stale'):
            # MemoryJobStore.recover_stale(lease_timeout) -> Dict[str, int]
            lease_timeout = 120  # Default timeout
            primary_stats = await self.primary.recover_stale(lease_timeout)

        primary_recovered = primary_stats.get('recovered', primary_stats.get('jobs_requeued', 0))
        primary_gpus = primary_stats.get('gpus_freed', 0)

        secondary_recovered = 0
        secondary_gpus = 0

        # Recover from secondary
        try:
            if hasattr(self.secondary, 'recover_stale_jobs'):
                secondary_stats = await self.secondary.recover_stale_jobs(now_ts)
                secondary_recovered = secondary_stats.get('recovered', secondary_stats.get('jobs_requeued', 0) or 0)
                secondary_gpus = secondary_stats.get('gpus_freed', 0)
                if primary_stats != secondary_stats:
                    logger.info(
                        f"Recovery stats differ: primary={primary_stats}, secondary={secondary_stats}"
                    )
            elif hasattr(self.secondary, 'recover_stale'):
                secondary_stats = await self.secondary.recover_stale(120)
                secondary_recovered = secondary_stats.get('recovered', secondary_stats.get('jobs_requeued', 0) or 0)
                secondary_gpus = secondary_stats.get('gpus_freed', 0)
        except Exception as e:
            logger.error(f"Secondary recovery failed: {e}")

        recovered_total = max(primary_recovered, secondary_recovered)
        gpus_freed_total = max(primary_gpus, secondary_gpus)

        return {
            'recovered': recovered_total,
            'gpus_freed': gpus_freed_total,
        }

    # GPU slot management (delegate to primary)

    async def reserve_slots(self, job_id: str, gpu_req: int) -> List[int]:
        """Reserve GPU slots in both stores (if they support it)."""
        slots = []
        if hasattr(self.primary, 'reserve_slots'):
            slots = await self.primary.reserve_slots(job_id, gpu_req)

        # Secondary may not support this method (e.g., SqliteJobStore manages GPU internally)
        try:
            if hasattr(self.secondary, 'reserve_slots'):
                await self.secondary.reserve_slots(job_id, gpu_req)
        except Exception as e:
            logger.debug(f"Secondary reserve_slots failed for {job_id}: {e}")
        return slots

    async def release_slots(self, job_id: str) -> int:
        """Release GPU slots in both stores (if they support it)."""
        count = 0
        if hasattr(self.primary, 'release_slots'):
            count = await self.primary.release_slots(job_id)

        try:
            if hasattr(self.secondary, 'release_slots'):
                await self.secondary.release_slots(job_id)
        except Exception as e:
            logger.debug(f"Secondary release_slots failed for {job_id}: {e}")
        return count

    async def get_slot_stats(self) -> Dict[str, int]:
        """Get GPU slot stats from primary."""
        return await self.primary.get_slot_stats()

    async def get_assigned_devices(self, job_id: str) -> List[int]:
        """Get assigned GPU devices from primary."""
        return await self.primary.get_assigned_devices(job_id)

    async def release_gpus(self, job_id: str) -> None:
        """Release GPUs in both stores."""
        await self.primary.release_gpus(job_id)
        try:
            await self.secondary.release_gpus(job_id)
        except Exception as e:
            logger.error(f"Secondary release_gpus failed for {job_id}: {e}")

    async def recover_stale(self, lease_timeout: int = 120) -> Dict[str, int]:
        """Recover stale jobs in both stores."""
        stats = await self.primary.recover_stale(lease_timeout)
        try:
            await self.secondary.recover_stale(lease_timeout)
        except Exception as e:
            logger.error(f"Secondary recover_stale failed: {e}")
        return stats

    # Log persistence methods

    async def append_log(
        self,
        job_id: str,
        stream: str,
        data: bytes,
        offset: int
    ) -> None:
        """Append log chunk to both stores."""
        await self.primary.append_log(job_id, stream, data, offset)
        try:
            await self.secondary.append_log(job_id, stream, data, offset)
        except Exception as e:
            logger.error(f"Secondary append_log failed for {job_id}: {e}")

    async def iter_logs(
        self,
        job_id: str,
        start_offset: int = 0,
        stream: Optional[str] = None
    ) -> List['LogChunk']:
        """
        Iterate log chunks from primary store.

        Args:
            job_id: Job identifier
            start_offset: Start from this byte offset
            stream: Filter by stream ('stdout', 'stderr'), or None for both

        Returns:
            List of LogChunk records from primary store
        """
        return await self.primary.iter_logs(job_id, start_offset, stream)

    # Validation helpers

    def _should_validate(self) -> bool:
        """Decide if we should perform expensive validation on this call."""
        # Validate every 100th call to avoid overhead
        import random
        return random.randint(1, 100) == 1

    def _compare_jobs(
        self,
        job_id: str,
        primary_job: Optional[JobRecord],
        secondary_job: Optional[JobRecord]
    ) -> None:
        """Compare jobs from both stores and log discrepancies."""
        if primary_job is None and secondary_job is None:
            return  # Both agree: job doesn't exist

        if primary_job is None:
            logger.warning(f"Discrepancy for {job_id}: exists in secondary but not primary")
            self._discrepancy_count += 1
            return

        if secondary_job is None:
            logger.warning(f"Discrepancy for {job_id}: exists in primary but not secondary")
            self._discrepancy_count += 1
            return

        # Compare key fields
        if primary_job.state != secondary_job.state:
            logger.warning(
                f"State mismatch for {job_id}: "
                f"primary={primary_job.state}, secondary={secondary_job.state}"
            )
            self._discrepancy_count += 1
