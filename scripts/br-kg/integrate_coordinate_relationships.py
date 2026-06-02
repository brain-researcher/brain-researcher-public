#!/usr/bin/env python3
"""
Integrate Coordinate-Based Relationships into BR-KG

This script:
1. Creates proper Study->Coordinate->BrainRegion relationships from NeuroSynth
2. Creates Study->Concept relationships based on text matching
3. Runs the activation edges creation to generate ACTIVATES relationships

This completes the coordinate-based relationship integration for BR-KG.
"""

import argparse
import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

from brain_researcher.services.br_kg.etl.loaders.enhanced_neurosynth_loader import (
    EnhancedNeurosynthLoader,
)
from brain_researcher.services.br_kg.etl.loaders.neurosynth_relationship_loader import (
    NeurosynthRelationshipLoader,
)
from brain_researcher.services.br_kg.spatial.create_activation_edges import (
    run_activation_edge_creation,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def _make_db(args):
    """Create the graph backend (Neo4j required)."""
    return require_neo4j_db(args.database, preload_cache=False)


def integrate_all_coordinate_relationships(
    db_path: str | None,
    limit_studies: int | None = None,
    activation_threshold: int = 5,
    dry_run: bool = False,
    backend: str | None = None,
):
    """
    Integrate all coordinate-based relationships.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
        limit_studies: Limit number of studies to process
        activation_threshold: Minimum coordinates for ACTIVATES edges
        dry_run: If True, preview changes without creating them
    """
    logger.info("Starting coordinate relationship integration...")

    # Load database
    class Args:  # lightweight shim so we can reuse _make_db
        def __init__(self, database, backend):
            self.database = database
            self.backend = backend

    db = _make_db(Args(db_path, backend))
    initial_stats = db.get_stats()
    logger.info(f"Initial database state: {initial_stats}")

    try:
        # Step 1: Create NeuroSynth relationships
        logger.info("\n=== Step 1: Creating NeuroSynth relationships ===")
        ns_loader = EnhancedNeurosynthLoader()
        rel_loader = NeurosynthRelationshipLoader(db)

        ns_stats = rel_loader.load_relationships(ns_loader, limit=limit_studies)
        logger.info(f"NeuroSynth relationship stats: {ns_stats}")

        # Step 2: Create ACTIVATES edges
        logger.info("\n=== Step 2: Creating ACTIVATES edges ===")
        total_activation_stats = run_activation_edge_creation(
            db,
            labels=("Concept", "Task"),
            threshold=activation_threshold,
            dry_run=dry_run,
        )
        logger.info(f"Activation stats: {total_activation_stats}")

        # Get final statistics
        final_stats = db.get_stats()

        # Print summary report
        logger.info("\n" + "=" * 60)
        logger.info("INTEGRATION SUMMARY")
        logger.info("=" * 60)

        logger.info("\nNeuroSynth Relationships Created:")
        for key, value in ns_stats.items():
            logger.info(f"  {key}: {value}")

        logger.info("\nACTIVATES Edges Created:")
        for key, value in total_activation_stats.items():
            logger.info(f"  {key}: {value}")

        logger.info("\nDatabase Growth:")
        logger.info(
            f"  Nodes: {initial_stats['total_nodes']} -> {final_stats['total_nodes']}"
        )
        logger.info(
            f"  Relationships: {initial_stats['total_relationships']} -> {final_stats['total_relationships']}"
        )

        logger.info("\nRelationship Types:")
        rel_types = final_stats.get("relationship_types", {})
        if isinstance(rel_types, list):
            for rel_type in rel_types:
                logger.info(f"  {rel_type}")
        else:
            for rel_type, count in rel_types.items():
                logger.info(f"  {rel_type}: {count}")

        if dry_run:
            logger.info("\n[DRY RUN] No changes were made to the database")

    except Exception as e:
        logger.error(f"Error during integration: {e}")
        raise
    finally:
        db.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Integrate coordinate-based relationships into BR-KG"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--limit-studies", type=int, help="Limit number of studies to process"
    )
    parser.add_argument(
        "--activation-threshold",
        type=int,
        default=5,
        help="Minimum coordinate evidence for ACTIVATES edges (default: 5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without creating them"
    )

    args = parser.parse_args()

    # Run integration
    integrate_all_coordinate_relationships(
        args.database,
        limit_studies=args.limit_studies,
        activation_threshold=args.activation_threshold,
        dry_run=args.dry_run,
        backend=None,
    )


if __name__ == "__main__":
    main()
