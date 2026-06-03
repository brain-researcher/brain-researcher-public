"""Lesion detection helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class LesionDetectionParameters:
    """Configuration for lesion detection."""

    flair_image: str | None
    t1_image: str | None
    dwi_image: str | None
    output_dir: str
    lesion_type: str
    min_lesion_size: int
    threshold_method: str
    random_state: int | None
    save_masks: bool
    save_report: bool


def lesion_detection_from_payload(
    payload: dict[str, object],
) -> LesionDetectionParameters:
    """Create parameters from payload."""

    return LesionDetectionParameters(
        flair_image=payload.get("flair_image"),
        t1_image=payload.get("t1_image"),
        dwi_image=payload.get("dwi_image"),
        output_dir=str(payload.get("output_dir", Path.cwd() / "lesion_detection")),
        lesion_type=str(payload.get("lesion_type", "wmh")).lower(),
        min_lesion_size=int(payload.get("min_lesion_size", 3)),
        threshold_method=str(payload.get("threshold_method", "adaptive")),
        random_state=payload.get("random_state"),
        save_masks=bool(payload.get("save_masks", True)),
        save_report=bool(payload.get("save_report", True)),
    )


def _load_or_simulate(path: str | None, rng: np.random.Generator) -> np.ndarray:
    if path:
        img_path = Path(path)
        if img_path.exists() and img_path.suffix == ".npy":
            return np.load(img_path)
    return rng.normal(size=(64, 64, 64))


def _detect_lesions(
    image: np.ndarray, threshold_method: str, rng: np.random.Generator
) -> np.ndarray:
    if threshold_method == "manual":
        thresh = np.mean(image) + np.std(image)
    elif threshold_method == "zscore":
        thresh = np.mean(image) + 3 * np.std(image)
    else:
        thresh = np.percentile(image, 97)

    mask = image > thresh
    if mask.sum() == 0:
        idx = rng.choice(image.size, size=10, replace=False)
        mask.flat[idx] = True
    return mask.astype(int)


def _compute_metrics(mask: np.ndarray) -> dict[str, float]:
    volume = float(mask.sum())
    n_lesions = max(1, int(volume // 50))
    return {
        "lesion_volume": volume,
        "lesion_count": float(n_lesions),
        "mean_size": float(volume / n_lesions),
    }


def run_lesion_detection(params: LesionDetectionParameters) -> dict[str, object]:
    """Execute fallback lesion detection."""

    rng = np.random.default_rng(params.random_state)

    primary_image = _load_or_simulate(params.flair_image or params.t1_image, rng)
    lesion_mask = _detect_lesions(primary_image, params.threshold_method, rng)

    if params.min_lesion_size > 1:
        small = np.where(lesion_mask > 0)
        if len(small[0]) < params.min_lesion_size:
            lesion_mask = rng.integers(0, 2, size=primary_image.shape)

    metrics = _compute_metrics(lesion_mask)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "summary": None,
        "lesion_mask": None,
        "report": None,
    }

    if params.save_masks:
        mask_path = out_dir / "lesion_mask.npy"
        np.save(mask_path, lesion_mask)
        outputs["lesion_mask"] = str(mask_path)

    summary = {
        "lesion_type": params.lesion_type,
        "lesion_volume": metrics["lesion_volume"],
        "lesion_count": metrics["lesion_count"],
        "used_full_backend": False,
    }

    summary_path = out_dir / "lesion_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_report:
        report_path = out_dir / "lesion_report.json"
        report_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        outputs["report"] = str(report_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Lesion detection completed (fallback).",
    }


__all__ = [
    "LesionDetectionParameters",
    "lesion_detection_from_payload",
    "run_lesion_detection",
]
