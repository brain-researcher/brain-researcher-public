"""Generate scan-aligned physiological nuisance regressors from raw traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:  # pragma: no cover - optional at import time
    from scipy.signal import hilbert
except Exception:  # pragma: no cover
    hilbert = None  # type: ignore


@dataclass(frozen=True)
class PhysioNoiseRegressorParameters:
    """Configuration for a deterministic physio-regressor export."""

    physio_file: str
    output_dir: str
    sampling_rate_hz: float
    t_r: float
    n_scans: int
    scan_start_s: float = 0.0
    delimiter: str | None = None
    cardiac_column: str | None = None
    respiratory_column: str | None = None
    cardiac_order: int = 3
    respiratory_order: int = 4
    interaction_order: int = 1
    include_resampled_traces: bool = True
    standardize: bool = True


def physio_noise_regressors_from_payload(
    payload: dict[str, object],
) -> PhysioNoiseRegressorParameters:
    """Create a typed parameter object from a tool payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "physio_noise_regressors"
    return PhysioNoiseRegressorParameters(
        physio_file=str(payload["physio_file"]),
        output_dir=str(output_dir),
        sampling_rate_hz=float(payload["sampling_rate_hz"]),
        t_r=float(payload["t_r"]),
        n_scans=int(payload["n_scans"]),
        scan_start_s=float(payload.get("scan_start_s", 0.0)),
        delimiter=str(payload["delimiter"]) if payload.get("delimiter") else None,
        cardiac_column=(
            str(payload["cardiac_column"]) if payload.get("cardiac_column") else None
        ),
        respiratory_column=(
            str(payload["respiratory_column"])
            if payload.get("respiratory_column")
            else None
        ),
        cardiac_order=max(0, int(payload.get("cardiac_order", 3))),
        respiratory_order=max(0, int(payload.get("respiratory_order", 4))),
        interaction_order=max(0, int(payload.get("interaction_order", 1))),
        include_resampled_traces=bool(payload.get("include_resampled_traces", True)),
        standardize=bool(payload.get("standardize", True)),
    )


def _read_physio_table(path: str, delimiter: str | None) -> pd.DataFrame:
    physio_path = Path(path)
    if not physio_path.exists():
        raise FileNotFoundError(f"Physio file not found: {path}")

    if delimiter:
        df = pd.read_csv(physio_path, sep=delimiter)
    elif physio_path.suffix.lower() == ".tsv":
        df = pd.read_csv(physio_path, sep="\t")
    elif physio_path.suffix.lower() == ".csv":
        df = pd.read_csv(physio_path)
    else:
        df = pd.read_csv(physio_path, sep=None, engine="python")

    if df.empty:
        raise ValueError(f"Physio file is empty: {path}")
    return df


def _resolve_column(
    df: pd.DataFrame,
    explicit: str | None,
    candidates: tuple[str, ...],
) -> str | None:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column '{explicit}' not found in physio file")
        return explicit

    lowered = {str(col).lower(): str(col) for col in df.columns}
    for candidate in candidates:
        for lowered_name, original in lowered.items():
            if candidate in lowered_name:
                return original
    return None


def _sanitize_trace(values: pd.Series) -> np.ndarray:
    trace = pd.to_numeric(values, errors="coerce").astype(float)
    trace = trace.replace([np.inf, -np.inf], np.nan)
    trace = trace.interpolate(limit_direction="both").fillna(0.0)
    return trace.to_numpy(dtype=float)


