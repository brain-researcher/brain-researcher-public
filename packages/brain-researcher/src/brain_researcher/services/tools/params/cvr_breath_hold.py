"""Lightweight CVR breath-hold analysis helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CVRBreathHoldParameters:
    """Configuration for a deterministic CVR breath-hold summary."""

    signal_file: str
    output_dir: str
    signal_column: str | None
    time_column: str | None
    delimiter: str | None
    events_file: str | None
    event_onset_column: str
    event_duration_column: str
    event_type_column: str | None
    breath_hold_label: str
    breath_hold_onsets: list[float] | None
    breath_hold_durations: list[float] | None
    t_r: float | None
    n_scans: int | None
    scan_start_s: float
    lag_min_s: float
    lag_max_s: float
    lag_step_s: float
    baseline_window_s: float
    standardize: bool
    detrend: bool


def _coerce_float_list(value: object | None) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return [float(item) for item in value]
    raise TypeError("Expected a list of numeric values")


def cvr_breath_hold_from_payload(payload: dict[str, object]) -> CVRBreathHoldParameters:
    """Create a typed parameter object from a tool payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "cvr_breath_hold"
    return CVRBreathHoldParameters(
        signal_file=str(payload["signal_file"]),
        output_dir=str(output_dir),
        signal_column=(
            str(payload["signal_column"]) if payload.get("signal_column") else None
        ),
        time_column=str(payload["time_column"]) if payload.get("time_column") else None,
        delimiter=str(payload["delimiter"]) if payload.get("delimiter") else None,
        events_file=str(payload["events_file"]) if payload.get("events_file") else None,
        event_onset_column=str(payload.get("event_onset_column", "onset")),
        event_duration_column=str(payload.get("event_duration_column", "duration")),
        event_type_column=(
            str(payload["event_type_column"])
            if payload.get("event_type_column")
            else None
        ),
        breath_hold_label=str(payload.get("breath_hold_label", "breath_hold")),
        breath_hold_onsets=_coerce_float_list(payload.get("breath_hold_onsets")),
        breath_hold_durations=_coerce_float_list(payload.get("breath_hold_durations")),
        t_r=float(payload["t_r"]) if payload.get("t_r") is not None else None,
        n_scans=int(payload["n_scans"]) if payload.get("n_scans") is not None else None,
        scan_start_s=float(payload.get("scan_start_s", 0.0)),
        lag_min_s=float(payload.get("lag_min_s", 0.0)),
        lag_max_s=float(payload.get("lag_max_s", 20.0)),
        lag_step_s=float(payload.get("lag_step_s", 0.5)),
        baseline_window_s=float(payload.get("baseline_window_s", 10.0)),
        standardize=bool(payload.get("standardize", True)),
        detrend=bool(payload.get("detrend", True)),
    )


def _read_table(path: str, delimiter: str | None) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CVR input file not found: {path}")

    suffix = file_path.suffix.lower()
    if suffix in {".parquet", ".pqt"}:
        df = pd.read_parquet(file_path)
    elif delimiter:
        df = pd.read_csv(file_path, sep=delimiter)
    elif suffix == ".tsv":
        df = pd.read_csv(file_path, sep="\t")
    elif suffix == ".csv":
        df = pd.read_csv(file_path)
    else:
        df = pd.read_csv(file_path, sep=None, engine="python")

    if df.empty:
        raise ValueError(f"CVR input file is empty: {path}")
    return df


def _resolve_column(
    df: pd.DataFrame,
    explicit: str | None,
    candidates: tuple[str, ...],
) -> str | None:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column '{explicit}' not found in CVR file")
        return explicit

    lowered = {str(col).lower(): str(col) for col in df.columns}
    for candidate in candidates:
        for lowered_name, original in lowered.items():
            if candidate in lowered_name:
                return original
    return None


