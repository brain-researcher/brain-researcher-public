"""Neo4j writeback for typed cross-stage loop signals."""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from typing import Sequence

from neo4j import GraphDatabase

from brain_researcher.core.contracts.loop_signals import LoopSignalBaseV1, parse_loop_signals

logger = logging.getLogger(__name__)

SIGNAL_TYPES = (
    "condition_tag",
    "sensitivity_finding",
    "design_constraint",
    "hypothesis_delta",
    "user_feedback",
)

_SIGNAL_FLAG_ENV = {
    "condition_tag": "BR_LOOP_SIGNAL_WRITEBACK_CONDITION_TAG",
    "sensitivity_finding": "BR_LOOP_SIGNAL_WRITEBACK_SENSITIVITY_FINDING",
    "design_constraint": "BR_LOOP_SIGNAL_WRITEBACK_DESIGN_CONSTRAINT",
    "hypothesis_delta": "BR_LOOP_SIGNAL_WRITEBACK_HYPOTHESIS_DELTA",
    "user_feedback": "BR_LOOP_SIGNAL_WRITEBACK_USER_FEEDBACK",
}


def _truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def enabled_signal_types() -> set[str]:
    """Return enabled loop signal types based on feature flags."""
    if _truthy_env(os.getenv("BR_LOOP_SIGNAL_WRITEBACK_ALL")) or _truthy_env(
        os.getenv("BR_LOOP_SIGNAL_WRITEBACK")
    ):
        return set(SIGNAL_TYPES)

    enabled: set[str] = set()
    for signal_type, env_name in _SIGNAL_FLAG_ENV.items():
        if _truthy_env(os.getenv(env_name)):
            enabled.add(signal_type)
    return enabled


def is_loop_signal_writeback_enabled(signal_type: str) -> bool:
    return signal_type in enabled_signal_types()


def _select_payload(signal: LoopSignalBaseV1) -> dict[str, object]:
    payload = signal.model_dump(mode="json", exclude_none=True)
    for key in (
        "schema_version",
        "signal_id",
        "signal_type",
        "stage",
        "run_id",
        "plan_id",
        "confidence",
        "created_at",
        "provenance",
    ):
        payload.pop(key, None)
    return payload


class Neo4jLoopSignalWriter:
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

    def write(
        self,
        signals: Sequence[LoopSignalBaseV1 | dict[str, object]],
        *,
        run_id: str | None = None,
        plan_id: str | None = None,
        dataset_id: str | None = None,
        task_family: str | None = None,
    ) -> int:
        parsed = parse_loop_signals(list(signals or []))
        enabled = enabled_signal_types()
        rows: list[dict[str, object]] = []
        for signal in parsed:
            if signal.signal_type not in enabled:
                continue
            row = {
                "signal_id": signal.signal_id,
                "signal_type": signal.signal_type,
                "schema_version": signal.schema_version,
                "stage": signal.stage,
                "confidence": signal.confidence,
                "created_at": signal.created_at,
                "provenance_json": json.dumps(signal.provenance or {}, ensure_ascii=False),
                "payload_json": json.dumps(_select_payload(signal), ensure_ascii=False),
                "run_id": signal.run_id or run_id,
                "plan_id": signal.plan_id or plan_id,
                "dataset_id": dataset_id,
                "task_family": task_family,
            }
            rows.append(row)

        if not rows:
            return 0

        query = """
        UNWIND $rows AS r
        MERGE (ls:LoopSignal {signal_id: r.signal_id})
        ON CREATE SET ls.created_at = timestamp()
        SET
            ls.updated_at = timestamp(),
            ls.schema_version = r.schema_version,
            ls.signal_type = r.signal_type,
            ls.stage = r.stage,
            ls.confidence = r.confidence,
            ls.created_at_iso = r.created_at,
            ls.provenance_json = r.provenance_json,
            ls.payload_json = r.payload_json,
            ls.task_family = r.task_family
        WITH ls, r
        FOREACH (_ IN CASE WHEN r.run_id IS NULL THEN [] ELSE [1] END |
            MERGE (run:Run {id: r.run_id})
            SET run.updated_at = timestamp()
            MERGE (run)-[:HAS_LOOP_SIGNAL]->(ls)
            FOREACH (_ IN CASE WHEN r.signal_type = "condition_tag" THEN [1] ELSE [] END |
                MERGE (run)-[:HAS_CONDITION_TAG]->(ls)
            )
            FOREACH (_ IN CASE WHEN r.signal_type = "sensitivity_finding" THEN [1] ELSE [] END |
                MERGE (run)-[:HAS_SENSITIVITY]->(ls)
            )
            FOREACH (_ IN CASE WHEN r.signal_type = "design_constraint" THEN [1] ELSE [] END |
                MERGE (run)-[:HAS_DESIGN_CONSTRAINT]->(ls)
            )
            FOREACH (_ IN CASE WHEN r.signal_type = "hypothesis_delta" THEN [1] ELSE [] END |
                MERGE (run)-[:HAS_HYPOTHESIS_DELTA]->(ls)
            )
            FOREACH (_ IN CASE WHEN r.signal_type = "user_feedback" THEN [1] ELSE [] END |
                MERGE (run)-[:HAS_USER_FEEDBACK]->(ls)
            )
        )
        WITH ls, r
        FOREACH (_ IN CASE WHEN r.plan_id IS NULL THEN [] ELSE [1] END |
            MERGE (p:Plan {id: r.plan_id})
            SET p.updated_at = timestamp()
            MERGE (p)-[:HAS_LOOP_SIGNAL]->(ls)
        )
        WITH ls, r
        OPTIONAL MATCH (d1:Dataset {id: r.dataset_id})
        WITH ls, r, d1
        OPTIONAL MATCH (d2:Dataset {dataset_id: r.dataset_id})
        WITH ls, r, coalesce(d1, d2) AS d
        FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
            MERGE (ls)-[:ABOUT_DATASET]->(d)
        )
        """

        t0 = time.time()
        with self._driver.session(database=self._database) as session:
            session.run(query, rows=rows).consume()
        logger.debug(
            "loop signal writeback ok rows=%d lag_ms=%.1f",
            len(rows),
            (time.time() - t0) * 1000.0,
        )
        return len(rows)


@lru_cache(maxsize=1)
def get_default_loop_signal_writer() -> Neo4jLoopSignalWriter | None:
    uri = os.getenv("NEO4J_URI", "").strip() or "bolt://localhost:7687"
    user = os.getenv("NEO4J_USER", "").strip() or "neo4j"
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        return None
    database = os.getenv("NEO4J_DATABASE")
    try:
        return Neo4jLoopSignalWriter(
            uri=uri,
            user=user,
            password=password,
            database=database,
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Unable to initialize loop signal writer: %s", exc)
        return None


__all__ = [
    "Neo4jLoopSignalWriter",
    "enabled_signal_types",
    "get_default_loop_signal_writer",
    "is_loop_signal_writeback_enabled",
]

