from pathlib import Path
import numpy as np
import nibabel as nib
from nilearn.image import resample_to_img
from neo4j import GraphDatabase

from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    default_atlas_output_root,
    existing_search_roots,
    resolve_local_volume_atlas,
)

URI = "bolt://localhost:7687"
USER = "neo4j"
PWD = "password"
ATLAS_ID = "atlas:yeo2011_17"
THR = 2.5


def load_atlas_resampled(target_img):
    try:
        atlas_path, _, _ = resolve_local_volume_atlas(
            "yeo17",
            existing_search_roots(None, default_atlas_output_root()),
        )
    except FileNotFoundError:
        if not allow_network_atlas_fetch():
            raise
        from nilearn.datasets import fetch_atlas_yeo_2011

        atlas = fetch_atlas_yeo_2011(
            n_networks=17,
            thickness="thick",
            data_dir=str(default_atlas_output_root() / "yeo_2011"),
        )
        atlas_path = getattr(atlas, "maps", None) or getattr(atlas, "thick_17", None)
        if atlas_path is None:
            raise FileNotFoundError("Yeo17 atlas maps not available from nilearn")
    atlas_img = nib.load(atlas_path)
    atlas_res = resample_to_img(
        atlas_img, target_img, force_resample=True, copy_header=True
    )
    data = atlas_res.get_fdata()
    if data.ndim == 4 and data.shape[3] == 1:
        data = data[..., 0]
    return data


def parcel_stats(stat_data, atlas_data, label):
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
        "voxels_gt": int(np.sum(vals > THR)),
    }


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    with driver.session() as sess:
        rows = sess.run(
            "MATCH (m:StatMap) WHERE m.source='neurosynth' AND m.path IS NOT NULL RETURN m.id AS id, m.path AS path"
        ).data()
    if not rows:
        print("No neurosynth statmaps with path")
        return
    first_img = nib.load(rows[0]["path"])
    atlas_data = load_atlas_resampled(first_img)

    processed = 0
    with driver.session() as sess:
        for r in rows:
            mid = r["id"]
            p = Path(r["path"])
            if not p.exists():
                continue
            try:
                stat_img = nib.load(str(p))
                stat_data = stat_img.get_fdata()
                if stat_data.ndim == 4:
                    stat_data = stat_data[..., 0]
                # basic shape check
                if stat_data.shape != atlas_data.shape:
                    print(f"[skip shape] {mid} {stat_data.shape}")
                    continue
            except Exception as exc:
                print(f"[skip load] {mid}: {exc}")
                continue

            # write parcel stats
            tx = sess.begin_transaction()
            for label in range(1, 18):
                stats = parcel_stats(stat_data, atlas_data, label)
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
                    atlas=ATLAS_ID,
                    mean=stats["mean"],
                    max=stats["max"],
                    voxels=stats["voxels"],
                    voxels_gt=stats["voxels_gt"],
                    thr=THR,
                )
            tx.run(
                """
                MATCH (m:StatMap {id:$mid})-[:IN_PARCELLATION {atlas:$atlas}]->(r:BrainRegion)-[:IN_NETWORK]->(n:Network)
                MERGE (m)-[:IN_NETWORK {source:$atlas}]->(n)
                """,
                mid=mid,
                atlas=ATLAS_ID,
            )
            tx.commit()
            processed += 1
            if processed % 100 == 0:
                print(f"processed {processed}/{len(rows)}")
    print(f"done {processed}/{len(rows)}")


if __name__ == "__main__":
    main()
