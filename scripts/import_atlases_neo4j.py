#!/usr/bin/env python3
"""Import atlas label maps into Neo4j as BrainRegion nodes with centroids.

Atlases: AAL, Schaefer2018 400Parcels 7Networks, Yeo17 (volumetric).

Requires: nilearn, nibabel, neo4j, numpy.
Uses Neo4j env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
"""

import os
import numpy as np
import nibabel as nib
from nilearn import datasets, image
from neo4j import GraphDatabase

from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    default_atlas_output_root,
    existing_search_roots,
    resolve_local_volume_atlas,
)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
SPACE = "MNI"

BATCH = []


def _atlas_search_roots():
    return existing_search_roots(None, default_atlas_output_root())


def _strip_background(labels):
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


def center_of_mass(img, label):
    data = img.get_fdata()
    mask = data == label
    if not mask.any():
        return None
    coords = np.argwhere(mask)
    mm = nib.affines.apply_affine(img.affine, coords).mean(axis=0)
    return mm.tolist()


def add_region(atlas, label_name, label_idx, coords):
    if coords is None:
        return
    node_id = f"{atlas}:{label_idx}"
    BATCH.append(
        {
            "id": node_id,
            "name": label_name,
            "atlas": atlas,
            "label_index": int(label_idx),
            "space": SPACE,
            "x": float(coords[0]),
            "y": float(coords[1]),
            "z": float(coords[2]),
        }
    )


def import_aal():
    try:
        atlas_path, labels, _ = resolve_local_volume_atlas("aal", _atlas_search_roots())
        img = image.load_img(str(atlas_path))
        atlas_labels = _strip_background(labels)
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        aal = datasets.fetch_atlas_aal(
            data_dir=str(default_atlas_output_root() / "aal")
        )
        img = image.load_img(aal.maps)
        atlas_labels = _strip_background(aal.labels)

    for idx, label in enumerate(atlas_labels, start=1):
        coords = center_of_mass(img, idx)
        add_region("AAL", label, idx, coords)


def import_schaefer():
    try:
        atlas_path, labels, _ = resolve_local_volume_atlas(
            "Schaefer2018_400",
            _atlas_search_roots(),
        )
        img = image.load_img(str(atlas_path))
        atlas_labels = _strip_background(labels)
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        sch = datasets.fetch_atlas_schaefer_2018(
            n_rois=400,
            yeo_networks=7,
            data_dir=str(default_atlas_output_root() / "schaefer_2018"),
        )
        img = image.load_img(sch.maps)
        atlas_labels = _strip_background(sch.labels)

    for idx, label in enumerate(atlas_labels, start=1):
        coords = center_of_mass(img, idx)
        add_region("Schaefer400-7N", label, idx, coords)


def import_yeo17():
    try:
        atlas_path, labels, _ = resolve_local_volume_atlas(
            "yeo17", _atlas_search_roots()
        )
        img = image.load_img(str(atlas_path))
        atlas_labels = _strip_background(labels)
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        yeo = datasets.fetch_atlas_yeo_2011(
            n_networks=17,
            thickness="thick",
            data_dir=str(default_atlas_output_root() / "yeo_2011"),
        )
        maps = getattr(yeo, "maps", None) or getattr(yeo, "thick_17", None)
        labels = getattr(yeo, "labels", None)
        if maps is None or labels is None:
            print("Yeo17 maps/labels not found; skipping")
            return
        img = image.load_img(maps)
        atlas_labels = _strip_background(labels)

    for idx, label in enumerate(atlas_labels, start=1):
        coords = center_of_mass(img, idx)
        add_region("Yeo17", label, idx, coords)


def write_to_neo4j():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with drv.session() as sess:
        sess.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:BrainRegion) REQUIRE r.id IS UNIQUE"
        )
        query = """
        UNWIND $rows AS row
        MERGE (r:BrainRegion {id: row.id})
        SET r.name = row.name,
            r.atlas = row.atlas,
            r.label_index = row.label_index,
            r.space = row.space,
            r.x = row.x, r.y = row.y, r.z = row.z
        """
        sess.run(query, rows=BATCH)
    drv.close()


def main():
    import_aal()
    import_schaefer()
    import_yeo17()
    write_to_neo4j()
    print(f"Inserted/merged {len(BATCH)} BrainRegion nodes")


if __name__ == "__main__":
    main()
