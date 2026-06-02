"""
Effect-size utilities for GLM outputs.

Focus on lightweight ROI/cluster summaries to keep things explainable and fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:  # optional deps
    import nibabel as nib
except ImportError:  # pragma: no cover
    nib = None


@dataclass
class RoiEffect:
    contrast: str
    roi: str
    mean_beta: Optional[float]
    mean_t: Optional[float] = None
    mean_z: Optional[float] = None
    percent_signal_change: Optional[float] = None
    partial_r2: Optional[float] = None
    baseline_desc: str = ""
    meaningful: Optional[bool] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contrast": self.contrast,
            "roi": self.roi,
            "mean_beta": self.mean_beta,
            "mean_t": self.mean_t,
            "mean_z": self.mean_z,
            "percent_signal_change": self.percent_signal_change,
            "partial_r2": self.partial_r2,
            "baseline_desc": self.baseline_desc,
            "meaningful": self.meaningful,
            "note": self.note,
        }


def _load_data(path: Path) -> Optional[np.ndarray]:
    if nib is None:
        return None
    try:
        return np.asarray(nib.load(str(path)).get_fdata(), dtype=float)
    except Exception:
        return None


def _iter_labels(mask_data: np.ndarray) -> List[tuple[str, np.ndarray]]:
    """
    Yield (label_name, boolean_mask) for:
    - 3D binary mask: single label 'mask'
    - 3D int mask: each non-zero integer label
    - 4D one-hot: one label per channel
    """
    labels: List[tuple[str, np.ndarray]] = []
    if mask_data.ndim == 3:
        uniq = np.unique(mask_data)
        if (
            np.array_equal(uniq, [0, 1])
            or np.array_equal(uniq, [0])
            or np.array_equal(uniq, [1])
        ):
            labels.append(("mask", mask_data > 0.5))
        else:
            # integer labels
            for val in uniq:
                if val == 0:
                    continue
                labels.append((f"label_{int(val)}", mask_data == val))
    elif mask_data.ndim == 4:
        # one-hot per channel
        for i in range(mask_data.shape[3]):
            labels.append((f"label_{i+1}", mask_data[..., i] > 0.5))
    return labels


def partial_r2_from_t(t_values: np.ndarray, df: float) -> np.ndarray:
    """Compute partial R² from t and degrees of freedom."""
    return (t_values**2) / (t_values**2 + df)


def roi_summary(
    contrast_name: str,
    beta_map: Optional[Path],
    t_map: Optional[Path],
    z_map: Optional[Path],
    roi_masks: Dict[str, Path],
    df: Optional[float] = None,
    baseline_map: Optional[Path] = None,
    psc_threshold: Optional[float] = None,
    partial_r2_threshold: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Compute ROI mean beta/PSC/partial R². Falls back gracefully if inputs missing.
    """
    summaries: List[RoiEffect] = []
    beta_data = _load_data(beta_map) if beta_map else None
    t_data = _load_data(t_map) if t_map else None
    z_data = _load_data(z_map) if z_map else None
    baseline_data = _load_data(baseline_map) if baseline_map else None

    for roi_name, mask_path in roi_masks.items():
        mask_data = _load_data(mask_path)
        if mask_data is None:
            summaries.append(
                RoiEffect(
                    contrast=contrast_name,
                    roi=roi_name,
                    mean_beta=None,
                    mean_t=None,
                    mean_z=None,
                    percent_signal_change=None,
                    partial_r2=None,
                    baseline_desc="mask unavailable",
                    meaningful=None,
                    note="mask_load_failed",
                ).to_dict()
            )
            continue

        labels = _iter_labels(mask_data)
        if not labels:
            summaries.append(
                RoiEffect(
                    contrast=contrast_name,
                    roi=roi_name,
                    mean_beta=None,
                    mean_t=None,
                    mean_z=None,
                    percent_signal_change=None,
                    partial_r2=None,
                    baseline_desc="mask empty",
                    meaningful=None,
                    note="",
                ).to_dict()
            )
            continue

        for lbl_name, mask in labels:
            if not mask.any():
                summaries.append(
                    RoiEffect(
                        contrast=contrast_name,
                        roi=f"{roi_name}:{lbl_name}",
                        mean_beta=None,
                        mean_t=None,
                        mean_z=None,
                        percent_signal_change=None,
                        partial_r2=None,
                        baseline_desc="mask empty",
                        meaningful=None,
                        note="",
                    ).to_dict()
                )
                continue

            mean_beta = (
                float(np.nanmean(beta_data[mask])) if beta_data is not None else None
            )
            mean_t = float(np.nanmean(t_data[mask])) if t_data is not None else None
            mean_z = float(np.nanmean(z_data[mask])) if z_data is not None else None
            baseline_desc = (
                "baseline: intercept (approx)"
                if baseline_data is None
                else "baseline: provided map"
            )

            psc = None
            if mean_beta is not None:
                base = (
                    np.nanmean(baseline_data[mask])
                    if baseline_data is not None
                    else 1.0
                )
                if np.isfinite(base) and abs(base) > 1e-12:
                    psc = float(100.0 * mean_beta / base)

            pr2 = None
            if t_data is not None and df is not None:
                pr2 = float(np.nanmean(partial_r2_from_t(t_data, df)[mask]))

            meaningful: Optional[bool] = None
            if psc_threshold is not None and psc is not None:
                meaningful = psc >= psc_threshold
            if partial_r2_threshold is not None and pr2 is not None:
                meaningful = (
                    pr2 >= partial_r2_threshold
                    if meaningful is None
                    else (meaningful and pr2 >= partial_r2_threshold)
                )

            summaries.append(
                RoiEffect(
                    contrast_name,
                    f"{roi_name}:{lbl_name}",
                    mean_beta,
                    mean_t,
                    mean_z,
                    psc,
                    pr2,
                    baseline_desc,
                    meaningful,
                ).to_dict()
            )

    return summaries
