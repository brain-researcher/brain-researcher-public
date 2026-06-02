"""Shared helpers for MNE connectivity analysis."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)
from brain_researcher.core.analysis.value_domain_router import (
    contracts_for,
    evaluate_value_domain,
    write_value_domain_diagnostics,
)
from brain_researcher.core.utils import configure_mne_environment

_SPECTRAL_METHODS = {
    "coherence",
    "coherency",
    "imcoh",
    "pli",
    "wpli",
    "plv",
    "psi",
}


def _ensure_tuple(value: Any) -> tuple[Any, ...] | None:
    if value is None:
        return None
    if isinstance(value, tuple | list | set):
        return tuple(value)
    return (value,)


def _ensure_method_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("coherence",)
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _ensure_indices(value: Any) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    if value is None:
        return None
    if (
        isinstance(value, tuple | list)
        and len(value) == 2
        and all(isinstance(v, tuple | list) for v in value)
    ):
        return (tuple(int(x) for x in value[0]), tuple(int(x) for x in value[1]))
    return None


@dataclass(frozen=True)
class MNEConnectivityParameters:
    output_dir: str
    methods: tuple[str, ...]
    epochs_file: str | None = None
    raw_file: str | None = None
    time_series: str | None = None
    mode: str = "multitaper"
    fmin: tuple[float, ...] | None = None
    fmax: tuple[float, ...] | None = None
    fskip: int = 0
    faverage: bool = False
    n_cycles: tuple[float, ...] | None = None
    tmin: float | None = None
    tmax: float | None = None
    picks: tuple[str, ...] | None = None
    indices: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    n_surrogates: int = 0
    p_value: float = 0.05
    gc_n_lags: int = 10
    save_matrix: bool = True
    save_plots: bool = True
    return_generator: bool = False


def mne_connectivity_from_payload(payload: dict[str, Any]) -> MNEConnectivityParameters:
    methods = _ensure_method_tuple(payload.get("method", "coherence"))
    picks = payload.get("picks")
    picks_tuple: tuple[str, ...] | None
    if isinstance(picks, str):
        picks_tuple = (picks,)
    else:
        picks_tuple = _ensure_tuple(picks)

    def _ensure_float_tuple(val: Any) -> tuple[float, ...] | None:
        if val is None:
            return None
        if isinstance(val, tuple | list | set):
            return tuple(float(v) for v in val)
        return (float(val),)

    n_cycles = payload.get("n_cycles")
    if isinstance(n_cycles, np.ndarray):
        n_cycles = n_cycles.tolist()

    return MNEConnectivityParameters(
        output_dir=str(payload["output_dir"]),
        methods=methods,
        epochs_file=payload.get("epochs_file"),
        raw_file=payload.get("raw_file"),
        time_series=payload.get("time_series"),
        mode=str(payload.get("mode", "multitaper")),
        fmin=_ensure_float_tuple(payload.get("fmin")),
        fmax=_ensure_float_tuple(payload.get("fmax")),
        fskip=int(payload.get("fskip", 0)),
        faverage=bool(payload.get("faverage", False)),
        n_cycles=_ensure_float_tuple(n_cycles),
        tmin=payload.get("tmin"),
        tmax=payload.get("tmax"),
        picks=picks_tuple,
        indices=_ensure_indices(payload.get("indices")),
        n_surrogates=int(payload.get("n_surrogates", 0)),
        p_value=float(payload.get("p_value", 0.05)),
        gc_n_lags=int(payload.get("gc_n_lags", 10)),
        save_matrix=bool(payload.get("save_matrix", True)),
        save_plots=bool(payload.get("save_plots", True)),
        return_generator=bool(payload.get("return_generator", False)),
    )


def _load_epochs(path: str, tmin: float | None, tmax: float | None):
    import mne

    epochs = mne.read_epochs(path, preload=True)
    if tmin is not None or tmax is not None:
        epochs = epochs.copy().crop(tmin=tmin, tmax=tmax)
    data = epochs.get_data()
    labels = tuple(epochs.ch_names)
    sfreq = float(epochs.info["sfreq"])
    return data, sfreq, labels


def _load_raw(path: str, tmin: float | None, tmax: float | None):
    import mne

    raw = mne.io.read_raw(path, preload=True)
    if tmin is not None or tmax is not None:
        raw.crop(tmin=tmin, tmax=tmax)
    data = raw.get_data()[np.newaxis, :, :]
    labels = tuple(raw.ch_names)
    sfreq = float(raw.info["sfreq"])
    return data, sfreq, labels


def _load_time_series(path: str):
    arr = np.load(path)
    if arr.ndim == 1:
        arr = arr[np.newaxis, np.newaxis, :]
    elif arr.ndim == 2:
        arr = arr[np.newaxis, ...]
    elif arr.ndim == 3:
        pass
    else:
        raise ValueError("time_series array must be 1D, 2D, or 3D")
    sfreq = 1.0
    labels = tuple(f"ch_{i}" for i in range(arr.shape[1]))
    return arr, sfreq, labels


def _apply_picks(
    data: np.ndarray,
    labels: tuple[str, ...],
    picks: tuple[str, ...] | None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    if picks is None:
        return data, labels
    indices: list[int] = []
    for pick in picks:
        if pick.lower() in ("eeg", "meg"):
            # Without full sensor metadata we cannot distinguish; skip.
            continue
        try:
            idx = labels.index(pick)
            indices.append(idx)
        except ValueError:
            continue
    if not indices:
        return data, labels
    data = data[:, indices, :]
    new_labels = tuple(labels[i] for i in indices)
    return data, new_labels


def _concatenate_epochs(data: np.ndarray) -> np.ndarray:
    n_epochs, n_channels, n_times = data.shape
    return data.transpose(1, 0, 2).reshape(n_channels, n_epochs * n_times)


def _frequency_mask(
    freqs: np.ndarray, params: MNEConnectivityParameters
) -> np.ndarray | None:
    if freqs.size == 0:
        return None
    fmin = params.fmin[0] if params.fmin else None
    fmax = params.fmax[0] if params.fmax else None
    if fmin is None and fmax is None:
        return None
    mask = np.ones_like(freqs, dtype=bool)
    if fmin is not None:
        mask &= freqs >= fmin
    if fmax is not None:
        mask &= freqs <= fmax
    return mask


def _coherence_matrix(
    data: np.ndarray, sfreq: float, params: MNEConnectivityParameters
) -> np.ndarray:
    from scipy.signal import coherence

    flattened = _concatenate_epochs(data)
    n_channels = flattened.shape[0]
    matrix = np.zeros((n_channels, n_channels))
    for i in range(n_channels):
        matrix[i, i] = 1.0
        for j in range(i + 1, n_channels):
            freqs, coh = coherence(
                flattened[i], flattened[j], fs=sfreq if sfreq else 1.0
            )
            mask = _frequency_mask(freqs, params)
            if mask is not None and mask.any():
                coh = coh[mask]
            value = float(np.mean(coh)) if coh.size else 0.0
            matrix[i, j] = matrix[j, i] = value
    return matrix


def _plv_matrix(data: np.ndarray) -> np.ndarray:
    from scipy.signal import hilbert

    analytic = hilbert(data, axis=-1)
    phases = np.angle(analytic)
    n_epochs, n_channels, _ = phases.shape
    matrix = np.ones((n_channels, n_channels))
    for i in range(n_channels):
        for j in range(i + 1, n_channels):
            phase_diff = np.exp(1j * (phases[:, i, :] - phases[:, j, :]))
            plv = np.abs(np.mean(phase_diff))
            matrix[i, j] = matrix[j, i] = float(plv)
    return matrix


def _correlation_matrix(data: np.ndarray) -> np.ndarray:
    flattened = _concatenate_epochs(data)
    corr = np.corrcoef(flattened)
    return corr


def _covariance_matrix(data: np.ndarray) -> np.ndarray:
    flattened = _concatenate_epochs(data)
    cov = np.cov(flattened)
    return cov


def _compute_connectivity_fallback(
    data: np.ndarray,
    sfreq: float,
    method: str,
    params: MNEConnectivityParameters,
) -> np.ndarray:
    method = method.lower()
    if method in {"coherence", "coherency", "imcoh"}:
        return _coherence_matrix(data, sfreq, params)
    if method in {"plv", "pli", "wpli", "psi"}:
        return _plv_matrix(data)
    if method in {"cor", "corr", "correlation"}:
        return _correlation_matrix(data)
    if method in {"cov", "covariance"}:
        return _covariance_matrix(data)
    # Default to correlation as a conservative fallback.
    return _correlation_matrix(data)


def _compute_connectivity_with_package(
    data: np.ndarray,
    sfreq: float,
    method: str,
    params: MNEConnectivityParameters,
) -> np.ndarray:
    import inspect

    from mne_connectivity import spectral_connectivity_epochs

    fmin = params.fmin
    fmax = params.fmax
    n_cycles = params.n_cycles
    kwargs = {
        "data": data,
        "method": method,
        "mode": params.mode,
        "sfreq": sfreq if sfreq else 1.0,
        "fmin": fmin[0] if fmin else None,
        "fmax": fmax[0] if fmax else None,
        "indices": params.indices,
        "fskip": params.fskip,
        "faverage": params.faverage,
        "verbose": False,
    }
    sig = inspect.signature(spectral_connectivity_epochs)
    if "n_cycles" in sig.parameters:
        kwargs["n_cycles"] = n_cycles[0] if n_cycles else None
    if "cwt_n_cycles" in sig.parameters:
        kwargs["cwt_n_cycles"] = n_cycles[0] if n_cycles else None
    con = spectral_connectivity_epochs(
        **{k: v for k, v in kwargs.items() if k in sig.parameters}
    )
    matrix = con.get_data(output="dense")
    if matrix.ndim == 3:
        matrix = matrix.mean(axis=-1)
    return matrix


def _plot_matrix(
    matrix: np.ndarray, labels: Iterable[str], title: str, output_file: Path
) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(matrix, cmap="viridis", interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.8)
    size = len(matrix)
    ax.set_title(title)
    if size <= 16:
        ax.set_xticks(range(size))
        ax.set_yticks(range(size))
        ax.set_xticklabels(labels, rotation=90)
        ax.set_yticklabels(labels)
    plt.tight_layout()
    fig.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_mne_connectivity(params: MNEConnectivityParameters) -> dict[str, Any]:
    configure_mne_environment()
    cache_dir = Path(params.output_dir) / ".numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_HOME", str(Path(params.output_dir)))

    import matplotlib

    matplotlib.use("Agg")

    if params.epochs_file:
        data, sfreq, labels = _load_epochs(params.epochs_file, params.tmin, params.tmax)
    elif params.raw_file:
        data, sfreq, labels = _load_raw(params.raw_file, params.tmin, params.tmax)
    elif params.time_series:
        data, sfreq, labels = _load_time_series(params.time_series)
    else:
        raise ValueError(
            "At least one of epochs_file, raw_file, or time_series must be provided."
        )

    data, labels = _apply_picks(data, labels, params.picks)
    output_path = Path(params.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    used_package = False
    method_results: dict[str, dict[str, Any]] = {}
    matrices: dict[str, str] = {}
    feature_contracts: dict[str, str] = {}
    plots: dict[str, str] = {}
    # Value-domain gate (record-or-raise, lenient): accumulate per-method
    # diagnostics into one sink and write a single sidecar after the loop. A
    # connectivity matrix is treated downstream as a covariance and may be
    # inverted, so it must be finite and well-conditioned; violations are
    # recorded (strict=False) instead of raising so the run still succeeds and
    # the review-gate detector
    # (checks.value_domain.value_domain_contract_violation_check) surfaces a
    # blocking finding. finite is always-on; well_conditioned is router-selected
    # for covariance/precision/correlation-style methods.
    value_domain_sink: list[dict[str, Any]] = []

    for method in params.methods:
        method_lower = method.lower()
        try:
            if method_lower in _SPECTRAL_METHODS:
                matrix = _compute_connectivity_with_package(
                    data, sfreq, method_lower, params
                )
                used_package = True
            else:
                raise ImportError
        except (ImportError, AttributeError, ValueError, RuntimeError):
            matrix = _compute_connectivity_fallback(data, sfreq, method_lower, params)

        matrix_label = f"{method_lower}_connectivity_matrix"
        evaluate_value_domain(
            "finite", matrix, matrix_label, strict=False, sink=value_domain_sink
        )
        if matrix.ndim == 2 and matrix.shape[0] == matrix.shape[1]:
            for contract in contracts_for(f"connectivity_{method_lower}"):
                evaluate_value_domain(
                    contract,
                    matrix,
                    matrix_label,
                    strict=False,
                    sink=value_domain_sink,
                )

        if params.save_matrix:
            matrix_file = output_path / f"connectivity_{method_lower}.npy"
            np.save(matrix_file, matrix)
            matrices[method] = str(matrix_file)
            contract = FeatureContract(
                matrix_kind=f"eeg_sensor_{method_lower}",
                source_level="eeg_epochs",
                n_rois=int(matrix.shape[0]),
                n_timepoints=int(data.shape[-1]) if data.ndim >= 3 else None,
                effective_n_timepoints=int(data.shape[-1]) if data.ndim >= 3 else None,
                transform_state="sensor_connectivity",
                extras={
                    "n_epochs": int(data.shape[0]) if data.ndim >= 3 else None,
                    "sfreq": float(sfreq),
                    "mode": params.mode,
                    "fmin": list(params.fmin) if params.fmin else None,
                    "fmax": list(params.fmax) if params.fmax else None,
                },
            )
            contract_dir = output_path / "feature_contracts" / method_lower
            feature_contracts[method] = str(
                write_feature_contract(contract, contract_dir)
            )

        if params.save_plots:
            plot_file = output_path / f"connectivity_{method_lower}.png"
            _plot_matrix(matrix, labels, f"{method.upper()} Connectivity", plot_file)
            plots[method] = str(plot_file)

        method_results[method] = {
            "shape": list(matrix.shape),
            "mean": float(np.mean(matrix)),
            "std": float(np.std(matrix)),
            "max": float(np.max(matrix)),
            "min": float(np.min(matrix)),
        }

    report = {
        "methods": list(params.methods),
        "n_channels": int(data.shape[1]),
        "frequency_range": [
            params.fmin[0] if params.fmin else None,
            params.fmax[0] if params.fmax else None,
        ],
        "mode": params.mode,
        "results": method_results,
    }
    report_file = output_path / "connectivity_report.json"
    with open(report_file, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    value_domain_path = write_value_domain_diagnostics(value_domain_sink, output_path)

    message = f"Connectivity analysis completed for {len(params.methods)} method(s)."

    return {
        "outputs": {
            "report": str(report_file),
            "matrices": matrices,
            "feature_contracts": feature_contracts,
            "plots": plots if params.save_plots else {},
            "value_domain_diagnostics": str(value_domain_path),
        },
        "summary": report,
        "message": message,
        "used_mne_connectivity_package": used_package,
    }


__all__ = [
    "MNEConnectivityParameters",
    "mne_connectivity_from_payload",
    "run_mne_connectivity",
]
