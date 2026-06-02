"""Feature selection helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class FeatureSelectionParameters:
    """Configuration for feature selection."""

    data_file: str
    labels_file: Optional[str]
    output_dir: str
    method: str
    task_type: str
    n_features: Optional[int]
    percentile: Optional[int]
    random_state: Optional[int]
    save_indices: bool
    save_scores: bool
    save_reduced_data: bool


def feature_selection_from_payload(
    payload: Dict[str, object],
) -> FeatureSelectionParameters:
    """Build parameters from payload."""

    return FeatureSelectionParameters(
        data_file=str(payload["data_file"]),
        labels_file=payload.get("labels_file"),
        output_dir=str(payload.get("output_dir", Path.cwd() / "feature_selection")),
        method=str(payload.get("method", "univariate")).lower(),
        task_type=str(payload.get("task_type", "classification")).lower(),
        n_features=payload.get("n_features"),
        percentile=payload.get("percentile"),
        random_state=payload.get("random_state"),
        save_indices=bool(payload.get("save_indices", True)),
        save_scores=bool(payload.get("save_scores", True)),
        save_reduced_data=bool(payload.get("save_reduced_data", True)),
    )


def _load_array(path: str) -> np.ndarray:
    arr_path = Path(path)
    if arr_path.suffix == ".npy":
        return np.load(arr_path)
    if arr_path.suffix == ".npz":
        npz = np.load(arr_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported data format: {path}")


def _determine_n_features(params: FeatureSelectionParameters, n_total: int) -> int:
    if params.n_features is not None:
        return int(np.clip(params.n_features, 1, n_total))
    if params.percentile is not None:
        k = int(np.ceil(n_total * params.percentile / 100.0))
        return max(1, min(k, n_total))
    return min(50, n_total)


def _compute_scores(
    data: np.ndarray,
    labels: Optional[np.ndarray],
    method: str,
    rng: np.random.Generator,
) -> np.ndarray:
    if method == "variance":
        return np.var(data, axis=0)
    if labels is not None and method in {"univariate", "mutual_info"}:
        means = []
        uniques = np.unique(labels)
        for lbl in uniques:
            means.append(np.mean(data[labels == lbl], axis=0))
        means = np.stack(means)
        return np.std(means, axis=0)
    if method == "stability":
        return rng.random(data.shape[1])
    return np.var(data, axis=0)


def run_feature_selection(params: FeatureSelectionParameters) -> Dict[str, object]:
    """Execute a lightweight feature selection routine."""

    rng = np.random.default_rng(params.random_state)

    data = _load_array(params.data_file)
    labels = _load_array(params.labels_file) if params.labels_file else None

    if data.ndim == 1:
        data = data[:, np.newaxis]

    n_samples, n_features = data.shape
    selected_count = _determine_n_features(params, n_features)

    scores = _compute_scores(data, labels, params.method, rng)
    order = np.argsort(scores)[::-1]
    selected_indices = order[:selected_count]

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "summary": None,
        "indices": None,
        "scores": None,
        "reduced_data": None,
    }

    summary = {
        "method": params.method,
        "task_type": params.task_type,
        "n_samples": n_samples,
        "n_features": n_features,
        "selected_features": int(selected_count),
        "used_full_backend": False,
    }

    summary_path = out_dir / "feature_selection_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_indices:
        indices_path = out_dir / "selected_indices.npy"
        np.save(indices_path, selected_indices)
        outputs["indices"] = str(indices_path)

    if params.save_scores:
        scores_path = out_dir / "feature_scores.npy"
        np.save(scores_path, scores)
        outputs["scores"] = str(scores_path)

    if params.save_reduced_data:
        reduced = data[:, selected_indices]
        reduced_path = out_dir / "reduced_data.npy"
        np.save(reduced_path, reduced)
        outputs["reduced_data"] = str(reduced_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "selected_indices": selected_indices.tolist(),
        "scores": scores[selected_indices].tolist(),
        "message": "Feature selection completed (fallback).",
    }


__all__ = [
    "FeatureSelectionParameters",
    "feature_selection_from_payload",
    "run_feature_selection",
]
