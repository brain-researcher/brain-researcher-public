"""Preprocess pupillometry traces into cleaned signals, events, and confounds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:  # pragma: no cover - optional at import time
    from scipy.signal import butter, filtfilt, find_peaks
except Exception:  # pragma: no cover
    butter = filtfilt = find_peaks = None  # type: ignore


@dataclass(frozen=True)
class PupillometryPreprocessParameters:
    """Configuration for deterministic pupil preprocessing."""

    pupil_file: str
    output_dir: str
    sampling_rate_hz: float | None = None
    delimiter: str | None = None
    time_column: str | None = None
    pupil_column: str | None = None
    min_pupil: float = 0.0
    blink_derivative_threshold: float = 6.0
    blink_padding_s: float = 0.15
    low_pass_hz: float = 4.0
    tonic_low_pass_hz: float = 0.2
    peak_prominence_z: float = 1.0
    peak_distance_s: float = 1.0
    standardize: bool = True
    t_r: float | None = None
    n_scans: int | None = None
    scan_start_s: float = 0.0


def pupillometry_preprocess_from_payload(
    payload: dict[str, object],
) -> PupillometryPreprocessParameters:
    """Create a typed parameter object from a tool payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "pupillometry_preprocess"
    sampling_rate = payload.get("sampling_rate_hz")
    t_r = payload.get("t_r")
    n_scans = payload.get("n_scans")
    return PupillometryPreprocessParameters(
        pupil_file=str(payload["pupil_file"]),
        output_dir=str(output_dir),
        sampling_rate_hz=float(sampling_rate) if sampling_rate is not None else None,
        delimiter=str(payload["delimiter"]) if payload.get("delimiter") else None,
        time_column=str(payload["time_column"]) if payload.get("time_column") else None,
        pupil_column=(
            str(payload["pupil_column"]) if payload.get("pupil_column") else None
        ),
        min_pupil=float(payload.get("min_pupil", 0.0)),
        blink_derivative_threshold=float(
            payload.get("blink_derivative_threshold", 6.0)
        ),
        blink_padding_s=float(payload.get("blink_padding_s", 0.15)),
        low_pass_hz=float(payload.get("low_pass_hz", 4.0)),
        tonic_low_pass_hz=float(payload.get("tonic_low_pass_hz", 0.2)),
        peak_prominence_z=float(payload.get("peak_prominence_z", 1.0)),
        peak_distance_s=float(payload.get("peak_distance_s", 1.0)),
        standardize=bool(payload.get("standardize", True)),
        t_r=float(t_r) if t_r is not None else None,
        n_scans=int(n_scans) if n_scans is not None else None,
        scan_start_s=float(payload.get("scan_start_s", 0.0)),
    )


def _read_pupil_table(path: str, delimiter: str | None) -> pd.DataFrame:
    pupil_path = Path(path)
    if not pupil_path.exists():
        raise FileNotFoundError(f"Pupil file not found: {path}")

    if pupil_path.suffix.lower() in {".parquet", ".pqt"}:
        df = pd.read_parquet(pupil_path)
    elif delimiter:
        df = pd.read_csv(pupil_path, sep=delimiter)
    elif pupil_path.suffix.lower() == ".tsv":
        df = pd.read_csv(pupil_path, sep="\t")
    elif pupil_path.suffix.lower() == ".csv":
        df = pd.read_csv(pupil_path)
    else:
        df = pd.read_csv(pupil_path, sep=None, engine="python")

    if df.empty:
        raise ValueError(f"Pupil file is empty: {path}")
    return df


def _resolve_column(
    df: pd.DataFrame,
    explicit: str | None,
    candidates: tuple[str, ...],
) -> str | None:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column '{explicit}' not found in pupil file")
        return explicit

    lowered = {str(col).lower(): str(col) for col in df.columns}
    for candidate in candidates:
        for lowered_name, original in lowered.items():
            if candidate in lowered_name:
                return original
    return None


