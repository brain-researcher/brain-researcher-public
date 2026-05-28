"""Benchmark Board API endpoints — task browsing, governance, import.

Router prefix: /api/benchmarks
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from brain_researcher.config.paths import get_data_root

from ..benchmark_importer import fetch_tasks_from_url, import_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

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
    schema_path = Path(__file__).resolve().parents[1] / "sqlite_schema" / "schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    _ensure_governance_columns(conn)


def _ensure_governance_columns(conn: sqlite3.Connection) -> None:
    """Best-effort additive migration for governance fields on existing DBs."""
    columns = conn.execute("PRAGMA table_info(benchmark_task_governance)").fetchall()
    existing: set[str] = {
        str(row["name"]) if isinstance(row, sqlite3.Row) else str(row[1]) for row in columns
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


TaskGovernanceStatus = Literal[
    "imported",
    "triaged",
    "validated",
    "active",
    "deprecated",
    "archived",
]
ValidationType = Literal[
    "manual_review",
    "ci_tests",
    "oracle_solution",
    "security_audit",
    "llm_judge",
]
ValidationResult = Literal["pass", "fail", "needs_fix"]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ImportRequest(BaseModel):
    url: str
    dataset_id: str | None = None
    version: str = "1.0"
    overwrite_governance: bool = False


class ImportResponse(BaseModel):
    dataset_id: str
    job_id: int
    status: str
    summary: dict[str, Any]


class GovernanceUpdate(BaseModel):
    status: TaskGovernanceStatus | None = None
    category: str | None = None
    notes: str | None = None
    owner: str | None = None
    created_by_name: str | None = None
    created_by_email: str | None = None
    created_by_profile: str | None = None


class ValidationCreate(BaseModel):
    validator: str
    type: ValidationType
    result: ValidationResult
    evidence_url: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/import", response_model=ImportResponse)
async def import_benchmark(req: ImportRequest):
    """Import tasks from a registry URL."""
    now = int(time.time())
    dataset_id = req.dataset_id or req.url.rstrip("/").split("/")[-1].replace(".json", "")

    conn = _get_conn()
    _ensure_tables(conn)

    # Record import job
    cur = conn.execute(
        """
        INSERT INTO benchmark_import_jobs
            (dataset_id, version, source_url, started_at, status)
        VALUES (?, ?, ?, ?, 'running')
        """,
        (dataset_id, req.version, req.url, now),
    )
    job_id = cur.lastrowid
    conn.commit()

    try:
        raw_tasks = await fetch_tasks_from_url(req.url)
        summary = import_tasks(
            conn,
            dataset_id,
            req.version,
            raw_tasks,
            source_url=req.url,
            overwrite_governance=req.overwrite_governance,
        )
        final_status = "succeeded" if summary.failed == 0 else "partial"
        conn.execute(
            """
            UPDATE benchmark_import_jobs SET
                finished_at = ?, status = ?, summary_json = ?
            WHERE id = ?
            """,
            (int(time.time()), final_status, json.dumps(summary.to_dict()), job_id),
        )
        conn.commit()
        return ImportResponse(
            dataset_id=dataset_id,
            job_id=job_id,
            status=final_status,
            summary=summary.to_dict(),
        )
    except Exception as exc:
        status_code = 400 if isinstance(exc, ValueError) else 502
        conn.execute(
            """
            UPDATE benchmark_import_jobs SET
                finished_at = ?, status = 'failed', summary_json = ?
            WHERE id = ?
            """,
            (int(time.time()), json.dumps({"error": str(exc)}), job_id),
        )
        conn.commit()
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        raise HTTPException(status_code=status_code, detail=f"Import failed: {exc}") from exc
    finally:
        conn.close()


@router.get("/datasets")
async def list_datasets(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List benchmark datasets."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        query = "SELECT * FROM benchmark_datasets WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) FROM benchmark_datasets" + (" WHERE status = ?" if status else ""),
            [status] if status else [],
        ).fetchone()[0]

        return {
            "datasets": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        conn.close()


@router.get("/datasets/{dataset_id}/tasks")
async def list_tasks(
    dataset_id: str,
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    difficulty: str | None = None,
    created_by: str | None = None,
    sort: str = Query("updated_at", pattern="^(task_id|source_category|source_difficulty|created_at|updated_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List tasks in a dataset with filters."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        query = """
            SELECT t.*, g.status AS gov_status, g.category AS gov_category, g.owner,
                   g.created_by_name AS gov_created_by_name
            FROM benchmark_tasks t
            LEFT JOIN benchmark_task_governance g
                ON t.dataset_id = g.dataset_id AND t.task_id = g.task_id
        """
        where_clauses = ["t.dataset_id = ?"]
        params: list[Any] = [dataset_id]

        if q:
            where_clauses.append("(t.task_id LIKE ? OR t.task_spec_json LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if status:
            where_clauses.append("g.status = ?")
            params.append(status)
        if category:
            where_clauses.append("(g.category = ? OR t.source_category = ?)")
            params.extend([category, category])
        if tag:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM benchmark_task_tags tt "
                "WHERE tt.dataset_id = t.dataset_id AND tt.task_id = t.task_id AND tt.tag = ?)"
            )
            params.append(tag)
        if difficulty:
            where_clauses.append("t.source_difficulty = ?")
            params.append(difficulty)
        if created_by:
            where_clauses.append(
                "COALESCE(g.created_by_name, t.source_created_by_name, '') LIKE ?"
            )
            params.append(f"%{created_by}%")

        query += " WHERE " + " AND ".join(where_clauses)
        query += f" ORDER BY t.{sort} {'DESC' if order == 'desc' else 'ASC'}"
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        # Get tags for each task
        tasks = []
        for row in rows:
            task = dict(row)
            tag_rows = conn.execute(
                "SELECT tag FROM benchmark_task_tags WHERE dataset_id = ? AND task_id = ?",
                (dataset_id, task["task_id"]),
            ).fetchall()
            task["tags"] = [r["tag"] for r in tag_rows]
            tasks.append(task)

        # Total count
        count_query = """
            SELECT COUNT(*) FROM benchmark_tasks t
            LEFT JOIN benchmark_task_governance g
                ON t.dataset_id = g.dataset_id AND t.task_id = g.task_id
            WHERE """ + " AND ".join(where_clauses)
        total = conn.execute(count_query, params[: -2]).fetchone()[0]

        return {"tasks": tasks, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


@router.get("/tasks/{dataset_id}/{task_id}")
async def get_task_detail(dataset_id: str, task_id: str):
    """Full task detail including governance, validations, and tags."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        task = conn.execute(
            "SELECT * FROM benchmark_tasks WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        governance = conn.execute(
            "SELECT * FROM benchmark_task_governance WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchone()

        validations = conn.execute(
            "SELECT * FROM benchmark_task_validations WHERE dataset_id = ? AND task_id = ? ORDER BY validated_at DESC",
            (dataset_id, task_id),
        ).fetchall()

        tags = conn.execute(
            "SELECT tag FROM benchmark_task_tags WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchall()

        dataset = conn.execute(
            "SELECT * FROM benchmark_datasets WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()

        result = dict(task)
        result["task_spec"] = json.loads(result.pop("task_spec_json", "{}"))
        result["governance"] = dict(governance) if governance else None
        result["validations"] = [dict(v) for v in validations]
        result["tags"] = [r["tag"] for r in tags]
        result["dataset"] = dict(dataset) if dataset else None

        return result
    finally:
        conn.close()


@router.patch("/tasks/{dataset_id}/{task_id}/governance")
async def update_governance(dataset_id: str, task_id: str, body: GovernanceUpdate):
    """Update governance fields for a task."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        task = conn.execute(
            "SELECT source_created_by_name FROM benchmark_tasks WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        now = int(time.time())
        # Ensure governance row exists
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark_task_governance
                (dataset_id, task_id, status, created_by_name, updated_at)
            VALUES (?, ?, 'imported', ?, ?)
            """,
            (dataset_id, task_id, task["source_created_by_name"], now),
        )
        updates: list[str] = []
        params: list[Any] = []
        if body.status is not None:
            updates.append("status = ?")
            params.append(body.status)
        if body.category is not None:
            updates.append("category = ?")
            params.append(body.category)
        if body.notes is not None:
            updates.append("notes = ?")
            params.append(body.notes)
        if body.owner is not None:
            updates.append("owner = ?")
            params.append(body.owner)
        if body.created_by_name is not None:
            updates.append("created_by_name = ?")
            params.append(body.created_by_name)
        if body.created_by_email is not None:
            updates.append("created_by_email = ?")
            params.append(body.created_by_email)
        if body.created_by_profile is not None:
            updates.append("created_by_profile = ?")
            params.append(body.created_by_profile)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        updates.append("updated_at = ?")
        params.append(now)
        params.extend([dataset_id, task_id])
        conn.execute(
            f"UPDATE benchmark_task_governance SET {', '.join(updates)} WHERE dataset_id = ? AND task_id = ?",
            params,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM benchmark_task_governance WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchone()
        return dict(row) if row else {"ok": True}
    finally:
        conn.close()


@router.post("/tasks/{dataset_id}/{task_id}/validations")
async def add_validation(dataset_id: str, task_id: str, body: ValidationCreate):
    """Add a validation record to a task."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        now = int(time.time())
        # Verify task exists
        task = conn.execute(
            "SELECT 1 FROM benchmark_tasks WHERE dataset_id = ? AND task_id = ?",
            (dataset_id, task_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        cur = conn.execute(
            """
            INSERT INTO benchmark_task_validations
                (dataset_id, task_id, validator, type, result, evidence_url, notes, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dataset_id, task_id, body.validator, body.type, body.result, body.evidence_url, body.notes, now),
        )
        conn.commit()
        return {"id": cur.lastrowid, "validated_at": now}
    finally:
        conn.close()


@router.get("/taxonomy")
async def get_taxonomy():
    """Aggregate distinct statuses, categories, tags, and difficulties."""
    conn = _get_conn()
    _ensure_tables(conn)
    try:
        statuses = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT status FROM benchmark_task_governance ORDER BY status"
            ).fetchall()
        ]
        categories = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT category FROM benchmark_task_governance WHERE category IS NOT NULL ORDER BY category"
            ).fetchall()
        ]
        tags = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT tag FROM benchmark_task_tags ORDER BY tag"
            ).fetchall()
        ]
        difficulties = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT source_difficulty FROM benchmark_tasks WHERE source_difficulty IS NOT NULL ORDER BY source_difficulty"
            ).fetchall()
        ]
        return {
            "statuses": statuses,
            "categories": categories,
            "tags": tags,
            "difficulties": difficulties,
        }
    finally:
        conn.close()
