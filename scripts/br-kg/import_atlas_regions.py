#!/usr/bin/env python3
"""
Import atlas parcellation regions into Neo4j as BrainRegion nodes.

This script loads atlas label images (AAL, Schaefer-400, Yeo-17) using nilearn,
computes centroids for each label, and creates/updates BrainRegion nodes in Neo4j.

Usage:
    NEO4J_URI=bolt://localhost:7687 python scripts/br-kg/import_atlas_regions.py \
        --atlases aal schaefer400 yeo17
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
from nilearn import datasets

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client
from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    default_atlas_output_root,
    existing_search_roots,
    resolve_local_volume_atlas,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Yeo 17-network label names (from Yeo et al., 2011)
YEO17_LABELS = {
    1: "VisCent",
    2: "VisPeri",
    3: "SomMotA",
    4: "SomMotB",
    5: "DorsAttnA",
    6: "DorsAttnB",
    7: "SalVentAttnA",
    8: "SalVentAttnB",
    9: "LimbicA",
    10: "LimbicB",
    11: "ContA",
    12: "ContB",
    13: "ContC",
    14: "DefaultA",
    15: "DefaultB",
    16: "DefaultC",
    17: "TempPar",
}


def _atlas_search_roots() -> list[Path]:
    return existing_search_roots(None, default_atlas_output_root())


def _strip_background(labels: list[object]) -> list[str]:
    normalized = [
        label.decode("utf-8") if isinstance(label, bytes) else str(label)
        for label in labels
    ]
    if normalized and normalized[0].strip().lower() in {
        "background",
        "none",
        "unknown",
        "???",
        "medial_wall",
    }:
        return normalized[1:]
    return normalized


def compute_centroids_from_nifti(
    img_path: str, labels_dict: dict[int, str] | None = None
) -> list[dict]:
    """
    Compute centroids for each label in a NIfTI parcellation image.

    Args:
        img_path: Path to the NIfTI label image
        labels_dict: Optional dict mapping label index -> name

    Returns:
        List of dicts with keys: label_index, name, x, y, z
    """
    img = nib.load(img_path)
    data = np.asarray(img.dataobj)

    # Handle 4D images (take first volume)
    if data.ndim == 4:
        data = data[:, :, :, 0]

    data = data.astype(int)
    affine = img.affine

    unique_labels = np.unique(data)
    unique_labels = unique_labels[unique_labels > 0]  # Skip background (0)

    regions = []
    for label_idx in unique_labels:
        # Find all voxels with this label
        mask = data == label_idx
        voxel_coords = np.array(np.where(mask)).T  # Shape: (N, 3)

        if len(voxel_coords) == 0:
            continue

        # Compute centroid in voxel space
        centroid_voxel = voxel_coords.mean(axis=0)

        # Convert to MNI space using affine (manual transform)
        # affine is 4x4, centroid is 3D
        centroid_homog = np.append(centroid_voxel, 1.0)  # Make it homogeneous [x,y,z,1]
        centroid_mni = affine @ centroid_homog
        centroid_mni = centroid_mni[:3]  # Extract x,y,z

        # Get name from labels dict or use generic name
        name = (
            labels_dict.get(int(label_idx), f"Region_{label_idx}")
            if labels_dict
            else f"Region_{label_idx}"
        )

        regions.append(
            {
                "label_index": int(label_idx),
                "name": name,
                "x": float(centroid_mni[0]),
                "y": float(centroid_mni[1]),
                "z": float(centroid_mni[2]),
            }
        )

    return regions


def load_aal_atlas() -> tuple[str, dict[int, str]]:
    """Load AAL atlas and return path + label names."""
    try:
        img_path, labels, _ = resolve_local_volume_atlas("aal", _atlas_search_roots())
        atlas_labels = _strip_background(labels)
        labels_dict = {idx: name for idx, name in enumerate(atlas_labels, start=1)}
        logger.info("Resolved AAL atlas from local atlas roots")
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        logger.info("Fetching AAL atlas from nilearn...")
        aal = datasets.fetch_atlas_aal(
            data_dir=str(default_atlas_output_root() / "aal")
        )
        img_path = aal.maps
        atlas_labels = _strip_background(list(aal.labels))
        labels_dict = {int(idx): name for idx, name in zip(aal.indices, atlas_labels)}

    logger.info(f"AAL atlas: {len(labels_dict)} regions")
    return str(img_path), labels_dict


def load_schaefer400_atlas() -> tuple[str, dict[int, str]]:
    """Load Schaefer 400-parcel 7-network atlas."""
    try:
        img_path, labels, _ = resolve_local_volume_atlas(
            "Schaefer2018_400",
            _atlas_search_roots(),
        )
        atlas_labels = _strip_background(labels)
        labels_dict = {i + 1: name for i, name in enumerate(atlas_labels)}
        logger.info("Resolved Schaefer atlas from local atlas roots")
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        logger.info("Fetching Schaefer 400-parcel atlas from nilearn...")
        schaefer = datasets.fetch_atlas_schaefer_2018(
            n_rois=400,
            yeo_networks=7,
            resolution_mm=2,
            data_dir=str(default_atlas_output_root() / "schaefer_2018"),
        )
        img_path = schaefer.maps
        atlas_labels = _strip_background(list(schaefer.labels))
        labels_dict = {i + 1: name for i, name in enumerate(atlas_labels)}

    logger.info(f"Schaefer atlas: {len(labels_dict)} regions")
    return str(img_path), labels_dict


def load_yeo17_atlas() -> tuple[str, dict[int, str]]:
    """Load Yeo 17-network atlas."""
    try:
        img_path, labels, _ = resolve_local_volume_atlas("yeo17", _atlas_search_roots())
        atlas_labels = _strip_background(labels)
        labels_dict = {i + 1: name for i, name in enumerate(atlas_labels)}
        logger.info("Resolved Yeo17 atlas from local atlas roots")
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        logger.info("Fetching Yeo 2011 atlas from nilearn...")
        yeo = datasets.fetch_atlas_yeo_2011(
            n_networks=17,
            thickness="thick",
            data_dir=str(default_atlas_output_root() / "yeo_2011"),
        )
        img_path = getattr(yeo, "maps", None) or getattr(yeo, "thick_17", None)
        if img_path is None:
            raise FileNotFoundError("Yeo17 atlas maps not available from nilearn")
        labels_dict = YEO17_LABELS

    logger.info(f"Yeo17 atlas: {len(labels_dict)} networks")
    return str(img_path), labels_dict


def import_atlas_to_neo4j(
    db, atlas_name: str, img_path: str, labels_dict: dict[int, str]
) -> int:
    """
    Import atlas regions as BrainRegion nodes into Neo4j.

    Args:
        db: Neo4j database client
        atlas_name: Name of the atlas (e.g., "AAL", "Schaefer400", "Yeo17")
        img_path: Path to the NIfTI label image
        labels_dict: Dict mapping label index -> region name

    Returns:
        Number of regions imported
    """
    logger.info(f"Computing centroids for {atlas_name}...")
    regions = compute_centroids_from_nifti(img_path, labels_dict)
    logger.info(f"Found {len(regions)} regions with non-zero voxels")

    imported = 0
    for region in regions:
        node_id = f"{atlas_name.lower()}:{region['label_index']}"

        # Use MERGE via raw Cypher query
        query = """
        MERGE (r:BrainRegion {id: $id})
        ON CREATE SET r.name = $name, r.atlas = $atlas, r.label_index = $label_index,
                      r.space = $space, r.x = $x, r.y = $y, r.z = $z
        ON MATCH SET r.name = $name, r.atlas = $atlas, r.label_index = $label_index,
                     r.space = $space, r.x = $x, r.y = $y, r.z = $z
        RETURN r.id as id
        """
        params = {
            "id": node_id,
            "name": region["name"],
            "atlas": atlas_name,
            "label_index": region["label_index"],
            "space": "MNI152",
            "x": round(region["x"], 2),
            "y": round(region["y"], 2),
            "z": round(region["z"], 2),
        }

        try:
            result = db.execute_query(query, params)
            if result:
                imported += 1
        except Exception as e:
            logger.warning(f"Failed to import region {node_id}: {e}")

    logger.info(f"Imported/merged {imported} BrainRegion nodes for {atlas_name}")
    return imported


def ensure_constraint(db) -> None:
    """Ensure uniqueness constraint on BrainRegion.id exists."""
    try:
        # Try to create constraint (will fail silently if exists)
        db.execute_query(
            "CREATE CONSTRAINT brainregion_id_unique IF NOT EXISTS "
            "FOR (r:BrainRegion) REQUIRE r.id IS UNIQUE"
        )
        logger.info("Created/verified uniqueness constraint on BrainRegion.id")
    except Exception as e:
        logger.warning(f"Could not create constraint (may already exist): {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Import atlas parcellation regions into Neo4j"
    )
    parser.add_argument(
        "--atlases",
        nargs="+",
        choices=["aal", "schaefer400", "yeo17", "all"],
        default=["all"],
        help="Atlases to import (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute centroids, don't write to Neo4j",
    )

    args = parser.parse_args()

    # Expand "all" to list of atlases
    atlases = args.atlases
    if "all" in atlases:
        atlases = ["aal", "schaefer400", "yeo17"]

    # Connect to Neo4j
    if not args.dry_run:
        db = create_graph_client(allow_sqlite_mock=False)
        logger.info(f"Connected to graph backend: {type(db).__name__}")
        ensure_constraint(db)
    else:
        db = None
        logger.info("DRY RUN - will not write to database")

    total_imported = 0

    try:
        for atlas in atlases:
            if atlas == "aal":
                img_path, labels_dict = load_aal_atlas()
                atlas_name = "AAL"
            elif atlas == "schaefer400":
                img_path, labels_dict = load_schaefer400_atlas()
                atlas_name = "Schaefer400"
            elif atlas == "yeo17":
                img_path, labels_dict = load_yeo17_atlas()
                atlas_name = "Yeo17"
            else:
                logger.warning(f"Unknown atlas: {atlas}")
                continue

            if args.dry_run:
                regions = compute_centroids_from_nifti(img_path, labels_dict)
                logger.info(
                    f"[DRY RUN] Would import {len(regions)} regions for {atlas_name}"
                )
                for r in regions[:5]:
                    logger.info(
                        f"  - {r['name']}: ({r['x']:.1f}, {r['y']:.1f}, {r['z']:.1f})"
                    )
            else:
                count = import_atlas_to_neo4j(db, atlas_name, img_path, labels_dict)
                total_imported += count

    finally:
        if db:
            db.close()

    logger.info(f"\nTotal BrainRegion nodes imported/merged: {total_imported}")


if __name__ == "__main__":
    main()
