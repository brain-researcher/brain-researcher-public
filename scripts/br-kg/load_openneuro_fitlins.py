#!/usr/bin/env python3
"""
Load OpenNeuro GLMfitlins data into existing BR-KG database.

This script loads FitLins processed OpenNeuro datasets including:
- Datasets with their tasks
- Contrasts and their specifications
- Links between datasets, tasks, and contrasts
"""

import argparse
import logging
import sys
from pathlib import Path

# Add br_kg directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.fitlins_loader import OpenNeuroFitLinsLoader
from brain_researcher.services.br_kg.etl.mappers.cross_source_linker import CrossSourceLinker
from graph.neo4j_utils import require_neo4j_db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_all_fitlins_datasets(db_path: str | None, limit: int = None):
    """
    Load all available OpenNeuro FitLins datasets into the database.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
        limit: Maximum number of datasets to load (None for all)
    """
    # Open database connection
    db = require_neo4j_db(db_path, preload_cache=False)
    logger.info("Connected to Neo4j backend for OpenNeuro FitLins load")

    # Get initial stats
    initial_stats = db.get_stats()
    logger.info(f"Initial database stats: {initial_stats}")

    # Initialize FitLins loader with correct path
    openneuro_dir = (
        Path(__file__).parent.parent.parent.parent
        / "llm_cogitive_function"
        / "openneuro_glmfitlins"
    )
    loader = OpenNeuroFitLinsLoader(db, openneuro_dir=str(openneuro_dir))

    # Get all dataset directories
    statsmodel_dir = loader.statsmodel_dir
    if not statsmodel_dir.exists():
        logger.error(f"Statsmodel directory not found: {statsmodel_dir}")
        return

    dataset_dirs = sorted(
        [d for d in statsmodel_dir.iterdir() if d.is_dir() and d.name.startswith("ds")]
    )

    if limit:
        dataset_dirs = dataset_dirs[:limit]

    logger.info(f"Found {len(dataset_dirs)} datasets to load")

    # Load each dataset
    successful = 0
    failed = 0

    for dataset_dir in dataset_dirs:
        dataset_id = dataset_dir.name
        logger.info(f"\nLoading dataset: {dataset_id}")

        result = loader.load_dataset(dataset_id)
        if result:
            successful += 1
        else:
            failed += 1

    # Run cross-source linking
    logger.info("\n=== Running cross-source linking ===")
    cross_linker = CrossSourceLinker(db, auto_link=True, dry_run=False)
    links_created = cross_linker.link_after_source_load("openneuro")
    logger.info(f"Created {links_created} MAPS_TO relationships")

    # Get final stats
    final_stats = db.get_stats()
    logger.info(f"\nFinal database stats: {final_stats}")

    # Calculate what was added
    nodes_added = final_stats["total_nodes"] - initial_stats["total_nodes"]
    relationships_added = (
        final_stats["total_relationships"] - initial_stats["total_relationships"]
    )

    logger.info("\n=== SUMMARY ===")
    logger.info(f"Datasets processed: {len(dataset_dirs)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Nodes added: {nodes_added}")
    logger.info(f"Relationships added: {relationships_added}")
    logger.info(f"MAPS_TO relationships created: {links_created}")

    # Show cross-source linking report
    logger.info("\n=== Cross-Source Linking Report ===")
    logger.info(cross_linker.get_linking_report())

    # Close database
    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Load OpenNeuro FitLins data into BR-KG"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--limit", type=int, help="Maximum number of datasets to load (default: all)"
    )

    args = parser.parse_args()

    load_all_fitlins_datasets(args.db_path, args.limit)


if __name__ == "__main__":
    main()
