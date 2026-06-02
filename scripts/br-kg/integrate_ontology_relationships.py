#!/usr/bin/env python3
"""
Integrate Ontology Relationships into BR-KG

This script creates all ontological relationships:
1. IS_A hierarchies between concepts
2. MEASURES relationships between tasks and concepts
3. PART_OF relationships between brain regions

This completes the ontology integration for BR-KG.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_relationships_loader import (
    CognitiveAtlasRelationshipsLoader,
)
from graph.neo4j_utils import require_neo4j_db

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def integrate_all_ontology_relationships(
    db_path: str | None, data_dir: str = "data/br-kg/raw", dry_run: bool = False
):
    """
    Integrate all ontological relationships.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
        data_dir: Directory containing cognitive atlas files
        dry_run: If True, preview changes without creating them
    """
    logger.info("Starting ontology relationship integration...")

    # Load database
    db = require_neo4j_db(db_path, preload_cache=False)
    initial_stats = db.get_stats()
    logger.info(f"Initial database state: {initial_stats}")

    try:
        # Check for required files
        data_path = Path(data_dir)
        concepts_file = data_path / "cognitive_concepts.json"
        tasks_file = data_path / "cognitive_tasks.json"

        if not concepts_file.exists() or not tasks_file.exists():
            logger.error(f"Cognitive Atlas files not found in {data_dir}")
            logger.info("Attempting to fetch Cognitive Atlas data...")

            # Try to fetch the data
            from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_loader import fetch_cognitive_atlas_data

            ca_files = fetch_cognitive_atlas_data(str(data_path))
            concepts_file = ca_files.get("concepts")
            tasks_file = ca_files.get("tasks")

            if not concepts_file or not tasks_file:
                logger.error("Failed to fetch Cognitive Atlas data")
                return

        # Create ontological relationships
        logger.info("\n=== Creating Ontological Relationships ===")

        ca_loader = CognitiveAtlasRelationshipsLoader(db)
        ca_stats = ca_loader.load_relationships_from_files(
            str(concepts_file), str(tasks_file)
        )

        # Get final statistics
        final_stats = db.get_stats()

        # Print summary report
        logger.info("\n" + "=" * 60)
        logger.info("ONTOLOGY INTEGRATION SUMMARY")
        logger.info("=" * 60)

        logger.info("\nRelationships Created:")
        for key, value in ca_stats.items():
            logger.info(f"  {key}: {value}")

        logger.info("\nDatabase Growth:")
        logger.info(
            f"  Nodes: {initial_stats['total_nodes']} -> {final_stats['total_nodes']}"
        )
        logger.info(
            f"  Relationships: {initial_stats['total_relationships']} -> {final_stats['total_relationships']}"
        )

        logger.info("\nRelationship Types:")
        for rel_type in ["IS_A", "MEASURES", "PART_OF"]:
            initial_count = initial_stats.get("relationship_types", {}).get(rel_type, 0)
            final_count = final_stats.get("relationship_types", {}).get(rel_type, 0)
            logger.info(
                f"  {rel_type}: {initial_count} -> {final_count} (+{final_count - initial_count})"
            )

        if dry_run:
            logger.info("\n[DRY RUN] No changes were made to the database")

    except Exception as e:
        logger.error(f"Error during integration: {e}")
        raise
    finally:
        db.close()


def verify_ontological_structure(db_path: str | None):
    """
    Verify the ontological structure of the database.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
    """
    logger.info("Verifying ontological structure...")

    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Check IS_A hierarchies
        is_a_rels = db.find_relationships(rel_type="IS_A")
        logger.info(f"\nIS_A relationships: {len(is_a_rels)}")

        # Show sample hierarchy
        if is_a_rels:
            logger.info("Sample IS_A hierarchy:")
            for i, (start, end, data) in enumerate(is_a_rels[:5]):
                start_node = db.get_node(start)
                end_node = db.get_node(end)
                if start_node and end_node:
                    start_name = start_node.get("name", start)
                    end_name = end_node.get("name", end)
                    logger.info(f"  {start_name} IS_A {end_name}")

        # Check MEASURES relationships
        measures_rels = db.find_relationships(rel_type="MEASURES")
        logger.info(f"\nMEASURES relationships: {len(measures_rels)}")

        # Show sample measures
        if measures_rels:
            logger.info("Sample MEASURES relationships:")
            for i, (start, end, data) in enumerate(measures_rels[:5]):
                start_node = db.get_node(start)
                end_node = db.get_node(end)
                if start_node and end_node:
                    task_name = start_node.get("name", start)
                    concept_name = end_node.get("name", end)
                    logger.info(f"  Task '{task_name}' MEASURES '{concept_name}'")

        # Check PART_OF relationships
        part_of_rels = db.find_relationships(rel_type="PART_OF")
        logger.info(f"\nPART_OF relationships: {len(part_of_rels)}")

        # Show sample part_of
        if part_of_rels:
            logger.info("Sample PART_OF hierarchy:")
            for i, (start, end, data) in enumerate(part_of_rels[:5]):
                start_node = db.get_node(start)
                end_node = db.get_node(end)
                if start_node and end_node:
                    child_name = start_node.get("name", start)
                    parent_name = end_node.get("name", end)
                    logger.info(f"  {child_name} PART_OF {parent_name}")

    finally:
        db.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Integrate ontological relationships into BR-KG"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--data-dir",
        default="data/br-kg/raw",
        help="Directory containing cognitive atlas files",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify ontological structure after integration",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without creating them"
    )

    args = parser.parse_args()

    # Run integration
    integrate_all_ontology_relationships(
        args.database, data_dir=args.data_dir, dry_run=args.dry_run
    )

    # Verify if requested
    if args.verify:
        logger.info("\n" + "=" * 60)
        verify_ontological_structure(args.database)


if __name__ == "__main__":
    main()
