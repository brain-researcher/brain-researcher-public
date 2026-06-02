#!/usr/bin/env python3
"""
Create all missing relationships in BR-KG database.

This script creates:
1. USES_TASK - Study → Task relationships based on text analysis
2. ACTIVATES - Task/Concept → BrainRegion based on coordinate evidence
3. IS_A - Concept hierarchies (if data available)
4. PART_OF - BrainRegion hierarchies
5. Additional HAS_COORDINATE relationships
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Import individual relationship creators
from create_uses_task_relationships import StudyTaskLinker
from fix_coordinate_relationships import fix_coordinate_relationships
from graph.neo4j_graph_database import Neo4jGraphDB
from graph.neo4j_utils import require_neo4j_db

from brain_researcher.services.br_kg.spatial.create_activation_edges import (
    run_activation_edge_creation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def create_brain_region_hierarchy(db: Neo4jGraphDB):
    """Create PART_OF relationships for brain region hierarchy."""
    logger.info("Creating brain region PART_OF hierarchy...")

    # Define basic brain region hierarchy
    hierarchy = {
        "frontal lobe": ["prefrontal cortex", "motor cortex", "premotor cortex"],
        "prefrontal cortex": [
            "dorsolateral prefrontal cortex",
            "ventromedial prefrontal cortex",
            "orbitofrontal cortex",
            "anterior cingulate cortex",
        ],
        "parietal lobe": [
            "superior parietal lobule",
            "inferior parietal lobule",
            "precuneus",
            "angular gyrus",
        ],
        "temporal lobe": [
            "superior temporal gyrus",
            "middle temporal gyrus",
            "inferior temporal gyrus",
            "hippocampus",
            "amygdala",
        ],
        "occipital lobe": ["primary visual cortex", "visual association areas"],
        "cerebellum": ["cerebellar cortex", "deep cerebellar nuclei"],
        "brainstem": ["midbrain", "pons", "medulla oblongata"],
        "basal ganglia": [
            "caudate nucleus",
            "putamen",
            "globus pallidus",
            "substantia nigra",
            "subthalamic nucleus",
        ],
    }

    created = 0

    # Get all brain regions
    regions = db.find_nodes(labels="BrainRegion")
    region_map = {r[1]["name"].lower(): r[0] for r in regions if "name" in r[1]}

    for parent_name, children in hierarchy.items():
        parent_name_lower = parent_name.lower()
        if parent_name_lower in region_map:
            parent_id = region_map[parent_name_lower]

            for child_name in children:
                child_name_lower = child_name.lower()
                if child_name_lower in region_map:
                    child_id = region_map[child_name_lower]

                    # Check if relationship exists
                    existing = db.find_relationships(
                        start_node=child_id, end_node=parent_id, rel_type="PART_OF"
                    )

                    if not existing:
                        db.create_relationship(
                            child_id,
                            parent_id,
                            "PART_OF",
                            {"source": "manual_hierarchy"},
                        )
                        created += 1
                        logger.debug(f"Created PART_OF: {child_name} -> {parent_name}")

    logger.info(f"Created {created} PART_OF relationships")
    return created


def create_concept_hierarchy(db: Neo4jGraphDB):
    """Create IS_A relationships for concept hierarchy."""
    logger.info("Creating concept IS_A hierarchy...")

    # Define basic concept hierarchy based on cognitive domains
    hierarchy = {
        "cognition": [
            "perception",
            "attention",
            "memory",
            "executive function",
            "language",
            "emotion",
            "motor function",
        ],
        "perception": [
            "visual perception",
            "auditory perception",
            "somatosensory perception",
        ],
        "memory": [
            "working memory",
            "episodic memory",
            "semantic memory",
            "procedural memory",
            "short term memory",
            "long term memory",
        ],
        "attention": [
            "selective attention",
            "sustained attention",
            "divided attention",
            "spatial attention",
            "visual attention",
        ],
        "executive function": [
            "inhibition",
            "cognitive control",
            "planning",
            "decision making",
            "task switching",
        ],
        "emotion": [
            "fear",
            "anger",
            "happiness",
            "sadness",
            "disgust",
            "surprise",
            "emotional regulation",
            "empathy",
        ],
        "language": [
            "speech production",
            "speech comprehension",
            "reading",
            "writing",
            "syntax",
            "semantics",
        ],
    }

    created = 0

    # Get all concepts
    concepts = db.find_nodes(labels="Concept")
    concept_map = {}

    # Build concept map by name (case-insensitive)
    for concept_id, concept_data in concepts:
        name = concept_data.get("name", "").lower()
        if name:
            concept_map[name] = concept_id

    # Create relationships
    for parent_name, children in hierarchy.items():
        parent_name_lower = parent_name.lower()

        # Find or create parent concept
        if parent_name_lower not in concept_map:
            # Create parent concept if it doesn't exist
            parent_id = db.create_node(
                "Concept",
                {
                    "name": parent_name,
                    "definition": f"Parent concept for {parent_name} domain",
                    "source": "hierarchy",
                },
            )
            if parent_id:
                concept_map[parent_name_lower] = parent_id
        else:
            parent_id = concept_map[parent_name_lower]

        if parent_id:
            for child_name in children:
                child_name_lower = child_name.lower()

                # Look for exact match or partial match
                child_id = None
                if child_name_lower in concept_map:
                    child_id = concept_map[child_name_lower]
                else:
                    # Look for partial matches
                    for concept_name, cid in concept_map.items():
                        if (
                            child_name_lower in concept_name
                            or concept_name in child_name_lower
                        ):
                            child_id = cid
                            break

                if child_id and child_id != parent_id:
                    # Check if relationship exists
                    existing = db.find_relationships(
                        start_node=child_id, end_node=parent_id, rel_type="IS_A"
                    )

                    if not existing:
                        db.create_relationship(
                            child_id, parent_id, "IS_A", {"source": "manual_hierarchy"}
                        )
                        created += 1
                        logger.debug(f"Created IS_A: {child_name} -> {parent_name}")

    logger.info(f"Created {created} IS_A relationships")
    return created


def main():
    """Main function to create all relationships."""
    parser = argparse.ArgumentParser(description="Create all missing relationships")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--skip-uses-task",
        action="store_true",
        help="Skip creating USES_TASK relationships",
    )
    parser.add_argument(
        "--skip-activates",
        action="store_true",
        help="Skip creating ACTIVATES relationships",
    )
    parser.add_argument(
        "--skip-hierarchies",
        action="store_true",
        help="Skip creating IS_A and PART_OF hierarchies",
    )
    parser.add_argument(
        "--skip-coordinates",
        action="store_true",
        help="Skip fixing coordinate relationships",
    )

    args = parser.parse_args()

    logger.info("Connecting to Neo4j backend for relationship creation")

    # Open database
    db = require_neo4j_db(args.db_path, preload_cache=False)

    try:
        # Get initial stats
        initial_stats = db.get_stats()
        logger.info(
            f"Initial database: {initial_stats['total_nodes']} nodes, {initial_stats['total_relationships']} relationships"
        )

        # 1. Fix coordinate relationships first (needed for ACTIVATES)
        if not args.skip_coordinates:
            logger.info("\n=== Fixing coordinate relationships ===")
            fix_coordinate_relationships(args.db_path)

        # 2. Create USES_TASK relationships
        if not args.skip_uses_task:
            logger.info("\n=== Creating USES_TASK relationships ===")
            linker = StudyTaskLinker(db)
            linker.create_uses_task_relationships(
                limit=1000
            )  # Start with first 1000 studies

        # 3. Create hierarchies
        if not args.skip_hierarchies:
            logger.info("\n=== Creating concept and region hierarchies ===")
            is_a_count = create_concept_hierarchy(db)
            part_of_count = create_brain_region_hierarchy(db)

        # 4. Create ACTIVATES edges
        if not args.skip_activates:
            logger.info("\n=== Creating ACTIVATES edges ===")
            run_activation_edge_creation(
                db,
                labels=("Task", "Concept"),
                threshold=3,
                dry_run=False,
            )

        # Final stats
        final_stats = db.get_stats()
        logger.info("\n=== Final database statistics ===")
        logger.info(
            f"Total nodes: {final_stats['total_nodes']} (+{final_stats['total_nodes'] - initial_stats['total_nodes']})"
        )
        logger.info(
            f"Total relationships: {final_stats['total_relationships']} (+{final_stats['total_relationships'] - initial_stats['total_relationships']})"
        )

        logger.info("\nRelationship types:")
        for rel_type, count in sorted(final_stats["relationship_types"].items()):
            initial_count = initial_stats["relationship_types"].get(rel_type, 0)
            if count != initial_count:
                logger.info(f"  {rel_type}: {count} (+{count - initial_count})")
            else:
                logger.info(f"  {rel_type}: {count}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
