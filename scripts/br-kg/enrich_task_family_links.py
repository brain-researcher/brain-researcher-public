#!/usr/bin/env python3
"""Enrich existing Task nodes with BELONGS_TO_FAMILY links using taxonomy matching."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.task_family_enrichment import (
    TaskFamilyEnrichmentConfig,
    enrich_existing_task_family_links,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-file",
        required=True,
        help="JSON file where the enrichment summary is written.",
    )
    parser.add_argument(
        "--include-dataset-tasks",
        default="true",
        choices=("true", "false"),
        help="Consider Task nodes linked from Dataset nodes.",
    )
    parser.add_argument(
        "--include-task-analysis-tasks",
        default="true",
        choices=("true", "false"),
        help="Consider Task nodes linked from TaskAnalysis nodes.",
    )
    parser.add_argument(
        "--only-missing-family",
        default="true",
        choices=("true", "false"),
        help="Only enrich Task nodes that do not already have a BELONGS_TO_FAMILY edge.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on candidate tasks, useful for dry runs.",
    )
    parser.add_argument(
        "--neo4j-database",
        help="Optional Neo4j database override.",
    )
    parser.add_argument(
        "--accepted-methods",
        default="exact_alias,aggressive_fuzzy_guarded",
        help="Comma-separated TaskFamilyMatcher methods to accept for writes.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    out_path = Path(args.output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db = require_neo4j_db(database=args.neo4j_database, preload_cache=False)
    summary = enrich_existing_task_family_links(
        db,
        config=TaskFamilyEnrichmentConfig(
            include_dataset_tasks=args.include_dataset_tasks == "true",
            include_task_analysis_tasks=args.include_task_analysis_tasks == "true",
            only_missing_family=args.only_missing_family == "true",
            limit=args.limit,
            accepted_methods=tuple(
                method.strip()
                for method in args.accepted_methods.split(",")
                if method.strip()
            ),
        ),
    )
    if hasattr(db, "commit"):
        db.commit()
    if hasattr(db, "close"):
        db.close()

    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote summary to {out_path}")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
