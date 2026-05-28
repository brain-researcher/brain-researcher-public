"""
CLI wrapper for loading Neuromaps parcellations into BR-KG.

Reusable parsing and insertion helpers live in
``brain_researcher.core.ingestion.loaders.neuromaps_parcellations`` so core
ingestion code does not import service modules.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from brain_researcher.core.ingestion.loaders.neuromaps_parcellations import (
    AtlasFile,
    NeuromapsGraphDBProtocol,
    build_node_properties,
    detect_column,
    discover_atlas_files,
    insert_brain_regions,
    insert_part_of_relationships,
    read_table,
    slugify,
)
from brain_researcher.core.ingestion.neuromaps_paths import preferred_neuromaps_root
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load Neuromaps parcellations into the BR-KG database."
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--base-path",
        default=str(preferred_neuromaps_root()),
        help="Directory containing Neuromaps atlas files.",
    )
    parser.add_argument(
        "--atlas",
        nargs="*",
        help="Specific atlas identifiers to load (matched against file stems).",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        help="Atlas identifiers to skip.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze the atlas files but do not write to the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    base_path = Path(args.base_path).resolve()

    logger.info("Connecting to Neo4j backend for Neuromaps load")
    logger.info("Using neuromaps directory: %s", base_path)

    atlas_files = discover_atlas_files(
        base_path, include=args.atlas, exclude=args.exclude
    )
    if not atlas_files:
        logger.warning("No atlas files discovered under %s", base_path)
        return

    logger.info("Discovered %d atlas file(s)", len(atlas_files))

    db = require_neo4j_db(args.db_path, preload_cache=False)

    total_nodes_created = 0
    total_nodes_skipped = 0
    total_part_of_created = 0
    total_part_of_skipped = 0

    try:
        for atlas_file in atlas_files:
            logger.info("Processing atlas: %s (%s)", atlas_file.atlas, atlas_file.path)
            try:
                df = read_table(atlas_file.path)
            except ValueError as exc:
                logger.warning("Skipping %s: %s", atlas_file.path, exc)
                continue

            nodes_created, nodes_skipped, node_lookup, column_info = (
                insert_brain_regions(
                    db=db,
                    atlas_file=atlas_file,
                    df=df,
                    dry_run=args.dry_run,
                )
            )

            name_col = column_info["name_col"]
            parent_col = column_info["parent_col"]

            part_of_created, part_of_skipped = insert_part_of_relationships(
                db=db,
                atlas_file=atlas_file,
                df=df,
                node_id_lookup=node_lookup,
                parent_col=parent_col,
                name_col=name_col,
                dry_run=args.dry_run,
            )

            total_nodes_created += nodes_created
            total_nodes_skipped += nodes_skipped
            total_part_of_created += part_of_created
            total_part_of_skipped += part_of_skipped

    finally:
        db.close()

    logger.info("Neuromaps import complete.")
    logger.info(
        "Nodes created: %d, nodes skipped: %d",
        total_nodes_created,
        total_nodes_skipped,
    )
    logger.info(
        "PART_OF created: %d, PART_OF skipped: %d",
        total_part_of_created,
        total_part_of_skipped,
    )

    if args.dry_run:
        logger.info("Dry-run mode enabled; no database changes were persisted.")


__all__ = [
    "AtlasFile",
    "NeuromapsGraphDBProtocol",
    "build_node_properties",
    "detect_column",
    "discover_atlas_files",
    "insert_brain_regions",
    "insert_part_of_relationships",
    "main",
    "parse_args",
    "read_table",
    "slugify",
]


if __name__ == "__main__":
    main()