def _sample_standardize(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    mean = np.mean(data)
    std = np.std(data, ddof=1) if data.size > 1 else 0.0
    if not np.isfinite(std) or std < 1e-6:
        return data - mean
    return (data - mean) / std


def _robust_zscore(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    median = float(np.median(data))
    mad = float(np.median(np.abs(data - median)))
    if not np.isfinite(mad) or mad < 1e-6:
        return _sample_standardize(data)
    return 0.67448975 * (data - median) / mad


def _build_time_axis(
    df: pd.DataFrame, params: PupillometryPreprocessParameters
) -> tuple[np.ndarray, float, str | None]:
    time_col = _resolve_column(
        df,
        params.time_column,
        ("time_s", "timestamp", "timestamps", "time", "times"),
    )
    if time_col is not None:
        times = pd.to_numeric(df[time_col], errors="coerce").to_numpy(dtype=float)
        if not np.all(np.isfinite(times)):
            raise ValueError("Time column must contain finite numeric values")
        deltas = np.diff(times)
        if np.any(deltas <= 0):
            raise ValueError("Time column must be strictly increasing")
        inferred_rate = 1.0 / float(np.median(deltas))
        sample_rate_hz = params.sampling_rate_hz or inferred_rate
        return times, float(sample_rate_hz), time_col

    if params.sampling_rate_hz is None or params.sampling_rate_hz <= 0:
        raise ValueError(
            "Provide either a valid time column or a positive sampling_rate_hz"
        )
    sample_rate_hz = float(params.sampling_rate_hz)
    times = np.arange(len(df), dtype=float) / sample_rate_hz
    return times, sample_rate_hz, None


def _dilate_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0 or not mask.any():
        return mask
    kernel = np.ones(radius * 2 + 1, dtype=int)
    return np.convolve(mask.astype(int), kernel, mode="same") > 0


def _lowpass_trace(
    trace: np.ndarray, sample_rate_hz: float, cutoff_hz: float
) -> np.ndarray:
    if butter is None or filtfilt is None:  # pragma: no cover - rare dependency issue
        raise ImportError("scipy is required for pupillometry filtering")
    if cutoff_hz <= 0:
        return np.asarray(trace, dtype=float)
    nyquist = sample_rate_hz / 2.0
    if cutoff_hz >= nyquist or trace.size < 8:
        return np.asarray(trace, dtype=float)
    b, a = butter(2, cutoff_hz / nyquist, btype="low")
    return filtfilt(b, a, np.asarray(trace, dtype=float))


def _resample_trace(
    values: np.ndarray, source_times: np.ndarray, target_times: np.ndarray
) -> np.ndarray:
    clamped = np.clip(target_times, source_times[0], source_times[-1])
    return np.interp(clamped, source_times, values)


def _blink_fraction_by_scan(
    blink_mask: np.ndarray,
    sample_rate_hz: float,
    t_r: float,
    n_scans: int,
    scan_start_s: float,
) -> np.ndarray:
    values = np.asarray(blink_mask, dtype=float)
    fractions = np.zeros(n_scans, dtype=float)
    for scan_idx in range(n_scans):
        start_s = scan_start_s + scan_idx * t_r
        end_s = start_s + t_r
        start_idx = max(int(np.floor(start_s * sample_rate_hz)), 0)
        end_idx = min(int(np.ceil(end_s * sample_rate_hz)), values.size)
        if end_idx <= start_idx:
            continue
        fractions[scan_idx] = float(np.mean(values[start_idx:end_idx]))
    return fractions


def run_pupillometry_preprocess(
    params: PupillometryPreprocessParameters,
) -> dict[str, object]:
    """Clean a pupil trace and export derivative signals plus arousal events."""

    df = _read_pupil_table(params.pupil_file, params.delimiter)
    pupil_col = _resolve_column(
        df,
        params.pupil_column,
        (
            "pupildiameter_raw",
            "pupil_diameter_raw",
            "pupil_diameter",
            "pupil",
            "diameter",
        ),
    )
    if pupil_col is None:
        raise ValueError("Unable to resolve a pupil column from the pupil file")

    times, sample_rate_hz, time_col = _build_time_axis(df, params)
    raw = pd.to_numeric(df[pupil_col], errors="coerce").to_numpy(dtype=float)

    filled_for_derivative = (
        pd.Series(raw)
        .replace([np.inf, -np.inf], np.nan)
        .interpolate(limit_direction="both")
        .bfill()
        .ffill()
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    invalid_mask = ~np.isfinite(raw) | (raw <= params.min_pupil)
    derivative = np.gradient(filled_for_derivative)
    derivative_outliers = (
        np.abs(_robust_zscore(derivative)) >= params.blink_derivative_threshold
    )
    blink_padding_samples = max(int(round(params.blink_padding_s * sample_rate_hz)), 0)
    blink_mask = _dilate_mask(
        invalid_mask | derivative_outliers,
        blink_padding_samples,
    )

    cleaned = (
        pd.Series(raw)
        .replace([np.inf, -np.inf], np.nan)
        .mask(blink_mask)
        .interpolate(limit_direction="both")
        .bfill()
        .ffill()
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    filtered = _lowpass_trace(cleaned, sample_rate_hz, params.low_pass_hz)
    tonic = _lowpass_trace(filtered, sample_rate_hz, params.tonic_low_pass_hz)
    phasic = filtered - tonic
    derivative_clean = np.gradient(filtered)

    raw_z = _sample_standardize(filtered) if params.standardize else filtered
    tonic_z = _sample_standardize(tonic) if params.standardize else tonic
    phasic_z = _sample_standardize(phasic) if params.standardize else phasic
    derivative_z = (
        _sample_standardize(derivative_clean)
        if params.standardize
        else derivative_clean
    )

    if find_peaks is None:  # pragma: no cover - rare dependency issue
        raise ImportError("scipy is required for pupillometry peak detection")
    peak_distance = max(int(round(params.peak_distance_s * sample_rate_hz)), 1)
    peaks, properties = find_peaks(
        phasic_z,
        prominence=params.peak_prominence_z,
        distance=peak_distance,
    )
    peak_prominence = properties.get("prominences", np.zeros(len(peaks), dtype=float))

    trace_df = pd.DataFrame(
        {
            "time_s": times,
            "pupil_raw": raw,
            "blink_mask": blink_mask.astype(int),
            "pupil_clean": cleaned,
            "pupil_filtered": filtered,
            "pupil_filtered_z": raw_z,
            "pupil_derivative1_z": derivative_z,
            "pupil_tonic": tonic,
            "pupil_tonic_z": tonic_z,
            "pupil_phasic": phasic,
            "pupil_phasic_z": phasic_z,
        }
    )
    events_df = pd.DataFrame(
        {
            "onset": times[peaks] if len(peaks) else np.asarray([], dtype=float),
            "duration": np.zeros(len(peaks), dtype=float),
            "trial_type": ["pupil_arousal_peak"] * len(peaks),
            "amplitude": phasic_z[peaks] if len(peaks) else np.asarray([], dtype=float),
            "prominence": peak_prominence,
        }
    )

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "pupil_preprocessed.tsv"
    events_path = out_dir / "pupil_arousal_events.tsv"
    metadata_path = out_dir / "pupil_preprocessed_metadata.json"

    trace_df.to_csv(trace_path, sep="\t", index=False)
    events_df.to_csv(events_path, sep="\t", index=False)

    outputs: dict[str, str] = {
        "preprocessed_tsv": str(trace_path),
        "events_tsv": str(events_path),
        "metadata_json": str(metadata_path),
    }

    scan_confounds_columns: list[str] = []
    if params.t_r is not None or params.n_scans is not None:
        if params.t_r is None or params.n_scans is None:
            raise ValueError("Provide both t_r and n_scans to export scan confounds")
        if params.t_r <= 0 or params.n_scans <= 0:
            raise ValueError("t_r and n_scans must be positive when provided")

        scan_times = (
            params.scan_start_s + np.arange(params.n_scans, dtype=float) * params.t_r
        )
        confounds_df = pd.DataFrame(
            {
                "pupil_filtered_z": _resample_trace(raw_z, times, scan_times),
                "pupil_derivative1_z": _resample_trace(derivative_z, times, scan_times),
                "pupil_tonic_z": _resample_trace(tonic_z, times, scan_times),
                "pupil_phasic_z": _resample_trace(phasic_z, times, scan_times),
                "pupil_blink_fraction": _blink_fraction_by_scan(
                    blink_mask,
                    sample_rate_hz,
                    params.t_r,
                    params.n_scans,
                    params.scan_start_s,
                ),
            }
        )
        confounds_path = out_dir / "pupil_confounds.tsv"
        confounds_df.to_csv(confounds_path, sep="\t", index=False)
        outputs["confounds_tsv"] = str(confounds_path)
        scan_confounds_columns = list(confounds_df.columns)

    metadata = {
        "source_file": str(Path(params.pupil_file).resolve()),
        "resolved_columns": {
            "pupil_column": pupil_col,
            "time_column": time_col,
        },
        "sampling_rate_hz": sample_rate_hz,
        "blink_fraction": float(np.mean(blink_mask.astype(float))),
        "blink_samples": int(np.sum(blink_mask)),
        "n_samples": int(len(trace_df)),
        "n_events": int(len(events_df)),
        "peak_prominence_z": params.peak_prominence_z,
        "peak_distance_s": params.peak_distance_s,
        "low_pass_hz": params.low_pass_hz,
        "tonic_low_pass_hz": params.tonic_low_pass_hz,
        "generated_columns": list(trace_df.columns),
        "scan_confounds_columns": scan_confounds_columns,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    summary = {
        "n_samples": int(len(trace_df)),
        "blink_fraction": float(np.mean(blink_mask.astype(float))),
        "n_events": int(len(events_df)),
        "sampling_rate_hz": sample_rate_hz,
        "scan_confounds_exported": bool(scan_confounds_columns),
    }

    return {
        "outputs": outputs,
        "summary": summary,
        "message": (
            "Preprocessed pupillometry trace and exported cleaned signals, "
            "arousal events, and optional scan-aligned confounds."
        ),
    }


__all__ = [
    "PupillometryPreprocessParameters",
    "pupillometry_preprocess_from_payload",
    "run_pupillometry_preprocess",
]
