#!/usr/bin/env python3
"""Rollback Task->TaskFamily BELONGS_TO_FAMILY edges by method tag/profile."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument("--method-tag", default="task_family_backfill_v1")
    parser.add_argument("--match-profile", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prune-empty-families", action="store_true")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_backfill_rollback_report.json"),
    )
    return parser.parse_args()


def _count_target_edges(session, method_tag: str | None, match_profile: str | None) -> int:
    query = """
    MATCH (:Task)-[r:BELONGS_TO_FAMILY]->(:TaskFamily)
    WHERE ($method_tag IS NULL OR r.method_tag = $method_tag)
      AND ($match_profile IS NULL OR r.match_profile = $match_profile)
    RETURN count(r) AS total
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "match_profile": match_profile,
        },
    ).single()
    return int((row or {}).get("total") or 0)


def _delete_target_edges(session, method_tag: str | None, match_profile: str | None) -> int:
    query = """
    MATCH (:Task)-[r:BELONGS_TO_FAMILY]->(:TaskFamily)
    WHERE ($method_tag IS NULL OR r.method_tag = $method_tag)
      AND ($match_profile IS NULL OR r.match_profile = $match_profile)
    WITH collect(r) AS rels
    FOREACH (r IN rels | DELETE r)
    RETURN size(rels) AS deleted
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "match_profile": match_profile,
        },
    ).single()
    return int((row or {}).get("deleted") or 0)


def _prune_empty_families(session) -> int:
    query = """
    MATCH (f:TaskFamily)
    WHERE NOT (:Task)-[:BELONGS_TO_FAMILY]->(f)
      AND NOT (f)--()
    WITH collect(f) AS nodes
    FOREACH (node IN nodes | DELETE node)
    RETURN size(nodes) AS deleted
    """
    row = session.run(query).single()
    return int((row or {}).get("deleted") or 0)


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            targeted = _count_target_edges(
                session,
                method_tag=args.method_tag,
                match_profile=args.match_profile,
            )
            deleted_edges = 0
            deleted_families = 0
            if not args.dry_run:
                deleted_edges = _delete_target_edges(
                    session,
                    method_tag=args.method_tag,
                    match_profile=args.match_profile,
                )
                if args.prune_empty_families:
                    deleted_families = _prune_empty_families(session)

    report = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "filter": {
            "method_tag": args.method_tag,
            "match_profile": args.match_profile,
        },
        "targeted_edges": targeted,
        "deleted_edges": deleted_edges,
        "deleted_task_families": deleted_families,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    if args.dry_run:
        print(f"Rollback dry-run: targeted_edges={targeted}")
    else:
        print(
            f"Rollback done: deleted_edges={deleted_edges}, "
            f"deleted_task_families={deleted_families}"
        )
    print(f"Wrote report: {args.output_json}")


if __name__ == "__main__":
    main()
