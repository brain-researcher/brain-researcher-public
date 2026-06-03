"""Yeo-17 feature extraction utilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from nilearn.image import resample_to_img

from brain_researcher.services.br_kg.spatial.neuromaps_assets import (
    NeuromapsAssets,
    resolve_neuromaps_assets,
)


@dataclass(frozen=True)
class Yeo17Feature:
    region_id: str
    weight: float
    pct_active: float
    n_vox: int
    z_thr: float


def _resample_if_needed(
    label_img: nib.Nifti1Image,
    target_img: nib.Nifti1Image,
) -> nib.Nifti1Image:
    if label_img.shape == target_img.shape and np.allclose(
        label_img.affine, target_img.affine
    ):
        return label_img
    return resample_to_img(
        label_img,
        target_img,
        interpolation="nearest",
        force_resample=True,
        copy_header=True,
    )


def compute_features(
    *,
    map_img: nib.Nifti1Image,
    label_img: nib.Nifti1Image,
    max_label: int = 17,
    z_threshold: float = 2.3,
) -> list[Yeo17Feature]:
    """Return Yeo-17 summaries for ``map_img``."""

    label_img = _resample_if_needed(label_img, map_img)

    data = np.asarray(map_img.get_fdata(), dtype=np.float32)
    if data.ndim == 4:
        # Some GLM FitLins exports store the statistical map as a single-volume 4D
        # file (x, y, z, 1). Reduce to 3D so region masks broadcast correctly.
        data = data[..., 0]
    labels = np.asarray(label_img.get_fdata(), dtype=np.int32)
    if labels.ndim == 4:
        labels = labels[..., 0]

    mask = labels > 0
    if not np.any(mask):
        return []

    data = data[mask]
    labels = labels[mask]

    sums = np.bincount(labels, weights=data, minlength=max_label + 1)
    counts = np.bincount(labels, minlength=max_label + 1)
    activations = np.bincount(
        labels,
        weights=(data >= z_threshold).astype(np.float32),
        minlength=max_label + 1,
    )

    rows: list[Yeo17Feature] = []
    for label in range(1, max_label + 1):
        n_vox = int(counts[label])
        if n_vox == 0:
            continue
        mean_z = float(sums[label] / n_vox)
        pct_active = float(activations[label] / n_vox)
        rows.append(
            Yeo17Feature(
                region_id=f"yeo17:{label:02d}",
                weight=mean_z,
                pct_active=pct_active,
                n_vox=n_vox,
                z_thr=float(z_threshold),
            )
        )
    return rows


def resolve_label_and_template(
    neuromaps_root: Path | None = None,
    *,
    label_globs: Sequence[str] | None = None,
    template_globs: Sequence[str] | None = None,
) -> NeuromapsAssets:
    return resolve_neuromaps_assets(
        base_dir=neuromaps_root,
        label_globs=label_globs,
        template_globs=template_globs,
    )


__all__ = ["Yeo17Feature", "compute_features", "resolve_label_and_template"]
