"""Multiverse convergence analysis for GLM results.

This module computes overlap/convergence metrics across multiple GLM model
variants (multiverse analysis), producing:
1. Voxel-wise "fraction of models significant" overlap maps
2. ROI-wise effect summary tables

These outputs support paper figures demonstrating result robustness across
analytical choices (HRF basis, confound strategy, high-pass filter).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def compute_multiverse_convergence(
    manifest_path: str,
    output_dir: str,
    threshold: float = 3.1,
    atlas: str = "schaefer-200",
    contrast: str | None = None,
) -> dict[str, Any]:
    """Compute convergence analysis across multiverse GLM results.

    Reads a multiverse manifest CSV, loads group-level Z maps for each model,
    and computes:
    1. Voxel-wise fraction of models with significant activation
    2. ROI-wise mean effect sizes per model

    Parameters
    ----------
    manifest_path : str
        Path to multiverse_manifest.csv with columns: model_id, spec, output_dir
    output_dir : str
        Directory to write output files
    threshold : float
        Z-score threshold for significance (default 3.1 ~ p<0.001 uncorrected)
    atlas : str
        Atlas name for ROI extraction (e.g., "schaefer-200", "aal", "harvard-oxford")
    contrast : str, optional
        Specific contrast to analyze. If None, uses first available contrast.

    Returns
    -------
    dict
        {
            "overlap_map": str (path to NIfTI),
            "roi_table": str (path to CSV),
            "summary": {
                "n_models": int,
                "n_voxels_any": int,
                "n_voxels_majority": int,
                "peak_overlap": float,
                "peak_coords_mni": [x, y, z]
            }
        }
    """
    # Lazy imports to avoid loading heavy dependencies at module import time
    try:
        import nibabel as nib
        from nilearn import datasets, image, maskers
    except ImportError as e:
        raise ImportError(
            "multiverse_convergence requires nibabel and nilearn. "
            "Install with: pip install nibabel nilearn"
        ) from e

    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse manifest
    models = _parse_manifest(manifest_path)
    if not models:
        raise ValueError(f"No models found in manifest: {manifest_path}")

    logger.info(f"Found {len(models)} models in manifest")

    # Collect Z-maps for each model
    z_maps = []
    model_ids = []
    for model in models:
        z_map_path = _find_z_map(model, contrast)
        if z_map_path and z_map_path.exists():
            try:
                z_maps.append(nib.load(str(z_map_path)))
                model_ids.append(model["model_id"])
                logger.debug(f"Loaded Z-map for {model['model_id']}: {z_map_path}")
            except Exception as e:
                logger.warning(f"Failed to load Z-map for {model['model_id']}: {e}")
        else:
            logger.warning(f"No Z-map found for {model['model_id']}")

    if len(z_maps) < 2:
        raise ValueError(
            f"Need at least 2 valid Z-maps for convergence analysis, got {len(z_maps)}"
        )

    logger.info(f"Loaded {len(z_maps)} Z-maps for convergence analysis")

    # Resample all maps to common space (first map's affine)
    reference = z_maps[0]
    resampled_maps = [reference]
    for zmap in z_maps[1:]:
        resampled = image.resample_to_img(zmap, reference, interpolation="continuous")
        resampled_maps.append(resampled)

    # Stack and compute overlap
    z_data = np.stack([img.get_fdata() for img in resampled_maps], axis=-1)

    # Compute fraction of models significant at each voxel
    significant = np.abs(z_data) > threshold
    overlap_fraction = significant.mean(axis=-1)

    # Create overlap NIfTI
    overlap_img = nib.Nifti1Image(overlap_fraction.astype(np.float32), reference.affine)
    overlap_path = output_dir / "multiverse_overlap.nii.gz"
    nib.save(overlap_img, str(overlap_path))
    logger.info(f"Saved overlap map: {overlap_path}")

    # Compute summary statistics
    mask = np.any(significant, axis=-1)
    n_voxels_any = int(mask.sum())
    n_voxels_majority = int((overlap_fraction > 0.5).sum())

    peak_idx = np.unravel_index(np.argmax(overlap_fraction), overlap_fraction.shape)
    peak_overlap = float(overlap_fraction[peak_idx])
    peak_coords_mni = _voxel_to_mni(peak_idx, reference.affine)

    # ROI analysis
    roi_table_path = output_dir / "roi_summary.csv"
    _compute_roi_summary(z_data, model_ids, reference.affine, atlas, roi_table_path)

    summary = {
        "n_models": len(z_maps),
        "n_voxels_any": n_voxels_any,
        "n_voxels_majority": n_voxels_majority,
        "peak_overlap": peak_overlap,
        "peak_coords_mni": peak_coords_mni,
        "threshold": threshold,
        "atlas": atlas,
    }

    return {
        "overlap_map": str(overlap_path),
        "roi_table": str(roi_table_path),
        "summary": summary,
    }


def _parse_manifest(manifest_path: Path) -> list[dict]:
    """Parse multiverse manifest CSV."""
    models = []
    with open(manifest_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with errors
            if row.get("error"):
                continue
            models.append(row)
    return models


def _find_z_map(model: dict, contrast: str | None) -> Path | None:
    """Find the group-level Z-map for a model.

    FitLins outputs follow BIDS-derivatives naming:
    - dataset_description.json
    - sub-*/...
    - group/ (or data_level)
        - *_stat-z_statmap.nii.gz

    The manifest should have 'output_dir' pointing to the FitLins output.
    """
    # Get output directory from manifest
    output_dir = model.get("output_dir") or model.get("output_path")
    if not output_dir:
        # Try to infer from spec path
        spec_path = model.get("spec")
        if spec_path:
            # Specs are in statsmodel_specs/{dataset}/
            # Outputs are in analyses/{dataset}/task-{task}[-mvXX]/
            spec_path = Path(spec_path)
            model.get("model_id", "")
            # This is a heuristic - may need adjustment
            return None
        return None

    output_path = Path(output_dir)
    if not output_path.exists():
        return None

    # Look for group-level Z-maps
    # FitLins naming: *_contrast-{name}_stat-z_statmap.nii.gz
    patterns = [
        "group/*_stat-z_statmap.nii.gz",
        "data_level/*_stat-z_statmap.nii.gz",
        "**/contrast-*_stat-z_statmap.nii.gz",
        "**/*_stat-z_statmap.nii.gz",
    ]

    for pattern in patterns:
        matches = list(output_path.glob(pattern))
        if matches:
            if contrast:
                # Filter by contrast name
                filtered = [m for m in matches if f"contrast-{contrast}" in m.name]
                if filtered:
                    return filtered[0]
            # Return first match
            return matches[0]

    return None


def _voxel_to_mni(voxel_idx: tuple, affine: np.ndarray) -> list[float]:
    """Convert voxel indices to MNI coordinates."""
    voxel = np.array([*voxel_idx, 1])
    mni = affine @ voxel
    return [round(float(c), 1) for c in mni[:3]]


def _compute_roi_summary(
    z_data: np.ndarray,
    model_ids: list[str],
    affine: np.ndarray,
    atlas: str,
    output_path: Path,
) -> dict:
    """Compute ROI-wise summary statistics.

    Creates a CSV with:
    - roi_name, roi_id
    - columns for each model's mean Z in that ROI
    - mean_z (across models), std_z, fraction_significant
    """
    try:
        import nibabel as nib
        from nilearn import datasets, maskers
    except ImportError:
        logger.warning("nilearn not available for ROI analysis")
        return {}

    # Fetch atlas
    atlas_data = _fetch_atlas(atlas)
    if atlas_data is None:
        logger.warning(f"Could not fetch atlas: {atlas}")
        # Write empty CSV
        with open(output_path, "w", newline="") as f:
            f.write("roi_id,roi_name,mean_z,std_z,fraction_significant\n")
        return {}

    atlas_img = atlas_data["maps"]
    labels = atlas_data.get("labels", [])

    # Create a reference image for the atlas masker
    ref_shape = z_data.shape[:3]
    ref_img = nib.Nifti1Image(np.zeros(ref_shape, dtype=np.float32), affine)

    # Extract ROI signals
    try:
        masker = maskers.NiftiLabelsMasker(
            labels_img=atlas_img,
            standardize=False,
            resampling_target="data",
        )
        # Fit to reference
        masker.fit(ref_img)
    except Exception as e:
        logger.warning(f"Failed to create atlas masker: {e}")
        with open(output_path, "w", newline="") as f:
            f.write("roi_id,roi_name,mean_z,std_z,fraction_significant\n")
        return {}

    # Extract mean Z for each model in each ROI
    roi_data = []
    for i, model_id in enumerate(model_ids):
        model_img = nib.Nifti1Image(z_data[..., i].astype(np.float32), affine)
        try:
            roi_means = masker.transform(model_img)[0]  # Shape: (n_rois,)
            roi_data.append(roi_means)
        except Exception as e:
            logger.warning(f"Failed to extract ROI data for {model_id}: {e}")
            roi_data.append(np.full(len(labels) if labels else 100, np.nan))

    if not roi_data:
        with open(output_path, "w", newline="") as f:
            f.write("roi_id,roi_name,mean_z,std_z,fraction_significant\n")
        return {}

    roi_data = np.array(roi_data)  # Shape: (n_models, n_rois)

    # Guard against empty ROI dimension (e.g., atlas/resample mismatch)
    if roi_data.ndim < 2 or roi_data.shape[1] == 0:
        logger.warning("ROI extraction returned no regions; writing empty summary.")
        with open(output_path, "w", newline="") as f:
            f.write("roi_id,roi_name,mean_z,std_z,fraction_significant\n")
        return {}

    # Compute summary stats
    rows = []
    n_rois = roi_data.shape[1]
    for roi_idx in range(n_rois):
        roi_name = labels[roi_idx] if roi_idx < len(labels) else f"ROI_{roi_idx + 1}"
        values = roi_data[:, roi_idx]
        valid = ~np.isnan(values)
        if valid.sum() == 0:
            continue

        mean_z = float(np.nanmean(values))
        std_z = float(np.nanstd(values))
        frac_sig = float((np.abs(values[valid]) > 3.1).mean())

        row = {
            "roi_id": roi_idx + 1,
            "roi_name": roi_name,
            "mean_z": round(mean_z, 3),
            "std_z": round(std_z, 3),
            "fraction_significant": round(frac_sig, 3),
        }
        # Add per-model columns
        for j, model_id in enumerate(model_ids):
            row[f"z_{model_id}"] = (
                round(float(values[j]), 3) if not np.isnan(values[j]) else ""
            )
        rows.append(row)

    # Write CSV
    if rows:
        fieldnames = [
            "roi_id",
            "roi_name",
            "mean_z",
            "std_z",
            "fraction_significant",
        ] + [f"z_{m}" for m in model_ids]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Saved ROI summary: {output_path}")
    else:
        with open(output_path, "w", newline="") as f:
            f.write("roi_id,roi_name,mean_z,std_z,fraction_significant\n")

    return {"n_rois": len(rows), "path": str(output_path)}


def _fetch_atlas(atlas: str):
    """Fetch atlas data from nilearn datasets."""
    try:
        from nilearn import datasets
    except ImportError:
        return None

    atlas_lower = atlas.lower().replace("-", "").replace("_", "")

    try:
        if "schaefer" in atlas_lower:
            # Parse number of parcels (default 200)
            n_parcels = 200
            for n in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
                if str(n) in atlas:
                    n_parcels = n
                    break
            data = datasets.fetch_atlas_schaefer_2018(n_rois=n_parcels)
            return {"maps": data["maps"], "labels": data["labels"]}

        elif "aal" in atlas_lower:
            data = datasets.fetch_atlas_aal()
            return {"maps": data["maps"], "labels": data["labels"]}

        elif "harvard" in atlas_lower or "ho" in atlas_lower:
            data = datasets.fetch_atlas_harvard_oxford("cort-maxprob-thr25-2mm")
            return {"maps": data["maps"], "labels": data["labels"]}

        elif "destrieux" in atlas_lower:
            data = datasets.fetch_atlas_destrieux_2009()
            return {"maps": data["maps"], "labels": data["labels"]}

        else:
            # Default to Schaefer 200
            logger.warning(f"Unknown atlas '{atlas}', falling back to Schaefer 200")
            data = datasets.fetch_atlas_schaefer_2018(n_rois=200)
            return {"maps": data["maps"], "labels": data["labels"]}

    except Exception as e:
        logger.warning(f"Failed to fetch atlas {atlas}: {e}")
        return None
