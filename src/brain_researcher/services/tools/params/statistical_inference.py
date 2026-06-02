"""Statistical inference helpers with bootstrap-oriented fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


@dataclass(frozen=True)
class StatisticalInferenceParameters:
    data_file: str
    labels_file: Optional[str] = None
    covariates_file: Optional[str] = None
    method: str = "bootstrap"
    test_type: str = "mean_diff"
    n_bootstrap: int = 1000
    bootstrap_method: str = "percentile"
    confidence_level: float = 0.95
    prior_type: str = "uninformative"
    prior_params: Optional[Dict[str, float]] = None
    n_mcmc: int = 5000
    burn_in: int = 1000
    robust_method: str = "trimmed_mean"
    trim_proportion: float = 0.1
    resampling_method: str = "permutation"
    n_resamples: int = 1000
    compute_effect_size: bool = True
    effect_size_type: str = "cohen_d"
    compute_power: bool = False
    target_effect_size: Optional[float] = None
    correct_multiple: bool = True
    correction_method: str = "fdr"
    compute_confidence_regions: bool = True
    region_method: str = "ellipse"
    output_dir: str = str(Path.cwd() / "statistical_inference")
    save_samples: bool = True
    save_intervals: bool = True
    save_effect_sizes: bool = True
    seed: Optional[int] = None


def statistical_inference_from_payload(
    payload: Dict[str, Any],
) -> StatisticalInferenceParameters:
    return StatisticalInferenceParameters(
        data_file=str(payload["data_file"]),
        labels_file=payload.get("labels_file"),
        covariates_file=payload.get("covariates_file"),
        method=str(payload.get("method", "bootstrap")),
        test_type=str(payload.get("test_type", "mean_diff")),
        n_bootstrap=int(payload.get("n_bootstrap", 1000)),
        bootstrap_method=str(payload.get("bootstrap_method", "percentile")),
        confidence_level=float(payload.get("confidence_level", 0.95)),
        prior_type=str(payload.get("prior_type", "uninformative")),
        prior_params=payload.get("prior_params"),
        n_mcmc=int(payload.get("n_mcmc", 5000)),
        burn_in=int(payload.get("burn_in", 1000)),
        robust_method=str(payload.get("robust_method", "trimmed_mean")),
        trim_proportion=float(payload.get("trim_proportion", 0.1)),
        resampling_method=str(payload.get("resampling_method", "permutation")),
        n_resamples=int(payload.get("n_resamples", 1000)),
        compute_effect_size=bool(payload.get("compute_effect_size", True)),
        effect_size_type=str(payload.get("effect_size_type", "cohen_d")),
        compute_power=bool(payload.get("compute_power", False)),
        target_effect_size=payload.get("target_effect_size"),
        correct_multiple=bool(payload.get("correct_multiple", True)),
        correction_method=str(payload.get("correction_method", "fdr")),
        compute_confidence_regions=bool(
            payload.get("compute_confidence_regions", True)
        ),
        region_method=str(payload.get("region_method", "ellipse")),
        output_dir=(
            str(payload["output_dir"])
            if payload.get("output_dir")
            else str(Path.cwd() / "statistical_inference")
        ),
        save_samples=bool(payload.get("save_samples", True)),
        save_intervals=bool(payload.get("save_intervals", True)),
        save_effect_sizes=bool(payload.get("save_effect_sizes", True)),
        seed=payload.get("seed"),
    )


def _load_matrix(path: str) -> np.ndarray:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(path)

    if file_path.suffix in {".npy", ".npz"}:
        data = np.load(file_path)
        if isinstance(data, np.lib.npyio.NpzFile):
            data = data[data.files[0]]
        return np.asarray(data, dtype=float)

    # fall back to CSV/TSV
    delimiter = "," if file_path.suffix.lower() == ".csv" else None
    return np.loadtxt(file_path, delimiter=delimiter)


def _bootstrap_samples(
    data: np.ndarray, n_bootstrap: int, rng: np.random.Generator
) -> np.ndarray:
    n_samples = data.shape[0]
    max_bootstrap = max(100, min(n_bootstrap, 4096))
    indices = rng.integers(0, n_samples, size=(max_bootstrap, n_samples))
    resampled = data[indices]
    return resampled.mean(axis=1)


def _summarise(values: np.ndarray) -> Dict[str, float]:
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
    }


def _effect_size(mean: np.ndarray, data: np.ndarray, method: str) -> np.ndarray:
    method = method.lower()
    std = data.std(axis=0, ddof=1)
    std[std == 0] = 1e-6
    if method in {"cohen_d", "hedges_g"}:
        return mean / std
    if method == "glass_delta":
        return mean / std
    return mean


def _power_estimate(effect_size: float, n: int, alpha: float) -> float:
    # Rough approximation using normal distribution
    if n <= 0:
        return 0.0
    z_alpha = 1.96  # ~95%
    z_beta = max((effect_size * np.sqrt(n) - z_alpha), -5)
    beta = 1.0 - 0.5 * (1 + np.math.erf(z_beta / np.sqrt(2)))
    return float(1.0 - beta)


def run_statistical_inference(params: StatisticalInferenceParameters) -> Dict[str, Any]:
    data = _load_matrix(params.data_file)
    if data.ndim == 1:
        data = data[:, np.newaxis]

    rng = np.random.default_rng(params.seed)
    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    estimate = data.mean(axis=0)
    bootstrap_samples = _bootstrap_samples(data, params.n_bootstrap, rng)

    lower_q = (1.0 - params.confidence_level) / 2.0 * 100
    upper_q = (1.0 - (1.0 - params.confidence_level) / 2.0) * 100
    intervals = np.stack(
        [
            np.percentile(bootstrap_samples, lower_q, axis=0),
            np.percentile(bootstrap_samples, upper_q, axis=0),
        ],
        axis=1,
    )

    outputs: Dict[str, Optional[str]] = {
        "summary": None,
        "bootstrap_samples": None,
        "confidence_intervals": None,
        "effect_sizes": None,
    }

    if params.save_samples:
        samples_path = output_dir / "stat_inference_bootstrap_samples.npy"
        np.save(samples_path, bootstrap_samples)
        outputs["bootstrap_samples"] = str(samples_path)

    if params.save_intervals:
        intervals_path = output_dir / "stat_inference_intervals.npy"
        np.save(intervals_path, intervals)
        outputs["confidence_intervals"] = str(intervals_path)

    effect_sizes = None
    if params.compute_effect_size:
        effect_sizes = _effect_size(estimate, data, params.effect_size_type)
        if params.save_effect_sizes:
            effect_path = output_dir / "stat_inference_effect_sizes.npy"
            np.save(effect_path, effect_sizes)
            outputs["effect_sizes"] = str(effect_path)

    power = None
    if params.compute_power and params.target_effect_size is not None:
        power = _power_estimate(
            float(params.target_effect_size), data.shape[0], params.confidence_level
        )

    summary = {
        "method": params.method,
        "test_type": params.test_type,
        "n_subjects": int(data.shape[0]),
        "n_features": int(data.shape[1]),
        "confidence_level": float(params.confidence_level),
        "estimate_stats": _summarise(estimate),
        "bootstrap_summary": _summarise(bootstrap_samples.mean(axis=1)),
        "used_full_backend": False,
    }

    if effect_sizes is not None:
        summary["effect_size_stats"] = _summarise(effect_sizes)
    if power is not None:
        summary["power_estimate"] = power

    summary_path = output_dir / "statistical_inference_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    result: Dict[str, Any] = {
        "outputs": outputs,
        "summary": summary,
        "message": "Statistical inference completed (fallback).",
    }

    if params.compute_confidence_regions:
        region_path = output_dir / "stat_inference_region.json"
        region_path.write_text(
            json.dumps(
                {"method": params.region_method, "status": "placeholder"}, indent=2
            ),
            encoding="utf-8",
        )
        result["confidence_region"] = str(region_path)

    return result


__all__ = [
    "StatisticalInferenceParameters",
    "statistical_inference_from_payload",
    "run_statistical_inference",
]
