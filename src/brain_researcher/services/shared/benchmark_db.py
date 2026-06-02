"""Shared SQLite helpers for the benchmark board."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from brain_researcher.config.paths import get_data_root

_DB_PATH: Path | None = None


def _resolve_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH
    _DB_PATH = Path(
        os.getenv("BR_BENCHMARK_DB_PATH")
        or os.getenv("BR_QUEUE_DB_PATH")
        or os.getenv("BR_QUEUE_DB")
        or str(get_data_root() / "orchestrator" / "jobs.sqlite")
    )
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_resolve_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create benchmark tables if they don't already exist."""

    schema_path = (
        Path(__file__).resolve().parents[1]
        / "orchestrator"
        / "sqlite_schema"
        / "schema.sql"
    )
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    _ensure_governance_columns(conn)


def _ensure_governance_columns(conn: sqlite3.Connection) -> None:
    """Best-effort additive migration for governance fields on existing DBs."""

    columns = conn.execute("PRAGMA table_info(benchmark_task_governance)").fetchall()
    existing: set[str] = {
        str(row["name"]) if isinstance(row, sqlite3.Row) else str(row[1])
        for row in columns
    }
    required = {
        "created_by_name": "created_by_name TEXT",
        "created_by_email": "created_by_email TEXT",
        "created_by_profile": "created_by_profile TEXT",
    }
    for name, definition in required.items():
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE benchmark_task_governance ADD COLUMN {definition}")
    conn.commit()
