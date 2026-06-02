#!/usr/bin/env python3
"""Materialize canonical BrainRegion hierarchy edges in Neo4j."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.spatial.brainregion_hierarchy import (
    HierarchySummary,
    materialize_explicit_part_of_from_dataframe,
    materialize_schaefer_network_part_of,
    materialize_yeo17_family_part_of,
    slugify,
)
from brain_researcher.services.br_kg.spatial.neuromaps_assets import (
    preferred_neuromaps_root,
)
from brain_researcher.services.br_kg.spatial.neuromaps_parcellations import (
    discover_atlas_files,
    read_table,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize canonical BrainRegion PART_OF hierarchy edges.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--base-path",
        default=str(preferred_neuromaps_root()),
        help="Optional directory containing atlas metadata files for explicit parent materialization.",
    )
    parser.add_argument(
        "--atlas",
        nargs="*",
        help="Limit explicit metadata pass to specific atlas file stems.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        help="Atlas identifiers to skip for both explicit and fallback passes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report hierarchy changes without writing to Neo4j.",
    )
    return parser.parse_args()


def _atlas_selected(selected: set[str], excluded: set[str], key: str) -> bool:
    key_slug = slugify(key)
    if key_slug in excluded:
        return False
    if not selected:
        return True
    return any(
        candidate == key_slug or candidate in key_slug or key_slug in candidate
        for candidate in selected
    )


def _log_summary(summary: HierarchySummary) -> None:
    logger.info(
        "%s | parents_created=%d part_of_created=%d part_of_skipped=%d rows_skipped=%d unresolved_children=%d unresolved_parents=%d",
        summary.scope,
        summary.parent_nodes_created,
        summary.part_of_created,
        summary.part_of_skipped,
        summary.rows_skipped,
        summary.unresolved_children,
        summary.unresolved_parents,
    )


def main() -> None:
    args = parse_args()
    selected = {slugify(item) for item in (args.atlas or [])}
    excluded = {slugify(item) for item in (args.exclude or [])}
    base_path = Path(args.base_path).expanduser().resolve()

    logger.info("Connecting to Neo4j for BrainRegion hierarchy materialization")
    db = require_neo4j_db(args.db_path, preload_cache=False)
    summaries: list[HierarchySummary] = []

    try:
        if not args.dry_run:
            db.begin()

        if base_path.exists():
            atlas_files = discover_atlas_files(
                base_path,
                include=args.atlas,
                exclude=args.exclude,
            )
            for atlas_file in atlas_files:
                try:
                    df = read_table(atlas_file.path)
                except ValueError as exc:
                    logger.warning("Skipping %s: %s", atlas_file.path, exc)
                    continue
                summary = materialize_explicit_part_of_from_dataframe(
                    db,
                    atlas=atlas_file.atlas,
                    df=df,
                    dry_run=args.dry_run,
                )
                summaries.append(summary)
                _log_summary(summary)
        else:
            logger.warning(
                "Atlas base path %s not found; skipping explicit metadata pass",
                base_path,
            )

        if _atlas_selected(selected, excluded, "yeo17"):
            summary = materialize_yeo17_family_part_of(db, dry_run=args.dry_run)
            summaries.append(summary)
            _log_summary(summary)

        if _atlas_selected(selected, excluded, "schaefer"):
            summary = materialize_schaefer_network_part_of(db, dry_run=args.dry_run)
            summaries.append(summary)
            _log_summary(summary)

        if not args.dry_run:
            db.commit()
    except Exception:
        if not args.dry_run:
            db.rollback()
        raise
    finally:
        db.close()

    logger.info("BrainRegion hierarchy materialization complete")


if __name__ == "__main__":
    main()
