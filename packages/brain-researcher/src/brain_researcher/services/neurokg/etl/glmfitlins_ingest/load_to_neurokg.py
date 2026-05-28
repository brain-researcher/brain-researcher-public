#!/usr/bin/env python3
"""Load GLM FitLins data into BR-KG database."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any

from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MANIFEST = Path("data/etl_cache/glmfitlins_ingest/dataset_manifest.csv")
CONTRASTS_RAW = Path("data/etl_cache/glmfitlins_ingest/contrasts_raw.csv")


def load_datasets(manifest_path: Path = MANIFEST) -> dict[str, dict[str, Any]]:
    """Load dataset information from manifest."""
    datasets: dict[str, dict[str, Any]] = {}
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return datasets

    with manifest_path.open() as f:
        for row in csv.DictReader(f):
            datasets[row["dataset_id"]] = {
                "spec_hash": row["spec_hash"],
                "annotation_path": row["annotation_path"],
                "spec_path": row["spec_path"],
                "task_label": row.get("task_label", ""),
            }
    return datasets


def _discover_annotation_path(dataset_id: str, task_label: str) -> Path | None:
    roots = [
        Path("llm_cognitive_function/data/processed_with_direction"),
        Path("llm_cogitive_function/data/processed_with_direction"),
    ]
    patterns = [
        f"{dataset_id}_{task_label}_annotations_with_lit.json",
        f"{dataset_id}_{task_label.replace('_', '')}_annotations_with_lit.json",
        f"{dataset_id}_{task_label.replace('-', '_')}_annotations_with_lit.json",
    ]
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            candidate = root / pattern
            if candidate.exists():
                return candidate
        for candidate in root.glob(f"{dataset_id}_*_annotations_with_lit.json"):
            parts = candidate.stem.split("_")
            if len(parts) > 1 and len(parts[1]) == 40:
                continue
            return candidate
    return None


def load_contrasts(contrasts_path: Path = CONTRASTS_RAW) -> list[dict[str, str]]:
    """Load contrast information."""
    contrasts = []
    if not contrasts_path.exists():
        logger.error(f"Contrasts file not found: {contrasts_path}")
        return contrasts

    with contrasts_path.open() as f:
        contrasts = list(csv.DictReader(f))
    return contrasts


def load_to_neurokg(
    manifest_path: Path = MANIFEST,
    contrasts_path: Path = CONTRASTS_RAW,
    db_path: Path | None = None,
) -> None:
    """Load GLM FitLins data into BR-KG.

    By default, loads into Neo4j (configured via NEO4J_* env vars).
    When db_path is provided, uses the SQLite-backed NeuroKGGraphDB (useful for
    offline runs and unit tests).
    """

    # Initialize database
    if db_path:
        db = NeuroKGGraphDB(str(db_path))
        logger.info("Connected to SQLite backend for GLM FitLins load: %s", db_path)
    else:
        db = require_neo4j_db(preload_cache=False)
        logger.info("Connected to Neo4j backend for GLM FitLins load")

    # Load data
    datasets = load_datasets(manifest_path)
    contrasts = load_contrasts(contrasts_path)

    if not datasets:
        logger.error("No datasets found to load")
        return

    # Create dataset nodes and associated publications
    dataset_nodes = {}
    dataset_publications = {}
    for ds_id, info in datasets.items():
        # Extract DOI from basic details if available
        details_path = Path(info["spec_path"]).parent / f"{ds_id}_basic-details.json"
        doi = ""
        dataset_name = ds_id

        if details_path.exists():
            try:
                details = json.loads(details_path.read_text())
                tasks = details.get("Tasks", {})
                for t in tasks.values():
                    links = t.get("cite_links")
                    if links:
                        doi = links[0]
                        break
                # Try to get a better name
                if "Name" in details:
                    dataset_name = details["Name"]
            except Exception as e:
                logger.warning(f"Failed to load details for {ds_id}: {e}")

        # Create dataset node
        node_id = db.create_node(
            labels=["Dataset", "OpenNeuro"],
            properties={
                "dataset_id": ds_id,
                "name": dataset_name,
                "doi": doi,
                "spec_hash": info["spec_hash"],
                "source": "openneuro_glmfitlins",
            },
        )
        dataset_nodes[ds_id] = node_id

        # Create or get publication node
        pub_node = None
        if doi:
            try:
                existing = db.find_nodes("Study", {"doi": doi})
                if existing:
                    pub_node = existing[0][0]
                    logger.debug(f"Found existing publication node for DOI {doi}")
                else:
                    pub_node = db.create_node(
                        labels=["Study"],
                        properties={"doi": doi, "title": doi},
                    )
                    logger.debug(f"Created new publication node for DOI {doi}")
            except Exception as e:
                logger.warning(
                    f"Failed to create/find publication node for DOI {doi}: {e}"
                )

        if pub_node:
            dataset_publications[ds_id] = pub_node

        logger.info(f"Created dataset node: {ds_id} -> {node_id}")

    # Create task and contrast nodes and relationships
    contrast_nodes = {}
    task_nodes: dict[tuple[str, str], str] = {}
    for contrast in contrasts:
        ds_id = contrast["dataset_id"]
        contrast_name = contrast["contrast_name"]
        task_label = contrast["task_label"]

        if ds_id not in dataset_nodes:
            logger.warning(
                f"Dataset {ds_id} not found, skipping contrast {contrast_name}"
            )
            continue

        task_key = (ds_id, task_label)
        task_node_id = task_nodes.get(task_key)
        if not task_node_id:
            existing = db.find_nodes("TaskSpec", {"name": task_label, "dataset": ds_id})
            if existing:
                task_node_id = existing[0][0]
            else:
                task_spec_id = f"{ds_id}_task-{task_label}"
                task_node_id = db.create_node(
                    labels=["TaskSpec"],
                    properties={
                        "id": task_spec_id,
                        "name": task_label,
                        "dataset": ds_id,
                        "source": "openneuro_glmfitlins",
                    },
                    node_id=task_spec_id,
                )
                db.create_relationship(
                    start_node=dataset_nodes[ds_id],
                    end_node=task_node_id,
                    rel_type="HAS_TASK",
                    properties={"task_name": task_label},
                )
            task_nodes[task_key] = task_node_id

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

        # Create relationship to dataset
        db.create_relationship(
            start_node=dataset_nodes[ds_id],
            end_node=node_id,
            rel_type="HAS_CONTRAST",
            properties={"task": task_label},
        )
        if task_node_id:
            db.create_relationship(
                start_node=task_node_id,
                end_node=node_id,
                rel_type="HAS_CONTRAST",
                properties={"task": task_label},
            )

        # Create relationship to publication if available
        if ds_id in dataset_publications:
            db.create_relationship(
                start_node=node_id,
                end_node=dataset_publications[ds_id],
                rel_type="BELONGS_TO",
            )
            logger.debug("Created BELONGS_TO relationship from contrast to publication")

        logger.debug(f"Created contrast: {contrast_key} -> {node_id}")

    # Load cognitive annotations
    annotation_count = 0
    annotations_loaded = 0
    annotations_missing = 0
    annotations_skipped_dir = 0
    annotations_failed = 0
    annotations_autodiscovered = 0
    for ds_id, info in datasets.items():
        ann_raw = info.get("annotation_path")
        task_label = info.get("task_label", "")
        if not ann_raw:
            candidate = _discover_annotation_path(ds_id, task_label)
            if candidate:
                ann_raw = str(candidate)
                annotations_autodiscovered += 1
            else:
                annotations_missing += 1
                logger.warning(f"No annotations path configured for {ds_id}")
                continue
        ann_path = Path(ann_raw)
        if ann_path.is_dir():
            candidate = _discover_annotation_path(ds_id, task_label)
            if candidate:
                ann_path = candidate
                annotations_autodiscovered += 1
            else:
                annotations_skipped_dir += 1
                logger.warning(
                    "Annotation path is a directory for %s; skipping (%s)",
                    ds_id,
                    ann_path,
                )
                continue
        if not ann_path.exists():
            candidate = _discover_annotation_path(ds_id, task_label)
            if candidate:
                ann_path = candidate
                annotations_autodiscovered += 1
            else:
                annotations_missing += 1
                logger.warning(f"No annotations found for {ds_id}")
                continue

        try:
            data = json.loads(ann_path.read_text())
            version = data.get("version_hash", "")
            annotations = data.get(
                "annotations", data if isinstance(data, list) else []
            )
        except Exception as e:
            annotations_failed += 1
            logger.error(f"Failed to load annotations for {ds_id}: {e}")
            continue
        annotations_loaded += 1

        for ann in annotations:
            contrast_name = ann.get("contrast_name")
            contrast_key = f"{ds_id}:{contrast_name}"

            if contrast_key not in contrast_nodes:
                logger.warning(
                    f"Contrast {contrast_key} not found, skipping annotations"
                )
                continue

            contrast_node_id = contrast_nodes[contrast_key]

            for construct in ann.get("constructs", []):
                construct_id = construct.get("id")
                construct_name = construct.get("name")

                if not construct_id or not construct_name:
                    continue

                # Create or find cognitive construct node
                existing = db.find_nodes(
                    labels=["CognitiveConstruct"],
                    properties={"construct_id": construct_id},
                )

                if existing:
                    construct_node_id = existing[0][0]
                else:
                    construct_node_id = db.create_node(
                        labels=["CognitiveConstruct", "Concept"],
                        properties={
                            "construct_id": construct_id,
                            "name": construct_name,
                            "source": "cognitive_atlas",
                        },
                    )
                    logger.debug(
                        f"Created construct: {construct_name} -> {construct_node_id}"
                    )

                # Create relationship with confidence scores
                db.create_relationship(
                    start_node=contrast_node_id,
                    end_node=construct_node_id,
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
                        "version_hash": version,
                    },
                )
                annotation_count += 1

    # Report stats
    stats = db.get_stats()

    logger.info(
        f"""
    GLM FitLins Data Loading Complete:
    - Datasets loaded: {len(dataset_nodes)}
    - Contrasts created: {len(contrast_nodes)}
    - Annotations created: {annotation_count}
    - Annotations loaded: {annotations_loaded}
    - Annotations missing: {annotations_missing}
    - Annotations skipped (dir): {annotations_skipped_dir}
    - Annotations failed: {annotations_failed}
    - Annotations auto-discovered: {annotations_autodiscovered}
    - Total nodes: {stats['total_nodes']}
    - Total relationships: {stats['total_relationships']}
    """
    )

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load GLM FitLins data into BR-KG")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--contrasts", type=Path, default=CONTRASTS_RAW)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    args = parser.parse_args()

    load_to_neurokg(args.manifest, args.contrasts, args.db_path)
