#!/usr/bin/env python3
"""CLI to calculate confidence for P0 relationships."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from typing import List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.quality.confidence import (
    compute_confidence_from_props,
    DEFAULT_CONFIDENCE_VERSION,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_REL_TYPES = [
    "MAPS_TO",
    "MEASURES",
    "HAS_TASK",
    "USES_TASK",
    "GENERATED_FROM",
    "COMPUTED_WITH",
    "DERIVED_FROM",
    "RELATED_TO",
    "IMPLEMENTS_FAMILY",
    "SUGGESTS_MEASURES",
]


def _parse_rel_types(raw: str) -> List[str]:
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(",", " ").split():
        if chunk.strip():
            parts.append(chunk.strip())
    return parts


def update_confidence(rel_types: List[str], limit: int | None, dry_run: bool) -> None:
    db = require_neo4j_db(preload_cache=False)
    logger.info("Connected to graph backend: %s", type(db).__name__)

    try:
        for rel_type in rel_types:
            rels = db.find_relationships(rel_type=rel_type)
            if limit:
                rels = rels[:limit]
            logger.info("Processing %s relationships for %s", len(rels), rel_type)

            updated = 0
            skipped = 0
            conf_version = DEFAULT_CONFIDENCE_VERSION

            for start_id, end_id, props in rels:
                updates = compute_confidence_from_props(props)
                if not updates:
                    skipped += 1
                    continue
                conf_version = updates.get("confidence_version", conf_version)

                if dry_run:
                    logger.info(
                        "[DRY RUN] %s (%s -> %s) confidence=%.3f",
                        rel_type,
                        start_id,
                        end_id,
                        updates["confidence"],
                    )
                else:
                    db.update_relationship(start_id, end_id, rel_type, updates)
                updated += 1

            logger.info(
                "Finished %s: updated=%s skipped=%s (confidence_version=%s)",
                rel_type,
                updated,
                skipped,
                conf_version,
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute confidence for relationships based on evidence/provenance",
    )
    parser.add_argument(
        "--rel-types",
        type=str,
        default=" ".join(DEFAULT_REL_TYPES),
        help="Relationship types to update (comma or space separated)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit relationships per type")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates")

    args = parser.parse_args()
    rel_types = _parse_rel_types(args.rel_types)

    update_confidence(rel_types, args.limit, args.dry_run)


if __name__ == "__main__":
    main()
