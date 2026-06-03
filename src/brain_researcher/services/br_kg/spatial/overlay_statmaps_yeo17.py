"""
Reusable Yeo17 statmap overlay helpers.

CLI entrypoints should import ``overlay_statmaps_yeo17`` from here rather than
from the legacy BR-KG script namespace.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from neo4j import GraphDatabase

# Nilearn is an optional dependency in some installs; import lazily
from nilearn.datasets import fetch_atlas_yeo_2011
from nilearn.image import resample_to_img


def _load_atlas() -> tuple[nib.Nifti1Image, np.ndarray, np.ndarray]:
    """Fetch Yeo17 atlas and return (img, data, affine_inverse)."""
    atlas_path = fetch_atlas_yeo_2011()["thick_17"]
    img = nib.load(atlas_path)
    data = img.get_fdata()
    # Some nilearn builds return a trailing singleton channel dim; squeeze it.
    if data.ndim == 4 and data.shape[3] == 1:
        data = data[..., 0]
    aff_inv = np.linalg.inv(img.affine)
    return img, data, aff_inv


def _parcel_stats(stat_data: np.ndarray, atlas_data: np.ndarray, label: int, threshold: float) -> Optional[dict]:
    mask = atlas_data == label
    if not np.any(mask):
        return None
    vals = stat_data[mask]
    if vals.size == 0:
        return None
    return {
        "mean": float(np.nanmean(vals)),
        "max": float(np.nanmax(vals)),
        "voxels": int(vals.size),
        "voxels_gt": int(np.sum(vals > threshold)),
    }


def overlay_statmaps_yeo17(
    uri: str,
    user: str,
    password: str,
    database: str = "neo4j",
    statmap_limit: Optional[int] = None,
    threshold: float = 2.5,
    atlas_id: str = "atlas:yeo2011_17",
    resample: bool = False,
) -> None:
    """
    For each StatMap with an on-disk path, overlay onto Yeo17 and write:
      (m)-[:IN_PARCELLATION {atlas}]->(yeo17:label) with summary stats
      (m)-[:IN_NETWORK {source=atlas}]->(Network) via the parcel's IN_NETWORK
    """
    atlas_img, atlas_data, _ = _load_atlas()
    driver = GraphDatabase.driver(uri, auth=(user, password), database=database)

    with driver.session() as sess:
        query = "MATCH (m:StatMap) WHERE m.path IS NOT NULL RETURN m.id AS id, m.path AS path"
        if statmap_limit:
            query += " LIMIT $limit"
        records = sess.run(query, limit=statmap_limit).data()

    if not records:
        print("No StatMaps with path found.")
        return

    processed = 0
    start = time.time()

    with driver.session() as sess:
        for rec in records:
            mid = rec["id"]
            path = rec["path"]
            if not path or not Path(path).exists():
                continue
            try:
                stat_img = nib.load(path)
                if resample:
                    stat_img = resample_to_img(stat_img, atlas_img, force_resample=False, copy_header=True)
                stat_data = stat_img.get_fdata()
                # squeeze 4D maps (take first vol) if needed
                if stat_data.ndim == 4:
                    stat_data = stat_data[..., 0]
            except Exception as exc:
                print(f"[skip] {mid}: cannot load/resample ({exc})")
                continue

            tx = sess.begin_transaction()
            for label in range(1, 18):  # Yeo17 labels are 1..17
                stats = _parcel_stats(stat_data, atlas_data, label, threshold)
                if not stats:
                    continue
                tx.run(
                    """
                    MATCH (m:StatMap {id:$mid})
                    MATCH (r:BrainRegion {id:$rid})
                    MERGE (m)-[rel:IN_PARCELLATION {atlas:$atlas}]->(r)
                    SET rel.mean = $mean,
                        rel.max = $max,
                        rel.voxels = $voxels,
                        rel.voxels_gt = $voxels_gt,
                        rel.threshold = $thr,
                        rel.updated_at = timestamp()
                    """,
                    mid=mid,
                    rid=f"yeo17:{label}",
                    atlas=atlas_id,
                    mean=stats["mean"],
                    max=stats["max"],
                    voxels=stats["voxels"],
                    voxels_gt=stats["voxels_gt"],
                    thr=threshold,
                )
            # propagate networks
            tx.run(
                """
                MATCH (m:StatMap {id:$mid})-[:IN_PARCELLATION {atlas:$atlas}]->(r:BrainRegion)-[:IN_NETWORK]->(n:Network)
                MERGE (m)-[:IN_NETWORK {source:$atlas}]->(n)
                """,
                mid=mid,
                atlas=atlas_id,
            )
            tx.commit()
            processed += 1
            if processed % 25 == 0:
                elapsed = time.time() - start
                print(f"Processed {processed}/{len(records)} statmaps in {elapsed:.1f}s")

    print(f"Overlay complete: {processed} statmaps processed in {time.time()-start:.1f}s")


__all__ = ["overlay_statmaps_yeo17"]
