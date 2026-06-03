"""SQLite-based cache store implementation.

Provides persistent cache storage with:
- Atomic pending state creation (prevents race conditions)
- LRU eviction based on last_accessed_at
- Tool and git-based invalidation
- Statistics tracking
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any

import os
import sqlite3

try:
    import aiosqlite
except ImportError:
    raise ImportError("aiosqlite is required for SQLite backend. Install with: pip install aiosqlite")

from .cache_store import CacheStore, CacheEntry, CacheStats

logger = logging.getLogger(__name__)


def _should_use_sync_sqlite() -> bool:
    """Decide whether to use sync sqlite3 connections instead of aiosqlite."""
    env = os.getenv("BR_SQLITE_SYNC")
    if env is not None:
        return env.lower() in {"1", "true", "yes", "y", "on"}
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


class _SyncCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

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

    def __init__(self, path: Path):
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None

    async def __aenter__(self):
        self._conn = sqlite3.connect(self._path)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        return False

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

    async def commit(self) -> None:
        self._conn.commit()


class SqliteCacheStore(CacheStore):
    """SQLite-based cache store.

    Uses the run_cache table created in sqlite_schema/schema.sql.

    Args:
        db_path: Path to SQLite database file (same DB as job store)
        busy_timeout_ms: SQLite busy timeout in milliseconds (default: 5000)
    """

    def __init__(
        self,
        db_path: str | Path,
        busy_timeout_ms: int = 5000
    ):
        self._db_path = Path(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._lock = asyncio.Lock()
        self._initialized = False
        self._use_sync = _should_use_sync_sqlite()

        # In-memory hit/miss tracking (not persisted)
        self._hit_count = 0
        self._miss_count = 0

    def _connect(self):
        """Return an async context manager for SQLite connections."""
        if self._use_sync:
            return _SyncConnection(self._db_path)
        return aiosqlite.connect(self._db_path)

    def _row_factory(self):
        return sqlite3.Row if self._use_sync else aiosqlite.Row

    async def initialize(self) -> None:
        """Initialize cache store.

        Note: Assumes schema.sql has already been applied by SqliteJobStore.
        This just verifies the table exists.
        """
        if self._initialized:
            return

        async with self._connect() as db:
            await self._configure_connection(db)

            # Verify run_cache table exists
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='run_cache'"
            )
            result = await cursor.fetchone()
            if not result:
                raise RuntimeError(
                    "run_cache table not found. Ensure schema.sql has been applied "
                    "by initializing SqliteJobStore first."
                )

        self._initialized = True
        logger.info(f"Initialized SqliteCacheStore with DB at {self._db_path}")

    async def _configure_connection(self, db: aiosqlite.Connection) -> None:
        """Configure SQLite connection with performance settings."""
        await db.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")

    async def lookup(self, cache_key: str) -> Optional[CacheEntry]:
        """Look up cache entry and update last_accessed_at."""
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()

            # Select and update access time atomically
            cursor = await db.execute(
                """
                SELECT cache_key, run_id, run_dir, state, meta_json,
                       created_at, last_accessed_at, tool_version, git_sha, size_bytes
                FROM run_cache
                WHERE cache_key = ?
                """,
                (cache_key,)
            )
            row = await cursor.fetchone()

            if not row:
                self._miss_count += 1
                return None

            # Update last_accessed_at
            await db.execute(
                "UPDATE run_cache SET last_accessed_at = ? WHERE cache_key = ?",
                (int(time.time()), cache_key)
            )
            await db.commit()

            self._hit_count += 1

            return CacheEntry(
                cache_key=row["cache_key"],
                run_id=row["run_id"],
                run_dir=row["run_dir"],
                state=row["state"],
                meta_json=row["meta_json"],
                created_at=row["created_at"],
                last_accessed_at=row["last_accessed_at"],
                tool_version=row["tool_version"],
                git_sha=row["git_sha"],
                size_bytes=row["size_bytes"],
            )

    async def create_and_mark_pending(
        self,
        cache_key: str,
        run_id: str,
        meta: Dict[str, Any],
        tool_version: Optional[str] = None,
        git_sha: Optional[str] = None,
    ) -> bool:
        """Ensure a cache entry exists in pending state.

        Returns True if reserved for this run_id, False if another worker already holds it.
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            now = int(time.time())
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO run_cache
                    (cache_key, run_id, run_dir, state, meta_json,
                     created_at, last_accessed_at, tool_version, git_sha)
                    VALUES (?, ?, '', 'pending', ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        state = 'pending',
                        run_id = excluded.run_id,
                        run_dir = '',
                        size_bytes = NULL,
                        meta_json = excluded.meta_json,
                        last_accessed_at = excluded.last_accessed_at,
                        tool_version = COALESCE(excluded.tool_version, run_cache.tool_version),
                        git_sha = COALESCE(excluded.git_sha, run_cache.git_sha)
                    WHERE run_cache.state = 'failed'
                    """,
                    (
                        cache_key,
                        run_id,
                        json.dumps(meta),
                        now,
                        now,
                        tool_version,
                        git_sha,
                    )
                )
                await db.commit()
                if cursor.rowcount > 0:
                    logger.debug(
                        f"Reserved cache entry {cache_key[:16]}... for pending run {run_id}"
                    )
                    return True

            except Exception as e:
                logger.error(f"Failed to create pending cache entry: {e}")
                raise

        return False

    async def mark_completed(
        self,
        cache_key: str,
        run_id: str,
        run_dir: str,
        size_bytes: Optional[int] = None,
    ) -> bool:
        """Mark a pending entry as completed."""
        async with self._connect() as db:
            await self._configure_connection(db)

            cursor = await db.execute(
                """
                UPDATE run_cache
                SET state = 'completed',
                    run_id = ?,
                    run_dir = ?,
                    size_bytes = ?,
                    last_accessed_at = ?
                WHERE cache_key = ? AND state = 'pending'
                """,
                (run_id, run_dir, size_bytes, int(time.time()), cache_key)
            )
            await db.commit()

            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Marked cache entry {cache_key[:16]}... as completed")
            else:
                logger.warning(
                    f"Failed to mark cache entry {cache_key[:16]}... as completed "
                    "(not found or not in pending state)"
                )

            return updated

    async def mark_failed(
        self,
        cache_key: str,
        run_id: str,
        error: str,
    ) -> bool:
        """Mark a pending entry as failed."""
        async with self._connect() as db:
            await self._configure_connection(db)

            # Update state and add error to meta
            cursor = await db.execute(
                """
                SELECT state, meta_json FROM run_cache WHERE cache_key = ?
                """,
                (cache_key,)
            )
            row = await cursor.fetchone()

            if not row:
                return False

            state, meta_json = row
            if state != "pending":
                logger.debug(
                    "Cache entry %s not pending (state=%s); mark_failed skipped",
                    cache_key[:16],
                    state,
                )
                return False

            # Add error to meta
            meta = json.loads(meta_json)
            meta["error"] = error
            meta["run_id"] = run_id

            await db.execute(
                """
                UPDATE run_cache
                SET state = 'failed',
                    run_id = ?,
                    meta_json = ?,
                    last_accessed_at = ?
                WHERE cache_key = ? AND state = 'pending'
                """,
                (run_id, json.dumps(meta), int(time.time()), cache_key)
            )
            await db.commit()

            logger.info(f"Marked cache entry {cache_key[:16]}... as failed: {error}")
            return True

    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        async with self._connect() as db:
            await self._configure_connection(db)

            cursor = await db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(COALESCE(size_bytes, 0)) as total_size
                FROM run_cache
                """
            )
            row = await cursor.fetchone()

            return CacheStats(
                total_entries=row[0] or 0,
                pending_entries=row[1] or 0,
                completed_entries=row[2] or 0,
                failed_entries=row[3] or 0,
                total_size_bytes=row[4] or 0,
                hit_count=self._hit_count,
                miss_count=self._miss_count,
            )

    async def clear_all(self) -> int:
        """Clear all cache entries."""
        async with self._connect() as db:
            await self._configure_connection(db)

            cursor = await db.execute("DELETE FROM run_cache")
            await db.commit()

            deleted = cursor.rowcount
            logger.info(f"Cleared all cache entries ({deleted} deleted)")
            return deleted

    async def clear_by_tool(self, tool_version: str) -> int:
        """Clear cache entries for a specific tool version."""
        async with self._connect() as db:
            await self._configure_connection(db)

            cursor = await db.execute(
                "DELETE FROM run_cache WHERE tool_version = ?",
                (tool_version,)
            )
            await db.commit()

            deleted = cursor.rowcount
            logger.info(f"Cleared {deleted} cache entries for tool {tool_version}")
            return deleted

    async def clear_by_git(self, git_sha: str) -> int:
        """Clear cache entries for a specific git SHA."""
        async with self._connect() as db:
            await self._configure_connection(db)

            cursor = await db.execute(
                "DELETE FROM run_cache WHERE git_sha = ?",
                (git_sha,)
            )
            await db.commit()

            deleted = cursor.rowcount
            logger.info(f"Cleared {deleted} cache entries for git SHA {git_sha[:8]}")
            return deleted

    async def gc_lru(self, max_entries: int) -> int:
        """Run garbage collection to keep cache under size limit.

        Keeps the most recently accessed entries up to max_entries.
        """
        async with self._connect() as db:
            await self._configure_connection(db)

            # Count total entries
            cursor = await db.execute("SELECT COUNT(*) FROM run_cache")
            total = (await cursor.fetchone())[0]

            if total <= max_entries:
                return 0

            # Delete oldest entries (keep newest max_entries)
            to_delete = total - max_entries

            await db.execute(
                """
                DELETE FROM run_cache
                WHERE cache_key IN (
                    SELECT cache_key
                    FROM run_cache
                    ORDER BY last_accessed_at ASC
                    LIMIT ?
                )
                """,
                (to_delete,)
            )
            await db.commit()

            logger.info(
                f"LRU eviction: deleted {to_delete} old entries "
                f"(kept {max_entries} most recent)"
            )
            return to_delete
