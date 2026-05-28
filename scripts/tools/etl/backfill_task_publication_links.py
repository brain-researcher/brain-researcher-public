#!/usr/bin/env python3
"""Backfill task-to-publication links via study bridge relationships.

This script targets graph variants where tasks are connected to Study nodes
(`USES_PARADIGM`, `HAS_TASK`, etc.) and studies carry publication metadata
or are connected to Publication/Paper nodes.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from typing import Any

from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)

TASK_LABELS = ["Task", "TaskSpec", "TaskDef", "TaskAnalysis"]
STUDY_LABELS = ["Study", "Experiment"]
PAPER_LABELS = ["Publication", "Paper"]
TASK_STUDY_REL_TYPES = ["USES_TASK", "HAS_TASK", "USES_PARADIGM"]
STUDY_PAPER_REL_TYPES = ["MENTIONS", "DESCRIBES", "CITED_BY", "ABOUT", "STUDIES"]
DEFAULT_REL_TYPE = "MENTIONS"
_REL_TYPE_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill task->paper relationships via Study bridge"
    )
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--relationship-type", default=DEFAULT_REL_TYPE)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _validate_rel_type(value: str) -> str:
    text = str(value or "").strip().upper()
    if not _REL_TYPE_RE.match(text):
        raise ValueError(f"Invalid relationship type: {value!r}")
    return text


def _query_candidate_pairs(db: Neo4jGraphDB, min_confidence: float) -> dict[str, int]:
    cypher = """
    MATCH (t)-[ts]-(s)
    WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
      AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
      AND type(ts) IN $task_study_rel_types
      AND ($min_confidence <= 0 OR coalesce(ts.confidence, 0.0) >= $min_confidence)
    MATCH (s)-[sp]-(p)
    WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
      AND type(sp) IN $study_paper_rel_types
      AND ($min_confidence <= 0 OR coalesce(sp.confidence, 0.0) >= $min_confidence)
    WITH DISTINCT coalesce(t.id, elementId(t)) AS task_id,
                  coalesce(p.id, elementId(p)) AS paper_id
    RETURN count(*) AS candidate_pairs
    """
    rec = db._run(
        cypher,
        {
            "task_labels": TASK_LABELS,
            "study_labels": STUDY_LABELS,
            "paper_labels": PAPER_LABELS,
            "task_study_rel_types": TASK_STUDY_REL_TYPES,
            "study_paper_rel_types": STUDY_PAPER_REL_TYPES,
            "min_confidence": float(min_confidence),
        },
    ).single()
    return {"candidate_pairs": int((rec or {}).get("candidate_pairs") or 0)}


def _apply_backfill(
    db: Neo4jGraphDB,
    *,
    rel_type: str,
    min_confidence: float,
) -> dict[str, int]:
    cypher = f"""
    MATCH (t)-[ts]-(s)
    WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
      AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
      AND type(ts) IN $task_study_rel_types
      AND ($min_confidence <= 0 OR coalesce(ts.confidence, 0.0) >= $min_confidence)
    MATCH (s)-[sp]-(p)
    WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
      AND type(sp) IN $study_paper_rel_types
      AND ($min_confidence <= 0 OR coalesce(sp.confidence, 0.0) >= $min_confidence)
    WITH DISTINCT t, p, ts, sp
    MERGE (t)-[rel:`{rel_type}`]->(p)
    ON CREATE SET
      rel.__task_pub_backfill_created = true,
      rel.confidence = coalesce(ts.confidence, sp.confidence, 0.6),
      rel.method = coalesce(rel.method, 'study_bridge_backfill'),
      rel.prov_source = coalesce(rel.prov_source, 'task-study-publication'),
      rel.source = coalesce(rel.source, 'task-study-publication'),
      rel.confidence_tier = coalesce(rel.confidence_tier, 'backfilled'),
      rel.created_at = coalesce(rel.created_at, timestamp())
    WITH rel
    RETURN count(*) AS attempted,
           count(CASE WHEN rel.__task_pub_backfill_created THEN 1 END) AS created
    """
    rec = db._run(
        cypher,
        {
            "task_labels": TASK_LABELS,
            "study_labels": STUDY_LABELS,
            "paper_labels": PAPER_LABELS,
            "task_study_rel_types": TASK_STUDY_REL_TYPES,
            "study_paper_rel_types": STUDY_PAPER_REL_TYPES,
            "min_confidence": float(min_confidence),
        },
    ).single()
    attempted = int((rec or {}).get("attempted") or 0)
    created = int((rec or {}).get("created") or 0)

    cleanup = f"""
    MATCH ()-[rel:`{rel_type}`]->()
    WHERE rel.__task_pub_backfill_created = true
    REMOVE rel.__task_pub_backfill_created
    RETURN count(rel) AS cleaned
    """
    cleaned_rec = db._run(cleanup).single()
    cleaned = int((cleaned_rec or {}).get("cleaned") or 0)
    return {
        "attempted_pairs": attempted,
        "created_links": created,
        "existing_links": max(attempted - created, 0),
        "cleaned_temp_flags": cleaned,
    }


def _count_tasks_without_papers(db: Neo4jGraphDB) -> int:
    cypher = """
    MATCH (t)
    WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
    OPTIONAL MATCH (t)-[]-(m)
    WHERE any(lbl IN labels(m) WHERE lbl IN $paper_labels OR lbl IN $study_labels)
    WITH t, count(DISTINCT m) AS linked
    WHERE linked = 0
    RETURN count(t) AS tasks_without_papers
    """
    rec = db._run(
        cypher,
        {"task_labels": TASK_LABELS, "paper_labels": PAPER_LABELS, "study_labels": STUDY_LABELS},
    ).single()
    return int((rec or {}).get("tasks_without_papers") or 0)


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    rel_type = _validate_rel_type(args.relationship_type)

    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        database=args.neo4j_database,
        preload_cache=False,
    )
    try:
        before_without = _count_tasks_without_papers(db)
        candidates = _query_candidate_pairs(db, args.min_confidence)

        report: dict[str, Any] = {
            "dry_run": bool(args.dry_run),
            "relationship_type": rel_type,
            "min_confidence": float(args.min_confidence),
            "tasks_without_papers_before": before_without,
            **candidates,
        }

        if not args.dry_run:
            report.update(_apply_backfill(db, rel_type=rel_type, min_confidence=args.min_confidence))
            report["tasks_without_papers_after"] = _count_tasks_without_papers(db)

        logger.info("task-publication backfill report: %s", report)
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
