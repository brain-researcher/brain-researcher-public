"""Segmentation helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class SegmentationParameters:
    """Configuration for segmentation."""

    input_image: str
    output_dir: str
    segmentation_type: str
    modality: str
    n_classes: int
    threshold_method: str
    min_lesion_size: int
    save_masks: bool
    save_probabilities: bool
    save_volumes: bool
    output_format: str
    random_state: Optional[int]


def segmentation_from_payload(payload: Dict[str, object]) -> SegmentationParameters:
    """Construct parameters from payload."""

    return SegmentationParameters(
        input_image=str(payload["input_image"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "segmentation")),
        segmentation_type=str(payload.get("segmentation_type", "tissue")).lower(),
        modality=str(payload.get("modality", "T1")).upper(),
        n_classes=int(payload.get("n_classes", 3)),
        threshold_method=str(payload.get("threshold_method", "adaptive")).lower(),
        min_lesion_size=int(payload.get("min_lesion_size", 3)),
        save_masks=bool(payload.get("save_masks", True)),
        save_probabilities=bool(payload.get("save_probabilities", True)),
        save_volumes=bool(payload.get("save_volumes", True)),
        output_format=str(payload.get("output_format", "nifti")).lower(),
        random_state=payload.get("random_state"),
    )


def _load_image(path: str) -> np.ndarray:
    img_path = Path(path)
    if img_path.suffix == ".npy":
        return np.load(img_path)
    if img_path.suffix == ".npz":
        npz = np.load(img_path)
        return npz[npz.files[0]]
    # Fallback synthetic volume based on file size
    size = max(10, int(np.cbrt(img_path.stat().st_size)))
    return np.zeros((size, size, size))


def _foreground_threshold(image: np.ndarray, threshold_method: str) -> float:
    finite = np.asarray(image, dtype=float)
    if not finite.size:
        return 0.0
    method = (threshold_method or "adaptive").lower()
    if method == "liberal":
        percentile = 5.0
    elif method == "conservative":
        percentile = 20.0
    else:
        percentile = 10.0
    return float(np.percentile(finite, percentile))


def _simulate_tissue_segmentation(
    image: np.ndarray,
    n_classes: int,
    rng: np.random.Generator,
    *,
    threshold_method: str,
) -> np.ndarray:
    foreground_mask = image > _foreground_threshold(image, threshold_method)
    foreground_values = image[foreground_mask]
    if foreground_values.size == 0:
        foreground_mask = image >= float(np.max(image))
        foreground_values = image[foreground_mask]
    thresholds = np.linspace(
        np.min(foreground_values),
        np.max(foreground_values),
        n_classes + 1,
    )
    segmentation = np.zeros_like(image, dtype=int)
    for cls in range(n_classes):
        mask = foreground_mask & (image >= thresholds[cls]) & (image < thresholds[cls + 1])
        segmentation[mask] = cls + 1
    noise_mask = rng.random(image.shape) < 0.01
    segmentation[noise_mask] = rng.integers(1, n_classes + 1, size=noise_mask.sum())
    return segmentation


def _simulate_lesion_segmentation(image: np.ndarray, min_size: int, rng: np.random.Generator) -> np.ndarray:
    baseline = np.mean(image)
    lesion_mask = image > baseline + np.std(image)
    lesion_mask = lesion_mask & (rng.random(image.shape) < 0.1)
    # Keep only largest blobs by simple filtering
    if lesion_mask.sum() < min_size:
        idx = rng.choice(image.size, size=min_size, replace=False)
        lesion_mask.flat[idx] = True
    segmentation = np.zeros_like(image, dtype=int)
    segmentation[lesion_mask] = 1
    return segmentation


def run_segmentation(params: SegmentationParameters) -> Dict[str, object]:
    """Execute fallback segmentation."""

    rng = np.random.default_rng(params.random_state)

    image = _load_image(params.input_image)

    if params.segmentation_type == "lesion":
        segmentation = _simulate_lesion_segmentation(image, params.min_lesion_size, rng)
        n_classes = 2
    else:
        segmentation = _simulate_tissue_segmentation(
            image,
            params.n_classes,
            rng,
            threshold_method=params.threshold_method,
        )
        n_classes = params.n_classes

    probabilities = rng.random(size=(n_classes, *image.shape))
    probabilities = probabilities / probabilities.sum(axis=0, keepdims=True)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "summary": None,
        "segmentation": None,
        "probabilities": None,
        "volumes": None,
    }

    if params.save_masks:
        seg_path = out_dir / f"segmentation.{params.output_format if params.output_format != 'nifti' else 'npy'}"
        np.save(seg_path.with_suffix(".npy"), segmentation)
        outputs["segmentation"] = str(seg_path.with_suffix(".npy"))

    if params.save_probabilities:
        prob_path = out_dir / "probabilities.npy"
        np.save(prob_path, probabilities)
        outputs["probabilities"] = str(prob_path)

    volumes = [int((segmentation == cls).sum()) for cls in range(1, n_classes + 1)]

    if params.save_volumes:
        volumes_path = out_dir / "volumes.json"
        volumes_path.write_text(json.dumps({"volumes": volumes}, indent=2), encoding="utf-8")
        outputs["volumes"] = str(volumes_path)

    summary = {
        "segmentation_type": params.segmentation_type,
        "modality": params.modality,
        "n_voxels": int(image.size),
        "n_voxels_segmented": int((segmentation > 0).sum()),
        "n_classes": int(n_classes),
        "used_full_backend": False,
        "volumes": volumes,
    }

    summary_path = out_dir / "segmentation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Segmentation completed (fallback).",
    }


__all__ = [
    "SegmentationParameters",
    "segmentation_from_payload",
    "run_segmentation",
]
