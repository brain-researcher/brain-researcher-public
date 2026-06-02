#!/usr/bin/env python3
"""Load GLM FitLins data with existing annotations into BR-KG."""

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from brain_researcher.services.br_kg.etl.mappers.cross_source_linker import (
    CrossSourceLinker,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
MANIFEST = Path("../etl/glmfitlins_ingest/dataset_manifest.csv")
CONTRASTS_RAW = Path("../etl/glmfitlins_ingest/contrasts_raw.csv")
ANNOT_DIR = Path("../../llm_cogitive_function/data/processed_with_direction")


def load_all_annotations():
    """Load all annotation files grouped by dataset."""
    dataset_annotations = defaultdict(list)

    for annot_file in ANNOT_DIR.glob("*.json"):
        try:
            with open(annot_file) as f:
                data = json.load(f)

            # Extract dataset ID from filename
            filename = annot_file.name
            dataset_id = filename.split("_")[0]

            # Handle both formats
            if isinstance(data, list):
                annotations = data
            elif isinstance(data, dict) and "annotations" in data:
                annotations = data["annotations"]
            else:
                continue

            dataset_annotations[dataset_id].extend(annotations)

        except Exception as e:
            logger.warning(f"Error loading {annot_file}: {e}")

    return dict(dataset_annotations)


def main():
    """Main function to load data into BR-KG."""

    # Initialize database
    db = require_neo4j_db(preload_cache=False)
    logger.info("Connected to Neo4j backend for GLM FitLins load")

    # Load contrasts
    contrasts = []
    with open(CONTRASTS_RAW) as f:
        contrasts = list(csv.DictReader(f))
    logger.info(f"Loaded {len(contrasts)} contrasts")

    # Load annotations
    dataset_annotations = load_all_annotations()
    logger.info(f"Loaded annotations for {len(dataset_annotations)} datasets")

    # Create dataset nodes
    dataset_nodes = {}
    for dataset_id in dataset_annotations.keys():
        node_id = db.create_node(
            labels=["Dataset", "OpenNeuro"],
            properties={
                "dataset_id": dataset_id,
                "name": dataset_id,
                "source": "openneuro_glmfitlins",
            },
        )
        dataset_nodes[dataset_id] = node_id
        logger.info(f"Created dataset node: {dataset_id}")

    # Create contrast nodes
    contrast_nodes = {}
    for contrast in contrasts:
        ds_id = contrast["dataset_id"]
        contrast_name = contrast["contrast_name"]
        task_label = contrast["task_label"]

        if ds_id not in dataset_nodes:
            # Create dataset if not exists
            node_id = db.create_node(
                labels=["Dataset", "OpenNeuro"],
                properties={
                    "dataset_id": ds_id,
                    "name": ds_id,
                    "source": "openneuro_glmfitlins",
                },
            )
            dataset_nodes[ds_id] = node_id

        # Create contrast node
        contrast_key = f"{ds_id}:{contrast_name}"
        node_id = db.create_node(
            labels=["Contrast", "GLMContrast"],
            properties={
                "name": contrast_name,
                "task_label": task_label,
                "dataset_id": ds_id,
                "source": "openneuro_glmfitlins",
            },
        )
        contrast_nodes[contrast_key] = node_id

        # Link to dataset
        db.create_relationship(
            start_node=dataset_nodes[ds_id],
            end_node=node_id,
            rel_type="HAS_CONTRAST",
            properties={"task": task_label},
        )

    logger.info(f"Created {len(contrast_nodes)} contrast nodes")

    # Create cognitive construct nodes and relationships
    construct_nodes = {}
    annotation_count = 0

    for dataset_id, annotations in dataset_annotations.items():
        for ann in annotations:
            contrast_name = ann.get("contrast_name")
            contrast_key = f"{dataset_id}:{contrast_name}"

            if contrast_key not in contrast_nodes:
                continue

            contrast_node_id = contrast_nodes[contrast_key]

            for construct in ann.get("constructs", []):
                construct_id = construct.get("id")
                construct_name = construct.get("name")

                if not construct_id or not construct_name:
                    continue

                # Create or find construct node
                if construct_id not in construct_nodes:
                    node_id = db.create_node(
                        labels=["CognitiveConstruct", "Concept"],
                        properties={
                            "construct_id": construct_id,
                            "name": construct_name,
                            "source": "cognitive_atlas",
                        },
                    )
                    construct_nodes[construct_id] = node_id
                else:
                    node_id = construct_nodes[construct_id]

                # Create relationship
                db.create_relationship(
                    start_node=contrast_node_id,
                    end_node=node_id,
                    rel_type="INVOLVES_CONSTRUCT",
                    properties={
                        "direction": construct.get("direction", "+1"),
                        "llm_confidence": float(construct.get("llm_confidence", 0)),
                        "literature_confidence": float(
                            construct.get("literature_confidence", 0)
                        ),
                        "overall_confidence": float(
                            construct.get("overall_confidence", 0)
                        ),
                    },
                )
                annotation_count += 1

    # Run cross-source linking
    logger.info("Running cross-source linking...")
    cross_linker = CrossSourceLinker(db, auto_link=True, dry_run=False)

    # Link after loading GLM FitLins data
    links_created = cross_linker.link_after_source_load("openneuro")
    logger.info(f"Created {links_created} MAPS_TO relationships")

    # Report stats
    stats = db.get_stats()

    logger.info(
        f"""
    GLM FitLins Data Loading Complete:
    - Datasets: {len(dataset_nodes)}
    - Contrasts: {len(contrast_nodes)}
    - Constructs: {len(construct_nodes)}
    - Annotations: {annotation_count}
    - Total nodes: {stats['total_nodes']}
    - Total relationships: {stats['total_relationships']}
    - MAPS_TO relationships created: {links_created}
    """
    )

    # Show cross-source linking report
    logger.info("\nCross-Source Linking Report:")
    logger.info(cross_linker.get_linking_report())

    db.close()


if __name__ == "__main__":
    main()
