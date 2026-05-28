#!/usr/bin/env python3
"""Rollback Publication-[:CITES]->Publication backfill by method tag."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument("--method-tag", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prune-orphan-publications", action="store_true")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "tmp/publication_citation_backfill/"
            "rollback_publication_citation_backfill_report.json"
        ),
    )
    return parser.parse_args(argv)


def _summarize_target_edges(session: Any, *, method_tag: str) -> dict[str, int]:
    query = """
    MATCH (src:Publication)-[r:CITES]->(dst:Publication)
    WHERE r.method_tag = $method_tag
    RETURN
      count(r) AS targeted_edges,
      count(DISTINCT src) AS targeted_sources,
      count(DISTINCT dst) AS targeted_targets
    """
    row = session.run(query, {"method_tag": method_tag}).single()
    return {
        "targeted_edges": int((row or {}).get("targeted_edges") or 0),
        "targeted_sources": int((row or {}).get("targeted_sources") or 0),
        "targeted_targets": int((row or {}).get("targeted_targets") or 0),
    }


def _target_publication_element_ids(session: Any, *, method_tag: str) -> list[str]:
    query = """
    MATCH (:Publication)-[r:CITES]->(p:Publication)
    WHERE r.method_tag = $method_tag
    RETURN DISTINCT elementId(p) AS publication_element_id
    ORDER BY publication_element_id
    """
    records = list(session.run(query, {"method_tag": method_tag}))
    publication_ids: list[str] = []
    for record in records:
        publication_id = str((record or {}).get("publication_element_id") or "").strip()
        if publication_id:
            publication_ids.append(publication_id)
    return publication_ids


def _count_prunable_publications(
    session: Any,
    *,
    method_tag: str,
    publication_element_ids: Sequence[str],
) -> int:
    if not publication_element_ids:
        return 0
    query = """
    MATCH (p:Publication)
    WHERE elementId(p) IN $publication_element_ids
      AND p.method_tag = $method_tag
      AND NOT EXISTS {
        MATCH (p)-[other]-()
        WHERE NOT (type(other) = 'CITES' AND other.method_tag = $method_tag)
      }
    RETURN count(DISTINCT p) AS prunable_publications
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "publication_element_ids": list(publication_element_ids),
        },
    ).single()
    return int((row or {}).get("prunable_publications") or 0)


def _delete_target_edges(session: Any, *, method_tag: str) -> int:
    query = """
    MATCH (:Publication)-[r:CITES]->(:Publication)
    WHERE r.method_tag = $method_tag
    WITH collect(r) AS rels
    FOREACH (r IN rels | DELETE r)
    RETURN size(rels) AS deleted_edges
    """
    row = session.run(query, {"method_tag": method_tag}).single()
    return int((row or {}).get("deleted_edges") or 0)


def _prune_orphan_publications(
    session: Any,
    *,
    method_tag: str,
    publication_element_ids: Sequence[str],
) -> int:
    if not publication_element_ids:
        return 0
    query = """
    MATCH (p:Publication)
    WHERE elementId(p) IN $publication_element_ids
      AND p.method_tag = $method_tag
      AND NOT (p)--()
    WITH collect(p) AS publications
    FOREACH (p IN publications | DELETE p)
    RETURN size(publications) AS deleted_publications
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "publication_element_ids": list(publication_element_ids),
        },
    ).single()
    return int((row or {}).get("deleted_publications") or 0)


def build_report(
    *,
    args: argparse.Namespace,
    summary: dict[str, int],
    prunable_publications: int,
    deleted_edges: int,
    deleted_publications: int,
) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "filter": {
            "method_tag": str(args.method_tag),
            "relationship_type": "CITES",
            "source_label": "Publication",
            "target_label": "Publication",
        },
        "prune_orphan_publications_requested": bool(args.prune_orphan_publications),
        **summary,
        "prunable_publications": int(prunable_publications),
        "deleted_edges": int(deleted_edges),
        "deleted_publications": int(deleted_publications),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            summary = _summarize_target_edges(session, method_tag=str(args.method_tag))
            publication_element_ids: list[str] = []
            prunable_publications = 0
            if args.prune_orphan_publications:
                publication_element_ids = _target_publication_element_ids(
                    session,
                    method_tag=str(args.method_tag),
                )
                prunable_publications = _count_prunable_publications(
                    session,
                    method_tag=str(args.method_tag),
                    publication_element_ids=publication_element_ids,
                )

            deleted_edges = 0
            deleted_publications = 0
            if not args.dry_run:
                deleted_edges = _delete_target_edges(
                    session,
                    method_tag=str(args.method_tag),
                )
                if args.prune_orphan_publications:
                    deleted_publications = _prune_orphan_publications(
                        session,
                        method_tag=str(args.method_tag),
                        publication_element_ids=publication_element_ids,
                    )

    report = build_report(
        args=args,
        summary=summary,
        prunable_publications=prunable_publications,
        deleted_edges=deleted_edges,
        deleted_publications=deleted_publications,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    if args.dry_run:
        print(
            "Rollback dry-run: "
            f"targeted_edges={report['targeted_edges']}, "
            f"prunable_publications={report['prunable_publications']}"
        )
    else:
        print(
            "Rollback done: "
            f"deleted_edges={report['deleted_edges']}, "
            f"deleted_publications={report['deleted_publications']}"
        )
    print(f"Wrote report: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
