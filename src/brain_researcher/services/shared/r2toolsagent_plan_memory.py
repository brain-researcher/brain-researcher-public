"""
Plan Memory Store for Brain Researcher Agent (MVP - Slice 1)

Relocated to ``services.shared`` (round 2 services-layer DAG work) so that lower
layers (e.g. ``services.tools``) can reuse the principle controller without a
back-edge into ``services.agent``. The public symbols remain importable from
``brain_researcher.services.agent.plan_memory`` for backward compatibility.

SQLite-backed storage for execution plans with support for:
- Recording plans and their outcomes
- Keyword-based recall of similar plans
- Hierarchical visibility (user/workspace/global)
- Outcome tracking for learning

MVP Implementation (Slice 1):
- SQLite backend (aligns with existing JobStore pattern)
- Keyword-based similarity (no embeddings)
- Basic hierarchical visibility
- Outcome tracking

Future Slices:
- Slice 2: LRU cache, PII redaction
- Slice 3: Embedding-based similarity, external issue tracker integration
- Slice 4: Metrics endpoints, dashboard integration
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_data_root

logger = logging.getLogger(__name__)


@dataclass
class PlanRecord:
    """Represents a stored execution plan."""

    plan_id: str
    user_id: str
    workspace_id: str | None
    query_text: str
    query_hash: str
    plan_json: str
    step_count: int
    complexity_level: str | None = None
    complexity_reason: str | None = None
    outcome: str = "pending"
    execution_time_ms: int | None = None
    error_message: str | None = None
    markdown_path: str | None = None
    source_plan_id: str | None = None
    tools_used: str | None = None
    shared_level: str = "user"
    created_at: int = field(default_factory=lambda: int(time.time()))
    finished_at: int | None = None
    tracker_provider: str | None = None
    tracker_issue_id: str | None = None
    linear_issue_id: str | None = None  # Deprecated alias for compatibility

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "plan_id": self.plan_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "query_text": self.query_text,
            "query_hash": self.query_hash,
            "plan_json": self.plan_json,
            "step_count": self.step_count,
            "complexity_level": self.complexity_level,
            "complexity_reason": self.complexity_reason,
            "outcome": self.outcome,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "markdown_path": self.markdown_path,
            "source_plan_id": self.source_plan_id,
            "tools_used": self.tools_used,
            "shared_level": self.shared_level,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "tracker_provider": self.tracker_provider,
            "tracker_issue_id": self.tracker_issue_id,
            "linear_issue_id": self.linear_issue_id,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PlanRecord":
        """Create from SQLite row."""
        # Handle tracker/linear fields gracefully across schema versions.
        tracker_provider = None
        tracker_issue_id = None
        linear_issue_id = None
        try:
            tracker_provider = row["tracker_provider"]
        except (KeyError, IndexError):
            pass
        try:
            tracker_issue_id = row["tracker_issue_id"]
        except (KeyError, IndexError):
            pass
        try:
            linear_issue_id = row["linear_issue_id"]
        except (KeyError, IndexError):
            pass

        if not tracker_issue_id and linear_issue_id:
            tracker_issue_id = linear_issue_id
            tracker_provider = tracker_provider or "linear"

        return cls(
            plan_id=row["plan_id"],
            user_id=row["user_id"],
            workspace_id=row["workspace_id"],
            query_text=row["query_text"],
            query_hash=row["query_hash"],
            plan_json=row["plan_json"],
            step_count=row["step_count"],
            complexity_level=row["complexity_level"],
            complexity_reason=row["complexity_reason"],
            outcome=row["outcome"],
            execution_time_ms=row["execution_time_ms"],
            error_message=row["error_message"],
            markdown_path=row["markdown_path"],
            source_plan_id=row["source_plan_id"],
            tools_used=row["tools_used"],
            shared_level=row["shared_level"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            tracker_provider=tracker_provider,
            tracker_issue_id=tracker_issue_id,
            linear_issue_id=linear_issue_id,
        )


@dataclass
class FailureRecord:
    """Represents a stored execution failure."""

    failure_id: str
    plan_id: str
    step_id: str | None
    tool_id: str | None
    error_category: str | None
    recovery_action: str | None
    is_retryable: bool | None
    error_message: str | None
    error_taxonomy: str | None
    recovery_actions: str | None
    attempt: int | None
    max_attempts: int | None
    recovered: bool | None
    created_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "tool_id": self.tool_id,
            "error_category": self.error_category,
            "recovery_action": self.recovery_action,
            "is_retryable": self.is_retryable,
            "error_message": self.error_message,
            "error_taxonomy": self.error_taxonomy,
            "recovery_actions": self.recovery_actions,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "recovered": self.recovered,
            "created_at": self.created_at,
        }


@dataclass
class PrincipleSessionRecord:
    """Represents a persisted cross-run principle controller session."""

    session_key: str
    created_at: int
    updated_at: int
    user_id: str | None
    workspace_id: str | None
    query_text: str
    query_hash: str
    seed_signature: list[str]
    relation_signature: list[str]
    taste_mode: str
    controller_mode: str
    active_principle_id: str | None
    posterior: dict[str, float]
    principles: list[dict[str, Any]]
    anomaly_state: dict[str, Any]
    session_state: dict[str, Any]
    last_run_id: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PrincipleSessionRecord":
        def _loads(raw: Any, default: Any) -> Any:
            if raw in (None, ""):
                return default
            try:
                return json.loads(raw)
            except Exception:
                return default

        return cls(
            session_key=row["session_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            user_id=row["user_id"],
            workspace_id=row["workspace_id"],
            query_text=row["query_text"],
            query_hash=row["query_hash"],
            seed_signature=list(_loads(row["seed_signature"], [])),
            relation_signature=list(_loads(row["relation_signature"], [])),
            taste_mode=row["taste_mode"],
            controller_mode=row["controller_mode"],
            active_principle_id=row["active_principle_id"],
            posterior=dict(_loads(row["posterior_json"], {})),
            principles=list(_loads(row["principles_json"], [])),
            anomaly_state=dict(_loads(row["anomaly_state_json"], {})),
            session_state=dict(_loads(row["session_json"], {})),
            last_run_id=row["last_run_id"],
        )


@dataclass
class PrincipleEventRecord:
    """Represents a persisted principle controller event."""

    event_id: str
    session_key: str
    created_at: int
    event_type: str
    run_id: str | None
    step_id: str | None
    active_principle_id: str | None
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PrincipleEventRecord":
        try:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        except Exception:
            payload = {}
        return cls(
            event_id=row["event_id"],
            session_key=row["session_key"],
            created_at=row["created_at"],
            event_type=row["event_type"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            active_principle_id=row["active_principle_id"],
            payload=dict(payload),
        )


class PlanMemory:
    """
    SQLite-backed plan memory store.

    Features:
    - Record execution plans with metadata
    - Recall similar plans using keyword matching
    - Track outcomes for learning
    - Hierarchical visibility (user/workspace/global)

    MVP Implementation:
    - No embeddings (keyword matching only)
    - No LRU cache (added in Slice 2)
    - Basic PII handling (full redaction in Slice 2)
    """

    # SQLite schema (MVP version)
    SCHEMA = """
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;

    CREATE TABLE IF NOT EXISTS plan_records (
        -- Identity
        plan_id           TEXT PRIMARY KEY,
        created_at        INTEGER NOT NULL,
        finished_at       INTEGER,

        -- Ownership & Scope
        user_id           TEXT NOT NULL,
        workspace_id      TEXT,
        shared_level      TEXT NOT NULL DEFAULT 'user'
                          CHECK(shared_level IN ('user', 'workspace', 'global')),

        -- Query & Intent
        query_text        TEXT NOT NULL,
        query_hash        TEXT NOT NULL,
        complexity_level  TEXT CHECK(complexity_level IN ('simple', 'complex', NULL)),
        complexity_reason TEXT,

        -- Plan Content
        plan_json         TEXT NOT NULL,
        step_count        INTEGER NOT NULL,
        tools_used        TEXT,

        -- Execution Outcome
        outcome           TEXT CHECK(outcome IN ('pending', 'succeeded', 'failed', 'cancelled'))
                          DEFAULT 'pending',
        execution_time_ms INTEGER,
        error_message     TEXT,

        -- Provenance
        source_plan_id    TEXT,
        markdown_path     TEXT,

        -- External tracker integration (Slice 3+)
        tracker_provider  TEXT,
        tracker_issue_id  TEXT,
        linear_issue_id   TEXT, -- deprecated compatibility column

        FOREIGN KEY(source_plan_id) REFERENCES plan_records(plan_id) ON DELETE SET NULL
    );

    -- Indexes for performance
    CREATE INDEX IF NOT EXISTS idx_plan_user_created
        ON plan_records(user_id, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_plan_workspace_shared
        ON plan_records(workspace_id, shared_level, outcome);

    CREATE INDEX IF NOT EXISTS idx_plan_query_hash
        ON plan_records(query_hash);

    CREATE INDEX IF NOT EXISTS idx_plan_outcome_created
        ON plan_records(outcome, created_at DESC);

    -- Failure records for step-level recovery learning
    CREATE TABLE IF NOT EXISTS failure_records (
        failure_id      TEXT PRIMARY KEY,
        plan_id         TEXT NOT NULL,
        created_at      INTEGER NOT NULL,
        step_id         TEXT,
        tool_id         TEXT,
        error_category  TEXT,
        recovery_action TEXT,
        is_retryable    INTEGER,
        error_message   TEXT,
        error_taxonomy  TEXT,
        recovery_actions TEXT,
        attempt         INTEGER,
        max_attempts    INTEGER,
        recovered       INTEGER,
        FOREIGN KEY(plan_id) REFERENCES plan_records(plan_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_failure_plan_created
        ON failure_records(plan_id, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_failure_category
        ON failure_records(error_category, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_failure_tool
        ON failure_records(tool_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS principle_sessions (
        session_key          TEXT PRIMARY KEY,
        created_at           INTEGER NOT NULL,
        updated_at           INTEGER NOT NULL,
        user_id              TEXT,
        workspace_id         TEXT,
        query_text           TEXT NOT NULL,
        query_hash           TEXT NOT NULL,
        seed_signature       TEXT NOT NULL,
        relation_signature   TEXT NOT NULL,
        taste_mode           TEXT NOT NULL,
        controller_mode      TEXT NOT NULL DEFAULT 'principle_v0',
        active_principle_id  TEXT,
        posterior_json       TEXT NOT NULL,
        principles_json      TEXT NOT NULL,
        anomaly_state_json   TEXT NOT NULL,
        session_json         TEXT NOT NULL,
        last_run_id          TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_principle_session_query_hash
        ON principle_sessions(query_hash, updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_principle_session_active
        ON principle_sessions(active_principle_id, updated_at DESC);

    CREATE TABLE IF NOT EXISTS principle_events (
        event_id              TEXT PRIMARY KEY,
        session_key           TEXT NOT NULL,
        created_at            INTEGER NOT NULL,
        run_id                TEXT,
        step_id               TEXT,
        event_type            TEXT NOT NULL,
        active_principle_id   TEXT,
        payload_json          TEXT NOT NULL,
        FOREIGN KEY(session_key) REFERENCES principle_sessions(session_key)
            ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_principle_event_session_created
        ON principle_events(session_key, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_principle_event_type_created
        ON principle_events(event_type, created_at DESC);
    """

    def __init__(self, db_path: str | None = None):
        """
        Initialize the plan memory store.

        Args:
            db_path: Path to SQLite database file (defaults to <repo>/data/plan_memory.db)
        """
        if db_path is None:
            db_path = os.getenv("BR_PLAN_MEMORY_DB") or str(
                get_data_root() / "plan_memory.db"
            )

        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()
        logger.info(f"PlanMemory initialized with database: {self.db_path}")

    def _init_db(self):
        """Initialize the SQLite database with schema and run migrations."""
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

            # Auto-migrate tracker fields for existing databases.
            self._run_migrations(conn)

    def _run_migrations(self, conn: sqlite3.Connection):
        """Run schema migrations for existing databases."""
        cursor = conn.execute("PRAGMA table_info(plan_records)")
        columns = {row[1] for row in cursor}

        if "tracker_provider" not in columns:
            conn.execute("ALTER TABLE plan_records ADD COLUMN tracker_provider TEXT")
            conn.commit()
            logger.info("Migrated plan_records: added tracker_provider column")

        if "tracker_issue_id" not in columns:
            conn.execute("ALTER TABLE plan_records ADD COLUMN tracker_issue_id TEXT")
            conn.commit()
            logger.info("Migrated plan_records: added tracker_issue_id column")

        # Deprecated compatibility column kept for one-release transition.
        if "linear_issue_id" not in columns:
            conn.execute("ALTER TABLE plan_records ADD COLUMN linear_issue_id TEXT")
            conn.commit()
            logger.info("Migrated plan_records: added linear_issue_id column")

        # Backfill generic tracker fields from legacy linear_issue_id values.
        conn.execute(
            """
            UPDATE plan_records
            SET
                tracker_issue_id = COALESCE(tracker_issue_id, linear_issue_id),
                tracker_provider = CASE
                    WHEN tracker_provider IS NULL
                         AND (tracker_issue_id IS NOT NULL OR linear_issue_id IS NOT NULL)
                    THEN 'linear'
                    ELSE tracker_provider
                END
            WHERE linear_issue_id IS NOT NULL
               OR tracker_issue_id IS NOT NULL
            """
        )
        conn.commit()

    def ensure_plan_record(
        self,
        *,
        plan_id: str,
        plan: dict[str, Any] | None = None,
        query: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> bool:
        """Ensure a plan record exists (best-effort placeholder if missing)."""
        if not plan_id:
            return False

        existing = self.get_plan(plan_id)
        if existing:
            return True

        safe_user = user_id or os.getenv("BR_PLAN_MEMORY_DEFAULT_USER", "anonymous")
        safe_workspace = workspace_id or os.getenv("BR_PLAN_MEMORY_DEFAULT_WORKSPACE")

        plan_payload = plan or {"plan_id": plan_id, "steps": []}
        plan_json = json.dumps(plan_payload)

        query_text = (
            query
            or plan_payload.get("query")
            or (plan_payload.get("context") or {}).get("query")
            or "unknown"
        )
        query_hash = self._hash_query(query_text)

        steps = plan_payload.get("steps")
        if not isinstance(steps, list):
            dag = (
                plan_payload.get("dag")
                if isinstance(plan_payload.get("dag"), dict)
                else {}
            )
            steps = dag.get("steps") if isinstance(dag.get("steps"), list) else []

        step_count = len(steps)
        tools_used = list(
            {
                step.get("tool") or step.get("tool_name")
                for step in steps
                if isinstance(step, dict)
            }
        )
        tools_json = json.dumps([t for t in tools_used if t])

        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO plan_records (
                        plan_id, created_at, user_id, workspace_id,
                        query_text, query_hash, plan_json, step_count, tools_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        int(time.time()),
                        safe_user,
                        safe_workspace,
                        query_text,
                        query_hash,
                        plan_json,
                        step_count,
                        tools_json,
                    ),
                )
                conn.commit()
            except Exception as exc:
                logger.debug("Failed to create placeholder plan record: %s", exc)
                return False
        return True

    @contextmanager
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _hash_query(query: str) -> str:
        """Generate MD5 hash for query deduplication."""
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """Extract keywords from text for matching."""
        # Simple keyword extraction (can be enhanced)
        import re

        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        # Filter common stopwords
        stopwords = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "has",
            "have",
            "been",
            "will",
            "with",
            "this",
            "that",
            "from",
            "they",
            "what",
            "which",
            "their",
            "would",
            "there",
            "could",
        }
        return set(words) - stopwords

    def record_plan(
        self,
        plan: dict[str, Any],
        user_id: str,
        workspace_id: str | None = None,
        query: str | None = None,
        complexity_level: str | None = None,
        complexity_reason: str | None = None,
        source_plan_id: str | None = None,
    ) -> str:
        """
        Record a new execution plan.

        Args:
            plan: Plan dictionary with steps
            user_id: User who created the plan
            workspace_id: Optional workspace context
            query: Original query text
            complexity_level: Assessed complexity level
            complexity_reason: Reason for complexity assessment
            source_plan_id: ID of source plan if adapted

        Returns:
            Generated plan_id
        """
        plan_id = plan.get("plan_id") or f"plan_{uuid.uuid4().hex[:12]}"
        query_text = query or plan.get("query", "")
        query_hash = self._hash_query(query_text)

        steps = plan.get("steps", [])
        step_count = len(steps)

        # Extract tools used
        tools_used = list(
            set(step.get("tool_name") or step.get("tool", "unknown") for step in steps)
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO plan_records (
                    plan_id, created_at, user_id, workspace_id,
                    query_text, query_hash, complexity_level, complexity_reason,
                    plan_json, step_count, tools_used, source_plan_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    int(time.time()),
                    user_id,
                    workspace_id,
                    query_text,
                    query_hash,
                    complexity_level,
                    complexity_reason,
                    json.dumps(plan),
                    step_count,
                    json.dumps(tools_used),
                    source_plan_id,
                ),
            )
            conn.commit()

        logger.info(f"Recorded plan {plan_id} with {step_count} steps")
        return plan_id

    def update_outcome(
        self,
        plan_id: str,
        outcome: str,
        execution_time_ms: int | None = None,
        error_message: str | None = None,
        step_results: dict[str, Any] | None = None,
    ):
        """
        Update plan outcome after execution.

        Args:
            plan_id: ID of the plan to update
            outcome: Execution outcome (succeeded/failed/cancelled)
            execution_time_ms: Total execution time in milliseconds
            error_message: Error message if failed
            step_results: Per-step execution results
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE plan_records
                SET outcome = ?,
                    finished_at = ?,
                    execution_time_ms = ?,
                    error_message = ?
                WHERE plan_id = ?
                """,
                (
                    outcome,
                    int(time.time()),
                    execution_time_ms,
                    error_message,
                    plan_id,
                ),
            )
            conn.commit()

        logger.info(f"Updated plan {plan_id} outcome: {outcome}")

    def record_failure(
        self,
        *,
        plan_id: str,
        step_id: str | None = None,
        tool_id: str | None = None,
        error_category: str | None = None,
        recovery_action: str | None = None,
        is_retryable: bool | None = None,
        error_message: str | None = None,
        error_taxonomy: dict[str, Any] | None = None,
        recovery_actions: list[dict[str, Any]] | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
        recovered: bool | None = None,
    ) -> str:
        """Record a step-level failure for recovery learning."""
        failure_id = f"fail_{uuid.uuid4().hex[:12]}"
        taxonomy_json = (
            json.dumps(error_taxonomy) if error_taxonomy is not None else None
        )
        actions_json = (
            json.dumps(recovery_actions) if recovery_actions is not None else None
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO failure_records (
                    failure_id, plan_id, created_at, step_id, tool_id,
                    error_category, recovery_action, is_retryable,
                    error_message, error_taxonomy, recovery_actions,
                    attempt, max_attempts, recovered
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    failure_id,
                    plan_id,
                    int(time.time()),
                    step_id,
                    tool_id,
                    error_category,
                    recovery_action,
                    1 if is_retryable else 0 if is_retryable is not None else None,
                    error_message,
                    taxonomy_json,
                    actions_json,
                    attempt,
                    max_attempts,
                    1 if recovered else 0 if recovered is not None else None,
                ),
            )
            conn.commit()
        return failure_id

    def list_failures(
        self,
        *,
        plan_id: str | None = None,
        tool_id: str | None = None,
        error_category: str | None = None,
        limit: int = 50,
    ) -> list[FailureRecord]:
        """Fetch recent failures with optional filters."""
        filters = []
        params: list[Any] = []
        if plan_id:
            filters.append("plan_id = ?")
            params.append(plan_id)
        if tool_id:
            filters.append("tool_id = ?")
            params.append(tool_id)
        if error_category:
            filters.append("error_category = ?")
            params.append(error_category)

        where_clause = " AND ".join(filters) if filters else "1=1"
        params.append(limit)
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT *
                FROM failure_records
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()
        failures: list[FailureRecord] = []
        for row in rows:
            failures.append(
                FailureRecord(
                    failure_id=row["failure_id"],
                    plan_id=row["plan_id"],
                    created_at=row["created_at"],
                    step_id=row["step_id"],
                    tool_id=row["tool_id"],
                    error_category=row["error_category"],
                    recovery_action=row["recovery_action"],
                    is_retryable=(
                        bool(row["is_retryable"])
                        if row["is_retryable"] is not None
                        else None
                    ),
                    error_message=row["error_message"],
                    error_taxonomy=row["error_taxonomy"],
                    recovery_actions=row["recovery_actions"],
                    attempt=row["attempt"],
                    max_attempts=row["max_attempts"],
                    recovered=(
                        bool(row["recovered"]) if row["recovered"] is not None else None
                    ),
                )
            )
        return failures

    def get_principle_session(self, session_key: str) -> PrincipleSessionRecord | None:
        """Fetch a persisted principle session by stable session key."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM principle_sessions WHERE session_key = ?",
                (session_key,),
            )
            row = cursor.fetchone()
            if row:
                return PrincipleSessionRecord.from_row(row)
        return None

    def upsert_principle_session(
        self,
        *,
        session_key: str,
        query_text: str,
        query_hash: str,
        seed_signature: list[str],
        relation_signature: list[str],
        taste_mode: str,
        controller_mode: str,
        active_principle_id: str | None,
        posterior: dict[str, float],
        principles: list[dict[str, Any]],
        anomaly_state: dict[str, Any],
        session_state: dict[str, Any],
        user_id: str | None = None,
        workspace_id: str | None = None,
        last_run_id: str | None = None,
    ) -> None:
        """Persist or update a cross-run principle session snapshot."""
        now = int(time.time())
        user_norm = user_id or os.getenv("BR_PLAN_MEMORY_DEFAULT_USER", "anonymous")
        workspace_norm = workspace_id or os.getenv("BR_PLAN_MEMORY_DEFAULT_WORKSPACE")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO principle_sessions (
                    session_key, created_at, updated_at, user_id, workspace_id,
                    query_text, query_hash, seed_signature, relation_signature,
                    taste_mode, controller_mode, active_principle_id,
                    posterior_json, principles_json, anomaly_state_json, session_json,
                    last_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    user_id = excluded.user_id,
                    workspace_id = excluded.workspace_id,
                    query_text = excluded.query_text,
                    query_hash = excluded.query_hash,
                    seed_signature = excluded.seed_signature,
                    relation_signature = excluded.relation_signature,
                    taste_mode = excluded.taste_mode,
                    controller_mode = excluded.controller_mode,
                    active_principle_id = excluded.active_principle_id,
                    posterior_json = excluded.posterior_json,
                    principles_json = excluded.principles_json,
                    anomaly_state_json = excluded.anomaly_state_json,
                    session_json = excluded.session_json,
                    last_run_id = excluded.last_run_id
                """,
                (
                    session_key,
                    now,
                    now,
                    user_norm,
                    workspace_norm,
                    query_text,
                    query_hash,
                    json.dumps(seed_signature, sort_keys=True),
                    json.dumps(relation_signature, sort_keys=True),
                    taste_mode,
                    controller_mode,
                    active_principle_id,
                    json.dumps(posterior, sort_keys=True),
                    json.dumps(principles, sort_keys=True),
                    json.dumps(anomaly_state, sort_keys=True),
                    json.dumps(session_state, sort_keys=True),
                    last_run_id,
                ),
            )
            conn.commit()

    def append_principle_event(
        self,
        *,
        session_key: str,
        event_type: str,
        payload: dict[str, Any],
        run_id: str | None = None,
        step_id: str | None = None,
        active_principle_id: str | None = None,
    ) -> str:
        """Append a principle controller event for audit/debugging."""
        event_id = f"pev_{uuid.uuid4().hex[:12]}"
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO principle_events (
                    event_id, session_key, created_at, run_id, step_id,
                    event_type, active_principle_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_key,
                    int(time.time()),
                    run_id,
                    step_id,
                    event_type,
                    active_principle_id,
                    json.dumps(payload, sort_keys=True),
                ),
            )
            conn.commit()
        return event_id

    def list_principle_events(
        self, session_key: str, *, limit: int = 50
    ) -> list[PrincipleEventRecord]:
        """Fetch recent principle controller events for a session."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT *
                FROM principle_events
                WHERE session_key = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_key, limit),
            )
            rows = cursor.fetchall()
        return [PrincipleEventRecord.from_row(row) for row in rows]

    def update_markdown_path(self, plan_id: str, markdown_path: str):
        """Update the markdown log path for a plan."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE plan_records SET markdown_path = ? WHERE plan_id = ?",
                (markdown_path, plan_id),
            )
            conn.commit()

    def update_tracker_issue(self, plan_id: str, provider: str, issue_id: str):
        """Persist provider issue mapping for a plan."""
        provider_norm = (provider or "").strip().lower() or "unknown"

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE plan_records
                SET tracker_provider = ?, tracker_issue_id = ?
                WHERE plan_id = ?
                """,
                (provider_norm, issue_id, plan_id),
            )
            if provider_norm == "linear":
                conn.execute(
                    "UPDATE plan_records SET linear_issue_id = ? WHERE plan_id = ?",
                    (issue_id, plan_id),
                )
            conn.commit()
        logger.debug(
            "Updated plan %s with tracker issue %s/%s",
            plan_id,
            provider_norm,
            issue_id,
        )

    def get_tracker_issue(self, plan_id: str) -> dict[str, str] | None:
        """Get provider issue mapping for a plan."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT tracker_provider, tracker_issue_id, linear_issue_id
                FROM plan_records
                WHERE plan_id = ?
                """,
                (plan_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            issue_id = row["tracker_issue_id"] or row["linear_issue_id"]
            if not issue_id:
                return None

            provider = row["tracker_provider"] or (
                "linear" if row["linear_issue_id"] else "unknown"
            )
            return {"provider": provider, "issue_id": issue_id}

    def update_linear_issue_id(self, plan_id: str, issue_id: str):
        """Deprecated compatibility wrapper."""
        self.update_tracker_issue(plan_id=plan_id, provider="linear", issue_id=issue_id)

    def get_linear_issue_id(self, plan_id: str) -> str | None:
        """Deprecated compatibility wrapper."""
        tracker_ref = self.get_tracker_issue(plan_id)
        if not tracker_ref:
            return None
        if tracker_ref.get("provider") != "linear":
            return None
        return tracker_ref.get("issue_id")

    def recall_similar(
        self,
        query: str,
        user_id: str,
        workspace_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Recall similar successful plans using keyword matching.

        MVP Implementation: Uses keyword overlap for similarity.
        Slice 3 will add embedding-based similarity.

        Args:
            query: Query to find similar plans for
            user_id: Current user ID
            workspace_id: Optional workspace context
            top_k: Maximum number of plans to return

        Returns:
            List of similar plan records with similarity scores
        """
        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            return []

        # Build visibility filter (hierarchical)
        visibility_params = [user_id]
        visibility_sql = "(user_id = ?"

        if workspace_id:
            visibility_sql += (
                " OR (workspace_id = ? AND shared_level IN ('workspace', 'global'))"
            )
            visibility_params.append(workspace_id)

        visibility_sql += " OR shared_level = 'global')"

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT plan_id, query_text, plan_json, outcome, execution_time_ms,
                       step_count, source_plan_id, tools_used, complexity_level
                FROM plan_records
                WHERE {visibility_sql}
                  AND outcome = 'succeeded'
                ORDER BY created_at DESC
                LIMIT 100
                """,
                visibility_params,
            )

            # Calculate keyword similarity scores
            results = []
            for row in cursor:
                plan_keywords = self._extract_keywords(row["query_text"])
                if not plan_keywords:
                    continue

                # Jaccard similarity
                intersection = len(query_keywords & plan_keywords)
                union = len(query_keywords | plan_keywords)
                similarity = intersection / union if union > 0 else 0

                if similarity > 0.2:  # Minimum threshold
                    # Get primary tool from tools_used
                    tools = json.loads(row["tools_used"]) if row["tools_used"] else []
                    primary_tool = tools[0] if tools else None

                    results.append(
                        {
                            "plan_id": row["plan_id"],
                            "query_text": row["query_text"],
                            "plan_json": row["plan_json"],
                            "similarity": similarity,
                            "execution_time_ms": row["execution_time_ms"],
                            "step_count": row["step_count"],
                            "primary_tool": primary_tool,
                            "complexity_level": row["complexity_level"],
                        }
                    )

            # Sort by similarity descending
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:top_k]

    def get_plan(self, plan_id: str) -> PlanRecord | None:
        """Get a specific plan by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM plan_records WHERE plan_id = ?", (plan_id,)
            )
            row = cursor.fetchone()
            if row:
                return PlanRecord.from_row(row)
        return None

    def share_plan(self, plan_id: str, user_id: str, level: str = "workspace") -> bool:
        """
        Share a plan to workspace or global scope.

        Args:
            plan_id: ID of the plan to share
            user_id: User attempting to share (must be owner)
            level: Sharing level ('workspace' or 'global')

        Returns:
            True if sharing succeeded
        """
        if level not in ("workspace", "global"):
            raise ValueError(f"Invalid sharing level: {level}")

        with self._get_connection() as conn:
            # Check ownership
            cursor = conn.execute(
                "SELECT user_id FROM plan_records WHERE plan_id = ?", (plan_id,)
            )
            row = cursor.fetchone()
            if not row or row["user_id"] != user_id:
                logger.warning(f"User {user_id} cannot share plan {plan_id}: not owner")
                return False

            conn.execute(
                "UPDATE plan_records SET shared_level = ? WHERE plan_id = ?",
                (level, plan_id),
            )
            conn.commit()

        logger.info(f"Plan {plan_id} shared at level: {level}")
        return True

    def get_stats(
        self, user_id: str | None = None, workspace_id: str | None = None, days: int = 7
    ) -> dict[str, Any]:
        """
        Get plan memory statistics for observability.

        Args:
            user_id: Filter by user
            workspace_id: Filter by workspace
            days: Number of days to look back

        Returns:
            Statistics dictionary
        """
        cutoff = int(time.time()) - (days * 24 * 60 * 60)

        with self._get_connection() as conn:
            # Build filter
            filters = ["created_at >= ?"]
            params = [cutoff]

            if user_id:
                filters.append("user_id = ?")
                params.append(user_id)

            if workspace_id:
                filters.append("workspace_id = ?")
                params.append(workspace_id)

            where_clause = " AND ".join(filters)

            # Total plans
            total = conn.execute(
                f"SELECT COUNT(*) as count FROM plan_records WHERE {where_clause}",
                params,
            ).fetchone()["count"]

            # Success rate
            succeeded = conn.execute(
                f"SELECT COUNT(*) as count FROM plan_records WHERE {where_clause} AND outcome = 'succeeded'",
                params,
            ).fetchone()["count"]

            failed = conn.execute(
                f"SELECT COUNT(*) as count FROM plan_records WHERE {where_clause} AND outcome = 'failed'",
                params,
            ).fetchone()["count"]

            # Average execution time
            avg_time = conn.execute(
                f"SELECT AVG(execution_time_ms) as avg_ms FROM plan_records WHERE {where_clause} AND execution_time_ms IS NOT NULL",
                params,
            ).fetchone()["avg_ms"]

            # Complexity distribution
            simple_count = conn.execute(
                f"SELECT COUNT(*) as count FROM plan_records WHERE {where_clause} AND complexity_level = 'simple'",
                params,
            ).fetchone()["count"]

            complex_count = conn.execute(
                f"SELECT COUNT(*) as count FROM plan_records WHERE {where_clause} AND complexity_level = 'complex'",
                params,
            ).fetchone()["count"]

        success_rate = succeeded / total if total > 0 else 0

        return {
            "total_plans": total,
            "success_rate": round(success_rate, 3),
            "succeeded": succeeded,
            "failed": failed,
            "avg_execution_time_ms": int(avg_time) if avg_time else None,
            "complexity_distribution": {
                "simple": simple_count,
                "complex": complex_count,
            },
            "period_days": days,
        }


def create_plan_memory(db_path: str | None = None) -> PlanMemory:
    """
    Factory function to create a PlanMemory instance.

    Args:
        db_path: Optional database path

    Returns:
        Configured PlanMemory instance
    """
    return PlanMemory(db_path=db_path)
