"""Neo4j-backed failure writer for optional KG write-through."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

from neo4j import GraphDatabase

from brain_researcher.core.contracts.loop_signals import (
    LoopSignalBaseV1,
    parse_loop_signals,
)
from brain_researcher.services.agent.monitoring import metrics_collector
from brain_researcher.services.agent.planner.kg_bridge import (
    resolve_tool_key,
    resolve_version_key,
)
from brain_researcher.services.agent.planner.loop_signal_neo4j import (
    get_default_loop_signal_writer,
)

logger = logging.getLogger(__name__)


def _truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def is_failure_writeback_enabled() -> bool:
    return _truthy_env(os.environ.get("BR_KG_FAILURE_WRITEBACK"))


def is_failure_agg_writeback_enabled() -> bool:
    """Feature flag for FAILED_ON aggregate writeback."""
    return _truthy_env(os.environ.get("BR_KG_FAILURE_AGG_WRITEBACK"))


def _truncate(text: str | None, limit: int = 1000) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit]


@dataclass(frozen=True)
class FailureKGRecord:
    failure_id: str
    plan_id: str
    step_id: str | None = None
    tool_id: str | None = None
    tool_version_id: str | None = None
    error_category: str | None = None
    recovery_action: str | None = None
    is_retryable: bool | None = None
    error_message: str | None = None
    error_taxonomy: dict[str, Any] | None = None
    recovery_actions: list[dict[str, Any]] | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    recovered: bool | None = None
    created_at: int | None = None
    message_hash: str | None = None
    dataset_id: str | None = None
    task_family: str | None = None
    run_id: str | None = None
    loop_signals: tuple[LoopSignalBaseV1, ...] = ()

    def to_row(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "tool_id": self.tool_id,
            "tool_version_id": self.tool_version_id,
            "error_category": self.error_category,
            "recovery_action": self.recovery_action,
            "is_retryable": self.is_retryable,
            "error_message": _truncate(self.error_message),
            "error_taxonomy": (
                json.dumps(self.error_taxonomy) if self.error_taxonomy else None
            ),
            "recovery_actions": (
                json.dumps(self.recovery_actions) if self.recovery_actions else None
            ),
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "recovered": self.recovered,
            "created_at": self.created_at,
            "message_hash": self.message_hash,
            "dataset_id": self.dataset_id,
            "task_family": self.task_family,
            "run_id": self.run_id,
            "ingested_at": int(time.time() * 1000),
        }


class Neo4jFailureWriter:
    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str | None = None,
    ) -> None:
        timeout_sec = float(os.getenv("BR_NEO4J_TIMEOUT_SEC", "2") or "2")
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=max(0.5, min(timeout_sec, 30.0)),
        )
        self._database = database

    def write(self, records: Sequence[FailureKGRecord]) -> None:
        rows = []
        loop_signals = []
        loop_signal_sample = None
        for r in records:
            if not r.failure_id or not r.plan_id:
                continue
            if r.loop_signals:
                loop_signals.extend(parse_loop_signals(list(r.loop_signals)))
                if loop_signal_sample is None:
                    loop_signal_sample = r
            row = r.to_row()
            row["tool_id"] = resolve_tool_key(row.get("tool_id")) or row.get("tool_id")
            row["tool_version_id"] = resolve_version_key(
                row.get("tool_version_id")
            ) or row.get("tool_version_id")
            rows.append(row)
        if not rows:
            return

        failure_ids = [r.get("failure_id") for r in rows if r.get("failure_id")]
        dedupe_hits = max(0, len(rows) - len(set(failure_ids)))
        failure_dedupe_rate = (dedupe_hits / len(rows)) if rows else 0.0
        t0 = time.time()

        query = """
        UNWIND $rows AS r
        MERGE (f:ExecutionFailure {failure_id: r.failure_id})
        ON CREATE SET f.created_at = coalesce(r.created_at, timestamp())
        SET
            f.updated_at = timestamp(),
            f.plan_id = r.plan_id,
            f.step_id = r.step_id,
            f.tool_id = r.tool_id,
            f.tool_version_id = r.tool_version_id,
            f.error_category = r.error_category,
            f.recovery_action = r.recovery_action,
            f.is_retryable = r.is_retryable,
            f.error_message = r.error_message,
            f.error_taxonomy = r.error_taxonomy,
            f.recovery_actions = r.recovery_actions,
            f.attempt = r.attempt,
            f.max_attempts = r.max_attempts,
            f.recovered = r.recovered,
            f.dataset_id = r.dataset_id,
            f.task_family = r.task_family,
            f.run_id = r.run_id,
            f.message_hash = r.message_hash
        WITH f, r
        CALL {
          WITH r
          OPTIONAL MATCH (t1:Tool {tool_id: r.tool_id})
          RETURN t1 LIMIT 1
        }
        WITH f, r, t1
        CALL {
          WITH r, t1
          OPTIONAL MATCH (t2:Tool {id: r.tool_id})
          RETURN t2 LIMIT 1
        }
        WITH f, r, coalesce(t1, t2) AS t
        FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
          MERGE (t)-[:HAD_FAILURE]->(f)
        )
        CALL {
          WITH r
          OPTIONAL MATCH (tv:ToolVersion {version_id: r.tool_version_id})
          RETURN tv LIMIT 1
        }
        WITH f, r, t, tv
        FOREACH (_ IN CASE WHEN tv IS NULL THEN [] ELSE [1] END |
          MERGE (tv)-[:HAD_FAILURE_VERSION]->(f)
        )
        CALL {
          WITH r
          OPTIONAL MATCH (d1:Dataset {id: r.dataset_id})
          RETURN d1 LIMIT 1
        }
        WITH f, r, t, tv, coalesce(d1, null) AS d1
        CALL {
          WITH r, d1
          OPTIONAL MATCH (d2:Dataset {dataset_id: r.dataset_id})
          RETURN d2 LIMIT 1
        }
        WITH f, r, t, tv, coalesce(d1, d2) AS d
        FOREACH (_ IN CASE WHEN $enable_failed_on AND d IS NOT NULL AND t IS NOT NULL THEN [1] ELSE [] END |
          MERGE (t)-[fo:FAILED_ON {task_family: coalesce(r.task_family, \"unknown\"), error_category: r.error_category}]->(d)
          SET fo.fail_count = coalesce(fo.fail_count, 0) + 1,
              fo.last_seen = timestamp(),
              fo.last_run_id = coalesce(r.run_id, r.plan_id)
        )
        WITH f, r, t, tv, d
        MERGE (run:Run {id: coalesce(r.run_id, r.plan_id)})
        MERGE (run)-[:HAD_FAILURE]->(f)
        FOREACH (_ IN CASE WHEN r.plan_id IS NULL THEN [] ELSE [1] END |
          MERGE (p:Plan {id: r.plan_id})
          SET p.updated_at = timestamp()
          MERGE (p)-[:HAS_RUN]->(run)
        )
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(
                    query,
                    rows=rows,
                    enable_failed_on=is_failure_agg_writeback_enabled(),
                ).consume()
            lag_ms = (time.time() - t0) * 1000
            metrics_collector.increment("kg_failure_writes_total", len(rows))
            metrics_collector.record("kg_failure_write_lag_ms", lag_ms)
            metrics_collector.record("kg_failure_dedupe_hit_rate", failure_dedupe_rate)
            metrics_collector.increment(
                "kg_writeback_success_total",
                labels={"type": "failure"},
            )
            if dedupe_hits > 0:
                metrics_collector.increment("kg_failure_dedupe_hits_total", dedupe_hits)
            logger.debug("failure writeback ok rows=%d lag_ms=%.1f", len(rows), lag_ms)
        except Exception as exc:  # pragma: no cover - best-effort
            metrics_collector.increment("kg_failure_write_errors_total", len(rows))
            metrics_collector.increment(
                "kg_writeback_fail_total",
                labels={"type": "failure"},
            )
            logger.warning("Neo4j failure write failed rows=%d err=%s", len(rows), exc)
            return

        if loop_signals:
            try:
                loop_writer = get_default_loop_signal_writer()
                if loop_writer and loop_signal_sample is not None:
                    loop_writer.write(
                        loop_signals,
                        run_id=loop_signal_sample.run_id,
                        plan_id=loop_signal_sample.plan_id,
                        dataset_id=loop_signal_sample.dataset_id,
                        task_family=loop_signal_sample.task_family,
                    )
            except Exception as exc:  # pragma: no cover - best-effort
                logger.debug("Loop signal writeback skipped for failure rows: %s", exc)


@lru_cache(maxsize=1)
def get_default_failure_writer() -> Neo4jFailureWriter | None:
    uri = os.getenv("NEO4J_URI", "").strip() or "bolt://localhost:7687"
    user = os.getenv("NEO4J_USER", "").strip() or "neo4j"
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        return None

    database = os.getenv("NEO4J_DATABASE")
    try:
        return Neo4jFailureWriter(
            uri=uri,
            user=user,
            password=password,
            database=database,
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Unable to initialize Neo4j failure writer: %s", exc)
        return None


__all__ = [
    "FailureKGRecord",
    "Neo4jFailureWriter",
    "get_default_failure_writer",
    "is_failure_writeback_enabled",
    "is_failure_agg_writeback_enabled",
]