def _to_numeric(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values = values.replace([np.inf, -np.inf], np.nan)
    return (
        values.interpolate(limit_direction="both")
        .bfill()
        .ffill()
        .fillna(0.0)
        .to_numpy(dtype=float)
    )


def _sample_standardize(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    mean = float(np.mean(data))
    std = float(np.std(data, ddof=1)) if data.size > 1 else 0.0
    if not np.isfinite(std) or std < 1e-6:
        return data - mean
    return (data - mean) / std


def _detrend(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    if data.size < 3:
        return data - float(np.mean(data))
    x = np.arange(data.size, dtype=float)
    slope, intercept = np.polyfit(x, data, 1)
    return data - (slope * x + intercept)


def _build_time_axis(
    df: pd.DataFrame, params: CVRBreathHoldParameters
) -> tuple[np.ndarray, float, str | None]:
    time_col = _resolve_column(
        df,
        params.time_column,
        ("time_s", "timestamp", "timestamps", "time", "times"),
    )
    if time_col is not None:
        times = _to_numeric(df[time_col])
        if times.size < 2:
            sample_rate_hz = 1.0 / max(params.t_r or 1.0, 1e-6)
            return times, sample_rate_hz, time_col
        if np.any(np.diff(times) <= 0):
            raise ValueError("Time column must be strictly increasing")
        sample_rate_hz = 1.0 / float(np.median(np.diff(times)))
        return times, sample_rate_hz, time_col

    if params.t_r is None or params.t_r <= 0:
        raise ValueError("Provide either a time column or a positive t_r")

    n_scans = params.n_scans or len(df)
    if params.n_scans is not None and params.n_scans != len(df):
        raise ValueError(
            "n_scans must match the number of rows when no time column is provided"
        )

    times = params.scan_start_s + np.arange(n_scans, dtype=float) * params.t_r
    return times, 1.0 / params.t_r, None


def _resolve_signal_column(
    df: pd.DataFrame, explicit: str | None, time_col: str | None
) -> str:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column '{explicit}' not found in CVR file")
        return explicit

    numeric_cols = list(df.select_dtypes(include=[np.number]).columns)
    if time_col in numeric_cols:
        numeric_cols.remove(time_col)
    if len(numeric_cols) == 1:
        return numeric_cols[0]

    candidates = ("bold", "signal", "timeseries", "roi", "global", "mean", "cvr")
    lowered = {str(col).lower(): str(col) for col in df.columns}
    for candidate in candidates:
        for lowered_name, original in lowered.items():
            if candidate in lowered_name and original != time_col:
                return original

    if len(numeric_cols) == 1:
        return numeric_cols[0]
    raise ValueError("Unable to resolve a unique BOLD signal column")


def _build_event_schedule(
    df: pd.DataFrame,
    params: CVRBreathHoldParameters,
) -> pd.DataFrame:
    onset_col = _resolve_column(
        df,
        params.event_onset_column,
        ("onset", "start", "start_time", "time_s", "time"),
    )
    if onset_col is None:
        raise ValueError("Unable to resolve an event onset column")

    duration_col = _resolve_column(
        df,
        params.event_duration_column,
        ("duration", "dur", "length"),
    )
    type_col = _resolve_column(
        df,
        params.event_type_column,
        ("trial_type", "event_type", "condition", "label"),
    )

    selected = df.copy()
    if type_col is not None and params.breath_hold_label:
        selected = selected[
            selected[type_col]
            .astype(str)
            .str.lower()
            .str.contains(params.breath_hold_label.lower(), na=False)
        ]

    if selected.empty:
        raise ValueError("No breath-hold events matched the provided schedule")

    default_duration = params.t_r if params.t_r is not None else 1.0
    events = pd.DataFrame(
        {
            "onset": pd.to_numeric(selected[onset_col], errors="coerce"),
            "duration": (
                pd.to_numeric(selected[duration_col], errors="coerce")
                if duration_col is not None
                else default_duration
            ),
        }
    )
    events = events.replace([np.inf, -np.inf], np.nan).dropna(subset=["onset"])
    if events.empty:
        raise ValueError("No valid breath-hold events were found")
    if "duration" not in events.columns:
        events["duration"] = default_duration
    events["duration"] = events["duration"].fillna(default_duration).astype(float)
    events["source"] = "events_file"
    return events[["onset", "duration", "source"]]


def _events_from_inline_schedule(
    params: CVRBreathHoldParameters,
) -> pd.DataFrame:
    if params.breath_hold_onsets is None and params.breath_hold_durations is None:
        return pd.DataFrame(columns=["onset", "duration", "source"])
    if params.breath_hold_onsets is None or params.breath_hold_durations is None:
        raise ValueError(
            "Provide both breath_hold_onsets and breath_hold_durations when using an inline schedule"
        )
    if len(params.breath_hold_onsets) != len(params.breath_hold_durations):
        raise ValueError(
            "breath_hold_onsets and breath_hold_durations must have the same length"
        )

    return pd.DataFrame(
        {
            "onset": [float(value) for value in params.breath_hold_onsets],
            "duration": [float(value) for value in params.breath_hold_durations],
            "source": "inline_schedule",
        }
    )


def _build_event_boxcar(times: np.ndarray, events: pd.DataFrame) -> np.ndarray:
    regressor = np.zeros(times.size, dtype=float)
    for _, row in events.iterrows():
        onset = float(row["onset"])
        duration = max(float(row["duration"]), 0.0)
        regressor[(times >= onset) & (times < onset + duration)] = 1.0
    return regressor


def _shift_regressor(
    times: np.ndarray, regressor: np.ndarray, lag_s: float
) -> np.ndarray:
    shifted_times = times - lag_s
    return np.interp(shifted_times, times, regressor, left=0.0, right=0.0)


def _corr_and_beta(
    signal: np.ndarray, regressor: np.ndarray
) -> tuple[float, float, float]:
    signal_centered = signal - float(np.mean(signal))
    reg_centered = regressor - float(np.mean(regressor))
    signal_scale = float(np.std(signal_centered, ddof=1)) if signal.size > 1 else 0.0
    reg_scale = float(np.std(reg_centered, ddof=1)) if regressor.size > 1 else 0.0
    if signal_scale < 1e-8 or reg_scale < 1e-8:
        return float("nan"), float("nan"), float("nan")

    corr = float(
        np.dot(signal_centered, reg_centered)
        / ((signal.size - 1) * signal_scale * reg_scale)
    )
    denom = float(np.dot(reg_centered, reg_centered))
    if abs(denom) < 1e-12:
        return float("nan"), float("nan"), float("nan")
    beta = float(np.dot(signal_centered, reg_centered) / denom)
    intercept = float(np.mean(signal) - beta * np.mean(regressor))
    return corr, beta, intercept


def run_cvr_breath_hold(
    params: CVRBreathHoldParameters,
) -> dict[str, object]:
    """Estimate a simple CVR lag and amplitude summary from breath-hold data."""

    if params.lag_step_s <= 0:
        raise ValueError("lag_step_s must be positive")
    if params.lag_max_s < params.lag_min_s:
        raise ValueError("lag_max_s must be greater than or equal to lag_min_s")
    if params.baseline_window_s <= 0:
        raise ValueError("baseline_window_s must be positive")

    signal_df = _read_table(params.signal_file, params.delimiter)
    signal_col = _resolve_signal_column(
        signal_df, params.signal_column, params.time_column
    )
    times, sample_rate_hz, resolved_time_col = _build_time_axis(signal_df, params)
    signal = _to_numeric(signal_df[signal_col])

    if signal.size != times.size:
        raise ValueError("Signal length must match the resolved time axis")

    if params.detrend:
        signal_proc = _detrend(signal)
    else:
        signal_proc = signal.copy()
    signal_z = _sample_standardize(signal_proc) if params.standardize else signal_proc

    event_frames: list[pd.DataFrame] = []
    if params.events_file:
        event_df = _read_table(params.events_file, params.delimiter)
        event_frames.append(_build_event_schedule(event_df, params))
    inline_events = _events_from_inline_schedule(params)
    if not inline_events.empty:
        event_frames.append(inline_events)

    if not event_frames:
        raise ValueError(
            "Provide an events_file or breath_hold_onsets/breath_hold_durations to estimate CVR lag"
        )

    events = (
        pd.concat(event_frames, ignore_index=True)
        .sort_values("onset")
        .reset_index(drop=True)
    )
    event_boxcar = _build_event_boxcar(times, events)

    lag_values = np.arange(
        params.lag_min_s,
        params.lag_max_s + params.lag_step_s * 0.5,
        params.lag_step_s,
        dtype=float,
    )
    lag_scan_rows: list[dict[str, float]] = []
    for lag_s in lag_values:
        shifted = _shift_regressor(times, event_boxcar, lag_s)
        shifted_proc = _sample_standardize(shifted) if params.standardize else shifted
        corr, beta, intercept = _corr_and_beta(signal_z, shifted_proc)
        lag_scan_rows.append(
            {
                "lag_s": float(lag_s),
                "correlation": corr,
                "beta": beta,
                "intercept": intercept,
                "event_coverage": float(np.mean(shifted > 0.0)),
            }
        )

    lag_scan_df = pd.DataFrame(lag_scan_rows)
    if lag_scan_df["correlation"].notna().any():
        positive = lag_scan_df["correlation"] > 0
        if positive.any():
            best_idx = lag_scan_df.loc[positive, "correlation"].idxmax()
        else:
            best_idx = lag_scan_df["correlation"].abs().idxmax()
    else:
        raise ValueError("Unable to estimate a CVR lag from the provided data")

    best_lag_s = float(lag_scan_df.loc[best_idx, "lag_s"])
    best_shifted = _shift_regressor(times, event_boxcar, best_lag_s)
    best_shifted_proc = (
        _sample_standardize(best_shifted) if params.standardize else best_shifted
    )
    best_corr, best_beta, best_intercept = _corr_and_beta(signal_z, best_shifted_proc)
    best_predicted = best_beta * best_shifted_proc + best_intercept

    event_rows: list[dict[str, float | int | str]] = []
    for event_index, event in events.reset_index(drop=True).iterrows():
        onset = float(event["onset"])
        duration = max(float(event["duration"]), 0.0)
        response_start = onset + best_lag_s
        response_end = response_start + duration
        baseline_start = max(float(times[0]), onset - params.baseline_window_s)
        baseline_end = onset

        response_mask = (times >= response_start) & (times < response_end)
        baseline_mask = (times >= baseline_start) & (times < baseline_end)

        response_mean = (
            float(np.mean(signal[response_mask]))
            if response_mask.any()
            else float("nan")
        )
        baseline_mean = (
            float(np.mean(signal[baseline_mask]))
            if baseline_mask.any()
            else float("nan")
        )
        amplitude = (
            response_mean - baseline_mean
            if np.isfinite(response_mean) and np.isfinite(baseline_mean)
            else float("nan")
        )
        percent_change = (
            100.0 * amplitude / baseline_mean
            if np.isfinite(amplitude)
            and np.isfinite(baseline_mean)
            and abs(baseline_mean) > 1e-8
            else float("nan")
        )

        event_rows.append(
            {
                "event_index": int(event_index),
                "onset_s": onset,
                "duration_s": duration,
                "response_start_s": response_start,
                "response_end_s": response_end,
                "baseline_start_s": baseline_start,
                "baseline_end_s": baseline_end,
                "baseline_mean": baseline_mean,
                "response_mean": response_mean,
                "amplitude": amplitude,
                "percent_change": percent_change,
                "lag_s": best_lag_s,
            }
        )

    event_summary_df = pd.DataFrame(event_rows)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timeseries_path = out_dir / "cvr_timeseries.tsv"
    lag_scan_path = out_dir / "cvr_lag_scan.tsv"
    event_summary_path = out_dir / "cvr_event_summary.tsv"
    summary_path = out_dir / "cvr_summary.json"

    timeseries_df = pd.DataFrame(
        {
            "time_s": times,
            "bold_signal_raw": signal,
            "bold_signal_proc": signal_proc,
            "bold_signal_z": signal_z,
            "breath_hold_regressor": event_boxcar,
            "breath_hold_regressor_shifted": best_shifted,
            "breath_hold_regressor_shifted_z": best_shifted_proc,
            "cvr_prediction": best_predicted,
            "cvr_residual": signal_z - best_predicted,
        }
    )
    timeseries_df.to_csv(timeseries_path, sep="\t", index=False)
    lag_scan_df.to_csv(lag_scan_path, sep="\t", index=False)
    event_summary_df.to_csv(event_summary_path, sep="\t", index=False)

    event_amplitude_mean = (
        float(event_summary_df["amplitude"].mean())
        if not event_summary_df.empty
        else float("nan")
    )
    event_amplitude_std = (
        float(event_summary_df["amplitude"].std(ddof=1))
        if len(event_summary_df) > 1
        else float("nan")
    )
    event_percent_change_mean = (
        float(event_summary_df["percent_change"].mean())
        if not event_summary_df.empty
        else float("nan")
    )

    summary = {
        "signal_file": str(Path(params.signal_file)),
        "resolved_columns": {
            "signal_column": signal_col,
            "time_column": resolved_time_col,
        },
        "events_file": str(Path(params.events_file)) if params.events_file else None,
        "n_events": int(len(events)),
        "n_samples": int(len(timeseries_df)),
        "sample_rate_hz": float(sample_rate_hz),
        "best_lag_s": best_lag_s,
        "best_correlation": best_corr,
        "best_beta": best_beta,
        "best_intercept": best_intercept,
        "lag_scan_range_s": [params.lag_min_s, params.lag_max_s],
        "lag_scan_step_s": params.lag_step_s,
        "event_amplitude_mean": event_amplitude_mean,
        "event_amplitude_std": event_amplitude_std,
        "event_percent_change_mean": event_percent_change_mean,
        "standardize": params.standardize,
        "detrend": params.detrend,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "outputs": {
            "timeseries_tsv": str(timeseries_path),
            "lag_scan_tsv": str(lag_scan_path),
            "event_summary_tsv": str(event_summary_path),
            "summary_json": str(summary_path),
        },
        "summary": summary,
        "message": (
            "Estimated a lightweight CVR breath-hold lag and amplitude summary "
            "from the provided signal and event schedule."
        ),
    }


__all__ = [
    "CVRBreathHoldParameters",
    "cvr_breath_hold_from_payload",
    "run_cvr_breath_hold",
]