def _sample_standardize(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    mean = np.mean(data)
    std = np.std(data, ddof=1) if data.size > 1 else 0.0
    if not np.isfinite(std) or std < 1e-6:
        return data - mean
    return (data - mean) / std


def _resample_trace(
    trace: np.ndarray, sample_rate_hz: float, scan_times: np.ndarray
) -> np.ndarray:
    sample_times = np.arange(trace.size, dtype=float) / max(sample_rate_hz, 1e-6)
    clamped_times = np.clip(scan_times, sample_times[0], sample_times[-1])
    return np.interp(clamped_times, sample_times, trace)


def _estimate_phase(trace: np.ndarray) -> np.ndarray:
    if hilbert is None:  # pragma: no cover - dependency failure is rare in tests
        raise ImportError(
            "scipy is required for physio phase estimation via Hilbert transform"
        )
    centered = np.asarray(trace, dtype=float) - float(np.mean(trace))
    if np.allclose(centered, 0.0):
        return np.zeros_like(centered)
    analytic = hilbert(centered)
    return np.unwrap(np.angle(analytic))


def _add_fourier_regressors(
    out: dict[str, np.ndarray],
    phase: np.ndarray,
    prefix: str,
    order: int,
) -> None:
    for harmonic in range(1, order + 1):
        out[f"{prefix}_sin{harmonic}"] = np.sin(harmonic * phase)
        out[f"{prefix}_cos{harmonic}"] = np.cos(harmonic * phase)


def run_physio_noise_regressors(
    params: PhysioNoiseRegressorParameters,
) -> dict[str, object]:
    """Generate scan-aligned nuisance regressors from raw physio traces."""

    if params.n_scans <= 0:
        raise ValueError("n_scans must be positive")
    if params.sampling_rate_hz <= 0 or params.t_r <= 0:
        raise ValueError("sampling_rate_hz and t_r must be positive")

    df = _read_physio_table(params.physio_file, params.delimiter)
    numeric_df = df.select_dtypes(include=[np.number]).copy()
    if numeric_df.empty:
        raise ValueError("Physio file must contain at least one numeric column")

    cardiac_col = _resolve_column(
        numeric_df,
        params.cardiac_column,
        ("cardiac", "pulse", "ppg", "ecg", "heart", "pleth"),
    )
    respiratory_col = _resolve_column(
        numeric_df,
        params.respiratory_column,
        ("resp", "respiratory", "breath", "belt"),
    )
    if cardiac_col is None and respiratory_col is None:
        raise ValueError(
            "Unable to resolve a cardiac or respiratory column from the physio file"
        )

    scan_times = (
        params.scan_start_s + np.arange(params.n_scans, dtype=float) * params.t_r
    )
    regressors: dict[str, np.ndarray] = {}
    resolved_columns: dict[str, str | None] = {
        "cardiac_column": cardiac_col,
        "respiratory_column": respiratory_col,
    }

    cardiac_phase_scan: np.ndarray | None = None
    respiratory_phase_scan: np.ndarray | None = None

    for family, column, order in (
        ("cardiac_retroicor", cardiac_col, params.cardiac_order),
        ("respiratory_retroicor", respiratory_col, params.respiratory_order),
    ):
        if column is None:
            continue

        raw_trace = _sanitize_trace(numeric_df[column])
        if params.standardize:
            raw_trace = _sample_standardize(raw_trace)
        resampled = _resample_trace(raw_trace, params.sampling_rate_hz, scan_times)
        if params.standardize:
            resampled = _sample_standardize(resampled)

        if params.include_resampled_traces:
            signal_prefix = family.replace("_retroicor", "_signal")
            regressors[f"{signal_prefix}_z"] = resampled
            derivative = np.gradient(resampled)
            if params.standardize:
                derivative = _sample_standardize(derivative)
            regressors[f"{signal_prefix}_derivative1"] = derivative

        if order <= 0:
            continue

        phase = _estimate_phase(raw_trace)
        phase_scan = _resample_trace(phase, params.sampling_rate_hz, scan_times)
        _add_fourier_regressors(regressors, phase_scan, family, order)

        if family.startswith("cardiac"):
            cardiac_phase_scan = phase_scan
        else:
            respiratory_phase_scan = phase_scan

    if (
        params.interaction_order > 0
        and cardiac_phase_scan is not None
        and respiratory_phase_scan is not None
    ):
        for order in range(1, params.interaction_order + 1):
            regressors[f"cardiorespiratory_sum_sin{order}"] = np.sin(
                order * (cardiac_phase_scan + respiratory_phase_scan)
            )
            regressors[f"cardiorespiratory_sum_cos{order}"] = np.cos(
                order * (cardiac_phase_scan + respiratory_phase_scan)
            )
            regressors[f"cardiorespiratory_diff_sin{order}"] = np.sin(
                order * (cardiac_phase_scan - respiratory_phase_scan)
            )
            regressors[f"cardiorespiratory_diff_cos{order}"] = np.cos(
                order * (cardiac_phase_scan - respiratory_phase_scan)
            )

    confounds_df = pd.DataFrame(regressors)
    if confounds_df.empty:
        raise ValueError("No physio regressors were generated")
    confounds_df = confounds_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    confounds_path = out_dir / "physio_confounds.tsv"
    metadata_path = out_dir / "physio_confounds_metadata.json"

    confounds_df.to_csv(confounds_path, sep="\t", index=False)

    metadata = {
        "physio_file": str(Path(params.physio_file)),
        "sampling_rate_hz": params.sampling_rate_hz,
        "t_r": params.t_r,
        "n_scans": params.n_scans,
        "scan_start_s": params.scan_start_s,
        "resolved_columns": resolved_columns,
        "orders": {
            "cardiac_order": params.cardiac_order,
            "respiratory_order": params.respiratory_order,
            "interaction_order": params.interaction_order,
        },
        "generated_columns": list(confounds_df.columns),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "confounds_tsv": str(confounds_path),
            "metadata_json": str(metadata_path),
        },
        "summary": {
            "n_columns": int(confounds_df.shape[1]),
            "n_scans": int(confounds_df.shape[0]),
            "generated_columns": list(confounds_df.columns),
            "resolved_columns": resolved_columns,
        },
        "message": "Physiological noise regressors generated.",
    }


