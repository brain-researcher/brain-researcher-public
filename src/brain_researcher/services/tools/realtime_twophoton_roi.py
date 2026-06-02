"""ROI loading, extraction, and Suite2p-to-runtime translation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation


def load_roi_manifest(manifest_path: str | Path) -> dict[str, np.ndarray]:
    """Load a runtime ROI manifest stored as `.npz`."""

    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"ROI manifest not found: {path}")
    with np.load(path, allow_pickle=True) as data:
        bundle = {key: data[key] for key in data.files}
    if "roi_masks" not in bundle:
        raise ValueError("ROI manifest must contain 'roi_masks'")
    if "neuropil_masks" not in bundle:
        bundle["neuropil_masks"] = np.zeros_like(bundle["roi_masks"], dtype=bool)
    return bundle


def extract_roi_values(
    frame: np.ndarray,
    roi_masks: np.ndarray,
    neuropil_masks: np.ndarray | None = None,
    neuropil_coeff: float = 0.7,
) -> np.ndarray:
    """Extract mean ROI values with optional neuropil subtraction."""

    image = frame.astype(np.float32).reshape(-1)
    roi_flat = roi_masks.reshape(roi_masks.shape[0], -1).astype(np.float32)
    roi_counts = np.clip(roi_flat.sum(axis=1), 1.0, None)
    roi_values = (roi_flat @ image) / roi_counts

    if neuropil_masks is None or neuropil_masks.size == 0:
        return roi_values.astype(np.float32)

    neuropil_flat = neuropil_masks.reshape(neuropil_masks.shape[0], -1).astype(
        np.float32
    )
    neuropil_counts = np.clip(neuropil_flat.sum(axis=1), 1.0, None)
    neuropil_values = (neuropil_flat @ image) / neuropil_counts
    corrected = roi_values - neuropil_coeff * neuropil_values
    return corrected.astype(np.float32)


def build_runtime_bundle_from_suite2p(
    suite2p_dir: str | Path,
    output_dir: str | Path,
    iscell_threshold: float = 0.5,
    max_rois: int | None = None,
) -> dict[str, str]:
    """Translate Suite2p outputs into runtime artifacts."""

    source_dir = Path(suite2p_dir)
    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    stat_path = source_dir / "stat.npy"
    ops_path = source_dir / "ops.npy"
    iscell_path = source_dir / "iscell.npy"
    if not stat_path.exists() or not ops_path.exists():
        raise FileNotFoundError(
            "Suite2p directory must contain at least stat.npy and ops.npy"
        )

    stat = np.load(stat_path, allow_pickle=True)
    ops = np.load(ops_path, allow_pickle=True).item()
    if iscell_path.exists():
        iscell = np.load(iscell_path, allow_pickle=True)
        keep = iscell[:, 0] >= float(iscell_threshold)
    else:
        keep = np.ones(len(stat), dtype=bool)

    selected_indices = np.flatnonzero(keep)
    if max_rois is not None:
        selected_indices = selected_indices[:max_rois]
    if len(selected_indices) == 0:
        raise ValueError("No Suite2p ROIs passed the selection threshold")

    ly = int(ops.get("Ly", 0))
    lx = int(ops.get("Lx", 0))
    if ly <= 0 or lx <= 0:
        mean_img = ops.get("meanImg")
        if mean_img is None:
            raise ValueError("Suite2p ops.npy is missing Ly/Lx and meanImg")
        ly, lx = map(int, mean_img.shape)

    roi_masks = np.zeros((len(selected_indices), ly, lx), dtype=bool)
    neuropil_masks = np.zeros_like(roi_masks)
    centroids = np.zeros((len(selected_indices), 2), dtype=np.float32)
    all_roi_mask = np.zeros((ly, lx), dtype=bool)

    for out_idx, stat_idx in enumerate(selected_indices):
        item = stat[int(stat_idx)]
        ypix = np.asarray(item["ypix"], dtype=int)
        xpix = np.asarray(item["xpix"], dtype=int)
        roi_masks[out_idx, ypix, xpix] = True
        centroids[out_idx] = [float(np.mean(ypix)), float(np.mean(xpix))]
        all_roi_mask |= roi_masks[out_idx]

    for out_idx, mask in enumerate(roi_masks):
        expanded = binary_dilation(mask, iterations=3)
        neuropil = expanded & ~mask & ~all_roi_mask
        neuropil_masks[out_idx] = neuropil

    roi_ids = selected_indices.astype(np.int32)
    reference = np.asarray(ops.get("meanImg"), dtype=np.float32)
    if reference.size == 0:
        reference = np.zeros((ly, lx), dtype=np.float32)

    manifest_path = dest_dir / "roi_manifest.npz"
    reference_path = dest_dir / "reference_template.npy"
    meta_path = dest_dir / "calibration_meta.json"

    np.savez_compressed(
        manifest_path,
        roi_masks=roi_masks,
        neuropil_masks=neuropil_masks,
        roi_ids=roi_ids,
        centroids=centroids,
    )
    np.save(reference_path, reference)
    meta = {
        "source_dir": str(source_dir),
        "n_rois": int(len(roi_ids)),
        "iscell_threshold": float(iscell_threshold),
        "reference_image_key": "meanImg",
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    return {
        "roi_manifest": str(manifest_path),
        "reference_template": str(reference_path),
        "calibration_meta": str(meta_path),
    }
