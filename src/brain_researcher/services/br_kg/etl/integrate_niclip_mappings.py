#!/usr/bin/env python3
"""
NiCLIP Integration Script

This script demonstrates the full workflow of:
1. Loading TaskSpec nodes from OpenNeuro
2. Mapping them to TaskDef nodes using NiCLIP synonyms
3. Creating HAS_CONCEPT edges from Contrasts to Concepts

Author: BR-KG Team
"""

import logging
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_loader import CognitiveAtlasLoader
from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.fitlins_loader import OpenNeuroFitLinsLoader
from brain_researcher.services.br_kg.etl.mappers.contrast_concept_linker import ContrastConceptLinker
from brain_researcher.services.br_kg.etl.mappers.task_mapper import TaskMapper
from graph.graph_database import BRKGGraphDB

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main integration workflow"""

    # Initialize database
    db_path = "data/br-kg/db/br_kg_integrated.db"
    logger.info(f"Initializing BR-KG database at {db_path}")
    db = BRKGGraphDB(db_path)

    # Create constraints
    logger.info("Creating database constraints...")
    db.create_constraint("Dataset", "id", "UNIQUE")
    db.create_constraint("TaskSpec", "id", "UNIQUE")
    db.create_constraint("TaskDef", "id", "UNIQUE")
    db.create_constraint("Contrast", "id", "UNIQUE")
    db.create_constraint("Concept", "id", "UNIQUE")

    # Step 1: Load Cognitive Atlas data
    logger.info("\n=== Step 1: Loading Cognitive Atlas data ===")
    cog_loader = CognitiveAtlasLoader(db)

    # Load concepts
    concepts_loaded = cog_loader.load_concepts_from_json(
        "data/cognitive_atlas/cognitive_concepts.json"
    )
    logger.info(f"Loaded {concepts_loaded} concepts")

    # Load tasks (TaskDef nodes)
    tasks_loaded = cog_loader.load_tasks_from_json(
        "data/cognitive_atlas/cognitive_tasks.json"
    )
    logger.info(f"Loaded {tasks_loaded} tasks")

    # Get all TaskDef nodes for mapping
    task_def_nodes = db.find_nodes("TaskDef")
    logger.info(f"Found {len(task_def_nodes)} TaskDef nodes in database")

    # Step 2: Load OpenNeuro dataset with FitLins
    logger.info("\n=== Step 2: Loading OpenNeuro dataset ===")
    fitlins_loader = OpenNeuroFitLinsLoader(db)

    # Load a sample dataset
    dataset_id = fitlins_loader.load_dataset("ds000002")
    if dataset_id:
        logger.info(f"Successfully loaded dataset {dataset_id}")
    else:
        logger.error("Failed to load dataset")
        return

    # Get TaskSpec nodes that need mapping
    task_spec_nodes = db.find_nodes("TaskSpec")
    logger.info(f"Found {len(task_spec_nodes)} TaskSpec nodes to map")

    # Step 3: Map TaskSpecs to TaskDefs using NiCLIP
    logger.info("\n=== Step 3: Mapping TaskSpecs to TaskDefs ===")

    # Initialize mapper
    mapper = TaskMapper()
    mapper.set_task_definitions(task_def_nodes)

    # Map each TaskSpec
    mapping_count = 0
    for task_spec_id, task_spec_data in task_spec_nodes:
        task_name = task_spec_data.get("name", "")

        mapping_result = mapper.map_task(task_name, task_spec_data)

        if mapping_result:
            # Create MAPS_TO relationship
            success = db.create_relationship(
                task_spec_id,
                mapping_result["task_def_id"],
                "MAPS_TO",
                {
                    "match_type": mapping_result["match_type"],
                    "confidence": mapping_result["confidence"],
                    "mapping_source": "niclip_integration",
                },
            )

            if success:
                mapping_count += 1
                logger.info(
                    f"Mapped '{task_name}' -> TaskDef "
                    f"({mapping_result['match_type']}, "
                    f"confidence: {mapping_result['confidence']:.2f})"
                )

    logger.info(f"Created {mapping_count} TaskSpec->TaskDef mappings")

    # Print mapping statistics
    logger.info("\nMapping Statistics:")
    logger.info(mapper.get_stats_summary())

    # Save unmatched tasks for review
    mapper.save_unmatched_log("logs/niclip_unmatched_tasks.tsv")
    mapper.save_stats("logs/niclip_mapping_stats.json")

    # Step 4: Link Contrasts to Concepts
    logger.info("\n=== Step 4: Linking Contrasts to Concepts ===")

    # Initialize contrast linker
    contrast_linker = ContrastConceptLinker()

    # Get all contrast and concept nodes
    contrast_nodes = db.find_nodes("Contrast")
    concept_nodes = db.find_nodes("Concept")

    logger.info(
        f"Found {len(contrast_nodes)} contrasts and {len(concept_nodes)} concepts"
    )

    # Link contrasts to concepts
    edges = contrast_linker.link_batch(contrast_nodes, concept_nodes)

    # Create the edges in the database
    edge_count = 0
    for edge_spec in edges:
        success = db.create_relationship(
            edge_spec["start_node"],
            edge_spec["end_node"],
            edge_spec["type"],
            edge_spec["properties"],
        )

        if success:
            edge_count += 1

    logger.info(f"Created {edge_count} Contrast->Concept edges")

    # Print linking statistics
    logger.info("\nContrast Linking Statistics:")
    logger.info(contrast_linker.get_stats_summary())

    # Step 5: Print final database statistics
    logger.info("\n=== Final Database Statistics ===")
    stats = db.get_stats()

    logger.info(f"Total nodes: {stats['total_nodes']}")
    logger.info(f"Total relationships: {stats['total_relationships']}")

    logger.info("\nNodes by type:")
    for label, count in sorted(stats["node_labels"].items()):
        logger.info(f"  {label}: {count}")

    logger.info("\nRelationships by type:")
    for rel_type, count in sorted(stats["relationship_types"].items()):
        logger.info(f"  {rel_type}: {count}")

    # Close database
    db.close()
    logger.info("\nIntegration completed successfully!")


if __name__ == "__main__":
    # Ensure required directories exist
    Path("data/br-kg/db").mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)

    # Run integration
    main()
