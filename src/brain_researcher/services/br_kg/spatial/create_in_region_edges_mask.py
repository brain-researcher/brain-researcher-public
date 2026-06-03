"""Runtime helpers for mask-based Coordinate -> BrainRegion mapping.

Usage (Neo4j backend from env):
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password \
    python scripts/br-kg/create_in_region_edges_mask.py \
        --atlas AAL

Supported atlases via nilearn fetchers:
    AAL, Schaefer400 (400 parcels, 7 networks), Yeo17 (volumetric 17-net map if present)

CLI wrappers should import this module instead of keeping the implementation
under the legacy BR-KG script namespace.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from neo4j import GraphDatabase
from nilearn import datasets, image


def fetch_atlas(atlas: str, label_map: str | None, label_names: str | None):
    img = None
    labels = None
    if label_map:
        img = image.load_img(label_map)
    if label_names and Path(label_names).exists():
        labels = Path(label_names).read_text().splitlines()

    name = atlas.lower()
    if name == "aal" and img is None:
        aal = datasets.fetch_atlas_aal()
        img = image.load_img(aal.maps)
        labels = aal.labels
    elif name == "schaefer400" and img is None:
        sch = datasets.fetch_atlas_schaefer_2018(n_rois=400, yeo_networks=7)
        img = image.load_img(sch.maps)
        labels = sch.labels
    elif name == "yeo17" and img is None:
        yeo = datasets.fetch_atlas_yeo_2011()
        map_key = next(
            (
                k
                for k in ["thick_17", "thin_17", "thick_17net", "thin_17net", "anat_17"]
                if hasattr(yeo, k)
            ),
            None,
        )
        labels_key = next(
            (
                k
                for k in ["thick_17_labels", "thin_17_labels", "labels_17"]
                if hasattr(yeo, k)
            ),
            None,
        )
        if map_key and labels_key:
            img = image.load_img(getattr(yeo, map_key))
            labels = getattr(yeo, labels_key)
    if img is None or labels is None:
        raise RuntimeError(
            f"Could not load atlas {atlas}; supply --label-map/--label-names"
        )
    return img, labels


def voxel_label(img, xyz_mm):
    ijk = np.round(np.linalg.inv(img.affine).dot([*xyz_mm, 1]))[:3].astype(int)
    data = img.get_fdata()
    if np.any(ijk < 0) or np.any(ijk >= data.shape):
        return 0
    return int(data[tuple(ijk)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--atlas",
        required=True,
        choices=["AAL", "Schaefer400", "Yeo17"],
        help="Atlas name",
    )
    ap.add_argument("--label-map", help="Path to label NIfTI")
    ap.add_argument("--label-names", help="Path to label names (one per line)")
    ap.add_argument("--limit", type=int, default=0, help="Limit coordinates for test")
    args = ap.parse_args()

    img, labels = fetch_atlas(args.atlas, args.label_map, args.label_names)
    max_label = int(np.max(img.get_fdata()))
    print(
        f"Loaded atlas {args.atlas} with max label {max_label}; labels len={len(labels)}"
    )

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "password")
    drv = GraphDatabase.driver(uri, auth=(user, pwd))

    with drv.session() as sess:
        sess.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:BrainRegion) REQUIRE r.id IS UNIQUE"
        )
        coords = sess.run(
            "MATCH (c:Coordinate) RETURN c.x AS x,c.y AS y,c.z AS z, elementId(c) AS cid"
            + (" LIMIT $lim" if args.limit else ""),
            lim=args.limit,
        ).values()
        print(f"Processing {len(coords)} coordinates...")
        created = 0
        skipped = 0
        for x, y, z, cid in coords:
            lbl = voxel_label(img, (x, y, z))
            if lbl <= 0:
                skipped += 1
                continue
            name = labels[lbl - 1] if lbl - 1 < len(labels) else f"label-{lbl}"
            rid = f"{args.atlas}:{lbl}"
            sess.run(
                "MERGE (r:BrainRegion {id:$id}) SET r.name=$name, r.atlas=$atlas, r.label_index=$idx, r.space='MNI'",
                id=rid,
                name=name,
                atlas=args.atlas,
                idx=lbl,
            )
            sess.run(
                "MATCH (c) WHERE elementId(c)=$cid MATCH (r:BrainRegion {id:$rid}) MERGE (c)-[:IN_REGION]->(r)",
                cid=cid,
                rid=rid,
            )
            created += 1
        print(
            f"Done. IN_REGION created/merged: {created}, skipped (label=0/outside): {skipped}"
        )
    drv.close()


if __name__ == "__main__":
    main()
