"""Encoding model helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class EncodingModelParameters:
    """Configuration for encoding model estimation."""

    brain_data_file: str
    stimulus_file: str
    output_dir: str
    model_type: str
    n_folds: int
    standardize: bool
    add_derivatives: bool
    random_state: int | None
    save_models: bool
    save_predictions: bool
    save_weights: bool


def encoding_model_from_payload(payload: dict[str, object]) -> EncodingModelParameters:
    """Create parameters from payload."""

    return EncodingModelParameters(
        brain_data_file=str(payload["brain_data_file"]),
        stimulus_file=str(payload["stimulus_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "encoding_models")),
        model_type=str(payload.get("model_type", "ridge")).lower(),
        n_folds=int(payload.get("n_folds", 5)),
        standardize=bool(payload.get("standardize", True)),
        add_derivatives=bool(payload.get("add_derivatives", False)),
        random_state=payload.get("random_state"),
        save_models=bool(payload.get("save_models", True)),
        save_predictions=bool(payload.get("save_predictions", True)),
        save_weights=bool(payload.get("save_weights", True)),
    )


def _load_array(path: str) -> np.ndarray:
    file_path = Path(path)
    if file_path.suffix == ".npy":
        return np.load(file_path)
    if file_path.suffix == ".npz":
        npz = np.load(file_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported array format: {path}")


def _prepare_design_matrix(stimulus: np.ndarray, add_derivatives: bool) -> np.ndarray:
    design = stimulus
    if add_derivatives:
        first_derivative = np.diff(stimulus, axis=0, prepend=stimulus[0:1])
        design = np.concatenate([design, first_derivative], axis=1)
    return design


def _fit_ridge(
    design: np.ndarray, responses: np.ndarray, alpha: float = 1.0
) -> tuple[np.ndarray, bool, str]:
    # Closed-form ridge solution.
    XtX = design.T @ design
    penalty = alpha * np.eye(XtX.shape[0])
    XtY = design.T @ responses
    ridge_matrix = XtX + penalty
    try:
        weights = np.linalg.solve(ridge_matrix, XtY)
        if np.all(np.isfinite(weights)):
            return weights, True, "numpy_solve"
    except np.linalg.LinAlgError:
        pass

    # Deterministic fallback for rank-deficient / unstable systems.
    weights = np.linalg.pinv(ridge_matrix) @ XtY
    if not np.all(np.isfinite(weights)):
        weights, *_ = np.linalg.lstsq(ridge_matrix, XtY, rcond=None)
    return weights, False, "numpy_fallback"


def run_encoding_model(params: EncodingModelParameters) -> dict[str, object]:
    """Execute encoding model fitting with lightweight calculations."""

    brain_data = _load_array(params.brain_data_file)
    stimulus = _load_array(params.stimulus_file)

    if brain_data.shape[0] != stimulus.shape[0]:
        raise ValueError("Brain data and stimulus must have matching time dimension.")

    design = _prepare_design_matrix(stimulus, params.add_derivatives)
    if params.standardize:
        design = (design - np.mean(design, axis=0)) / (np.std(design, axis=0) + 1e-6)

    weights, used_full_backend, backend_name = _fit_ridge(design, brain_data, alpha=1.0)

    predicted = design @ weights
    residuals = brain_data - predicted
    r2_scores = 1.0 - np.sum(residuals**2, axis=0) / (
        np.sum((brain_data - np.mean(brain_data, axis=0)) ** 2, axis=0) + 1e-8
    )
    # Handle potential numerical issues
    r2_scores = np.clip(r2_scores, -1.0, 1.0)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "summary": None,
        "weights": None,
        "predictions": None,
        "model": None,
    }

    if params.save_weights:
        weights_path = out_dir / "encoding_weights.npy"
        np.save(weights_path, weights)
        outputs["weights"] = str(weights_path)

    if params.save_predictions:
        predictions_path = out_dir / "encoding_predictions.npy"
        np.save(predictions_path, predicted)
        outputs["predictions"] = str(predictions_path)

    summary = {
        "model_type": params.model_type,
        "n_timepoints": int(brain_data.shape[0]),
        "n_voxels": int(brain_data.shape[1]),
        "n_features": int(design.shape[1]),
        "mean_r2": float(np.mean(r2_scores)),
        "median_r2": float(np.median(r2_scores)),
        "used_full_backend": bool(used_full_backend),
        "backend_name": backend_name,
    }

    summary_path = out_dir / "encoding_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_models:
        model_path = out_dir / "encoding_model.json"
        model_path.write_text(
            json.dumps({"alpha": 1.0, "type": params.model_type}), encoding="utf-8"
        )
        outputs["model"] = str(model_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "r2_scores": r2_scores.tolist(),
        "message": f"Encoding model completed ({backend_name}).",
    }


__all__ = [
    "EncodingModelParameters",
    "encoding_model_from_payload",
    "run_encoding_model",
]
