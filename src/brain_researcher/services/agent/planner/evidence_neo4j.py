"""Neo4j-backed evidence store for tool×task_family priors.

Storage model (Option B):
  (:ToolEvidence {tool_id, tool_version, task_family, success_count, fail_count,
                 latency_ms_samples, failure_categories, updated_at})
  (:Tool)-[:HAS_EVIDENCE]->(:ToolEvidence)   (optional; best-effort)

This is additive and low-risk: it does not require modifying existing :Tool
properties and tolerates missing :Tool nodes.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Mapping, Sequence, Optional

from neo4j import GraphDatabase

from .evidence import ToolEvidenceReader, ToolEvidenceRecord, ToolEvidenceStats, ToolEvidenceWriter
from .loop_signal_neo4j import get_default_loop_signal_writer
from .prior_config import load_prior_config

from brain_researcher.services.agent.monitoring import metrics_collector

logger = logging.getLogger(__name__)

class Neo4jToolEvidenceStore(ToolEvidenceWriter, ToolEvidenceReader):
    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str | None = None,
        sample_window: int = 50,
        min_samples: int = 5,
    ) -> None:
        timeout_sec = float(os.getenv("BR_NEO4J_TIMEOUT_SEC", "2") or "2")
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=max(0.5, min(timeout_sec, 30.0)),
        )
        self._database = database
        cfg = load_prior_config()
        sample_window = cfg.get("latency", {}).get("sample_window", sample_window)
        min_samples_cfg = cfg.get("min_samples", {})
        self._sample_window = max(5, min(int(sample_window), 500))
        self._min_samples = max(1, int(min_samples_cfg.get("dataset_id", min_samples)))

    def write(self, records: Sequence[ToolEvidenceRecord]) -> None:
        if not records:
            return

        t0 = time.time()
        # Group into a compact payload for UNWIND.
        rows = []
        loop_signals = []
        for r in records:
            if not r.tool_id or not r.task_family:
                continue
            if r.loop_signals:
                loop_signals.extend(r.loop_signals)
            rows.append(
                {
                    "tool_id": r.tool_id,
                    "tool_version": r.tool_version or "",
                    "task_family": r.task_family,
                    "success_inc": 1 if r.outcome == "success" else 0,
                    "fail_inc": 1 if r.outcome != "success" else 0,
                    "latency_ms": int(r.latency_ms) if isinstance(r.latency_ms, int) else None,
                    "failure_category": r.failure_category or None,
                    "dataset_id": r.dataset_id or None,
                    "dataset_family": r.dataset_family or None,
                    "run_id": r.run_id or None,
                    "plan_id": r.plan_id or None,
                }
            )

        if not rows:
            return

        query = f"""
        UNWIND $rows AS r
        MERGE (e:ToolEvidence {{
            tool_id: r.tool_id,
            tool_version: r.tool_version,
            task_family: r.task_family
        }})
        ON CREATE SET
            e.success_count = 0,
            e.fail_count = 0,
            e.latency_ms_samples = [],
            e.failure_categories = [],
            e.created_at = timestamp()
        SET
            e.updated_at = timestamp(),
            e.success_count = coalesce(e.success_count, 0) + coalesce(r.success_inc, 0),
            e.fail_count = coalesce(e.fail_count, 0) + coalesce(r.fail_inc, 0),
            e.latency_ms_samples =
                CASE
                    WHEN r.latency_ms IS NULL THEN e.latency_ms_samples
                    ELSE (coalesce(e.latency_ms_samples, []) + [r.latency_ms])[-{self._sample_window}..]
                END,
            e.failure_categories =
                CASE
                    WHEN r.failure_category IS NULL THEN e.failure_categories
                    ELSE (coalesce(e.failure_categories, []) + [r.failure_category])[-{self._sample_window}..]
                END,
            e.dataset_id = coalesce(r.dataset_id, e.dataset_id),
            e.dataset_family = coalesce(r.dataset_family, e.dataset_family)
        WITH e, r
        FOREACH (_ IN CASE WHEN r.run_id IS NULL THEN [] ELSE [1] END |
            MERGE (run:Run {id: r.run_id})
            SET run.updated_at = timestamp(),
                run.last_state = CASE WHEN r.fail_inc > 0 THEN 'fail' ELSE 'success' END,
                run.plan_id = coalesce(run.plan_id, r.plan_id),
                run.dataset_id = coalesce(run.dataset_id, r.dataset_id),
                run.last_latency_ms = coalesce(r.latency_ms, run.last_latency_ms)
            MERGE (run)-[:HAS_EVIDENCE]->(e)
            FOREACH (_ IN CASE WHEN r.plan_id IS NULL THEN [] ELSE [1] END |
                MERGE (p:Plan {id: r.plan_id})
                SET p.updated_at = timestamp()
                MERGE (p)-[:HAS_RUN]->(run)
            )
        )
        WITH e, r, run
        OPTIONAL MATCH (t:Tool {{id: r.tool_id}})
        FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
            MERGE (t)-[:HAS_EVIDENCE]->(e)
            MERGE (t)-[:USED_IN_RUN]->(run)
        )
        WITH e, r, run
        OPTIONAL MATCH (tv:ToolVersion {{version_id: r.tool_version}})
        FOREACH (_ IN CASE WHEN tv IS NULL OR run IS NULL THEN [] ELSE [1] END |
            MERGE (tv)-[:USED_IN_RUN]->(run)
        )
        WITH e, r, run
        OPTIONAL MATCH (d1:Dataset {{id: r.dataset_id}})
        WITH e, r, run, d1
        OPTIONAL MATCH (d2:Dataset {{dataset_id: r.dataset_id}})
        WITH e, r, run, coalesce(d1, d2) AS d
        FOREACH (_ IN CASE WHEN run IS NULL OR d IS NULL THEN [] ELSE [1] END |
            MERGE (run)-[:USED_DATASET]->(d)
        )
        """

        try:
            with self._driver.session(database=self._database) as session:
                session.run(query, rows=rows).consume()
            lag_ms = (time.time() - t0) * 1000
            metrics_collector.increment("kg_evidence_writes_total", len(rows))
            metrics_collector.record("kg_evidence_write_lag_ms", lag_ms)
            metrics_collector.increment(
                "kg_writeback_success_total",
                labels={"type": "evidence"},
            )
            logger.debug("evidence writeback ok rows=%d lag_ms=%.1f", len(rows), lag_ms)
        except Exception as exc:  # pragma: no cover - best-effort
            metrics_collector.increment("kg_evidence_write_errors_total", len(rows))
            metrics_collector.increment(
                "kg_writeback_fail_total",
                labels={"type": "evidence"},
            )
            logger.warning("Neo4j evidence write failed rows=%d err=%s", len(rows), exc)
            return

        # Loop signal writeback is best-effort and independently feature-gated.
        if loop_signals:
            try:
                loop_writer = get_default_loop_signal_writer()
                if loop_writer:
                    sample = next((r for r in records if r and r.loop_signals), None)
                    loop_writer.write(
                        loop_signals,
                        run_id=sample.run_id if sample else None,
                        plan_id=sample.plan_id if sample else None,
                        dataset_id=sample.dataset_id if sample else None,
                        task_family=sample.task_family if sample else None,
                    )
            except Exception as exc:  # pragma: no cover - best-effort
                logger.debug("Loop signal writeback skipped for evidence rows: %s", exc)

    def read_stats(
        self,
        *,
        tool_versions: Mapping[str, str],
        task_family: str,
        tool_ids: Sequence[str],
        dataset_id: str | None = None,
    ) -> dict[str, ToolEvidenceStats]:
        if not tool_ids or not task_family:
            return {}

        pairs = [
            {
                "tool_id": tid,
                "tool_version": (tool_versions.get(tid) or ""),
            }
            for tid in tool_ids
            if isinstance(tid, str) and tid
        ]
        if not pairs:
            return {}

        query = """
        UNWIND $pairs AS p
        OPTIONAL MATCH (e1:ToolEvidence {
            tool_id: p.tool_id,
            tool_version: p.tool_version,
            task_family: $task_family,
            dataset_id: $dataset_id
        })
        OPTIONAL MATCH (e2:ToolEvidence {
            tool_id: p.tool_id,
            tool_version: p.tool_version,
            task_family: $task_family,
            dataset_family: $dataset_family
        })
        OPTIONAL MATCH (e3:ToolEvidence {
            tool_id: p.tool_id,
            tool_version: p.tool_version,
            task_family: $task_family
        })
        WITH p.tool_id AS tool_id, [e1, e2, e3] AS candidates
        WITH tool_id, [e IN candidates WHERE e IS NOT NULL][0] AS e, [e1, e2, e3] AS all_e
        RETURN
            tool_id,
            coalesce(e.success_count, 0) AS success_count,
            coalesce(e.fail_count, 0) AS fail_count,
            coalesce(e.latency_ms_samples, []) AS latency_ms_samples,
            coalesce(e.failure_categories, []) AS failure_categories,
            coalesce(e.success_count,0) + coalesce(e.fail_count,0) AS n,
            CASE
                WHEN e IS NULL THEN 'none'
                WHEN e1 IS NOT NULL THEN 'dataset_id'
                WHEN e2 IS NOT NULL THEN 'dataset_family'
                ELSE 'global'
            END AS layer
        """

        try:
            with self._driver.session(database=self._database) as session:
                dataset_family = None
                if dataset_id and ":" in dataset_id:
                    parts = dataset_id.split(":")
                    if len(parts) >= 2:
                        dataset_family = ":".join(parts[:2])

                res = session.run(
                    query,
                    pairs=pairs,
                    task_family=task_family,
                    dataset_id=dataset_id,
                    dataset_family=dataset_family,
                )
                out: dict[str, ToolEvidenceStats] = {}
                for row in res:
                    tid = row.get("tool_id")
                    if not isinstance(tid, str) or not tid:
                        continue
                    n = int(row.get("n") or 0)
                    layer = str(row.get("layer") or "none")
                    # Enforce min_samples by falling back manually if needed
                    if n < self._min_samples and layer in {"dataset_id", "dataset_family"}:
                        continue  # let caller rely on global entries populated separately
                    out[tid] = ToolEvidenceStats(
                        success_count=int(row.get("success_count") or 0),
                        fail_count=int(row.get("fail_count") or 0),
                        latency_ms_samples=tuple(int(x) for x in (row.get("latency_ms_samples") or []) if isinstance(x, int)),
                        failure_categories=tuple(str(x) for x in (row.get("failure_categories") or []) if isinstance(x, str)),
                        samples_used=n,
                        layer_used=layer,
                    )
                return out
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("Neo4j evidence read failed: %s", exc)
            return {}


@lru_cache(maxsize=1)
def get_default_evidence_store() -> Neo4jToolEvidenceStore | None:
    """Create a shared Neo4j evidence store (best-effort).

    Returns None if Neo4j creds are not configured.
    """

    uri = os.getenv("NEO4J_URI", "").strip() or "bolt://localhost:7687"
    user = os.getenv("NEO4J_USER", "").strip() or "neo4j"
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        return None

    database = os.getenv("NEO4J_DATABASE")
    sample_window = int(os.getenv("BR_KG_EVIDENCE_SAMPLE_WINDOW", "50") or "50")
    try:
        return Neo4jToolEvidenceStore(
            uri=uri,
            user=user,
            password=password,
            database=database,
            sample_window=sample_window,
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Unable to initialize Neo4j evidence store: %s", exc)
        return None


__all__ = ["Neo4jToolEvidenceStore", "get_default_evidence_store"]
