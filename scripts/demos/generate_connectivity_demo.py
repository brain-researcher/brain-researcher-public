#!/usr/bin/env python
"""Generate functional connectivity demo artifacts from real fMRI data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from nilearn import datasets
from nilearn.connectome import ConnectivityMeasure
from nilearn.maskers import NiftiLabelsMasker, NiftiMasker

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    write_feature_contract,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate connectivity demo artifacts")
    parser.add_argument(
        "--bold",
        type=Path,
        default=Path(
            "/app/data/openneuro/ds000114/sub-06/"
            "ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz"
        ),
        help="Path to the 4D BOLD NIfTI file",
    )
    parser.add_argument(
        "--atlas",
        type=str,
        default="schaefer",
        choices=["schaefer", "harvard_oxford"],
        help="Atlas to use for ROI extraction",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/app/data/demo/connectivity_dmn/real"),
        help="Directory where outputs will be written",
    )
    parser.add_argument(
        "--seed-label-filter",
        type=str,
        default="PCC",
        help="Substring to match for selecting the seed ROI",
    )
    parser.add_argument(
        "--kind",
        type=str,
        default="correlation",
        choices=["correlation", "partial correlation"],
        help="Connectivity measure kind",
    )
    return parser


def load_atlas(kind: str):
    if kind == "schaefer":
        atlas = datasets.fetch_atlas_schaefer_2018(n_rois=200, yeo_networks=7, resolution_mm=2)
        labels = list(atlas["labels"])
        img = atlas["maps"]
    else:
        atlas = datasets.fetch_atlas_harvard_oxford("cort-maxprob-thr50-2mm")
        labels = [lbl.decode("utf-8") if isinstance(lbl, bytes) else lbl for lbl in atlas["labels"]]
        img = atlas["maps"]
    return img, labels


def compute_roi_timeseries(bold_path: Path, atlas_img, labels):
    masker = NiftiLabelsMasker(
        labels_img=atlas_img,
        labels=labels,
        standardize=True,
        detrend=True,
        smoothing_fwhm=4.0,
    )
    ts = masker.fit_transform(str(bold_path))
    valid = ~np.all(ts == 0, axis=0)
    return ts[:, valid], [lbl for lbl, keep in zip(labels, valid) if keep]


def compute_connectivity(ts: np.ndarray, kind: str) -> np.ndarray:
    measure = ConnectivityMeasure(kind=kind)
    matrix = measure.fit_transform([ts])[0]
    return np.clip(matrix, -1.0, 1.0)


def save_matrix(matrix: np.ndarray, labels: list[str], out_csv: Path):
    df = pd.DataFrame(matrix, index=labels, columns=labels)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, float_format="%.6f")


def save_metrics(matrix: np.ndarray, labels: list[str], out_json: Path):
    strength = matrix.mean(axis=1)
    metrics = {
        "roi_metrics": [
            {"label": label, "mean_connectivity": float(val)}
            for label, val in zip(labels, strength)
        ],
        "global": {
            "mean_connectivity": float(strength.mean()),
            "std_connectivity": float(strength.std()),
        },
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(metrics, indent=2))


def compute_seed_map(bold_path: Path, seed_ts: np.ndarray, out_path: Path):
    voxel_masker = NiftiMasker(standardize=True)
    voxel_series = voxel_masker.fit_transform(str(bold_path))
    seed = seed_ts.squeeze()
    seed_std = seed.std() or 1e-6
    seed = (seed - seed.mean()) / seed_std
    vox_std = voxel_series.std(axis=0)
    vox_std[vox_std < 1e-6] = 1e-6
    vox = (voxel_series - voxel_series.mean(axis=0)) / vox_std
    corr = np.dot(vox.T, seed) / (seed.shape[0] - 1)
    corr_img = voxel_masker.inverse_transform(corr)
    corr_img.to_filename(out_path)


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    atlas_img, labels = load_atlas(args.atlas)
    time_series, kept_labels = compute_roi_timeseries(args.bold, atlas_img, labels)
    matrix = compute_connectivity(time_series, args.kind)

    matrix_path = args.output_dir / "connectivity_matrix.csv"
    metrics_path = args.output_dir / "network_metrics.json"
    save_matrix(matrix, kept_labels, matrix_path)
    save_metrics(matrix, kept_labels, metrics_path)
    feature_contract_path = write_feature_contract(
        build_feature_contract(
            matrix,
            matrix_kind=args.kind,
            source_level="roi_timeseries",
            n_rois=int(len(kept_labels)),
            n_timepoints=int(time_series.shape[0]),
            effective_n_timepoints=int(time_series.shape[0]),
            covariance_estimator="EmpiricalCovariance",
            extras={
                "demo": True,
                "atlas": args.atlas,
                "bold": str(args.bold),
            },
        ),
        args.output_dir,
    )

    seed_indices = [i for i, label in enumerate(kept_labels) if args.seed_label_filter.lower() in label.lower()]
    if not seed_indices:
        seed_indices = [int(np.argmax(matrix.mean(axis=1)))]
    seed_idx = seed_indices[0]
    seed_map_path = args.output_dir / f"seed_{seed_idx:03d}_corr.nii.gz"
    compute_seed_map(args.bold, time_series[:, seed_idx], seed_map_path)

    manifest = {
        "bold": str(args.bold),
        "atlas": args.atlas,
        "roi_count": len(kept_labels),
        "seed_label": kept_labels[seed_idx],
        "matrix_csv": str(matrix_path),
        "feature_contract": str(feature_contract_path),
        "metrics_json": str(metrics_path),
        "seed_map": str(seed_map_path),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
