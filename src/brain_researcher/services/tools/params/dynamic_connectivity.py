"""Dynamic connectivity helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    write_feature_contract,
)
from brain_researcher.core.analysis.value_domain_router import (
    contracts_for,
    evaluate_value_domain,
    write_value_domain_diagnostics,
)


@dataclass(frozen=True)
class DynamicConnectivityParameters:
    """Configuration for dynamic connectivity analysis."""

    timeseries_file: str
    output_dir: str
    connectivity_method: str
    dynamic_method: str
    window_length: int | None
    window_overlap: float
    n_states: int
    random_state: int | None
    save_matrices: bool
    save_states: bool
    save_metrics: bool


def dynamic_connectivity_from_payload(
    payload: dict[str, object],
) -> DynamicConnectivityParameters:
    """Create parameters from payload."""

    return DynamicConnectivityParameters(
        timeseries_file=str(payload["timeseries_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "dynamic_connectivity")),
        connectivity_method=str(payload.get("connectivity_method", "correlation")),
        dynamic_method=str(payload.get("dynamic_method", "sliding_window")),
        window_length=payload.get("window_length"),
        window_overlap=float(payload.get("window_overlap", 0.5)),
        n_states=int(payload.get("n_states", 5)),
        random_state=payload.get("random_state"),
        save_matrices=bool(payload.get("save_matrices", True)),
        save_states=bool(payload.get("save_states", True)),
        save_metrics=bool(payload.get("save_metrics", True)),
    )


def _load_timeseries(path: str) -> np.ndarray:
    ts_path = Path(path)
    if ts_path.suffix == ".npy":
        arr = np.load(ts_path, allow_pickle=True)
        if isinstance(arr, np.lib.npyio.NpzFile):  # pragma: no cover
            first_key = list(arr.keys())[0]
            arr = arr[first_key]
        if getattr(arr, "dtype", None) is object:
            if arr.size != 1:
                raise ValueError(
                    "Timeseries object array must contain exactly one element (time x ROI)."
                )
            arr = arr.flat[0]
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        return np.asarray(arr)
    if ts_path.suffix == ".npz":
        npz = np.load(ts_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported timeseries format: {path}")


def _compute_window_indices(
    n_timepoints: int, window_len: int, overlap: float
) -> list[tuple[int, int]]:
    step = max(1, int(window_len * (1 - overlap)))
    indices = []
    start = 0
    while start + window_len <= n_timepoints:
        indices.append((start, start + window_len))
        start += step
    if not indices:
        indices.append((0, n_timepoints))
    return indices


def _window_connectivity(
    timeseries: np.ndarray, window_len: int, overlap: float
) -> np.ndarray:
    n_time, n_roi = timeseries.shape
    indices = _compute_window_indices(n_time, window_len, overlap)
    matrices = []
    for start, end in indices:
        window_ts = timeseries[start:end]
        if window_ts.shape[0] < 2:
            corr = np.zeros((n_roi, n_roi))
        else:
            corr = np.corrcoef(window_ts, rowvar=False)
        matrices.append(corr)
    return np.stack(matrices), indices


def _cluster_states(
    matrices: np.ndarray, n_states: int, rng: np.random.Generator
) -> np.ndarray:
    flat = matrices.reshape(matrices.shape[0], -1)
    centroids = flat[:n_states]
    if centroids.shape[0] < n_states:
        padding = rng.normal(size=(n_states - centroids.shape[0], flat.shape[1]))
        centroids = np.vstack([centroids, padding])
    distances = np.linalg.norm(flat[:, None, :] - centroids[None, :, :], axis=2)
    assignments = np.argmin(distances, axis=1)
    return assignments


def _compute_metrics(matrices: np.ndarray, assignments: np.ndarray) -> dict[str, float]:
    variability = float(np.std(matrices, axis=0).mean())
    dwell_time = float(
        np.bincount(assignments, minlength=np.max(assignments) + 1).mean()
    )
    transitions = np.sum(assignments[1:] != assignments[:-1])
    transition_rate = float(transitions / max(1, len(assignments) - 1))
    return {
        "variability": variability,
        "mean_dwell": dwell_time,
        "transition_rate": transition_rate,
    }


def run_dynamic_connectivity(
    params: DynamicConnectivityParameters,
) -> dict[str, object]:
    """Execute fallback dynamic connectivity analysis."""

    rng = np.random.default_rng(params.random_state)
    timeseries = _load_timeseries(params.timeseries_file)
    if timeseries.ndim != 2:
        raise ValueError("Timeseries must be 2D (time x ROI).")

    n_timepoints = timeseries.shape[0]
    window_len = params.window_length or max(10, n_timepoints // 5)
    window_len = min(window_len, n_timepoints)

    matrices, indices = _window_connectivity(
        timeseries, window_len, params.window_overlap
    )
    assignments = _cluster_states(matrices, params.n_states, rng)
    metrics = _compute_metrics(matrices, assignments)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "summary": None,
        "matrices": None,
        "states": None,
        "metrics": None,
        "feature_contract": None,
        "value_domain_diagnostics": None,
    }

    # Value-domain gate (record-or-raise, lenient). Each sliding-window matrix is
    # a per-window functional-connectivity matrix that downstream state
    # clustering / inversion treats as a covariance, so it must be finite and
    # well-conditioned. We record violations into a sidecar (strict=False)
    # instead of raising so the run still succeeds and the review-gate detector
    # (checks.value_domain.value_domain_contract_violation_check) surfaces a
    # blocking finding on the succeeded run. ``finite`` is the always-on
    # stage-boundary guard, evaluated once over the full window stack;
    # ``well_conditioned`` is per-window (the validator requires a 2D square
    # matrix) and is selected via the declarative router for covariance/
    # correlation-style methods.
    value_domain_sink: list[dict[str, Any]] = []
    stack_label = f"dynamic_{params.connectivity_method}_window_stack"
    evaluate_value_domain(
        "finite", matrices, stack_label, strict=False, sink=value_domain_sink
    )
    window_contracts = contracts_for(
        f"dynamic_connectivity_{params.connectivity_method}"
    )
    for window_index in range(matrices.shape[0]):
        window_label = f"dynamic_{params.connectivity_method}_window_{window_index}"
        for contract in window_contracts:
            evaluate_value_domain(
                contract,
                matrices[window_index],
                window_label,
                strict=False,
                sink=value_domain_sink,
            )
    value_domain_path = write_value_domain_diagnostics(value_domain_sink, out_dir)
    outputs["value_domain_diagnostics"] = str(value_domain_path)

    if params.save_matrices:
        matrices_path = out_dir / "dynamic_matrices.npy"
        np.save(matrices_path, matrices)
        outputs["matrices"] = str(matrices_path)
        try:
            contract = build_feature_contract(
                matrices,
                matrix_kind=f"dynamic_{params.connectivity_method}",
                source_level="roi_timeseries_sliding_windows",
                n_rois=int(timeseries.shape[1]),
                n_timepoints=int(n_timepoints),
                effective_n_timepoints=int(window_len),
                covariance_estimator="PearsonCorrelation",
                extras={
                    "n_windows": int(matrices.shape[0]),
                    "window_indices": [[int(a), int(b)] for a, b in indices],
                    "window_overlap": float(params.window_overlap),
                    "dynamic_method": params.dynamic_method,
                },
            )
            contract_path = write_feature_contract(contract, out_dir)
            outputs["feature_contract"] = str(contract_path)
        except Exception:
            outputs["feature_contract"] = None

    if params.save_states:
        states_path = out_dir / "state_assignments.npy"
        np.save(states_path, assignments)
        outputs["states"] = str(states_path)

    summary = {
        "connectivity_method": params.connectivity_method,
        "dynamic_method": params.dynamic_method,
        "n_windows": int(matrices.shape[0]),
        "window_length": int(window_len),
        "n_states": int(params.n_states),
        "metrics": metrics,
        "used_full_backend": False,
    }

    summary_path = out_dir / "dynamic_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_metrics:
        metrics_path = out_dir / "dynamic_metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        outputs["metrics"] = str(metrics_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Dynamic connectivity completed (fallback).",
    }


__all__ = [
    "DynamicConnectivityParameters",
    "dynamic_connectivity_from_payload",
    "run_dynamic_connectivity",
]