def merge_scan_confounds_tables(
    tables: dict[str, str],
    output_dir: str,
    *,
    output_name: str = "merged_confounds.tsv",
    metadata_name: str = "merged_confounds_metadata.json",
) -> dict[str, object]:
    """Merge scan-aligned confounds tables into a single TSV + metadata JSON."""

    if not tables:
        raise ValueError("At least one confounds table must be provided")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    merged: pd.DataFrame | None = None
    metadata_sources: list[dict[str, object]] = []

    for label, table_path in tables.items():
        df = _read_physio_table(table_path, None)
        numeric_df = df.select_dtypes(include=[np.number]).copy()
        if numeric_df.empty:
            raise ValueError(
                f"Confounds table '{table_path}' did not contain numeric columns"
            )
        numeric_df = numeric_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if merged is None:
            merged = numeric_df.reset_index(drop=True)
        else:
            if len(numeric_df) != len(merged):
                raise ValueError(
                    f"Confounds table '{table_path}' has {len(numeric_df)} rows; expected {len(merged)}"
                )
            renamed = numeric_df.reset_index(drop=True).copy()
            rename_map: dict[str, str] = {}
            for column in renamed.columns:
                new_column = column
                if new_column in merged.columns:
                    new_column = f"{label}__{column}"
                rename_map[column] = new_column
            renamed = renamed.rename(columns=rename_map)
            merged = pd.concat([merged, renamed], axis=1)

        metadata_sources.append(
            {
                "label": label,
                "path": str(Path(table_path)),
                "columns": list(numeric_df.columns),
                "n_columns": int(numeric_df.shape[1]),
                "n_rows": int(numeric_df.shape[0]),
            }
        )

    assert merged is not None
    merged_path = out_dir / output_name
    metadata_path = out_dir / metadata_name
    merged.to_csv(merged_path, sep="	", index=False)
    metadata = {
        "sources": metadata_sources,
        "n_rows": int(merged.shape[0]),
        "n_columns": int(merged.shape[1]),
        "generated_columns": list(merged.columns),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "confounds_tsv": str(merged_path),
            "metadata_json": str(metadata_path),
        },
        "summary": {
            "n_columns": int(merged.shape[1]),
            "n_scans": int(merged.shape[0]),
            "generated_columns": list(merged.columns),
            "sources": metadata_sources,
        },
        "message": "Confounds tables merged.",
    }


__all__ = [
    "PhysioNoiseRegressorParameters",
    "physio_noise_regressors_from_payload",
    "merge_scan_confounds_tables",
    "run_physio_noise_regressors",
]
