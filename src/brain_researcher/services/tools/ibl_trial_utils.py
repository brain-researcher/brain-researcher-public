"""Pure trial-alignment and label-encoding helpers for IBL tools.

Extracted from ibl_tools.py.  These functions share no imports from
ibl_tools and have no class-hierarchy dependencies, making them a
clean, standalone cluster.

All names remain importable from ibl_tools via the re-export block added
there, so existing callers (IBLSpikeBehaviorAlignmentTool,
IBLDecodingDatasetTool) are unaffected whether they import from ibl_tools
or directly from this module.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _assign_trials(
    timestamps: np.ndarray,
    interval_start: np.ndarray,
    interval_end: np.ndarray,
) -> np.ndarray:
    assigned = np.full(len(timestamps), -1, dtype=int)
    if len(interval_start) == 0 or len(timestamps) == 0:
        return assigned
    candidate = np.searchsorted(interval_start, timestamps, side="right") - 1
    valid = (
        (candidate >= 0)
        & (candidate < len(interval_end))
        & (timestamps >= interval_start[np.clip(candidate, 0, len(interval_start) - 1)])
        & (timestamps <= interval_end[np.clip(candidate, 0, len(interval_end) - 1)])
    )
    assigned[valid] = candidate[valid]
    return assigned


def _append_trial_membership(
    df: pd.DataFrame,
    *,
    time_column: str,
    trials: pd.DataFrame,
) -> pd.DataFrame:
    if time_column not in df.columns or "interval_start" not in trials.columns or "interval_end" not in trials.columns:
        return df
    interval_start = trials["interval_start"].to_numpy(dtype=float)
    interval_end = trials["interval_end"].to_numpy(dtype=float)
    times = df[time_column].to_numpy(dtype=float)
    trial_index = _assign_trials(times, interval_start, interval_end)
    out = df.copy()
    out["trial_index"] = trial_index
    valid = out["trial_index"] >= 0
    if valid.any():
        trial_lookup = trials.set_index("trial_index")
        for column in (
            "choice",
            "contrastLeft",
            "contrastRight",
            "feedbackType",
            "probabilityLeft",
            "stimOn_times",
            "response_times",
            "feedback_times",
            "interval_start",
            "interval_end",
        ):
            if column in trial_lookup.columns:
                out.loc[valid, column] = (
                    out.loc[valid, "trial_index"].map(trial_lookup[column]).to_numpy()
                )
        if "stimOn_times" in out.columns:
            out["time_from_stimOn_s"] = out[time_column] - out["stimOn_times"]
        if "interval_start" in out.columns:
            out["time_from_trial_start_s"] = out[time_column] - out["interval_start"]
    return out


def _safe_session_stem(session_id: str) -> str:
    return session_id.replace("/", "__")


def _with_trial_index(df: pd.DataFrame) -> pd.DataFrame:
    if "trial_index" in df.columns:
        return df
    out = df.copy()
    out.insert(0, "trial_index", np.arange(len(out), dtype=int))
    return out


def _prepare_ibl_trial_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = _with_trial_index(df).copy()
    if "contrastLeft" in out.columns and "contrastRight" in out.columns:
        left = pd.to_numeric(out["contrastLeft"], errors="coerce")
        right = pd.to_numeric(out["contrastRight"], errors="coerce")
        out["signed_contrast"] = right.fillna(0.0) - left.fillna(0.0)
        out["stimulus_side"] = np.select(
            [right > left, left > right],
            [1, -1],
            default=0,
        ).astype("int64")
        out["zero_contrast"] = (
            left.fillna(0.0).eq(0.0) & right.fillna(0.0).eq(0.0)
        )
        out["max_contrast"] = np.maximum(
            left.abs().fillna(0.0),
            right.abs().fillna(0.0),
        )
    return out


def _fallback_trials_from_spikes(spikes_df: pd.DataFrame) -> pd.DataFrame | None:
    if "trial_index" not in spikes_df.columns:
        return None
    candidate_columns = [
        "trial_index",
        "choice",
        "contrastLeft",
        "contrastRight",
        "feedbackType",
        "probabilityLeft",
        "stimOn_times",
        "response_times",
        "feedback_times",
        "interval_start",
        "interval_end",
        "signed_contrast",
        "stimulus_side",
        "zero_contrast",
        "max_contrast",
    ]
    available = [column for column in candidate_columns if column in spikes_df.columns]
    if len(available) == 1:
        return None
    return (
        spikes_df.loc[spikes_df["trial_index"] >= 0, available]
        .drop_duplicates(subset=["trial_index"])
        .sort_values("trial_index")
        .reset_index(drop=True)
    )


def _resolve_label_values(df: pd.DataFrame, label_field: str) -> pd.Series:
    if label_field in df.columns:
        return df[label_field]
    raise KeyError(f"Unsupported IBL label_field: {label_field}")


def _encode_label_array(values: pd.Series, *, label_field: str) -> tuple[np.ndarray, dict[str, Any]]:
    observed = values.dropna()
    if observed.empty:
        raise ValueError(f"No valid labels found for {label_field}")

    numeric = pd.to_numeric(observed, errors="coerce")
    numeric_fraction = float(numeric.notna().mean()) if len(observed) else 0.0
    if numeric_fraction == 1.0 and numeric.nunique(dropna=True) > 10:
        array = numeric.to_numpy(dtype=np.float32)
        return array, {
            "label_field": label_field,
            "label_type": "continuous",
            "unique_count": int(pd.Series(array).nunique(dropna=True)),
        }

    if numeric_fraction == 1.0:
        ordered_values = sorted(
            value.item() if isinstance(value, np.generic) else value
            for value in numeric.unique().tolist()
        )
        mapping = {value: index for index, value in enumerate(ordered_values)}
        encoded = numeric.map(mapping).to_numpy(dtype=np.int64)
    else:
        normalized = observed.astype(str)
        ordered_values = sorted(normalized.unique().tolist())
        mapping = {value: index for index, value in enumerate(ordered_values)}
        encoded = normalized.map(mapping).to_numpy(dtype=np.int64)

    return encoded, {
        "label_field": label_field,
        "label_type": "categorical",
        "mapping": [
            {"code": int(index), "value": value}
            for index, value in enumerate(ordered_values)
        ],
    }


def _encode_group_array(values: pd.Series, *, group_by: str) -> tuple[np.ndarray, dict[str, Any]]:
    observed = values.fillna("unknown").astype(str)
    ordered_values = sorted(observed.unique().tolist())
    mapping = {value: index for index, value in enumerate(ordered_values)}
    encoded = observed.map(mapping).to_numpy(dtype=np.int64)
    return encoded, {
        "group_by": group_by,
        "mapping": [
            {"code": int(index), "value": value}
            for index, value in enumerate(ordered_values)
        ],
    }


__all__ = [
    "_assign_trials",
    "_append_trial_membership",
    "_safe_session_stem",
    "_with_trial_index",
    "_prepare_ibl_trial_metadata",
    "_fallback_trials_from_spikes",
    "_resolve_label_values",
    "_encode_label_array",
    "_encode_group_array",
]
