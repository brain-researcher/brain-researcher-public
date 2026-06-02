#!/usr/bin/env python3
"""
Cognitive Atlas Relationships Loader

This module creates IS_A hierarchical relationships between concepts
and MEASURES relationships between tasks and concepts from Cognitive Atlas data.

It works with the existing CognitiveAtlasLoader to enhance the knowledge graph
with proper ontological relationships.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


class CognitiveAtlasRelationshipsLoader:
    """Creates ontological relationships for Cognitive Atlas data."""

    def __init__(self, db):
        """Initialize the loader with a database connection."""
        self.db = db
        self.stats = defaultdict(int)

    def load_relationships_from_files(
        self, concepts_file: str, tasks_file: str
    ) -> dict[str, int]:
        """
        Load relationships from Cognitive Atlas JSON files.

        Args:
            concepts_file: Path to cognitive_concepts.json
            tasks_file: Path to cognitive_tasks.json

        Returns:
            Statistics dictionary
        """
        logger.info("Loading Cognitive Atlas relationships...")

        # Load concepts data
        with open(concepts_file) as f:
            concepts_data = json.load(f)

        # Load tasks data
        with open(tasks_file) as f:
            tasks_data = json.load(f)

        # Process IS_A relationships from concept hierarchies
        self._create_concept_hierarchies(concepts_data)

        # Process MEASURES relationships from task-concept mappings
        self._create_task_concept_relationships(tasks_data)

        # Create PART_OF relationships for brain regions if available
        self._create_brain_region_hierarchies()

        logger.info(f"Cognitive Atlas relationships loaded: {dict(self.stats)}")
        return dict(self.stats)

    def _create_concept_hierarchies(self, concepts_data: list[dict]):
        """Create IS_A relationships between concepts based on their hierarchy."""
        logger.info("Creating concept IS_A hierarchies...")

        # First pass: ensure all concepts exist
        concept_id_map = {}
        for concept in concepts_data:
            if isinstance(concept, dict):
                ca_id = concept.get("id", "")
                name = concept.get("name", "")

                if ca_id and name:
                    # Find existing concept node
                    existing = self.db.find_nodes("Concept", {"ca_id": ca_id})
                    if not existing:
                        existing = self.db.find_nodes("Concept", {"name": name})

                    if existing:
                        concept_id_map[ca_id] = existing[0][0]

        # Second pass: create IS_A relationships
        for concept in concepts_data:
            if isinstance(concept, dict):
                ca_id = concept.get("id", "")

                # Handle parents/is_a relationships
                parents = concept.get("parents", []) or concept.get("is_a", [])

                if ca_id in concept_id_map and parents:
                    child_node_id = concept_id_map[ca_id]

                    for parent in parents:
                        parent_id = None

                        if isinstance(parent, dict):
                            parent_id = parent.get("id", "")
                        elif isinstance(parent, str):
                            parent_id = parent

                        if parent_id and parent_id in concept_id_map:
                            parent_node_id = concept_id_map[parent_id]

                            # Check if relationship already exists
                            existing_rels = self.db.find_relationships(
                                start_node=child_node_id,
                                end_node=parent_node_id,
                                rel_type="IS_A",
                            )

                            if not existing_rels:
                                success = self.db.create_relationship(
                                    child_node_id,
                                    parent_node_id,
                                    "IS_A",
                                    {
                                        "source": "cognitive_atlas",
                                        "created_by": "cognitive_atlas_relationships_loader",
                                    },
                                )

                                if success:
                                    self.stats["IS_A_created"] += 1
                                    logger.debug(
                                        f"Created IS_A: {ca_id} -> {parent_id}"
                                    )

    def _create_task_concept_relationships(self, tasks_data: list[dict]):
        """Create MEASURES relationships between tasks and concepts."""
        logger.info("Creating task MEASURES concept relationships...")

        # Build concept lookup by name and ID
        all_concepts = self.db.find_nodes("Concept")
        concept_lookup = {}

        for concept_id, concept_data in all_concepts:
            name = concept_data.get("name", "").lower()
            ca_id = concept_data.get("ca_id", "")

            if name:
                concept_lookup[name] = concept_id
            if ca_id:
                concept_lookup[ca_id] = concept_id

        # Process each task
        for task in tasks_data:
            if isinstance(task, dict):
                task_name = task.get("name", "")
                task_ca_id = task.get("id", "")

                # Find the task node
                task_node = None
                if task_ca_id:
                    task_nodes = self.db.find_nodes("TaskDef", {"ca_id": task_ca_id})
                    if not task_nodes:
                        task_nodes = self.db.find_nodes("Task", {"ca_id": task_ca_id})

                if not task_nodes and task_name:
                    task_nodes = self.db.find_nodes("TaskDef", {"name": task_name})
                    if not task_nodes:
                        task_nodes = self.db.find_nodes("Task", {"name": task_name})

                if task_nodes:
                    task_node_id = task_nodes[0][0]

                    # Get measured concepts
                    measured_concepts = task.get("concepts", []) or task.get(
                        "measures", []
                    )

                    for concept_ref in measured_concepts:
                        concept_node_id = None

                        if isinstance(concept_ref, dict):
                            # Try by ID first
                            ref_id = concept_ref.get("id", "")
                            if ref_id and ref_id in concept_lookup:
                                concept_node_id = concept_lookup[ref_id]
                            else:
                                # Try by name
                                ref_name = concept_ref.get("name", "").lower()
                                if ref_name and ref_name in concept_lookup:
                                    concept_node_id = concept_lookup[ref_name]
                        elif isinstance(concept_ref, str):
                            # Direct ID or name reference
                            if concept_ref in concept_lookup:
                                concept_node_id = concept_lookup[concept_ref]
                            elif concept_ref.lower() in concept_lookup:
                                concept_node_id = concept_lookup[concept_ref.lower()]

                        if concept_node_id:
                            # Check if relationship exists
                            existing_rels = self.db.find_relationships(
                                start_node=task_node_id,
                                end_node=concept_node_id,
                                rel_type="MEASURES",
                            )

                            if not existing_rels:
                                success = self.db.create_relationship(
                                    task_node_id,
                                    concept_node_id,
                                    "MEASURES",
                                    {
                                        "source": "cognitive_atlas",
                                        "created_by": "cognitive_atlas_relationships_loader",
                                    },
                                )

                                if success:
                                    self.stats["MEASURES_created"] += 1
                                    logger.debug(
                                        f"Created MEASURES: {task_name} -> concept"
                                    )

    def _create_brain_region_hierarchies(self):
        """Create PART_OF relationships for brain region hierarchies."""
        logger.info("Creating brain region PART_OF hierarchies...")

        # Define some basic brain region hierarchies
        # This is a simplified example - in practice, you'd load from an atlas
        region_hierarchies = [
            ("dorsolateral prefrontal cortex", "prefrontal cortex"),
            ("ventromedial prefrontal cortex", "prefrontal cortex"),
            ("orbitofrontal cortex", "prefrontal cortex"),
            ("prefrontal cortex", "frontal lobe"),
            ("primary motor cortex", "frontal lobe"),
            ("inferior frontal gyrus", "frontal lobe"),
            ("anterior cingulate cortex", "cingulate cortex"),
            ("posterior cingulate cortex", "cingulate cortex"),
            ("cingulate cortex", "limbic system"),
            ("hippocampus", "medial temporal lobe"),
            ("amygdala", "medial temporal lobe"),
            ("entorhinal cortex", "medial temporal lobe"),
            ("medial temporal lobe", "temporal lobe"),
            ("primary visual cortex", "occipital lobe"),
            ("extrastriate cortex", "occipital lobe"),
            ("posterior parietal cortex", "parietal lobe"),
            ("intraparietal sulcus", "parietal lobe"),
            ("precuneus", "parietal lobe"),
        ]

        for child_name, parent_name in region_hierarchies:
            # Find the brain region nodes
            child_nodes = self.db.find_nodes("BrainRegion", {"name": child_name})
            parent_nodes = self.db.find_nodes("BrainRegion", {"name": parent_name})

            if child_nodes and parent_nodes:
                child_id = child_nodes[0][0]
                parent_id = parent_nodes[0][0]

                # Check if relationship exists
                existing_rels = self.db.find_relationships(
                    start_node=child_id, end_node=parent_id, rel_type="PART_OF"
                )

                if not existing_rels:
                    success = self.db.create_relationship(
                        child_id,
                        parent_id,
                        "PART_OF",
                        {
                            "source": "anatomical_ontology",
                            "created_by": "cognitive_atlas_relationships_loader",
                        },
                    )

                    if success:
                        self.stats["PART_OF_created"] += 1
                        logger.debug(f"Created PART_OF: {child_name} -> {parent_name}")


def integrate_cognitive_atlas_relationships(
    db_path: str, data_dir: str = "data/br-kg/raw"
) -> dict[str, int]:
    """
    Convenience function to integrate Cognitive Atlas relationships.

    Args:
        db_path: Path to BR-KG database
        data_dir: Directory containing cognitive atlas JSON files
    """
    import os
    import sys

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    from graph.graph_database import BRKGGraphDB

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Load database
    logger.info(f"Loading database: {db_path}")
    db = BRKGGraphDB(db_path)

    # Find cognitive atlas files
    data_path = Path(data_dir)
    concepts_file = data_path / "cognitive_concepts.json"
    tasks_file = data_path / "cognitive_tasks.json"

    if not concepts_file.exists() or not tasks_file.exists():
        logger.error(f"Cognitive Atlas files not found in {data_dir}")
        logger.error("Please run init_database.py first to fetch the data")
        return {}

    # Load relationships
    loader = CognitiveAtlasRelationshipsLoader(db)
    stats = loader.load_relationships_from_files(str(concepts_file), str(tasks_file))

    # Get final database stats
    db_stats = db.get_stats()
    logger.info(f"Final database stats: {db_stats}")

    db.close()

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Load Cognitive Atlas relationships into BR-KG"
    )
    parser.add_argument("db_path", help="Path to BR-KG database")
    parser.add_argument(
        "--data-dir",
        default="data/br-kg/raw",
        help="Directory containing cognitive atlas JSON files",
    )

    args = parser.parse_args()

    stats = integrate_cognitive_atlas_relationships(args.db_path, args.data_dir)
    print(f"\nCompleted! Statistics: {stats}")
