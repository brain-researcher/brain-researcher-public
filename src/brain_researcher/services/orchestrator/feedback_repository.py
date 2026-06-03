"""Persistence helpers for UI feedback submissions."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

import logging

from brain_researcher.config.paths import get_data_root

logger = logging.getLogger(__name__)


@dataclass
class FeedbackRecord:
    """Domain object representing a stored feedback submission."""

    id: str
    rating: int
    category: str
    title: str
    description: str
    emoji_rating: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    user_agent: Optional[str]
    url: Optional[str]
    screenshot_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any]


class FeedbackRepository:
    """SQLite-backed repository for feedback submissions and screenshots."""

    def __init__(self, db_path: Optional[os.PathLike[str] | str] = None) -> None:
        configured_dir = os.getenv("FEEDBACK_DATA_DIR")
        base_dir = (
            Path(configured_dir).expanduser()
            if configured_dir
            else get_data_root() / "feedback"
        )
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path or base_dir / "feedback.db")
        self.screenshot_dir = base_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_submissions (
                    id TEXT PRIMARY KEY,
                    rating INTEGER NOT NULL,
                    emoji_rating TEXT,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    user_agent TEXT,
                    url TEXT,
                    screenshot_url TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_screenshots (
                    id TEXT PRIMARY KEY,
                    feedback_id TEXT,
                    file_path TEXT NOT NULL,
                    content_type TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _get_conn(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def save_submission(self, record: FeedbackRecord) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback_submissions (
                    id, rating, emoji_rating, category, title, description,
                    user_id, session_id, user_agent, url, screenshot_url,
                    metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.rating,
                    record.emoji_rating,
                    record.category,
                    record.title,
                    record.description,
                    record.user_id,
                    record.session_id,
                    record.user_agent,
                    record.url,
                    record.screenshot_url,
                    json.dumps(record.metadata or {}),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )

    def list_submissions(
        self,
        *,
        limit: int = 50,
        category: Optional[str] = None,
    ) -> List[FeedbackRecord]:
        query = "SELECT * FROM feedback_submissions"
        params: List[Any] = []
        if category:
            query += " WHERE category = ?"
            params.append(category)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_submission(self, feedback_id: str) -> Optional[FeedbackRecord]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM feedback_submissions WHERE id = ?",
                (feedback_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def save_screenshot(
        self,
        *,
        feedback_id: Optional[str],
        filename: str,
        content: bytes,
        content_type: Optional[str],
    ) -> str:
        timestamp_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        screenshot_id = f"shot_{timestamp_suffix}_{os.urandom(4).hex()}"
        extension = Path(filename).suffix or ".png"
        rel_path = f"{screenshot_id}{extension}"
        dest = self.screenshot_dir / rel_path
        with dest.open("wb") as fp:
            fp.write(content)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback_screenshots (id, feedback_id, file_path, content_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    screenshot_id,
                    feedback_id,
                    rel_path,
                    content_type,
                    datetime.utcnow().isoformat(),
                ),
            )
        return screenshot_id

    def resolve_screenshot(self, screenshot_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM feedback_screenshots WHERE id = ?",
                (screenshot_id,),
            ).fetchone()
        if not row:
            return None
        path = self.screenshot_dir / row["file_path"]
        if not path.exists():
            return None
        return {
            "path": path,
            "content_type": row["content_type"] or "image/png",
        }

    def _row_to_record(self, row: sqlite3.Row) -> FeedbackRecord:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        return FeedbackRecord(
            id=row["id"],
            rating=row["rating"],
            category=row["category"],
            title=row["title"],
            description=row["description"],
            emoji_rating=row["emoji_rating"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            user_agent=row["user_agent"],
            url=row["url"],
            screenshot_url=row["screenshot_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=metadata,
        )


__all__ = ["FeedbackRepository", "FeedbackRecord"]
