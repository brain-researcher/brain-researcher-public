"""SQLite-backed persistence for orchestrator UI state.

This module provides a small, durable store for state that is otherwise held
in-memory (threads/messages, notifications, demo share tokens). It is intended
to survive process restarts in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import sqlite3

try:
    import aiosqlite
except ImportError:  # pragma: no cover - optional dependency
    aiosqlite = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _should_use_sync_sqlite() -> bool:
    """Decide whether to use sync sqlite3 connections instead of aiosqlite."""
    env = os.getenv("BR_SQLITE_SYNC")
    if env is not None:
        return env.lower() in {"1", "true", "yes", "y", "on"}
    if aiosqlite is None:
        return True
    # Prefer sync in pytest to avoid aiosqlite thread hangs.
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


class _SyncCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    def __await__(self):
        async def _noop():
            return self

        return _noop().__await__()

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    async def close(self) -> None:
        self._cursor.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._cursor.close()
        return False


class _SyncConnection:
    """Async-compatible wrapper around sqlite3.Connection."""

    def __init__(
        self,
        path: Path,
        lock: Optional[threading.Lock] = None,
        timeout_s: Optional[float] = None,
    ):
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = lock
        self._timeout_s = timeout_s

    async def __aenter__(self):
        if self._lock is not None:
            self._lock.acquire()
        try:
            timeout = self._timeout_s if self._timeout_s is not None else 5.0
            self._conn = sqlite3.connect(
                self._path,
                timeout=timeout,
                check_same_thread=False,
            )
            return self
        except Exception:
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


def _parse_epoch_seconds(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, str):
        try:
            candidate = value.rstrip("Z")
            dt = datetime.fromisoformat(candidate)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


class SqliteStateStore:
    """Persistent state store for orchestrator/UI state (SQLite WAL mode)."""

    def __init__(self, db_path: str | Path, busy_timeout_ms: int = 5000):
        self._db_path = Path(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._use_sync = _should_use_sync_sqlite()
        self._sync_lock = threading.Lock() if self._use_sync else None

    def _connect(self):
        if self._use_sync:
            timeout_s = self._busy_timeout_ms / 1000.0
            return _SyncConnection(self._db_path, self._sync_lock, timeout_s)
        if aiosqlite is None:  # pragma: no cover - optional dependency
            raise RuntimeError("aiosqlite is required for async SQLite connections")
        return aiosqlite.connect(self._db_path)

    def _row_factory(self):
        return sqlite3.Row if self._use_sync else aiosqlite.Row

    async def _configure_connection(self, db) -> None:
        await db.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms};")
        await db.execute("PRAGMA synchronous=NORMAL;")
        cursor = await db.execute("PRAGMA journal_mode=WAL;")
        await cursor.fetchone()
        await cursor.close()

    async def initialize(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as exc:
                raise RuntimeError(
                    f"Cannot create state DB directory {self._db_path.parent}: {exc}."
                ) from exc

            if not os.access(self._db_path.parent, os.W_OK):
                raise RuntimeError(
                    f"State DB directory {self._db_path.parent} is not writable."
                )

            schema_sql = """
            CREATE TABLE IF NOT EXISTS threads (
              thread_id TEXT PRIMARY KEY,
              user_id TEXT,
              thread_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
              message_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              message_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_thread_time
              ON messages(thread_id, created_at);

            CREATE TABLE IF NOT EXISTS notifications (
              notification_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              notification_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              read INTEGER NOT NULL DEFAULT 0,
              expires_at INTEGER,
              updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notifications_user_created
              ON notifications(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notifications_user_read
              ON notifications(user_id, read, created_at DESC);

            CREATE TABLE IF NOT EXISTS monitors (
              monitor_id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              thread_id TEXT,
              source_type TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              monitor_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_monitors_owner_updated
              ON monitors(owner_user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_monitors_source
              ON monitors(source_type, source_ref);
            CREATE INDEX IF NOT EXISTS idx_monitors_thread
              ON monitors(thread_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS monitor_events (
              event_id INTEGER PRIMARY KEY AUTOINCREMENT,
              monitor_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              event_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY(monitor_id) REFERENCES monitors(monitor_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_monitor_events_monitor_created
              ON monitor_events(monitor_id, created_at DESC, event_id DESC);

            CREATE TABLE IF NOT EXISTS chat_bridges (
              bridge_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              platform TEXT NOT NULL,
              bridge_key TEXT NOT NULL,
              bridge_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_bridges_platform_key
              ON chat_bridges(platform, bridge_key);
            CREATE INDEX IF NOT EXISTS idx_chat_bridges_thread_platform
              ON chat_bridges(thread_id, platform, updated_at DESC);

            CREATE TABLE IF NOT EXISTS demo_shares (
              token_hash TEXT PRIMARY KEY,
              demo_id TEXT NOT NULL,
              is_public INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              revoked_at INTEGER,
              created_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_demo_shares_demo_id
              ON demo_shares(demo_id);

            CREATE TABLE IF NOT EXISTS analysis_shares (
              token_hash TEXT PRIMARY KEY,
              analysis_id TEXT NOT NULL,
              share_level TEXT NOT NULL DEFAULT 'summary'
                          CHECK(share_level IN ('summary', 'full')),
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              revoked_at INTEGER,
              created_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_analysis_shares_analysis_id
              ON analysis_shares(analysis_id);
            """

            async with self._connect() as db:
                await self._configure_connection(db)
                await db.executescript(schema_sql)
                await db.commit()

            self._initialized = True
            logger.info("SQLite state store initialized at %s", self._db_path)

    # ---------------------------------------------------------------------
    # Threads / Messages
    # ---------------------------------------------------------------------

    async def upsert_thread(
        self,
        *,
        thread_id: str,
        thread: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        now = int(time.time())
        thread_json = json.dumps(thread, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO threads (thread_id, user_id, thread_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                  user_id = COALESCE(excluded.user_id, threads.user_id),
                  thread_json = excluded.thread_json,
                  updated_at = excluded.updated_at
                """,
                (thread_id, user_id, thread_json, now, now),
            )
            await db.commit()

    async def get_thread(self, thread_id: str) -> Optional[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                "SELECT thread_json FROM threads WHERE thread_id = ?",
                (thread_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return json.loads(row["thread_json"])

    async def list_threads(
        self,
        *,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            if user_id:
                cursor = await db.execute(
                    """
                    SELECT thread_json
                    FROM threads
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT thread_json
                    FROM threads
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
            rows = await cursor.fetchall()
            await cursor.close()
            return [json.loads(row["thread_json"]) for row in rows]

    async def append_message(
        self,
        *,
        thread_id: str,
        message_id: str,
        message: dict[str, Any],
    ) -> None:
        now = int(time.time())
        created_at = _parse_epoch_seconds(message.get("timestamp")) or now
        message_json = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT OR REPLACE INTO messages (message_id, thread_id, message_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, thread_id, message_json, created_at),
            )
            await db.commit()

    async def list_messages(
        self,
        *,
        thread_id: str,
        limit: int = 200,
        before_message_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()

            before_ts: int | None = None
            if before_message_id:
                async with db.execute(
                    "SELECT created_at FROM messages WHERE message_id = ? AND thread_id = ?",
                    (before_message_id, thread_id),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        before_ts = int(row["created_at"])

            if before_ts is not None:
                cursor = await db.execute(
                    """
                    SELECT message_json
                    FROM messages
                    WHERE thread_id = ? AND created_at < ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (thread_id, before_ts, limit),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT message_json
                    FROM messages
                    WHERE thread_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (thread_id, limit),
                )

            rows = await cursor.fetchall()
            await cursor.close()
            # Return ascending order for callers.
            messages = [json.loads(row["message_json"]) for row in rows]
            messages.reverse()
            return messages

    # ---------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------

    async def upsert_notification(self, notification: dict[str, Any]) -> None:
        now = int(time.time())
        notification_id = str(notification.get("id") or "")
        user_id = str(notification.get("user_id") or "")
        if not notification_id or not user_id:
            raise ValueError("notification.id and notification.user_id are required")
        created_at = _parse_epoch_seconds(notification.get("created_at")) or now
        expires_at = _parse_epoch_seconds(notification.get("expires_at"))
        read = 1 if notification.get("read") else 0
        notification_json = json.dumps(notification, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO notifications (
                  notification_id,
                  user_id,
                  notification_json,
                  created_at,
                  read,
                  expires_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notification_id) DO UPDATE SET
                  user_id = excluded.user_id,
                  notification_json = excluded.notification_json,
                  read = excluded.read,
                  expires_at = excluded.expires_at,
                  updated_at = excluded.updated_at
                """,
                (
                    notification_id,
                    user_id,
                    notification_json,
                    created_at,
                    read,
                    expires_at,
                    now,
                ),
            )
            await db.commit()

    async def list_notifications(
        self,
        *,
        user_id: str,
        limit: int = 50,
        unread_only: bool = False,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()

            cursor_created_at: int | None = None
            if cursor:
                async with db.execute(
                    "SELECT created_at FROM notifications WHERE notification_id = ? AND user_id = ?",
                    (cursor, user_id),
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        cursor_created_at = int(row["created_at"])

            clauses: list[str] = ["user_id = ?"]
            params: list[Any] = [user_id]
            if unread_only:
                clauses.append("read = 0")
            if cursor_created_at is not None:
                clauses.append("created_at < ?")
                params.append(cursor_created_at)

            where_sql = " AND ".join(clauses)
            sql = f"""
                SELECT notification_json
                FROM notifications
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
            """
            params.append(limit)
            cursor_obj = await db.execute(sql, params)
            rows = await cursor_obj.fetchall()
            await cursor_obj.close()
            return [json.loads(row["notification_json"]) for row in rows]

    async def count_unread_notifications(self, user_id: str) -> int:
        async with self._connect() as db:
            await self._configure_connection(db)
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = ? AND read = 0",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return int(row[0] if row else 0)

    async def count_notifications(self, user_id: str) -> int:
        async with self._connect() as db:
            await self._configure_connection(db)
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return int(row[0] if row else 0)

    async def mark_notifications_read(self, user_id: str, notification_ids: list[str]) -> int:
        if not notification_ids:
            return 0
        now = int(time.time())
        updated = 0
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            try:
                for notification_id in notification_ids:
                    async with db.execute(
                        """
                        SELECT notification_json
                        FROM notifications
                        WHERE notification_id = ? AND user_id = ?
                        """,
                        (notification_id, user_id),
                    ) as cursor:
                        row = await cursor.fetchone()
                        if not row:
                            continue
                        payload = json.loads(row["notification_json"])
                        payload["read"] = True
                        payload["read_at"] = datetime.utcnow().isoformat()
                        payload_json = json.dumps(
                            payload, separators=(",", ":"), ensure_ascii=False
                        )
                        cursor2 = await db.execute(
                            """
                            UPDATE notifications
                            SET notification_json = ?,
                                read = 1,
                                updated_at = ?
                            WHERE notification_id = ? AND user_id = ?
                            """,
                            (payload_json, now, notification_id, user_id),
                        )
                        updated += cursor2.rowcount
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return updated

    # ---------------------------------------------------------------------
    # Monitors / Monitor Events / Chat Bridges
    # ---------------------------------------------------------------------

    async def upsert_monitor(self, monitor: dict[str, Any]) -> None:
        now = int(time.time())
        monitor_id = str(monitor.get("id") or "")
        owner_user_id = str(monitor.get("owner_user_id") or "")
        source_type = str(monitor.get("source_type") or "")
        source_ref = str(monitor.get("source_ref") or "")
        if not monitor_id or not owner_user_id or not source_type or not source_ref:
            raise ValueError(
                "monitor.id, monitor.owner_user_id, monitor.source_type, and monitor.source_ref are required"
            )

        created_at = _parse_epoch_seconds(monitor.get("created_at")) or now
        monitor_json = json.dumps(monitor, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO monitors (
                  monitor_id,
                  owner_user_id,
                  thread_id,
                  source_type,
                  source_ref,
                  monitor_json,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                  owner_user_id = excluded.owner_user_id,
                  thread_id = excluded.thread_id,
                  source_type = excluded.source_type,
                  source_ref = excluded.source_ref,
                  monitor_json = excluded.monitor_json,
                  updated_at = excluded.updated_at
                """,
                (
                    monitor_id,
                    owner_user_id,
                    monitor.get("thread_id"),
                    source_type,
                    source_ref,
                    monitor_json,
                    created_at,
                    now,
                ),
            )
            await db.commit()

    async def get_monitor(self, monitor_id: str) -> Optional[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                "SELECT monitor_json FROM monitors WHERE monitor_id = ?",
                (monitor_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return json.loads(row["monitor_json"])

    async def list_monitors(
        self,
        *,
        owner_user_id: str | None = None,
        thread_id: str | None = None,
        source_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id:
            clauses.append("owner_user_id = ?")
            params.append(owner_user_id)
        if thread_id:
            clauses.append("thread_id = ?")
            params.append(thread_id)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            cursor = await db.execute(
                f"""
                SELECT monitor_json
                FROM monitors
                {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return [json.loads(row["monitor_json"]) for row in rows]

    async def append_monitor_event(
        self,
        *,
        monitor_id: str,
        event_type: str,
        event: dict[str, Any],
    ) -> int:
        now = int(time.time())
        event_json = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            cursor = await db.execute(
                """
                INSERT INTO monitor_events (
                  monitor_id,
                  event_type,
                  event_json,
                  created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (monitor_id, event_type, event_json, now),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def list_monitor_events(
        self,
        *,
        monitor_id: str,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            cursor = await db.execute(
                """
                SELECT event_id, event_type, event_json, created_at
                FROM monitor_events
                WHERE monitor_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (monitor_id, after_event_id, limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            items: list[dict[str, Any]] = []
            for row in rows:
                payload = json.loads(row["event_json"])
                items.append(
                    {
                        "event_id": int(row["event_id"]),
                        "event_type": row["event_type"],
                        "created_at": int(row["created_at"]),
                        "payload": payload,
                    }
                )
            return items

    async def upsert_chat_bridge(self, bridge: dict[str, Any]) -> None:
        now = int(time.time())
        bridge_id = str(bridge.get("id") or "")
        thread_id = str(bridge.get("thread_id") or "")
        platform = str(bridge.get("platform") or "")
        bridge_key = str(bridge.get("bridge_key") or "")
        if not bridge_id or not thread_id or not platform or not bridge_key:
            raise ValueError(
                "bridge.id, bridge.thread_id, bridge.platform, and bridge.bridge_key are required"
            )
        created_at = _parse_epoch_seconds(bridge.get("created_at")) or now
        bridge_json = json.dumps(bridge, separators=(",", ":"), ensure_ascii=False)
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO chat_bridges (
                  bridge_id,
                  thread_id,
                  platform,
                  bridge_key,
                  bridge_json,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bridge_id) DO UPDATE SET
                  thread_id = excluded.thread_id,
                  platform = excluded.platform,
                  bridge_key = excluded.bridge_key,
                  bridge_json = excluded.bridge_json,
                  updated_at = excluded.updated_at
                """,
                (
                    bridge_id,
                    thread_id,
                    platform,
                    bridge_key,
                    bridge_json,
                    created_at,
                    now,
                ),
            )
            await db.commit()

    async def get_chat_bridge(self, bridge_id: str) -> Optional[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                "SELECT bridge_json FROM chat_bridges WHERE bridge_id = ?",
                (bridge_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return json.loads(row["bridge_json"])

    async def get_chat_bridge_by_external(
        self,
        *,
        platform: str,
        bridge_key: str,
    ) -> Optional[dict[str, Any]]:
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                """
                SELECT bridge_json
                FROM chat_bridges
                WHERE platform = ? AND bridge_key = ?
                """,
                (platform, bridge_key),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return json.loads(row["bridge_json"])

    async def list_chat_bridges(
        self,
        *,
        thread_id: str | None = None,
        platform: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if thread_id:
            clauses.append("thread_id = ?")
            params.append(thread_id)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            cursor = await db.execute(
                f"""
                SELECT bridge_json
                FROM chat_bridges
                {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return [json.loads(row["bridge_json"]) for row in rows]

    # ---------------------------------------------------------------------
    # Demo share tokens
    # ---------------------------------------------------------------------

    @staticmethod
    def hash_demo_share_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def store_demo_share(
        self,
        *,
        share_token: str,
        demo_id: str,
        is_public: bool,
        expires_at: datetime,
        created_by: str | None = None,
    ) -> None:
        token_hash = self.hash_demo_share_token(share_token)
        now = int(time.time())
        expires_at_ts = int(expires_at.timestamp())
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO demo_shares (
                  token_hash,
                  demo_id,
                  is_public,
                  created_at,
                  expires_at,
                  revoked_at,
                  created_by
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (token_hash, demo_id, 1 if is_public else 0, now, expires_at_ts, created_by),
            )
            await db.commit()

    async def resolve_demo_share(
        self,
        *,
        share_token: str,
        now: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        token_hash = self.hash_demo_share_token(share_token)
        now_dt = now or datetime.utcnow()
        now_ts = int(now_dt.timestamp())
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                """
                SELECT demo_id, is_public, created_at, expires_at, revoked_at, created_by
                FROM demo_shares
                WHERE token_hash = ?
                """,
                (token_hash,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                revoked_at = row["revoked_at"]
                if revoked_at is not None:
                    return None
                expires_at = int(row["expires_at"])
                if expires_at <= now_ts:
                    return None
                return {
                    "demo_id": row["demo_id"],
                    "is_public": bool(row["is_public"]),
                    "created_at": int(row["created_at"]),
                    "expires_at": expires_at,
                    "created_by": row["created_by"],
                }

    # ---------------------------------------------------------------------
    # Analysis share tokens
    # ---------------------------------------------------------------------

    @staticmethod
    def hash_analysis_share_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def store_analysis_share(
        self,
        *,
        share_token: str,
        analysis_id: str,
        share_level: str,
        expires_at: datetime,
        created_by: str | None = None,
    ) -> None:
        token_hash = self.hash_analysis_share_token(share_token)
        now = int(time.time())
        expires_at_ts = int(expires_at.timestamp())
        async with self._connect() as db:
            await self._configure_connection(db)
            await db.execute(
                """
                INSERT INTO analysis_shares (
                  token_hash,
                  analysis_id,
                  share_level,
                  created_at,
                  expires_at,
                  revoked_at,
                  created_by
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (token_hash, analysis_id, share_level, now, expires_at_ts, created_by),
            )
            await db.commit()

    async def resolve_analysis_share(
        self,
        *,
        share_token: str,
        now: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        token_hash = self.hash_analysis_share_token(share_token)
        now_dt = now or datetime.utcnow()
        now_ts = int(now_dt.timestamp())
        async with self._connect() as db:
            await self._configure_connection(db)
            db.row_factory = self._row_factory()
            async with db.execute(
                """
                SELECT analysis_id, share_level, created_at, expires_at, revoked_at, created_by
                FROM analysis_shares
                WHERE token_hash = ?
                """,
                (token_hash,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                revoked_at = row["revoked_at"]
                if revoked_at is not None:
                    return None
                expires_at = int(row["expires_at"])
                if expires_at <= now_ts:
                    return None
                return {
                    "analysis_id": row["analysis_id"],
                    "share_level": row["share_level"],
                    "created_at": int(row["created_at"]),
                    "expires_at": expires_at,
                    "created_by": row["created_by"],
                }

    async def revoke_analysis_share(self, *, share_token: str) -> bool:
        token_hash = self.hash_analysis_share_token(share_token)
        now = int(time.time())
        async with self._connect() as db:
            await self._configure_connection(db)
            cursor = await db.execute(
                """
                UPDATE analysis_shares
                SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (now, token_hash),
            )
            await db.commit()
            return cursor.rowcount > 0
