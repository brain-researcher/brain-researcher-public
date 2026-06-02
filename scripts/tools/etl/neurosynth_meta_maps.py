#!/usr/bin/env python3
"""
Compute Neurosynth-style association maps with NiMARE and (optionally) ingest
summaries into Neo4j.

Pipeline:
1) Load the NiMARE Neurosynth v7 dataset already cached on disk.
2) For each term, run MKDAChi2 (reverse-inference / association) with
   FDR=0.01 correction; save z / pAgF / pFgA maps.
3) Summarize maps onto an atlas (defaults to Yeo 2011 17-network) with parcel
   mean / max; write TSV + manifest JSON.
4) If requested, ingest StatMap + Collection + Term into Neo4j (no voxels).

Notes
-----
- This is deliberately conservative: it skips terms with too few studies
  (default n_pos < 20 or n_neg < 20) and caps the number of terms processed
  (default 100) to keep runtime reasonable. Adjust with CLI flags.
- Voxelwise NIfTIs stay on disk; Neo4j only stores paths and summaries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from nilearn import image
from nilearn.input_data import NiftiLabelsMasker
from nimare.correct import FDRCorrector
from nimare.dataset import Dataset
from nimare.meta.cbma.mkda import MKDAChi2
from nimare.io import convert_neurosynth_to_dataset

try:
    from brain_researcher.services.br_kg.graph.neo4j_graph_database import (
        Neo4jGraphDB,
    )
except Exception:
    Neo4jGraphDB = None  # optional dependency for ingest

LOG = logging.getLogger("neurosynth_meta_maps")


@dataclass
class MapEntry:
    term: str
    n_pos: int
    n_neg: int
    estimator: str
    alpha: float
    map_type: str
    is_thresholded: bool
    z_map: str
    pagf_map: str | None
    pfgA_map: str | None
    roi_summary_tsv: str


def load_dataset(data_dir: Path, dataset_file: Path | None = None) -> Dataset:
    """
    Load a cached Dataset if present; otherwise build it once from local Neurosynth files
    (no re-downloading).
    """
    if dataset_file:
        dataset_file = dataset_file.expanduser().resolve()
        LOG.info("Checking cached Dataset at %s", dataset_file)
        if dataset_file.exists():
            try:
                LOG.info("Loading cached Dataset: %s", dataset_file)
                return Dataset.load(str(dataset_file))
            except Exception as exc:
                LOG.warning("Failed to load cached Dataset (%s); will rebuild. Error: %s", dataset_file, exc)
        else:
            LOG.info("Cached Dataset not found; will build and save to %s", dataset_file)

    LOG.info("Converting local Neurosynth bundle -> Dataset")
    # Locate files locally
    root = data_dir
    coords = next(root.glob("**/data-neurosynth_version-7_coordinates.tsv.gz"))
    meta = next(root.glob("**/data-neurosynth_version-7_metadata.tsv.gz"))
    features_path = next(root.glob("**/data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz"))
    vocab_path = next(root.glob("**/data-neurosynth_version-7_vocab-terms_vocabulary.txt"))

    dset = convert_neurosynth_to_dataset(
        str(coords),
        str(meta),
        annotations_files=[{"features": str(features_path), "vocabulary": str(vocab_path)}],
        target="mni152_2mm",
    )
    if dataset_file:
        dataset_file.parent.mkdir(parents=True, exist_ok=True)
        dset.save(str(dataset_file))
        LOG.info("Cached Dataset saved to %s", dataset_file)
    return dset


def term_ids(dset: Dataset) -> Iterable[str]:
    return dset.get_labels()


def compute_maps(
    dset: Dataset,
    term: str,
    out_dir: Path,
    min_pos: int,
    min_neg: int,
    alpha: float,
    kernel_r: float,
) -> MapEntry | None:
    pos_ids = dset.get_studies_by_label(labels=[term], label_threshold=0.001)
    neg_ids = list(set(dset.ids) - set(pos_ids))
    if len(pos_ids) < min_pos or len(neg_ids) < min_neg:
        return None

    pos_dset = dset.slice(pos_ids)
    neg_dset = dset.slice(neg_ids)

    meta = MKDAChi2(kernel__r=kernel_r)
    res = meta.fit(pos_dset, neg_dset)

    corr = FDRCorrector(method="indep", alpha=alpha)
    cres = corr.transform(res)

    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"neurosynth_{term}"

    z_name = "z_desc-association_level-voxel_corr-FDR_method-indep"
    if z_name not in cres.maps:
        z_name = "z_desc-association"
    z_map = cres.get_map(z_name)
    z_path = f"{prefix}_z.nii.gz"
    image.load_img(z_map).to_filename(z_path)

    pagf_path = None
    pfgA_path = None
    if "prob_desc-AgF" in res.maps:
        pagf = res.get_map("prob_desc-AgF")
        pagf_path = f"{prefix}_pAgF.nii.gz"
        image.load_img(pagf).to_filename(pagf_path)
    if "prob_desc-FgA" in res.maps:
        pfga = res.get_map("prob_desc-FgA")
        pfgA_path = f"{prefix}_pFgA.nii.gz"
        image.load_img(pfga).to_filename(pfgA_path)

    return MapEntry(
        term=term,
        n_pos=len(pos_ids),
        n_neg=len(neg_ids),
        estimator="MKDAChi2",
        alpha=alpha,
        map_type="Z map",
        is_thresholded=False,
        z_map=z_path,
        pagf_map=pagf_path,
        pfgA_map=pfgA_path,
        roi_summary_tsv="",
    )


def summarize_roi(z_path: str, atlas_path: Path, out_tsv: Path) -> None:
    z_img = image.load_img(z_path)
    atlas_img = image.resample_to_img(atlas_path, z_img, interpolation="nearest")
    atlas_data = atlas_img.get_fdata()
    if atlas_data.ndim == 4:
        atlas_data = atlas_data[..., 0]
    z_data = z_img.get_fdata()

    labels = np.unique(atlas_data).astype(int)
    labels = labels[labels > 0]
    rows = []
    for label in labels:
        mask = atlas_data == label
        if not np.any(mask):
            rows.append((label, np.nan, np.nan))
            continue
        vals = z_data[mask]
        z_mean = float(np.nanmean(vals)) if vals.size else np.nan
        z_max = float(np.nanmax(vals)) if vals.size else np.nan
        rows.append((label, z_mean, z_max))
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open("w", encoding="utf-8") as f:
        f.write("label\tz_mean\tz_max\n")
        for label, z_mean, z_max in rows:
            f.write(f"{label}\t{z_mean:.6f}\t{z_max:.6f}\n")


def ingest_neo4j(
    entries: list[MapEntry],
    collection_name: str,
    atlas: str,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> None:
    if Neo4jGraphDB is None:
        LOG.warning("Neo4j not available; skipping ingest")
        return
    uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = user or os.getenv("NEO4J_USER", "neo4j")
    password = password or os.getenv("NEO4J_PASSWORD", "password")
    database = database or os.getenv("NEO4J_DATABASE") or None
    db = Neo4jGraphDB(uri=uri, user=user, password=password, database=database, preload_cache=False)

    coll_id = f"neurosynth_collection:{collection_name}"
    db.create_node("Collection", {"id": coll_id, "name": collection_name, "source": "neurosynth"}, node_id=coll_id)

    for e in entries:
        sid = f"neurosynth_statmap:{e.term}"
        db.create_node("StatMap", {
            "id": sid,
            "term": e.term,
            "source": "neurosynth",
            "map_type": e.map_type,
            "is_thresholded": e.is_thresholded,
            "alpha": e.alpha,
            "estimator": e.estimator,
            "n_pos": e.n_pos,
            "n_neg": e.n_neg,
            "file": e.z_map,
            "pagf_file": e.pagf_map,
            "pfga_file": e.pfgA_map,
        })
        tid = f"neurosynth_term:{e.term}"
        db.create_node("Term", {"id": tid, "name": e.term, "source": "neurosynth"}, node_id=tid)
        db.create_relationship(sid, coll_id, "BELONGS_TO", {})
        try:
            z_img = image.load_img(e.z_map)
            z_data = z_img.get_fdata()
            weight = float(np.nanmax(z_data)) if np.isfinite(z_data).any() else 0.0
        except Exception:
            weight = 0.0
        db.create_relationship(sid, tid, "HAS_TERM", {"weight": weight, "atlas": atlas})

    db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=Path("data/neurosynth_nimare/neurosynth"))
    ap.add_argument("--dataset-file", type=Path, default=Path("data/neurosynth_nimare/neurosynth_dataset_v7.pkl.gz"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/neurosynth_maps"))
    ap.add_argument("--manifest", type=Path, default=None, help="Optional existing manifest to reuse/ingest")
    ap.add_argument(
        "--atlas",
        type=Path,
        default=Path(
            "data/br-kg/raw/nilearn_atlases/yeo_2011/Yeo_JNeurophysiol11_MNI152/"
            "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm.nii.gz"
        ),
    )
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--min-pos", type=int, default=20)
    ap.add_argument("--min-neg", type=int, default=20)
    ap.add_argument("--max-terms", type=int, default=100, help="0 means all terms")
    ap.add_argument("--kernel-r", type=float, default=10.0)
    ap.add_argument("--ingest", action="store_true", help="Ingest summaries into Neo4j")
    ap.add_argument("--ingest-only", action="store_true", help="Skip map computation; ingest existing manifest")
    ap.add_argument("--neo4j-uri", type=str, default=None)
    ap.add_argument("--neo4j-user", type=str, default=None)
    ap.add_argument("--neo4j-password", type=str, default=None)
    ap.add_argument("--neo4j-database", type=str, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest_path = args.manifest

    # If ingest-only was requested, just load manifest and ingest.
    if args.ingest_only:
        if manifest_path is None:
            ap.error("--ingest-only requires --manifest")
        LOG.info("Loading manifest for ingest-only: %s", manifest_path)
        entries_raw = json.loads(manifest_path.read_text())
        manifest = [MapEntry(**m) for m in entries_raw]
        if args.ingest:
            ingest_neo4j(
                manifest,
                "Neurosynth Reverse Inference Maps",
                args.atlas.name,
                uri=args.neo4j_uri,
                user=args.neo4j_user,
                password=args.neo4j_password,
                database=args.neo4j_database,
            )
        return

    LOG.info("Loading dataset from %s", args.data_dir)
    dset = load_dataset(args.data_dir, args.dataset_file)

    terms = list(term_ids(dset))
    LOG.info("Found %d terms", len(terms))

    manifest: list[MapEntry] = []
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    for term in terms:
        if args.max_terms and processed >= args.max_terms:
            break
        entry = compute_maps(
            dset,
            term,
            out_dir / term,
            min_pos=args.min_pos,
            min_neg=args.min_neg,
            alpha=args.alpha,
            kernel_r=args.kernel_r,
        )
        if entry is None:
            continue
        roi_tsv = out_dir / term / "roi_summary.tsv"
        summarize_roi(entry.z_map, args.atlas, roi_tsv)
        entry.roi_summary_tsv = str(roi_tsv)
        manifest.append(entry)
        processed += 1
        LOG.info("Processed %s (n_pos=%d, n_neg=%d)", term, entry.n_pos, entry.n_neg)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps([asdict(m) for m in manifest], indent=2), encoding="utf-8")
    LOG.info("Wrote manifest for %d terms to %s", len(manifest), manifest_path)

    if args.ingest:
        ingest_neo4j(manifest, "Neurosynth Reverse Inference Maps", args.atlas.name)


if __name__ == "__main__":
    main()
