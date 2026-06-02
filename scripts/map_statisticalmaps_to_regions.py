#!/usr/bin/env python3
"""Map NeuroVault StatisticalMap nodes to BrainRegion via atlas overlap (Schaefer400-7N).

Downloads NIfTI via NeuroVault API (https://neurovault.org/api/images/<id>/ -> file).
"""

import os
import pathlib
import requests
import numpy as np
import nibabel as nib
from tqdm import tqdm
from neo4j import GraphDatabase
from nilearn import datasets, image

from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    default_atlas_output_root,
    existing_search_roots,
    resolve_local_volume_atlas,
)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
DOWNLOAD_DIR = pathlib.Path("data/neurovault/downloaded")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

try:
    _atlas_path, _, _ = resolve_local_volume_atlas(
        "Schaefer2018_400",
        existing_search_roots(None, default_atlas_output_root()),
    )
except FileNotFoundError:
    if not allow_network_atlas_fetch():
        raise
    sch = datasets.fetch_atlas_schaefer_2018(
        n_rois=400,
        yeo_networks=7,
        resolution_mm=2,
        data_dir=str(default_atlas_output_root() / "schaefer_2018"),
    )
    _atlas_path = sch.maps

# Atlas
ATLAS_IMG = image.load_img(_atlas_path)
ATLAS_NAME = "Schaefer400-7N"
ATLAS_MAX = int(np.max(ATLAS_IMG.get_fdata()))


def api_file_url(page_url: str) -> str:
    # page_url like http://neurovault.org/images/2/
    parts = page_url.rstrip("/").split("/")
    img_id = parts[-1]
    api = f"https://neurovault.org/api/images/{img_id}/"
    r = requests.get(api, timeout=30)
    r.raise_for_status()
    js = r.json()
    return js.get("file") or js.get("image")


def download_nii(page_url: str, map_id: str) -> pathlib.Path:
    dest = DOWNLOAD_DIR / f"{map_id}.nii.gz"
    if dest.exists():
        return dest
    file_url = api_file_url(page_url)
    if not file_url:
        raise ValueError(f"No file URL in API for {page_url}")
    with requests.get(file_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return dest


def map_to_regions(nii_path: pathlib.Path):
    img = image.load_img(str(nii_path))
    resamp = image.resample_to_img(img, ATLAS_IMG, interpolation="nearest")
    data = resamp.get_fdata()
    atlas = ATLAS_IMG.get_fdata()
    overlaps = []
    for lbl in range(1, ATLAS_MAX + 1):
        vox = int(np.sum((data != 0) & (atlas == lbl)))
        if vox > 0:
            overlaps.append((lbl, vox))
    total_vox = int(np.sum(data != 0))
    return overlaps, total_vox


def main():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with drv.session() as sess:
        sess.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:BrainRegion) REQUIRE r.id IS UNIQUE"
        )
        maps = sess.run(
            "MATCH (s:StatisticalMap) WHERE s.url IS NOT NULL RETURN s.id AS id, s.url AS url"
        ).values()
    if not maps:
        print("No StatisticalMap with url found")
        return
    print(f"Found {len(maps)} StatisticalMap nodes with URLs")

    created = 0
    with drv.session() as sess:
        for map_id, url in tqdm(maps):
            try:
                safe_id = map_id.replace(":", "_")
                nii = download_nii(url, safe_id)
                overlaps, total_vox = map_to_regions(nii)
                for lbl, vox in overlaps:
                    rid = f"{ATLAS_NAME}:{lbl}"
                    pct = (vox / total_vox * 100.0) if total_vox > 0 else 0.0
                    sess.run(
                        "MATCH (s:StatisticalMap {id:$sid}) "
                        "MERGE (r:BrainRegion {id:$rid}) "
                        "MERGE (s)-[rel:IN_REGION]->(r) "
                        "SET rel.voxels=$vox, rel.overlap_pct=$pct, rel.atlas=$atlas",
                        sid=map_id,
                        rid=rid,
                        vox=vox,
                        pct=pct,
                        atlas=ATLAS_NAME,
                    )
                created += len(overlaps)
            except Exception as e:
                print(f"Failed {map_id}: {e}")
                continue
    print(f"IN_REGION edges created/merged: {created}")
    drv.close()


if __name__ == "__main__":
    main()
