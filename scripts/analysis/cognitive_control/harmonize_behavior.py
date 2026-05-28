#!/usr/bin/env python3
"""Harmonize DMCC behavioral events into analysis-ready summary tables.

This first-pass harmonizer is scoped to the locally downloaded OpenNeuro
`ds003465` metadata/event files. It produces:

- a trial-level QC table,
- run-level summaries,
- run-by-trial-type summaries,
- task-level summaries, and
- a participant-session behavioral table aligned to the cognitive-control spec.

The participant-session table is one row per participant per session and is the
closest artifact to the eventual canonical SEM input. Because the local DMCC
download is metadata-only and sparse, `_v` columns are currently derived as
within-session z-scores of preregistered raw fallback scores when possible.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_meta_only"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "harmonized_behavior"
    / "dmcc"
)
DATASET_NAME = "dmcc"
STANDARD_NORMAL = NormalDist()

REQUIRED_RESPONSE_BY_TASK: dict[str, set[str] | None] = {
    "Axcpt": {"AX", "AY", "BX", "BY"},
    "Cuedts": None,
    "Stern": None,
    "Stroop": None,
}

TASK_CONFIGS: dict[str, dict[str, Any]] = {
    "Axcpt": {
        "task_canonical": "axcpt",
        "raw_column": "dmcc_axcpt_raw",
        "contrast_column": "trial_type",
        "high_demand_trial_types": {"BX"},
        "low_demand_trial_types": {"BY"},
    },
    "Cuedts": {
        "task_canonical": "taskswitch",
        "raw_column": "dmcc_taskswitch_raw",
        "contrast_column": "trial_switch",
        "high_demand_trial_types": {"switch"},
        "low_demand_trial_types": {"repeat"},
    },
    "Stern": {
        "task_canonical": "sternberg",
        "raw_column": "dmcc_sternberg_raw",
        "contrast_column": "trial_type",
        "high_demand_trial_types": {"RN"},
        "low_demand_trial_types": {"NN"},
    },
    "Stroop": {
        "task_canonical": "stroop",
        "raw_column": "dmcc_stroop_raw",
        "contrast_column": "trial_type",
        "high_demand_trial_types": {"InCon"},
        "low_demand_trial_types": {"Con"},
    },
}

OPTIONAL_EVENT_COLUMNS = [
    "trial_cue",
    "trial_switch",
    "trial_length",
    "trial_lwpc",
    "response_button",
]
SUMMARY_GROUP_COLUMNS = ["dataset", "participant_id", "session_id", "task"]
SESSION_GROUP_COLUMNS = ["dataset", "participant_id", "session_id"]


def _clean_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.integer | int):
        return int(value)
    if isinstance(value, np.floating | float):
        return float(value)
    return value


def _json_counts(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "{}"
    counts = {
        str(key): int(val) for key, val in non_null.astype(str).value_counts().items()
    }
    return json.dumps(dict(sorted(counts.items())), sort_keys=True)


def _safe_mean(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return float("nan")
    return float(non_null.mean())


def _safe_std(series: pd.Series) -> float:
    non_null = series.dropna()
    if len(non_null) < 2:
        return float("nan")
    return float(non_null.std(ddof=1))


def _safe_median(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return float("nan")
    return float(non_null.median())


def _mad(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return float("nan")
    center = float(non_null.median())
    return float(np.median(np.abs(non_null.to_numpy(dtype=float) - center)))


def _zscore_group(series: pd.Series) -> pd.Series:
    non_null = series.dropna()
    if len(non_null) < 2:
        return pd.Series(np.nan, index=series.index, dtype=float)
    std = float(non_null.std(ddof=0))
    if std == 0.0:
        return pd.Series(np.nan, index=series.index, dtype=float)
    mean = float(non_null.mean())
    return (series - mean) / std


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_bids_entities(path: Path) -> dict[str, Any]:
    name = path.name
    for suffix in ("_events.tsv", "_bold.json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    entities: dict[str, Any] = {
        "participant_id": None,
        "session_id": None,
        "task": None,
        "acquisition": None,
        "run": None,
    }
    for token in name.split("_"):
        if token.startswith("sub-"):
            entities["participant_id"] = token
        elif token.startswith("ses-"):
            entities["session_id"] = token
        elif token.startswith("task-"):
            entities["task"] = token.split("-", 1)[1]
        elif token.startswith("acq-"):
            entities["acquisition"] = token.split("-", 1)[1]
        elif token.startswith("run-"):
            run_value = token.split("-", 1)[1]
            entities["run"] = int(run_value) if run_value.isdigit() else run_value
    return entities


def _load_participants(dataset_root: Path) -> pd.DataFrame:
    participants_path = dataset_root / "participants.tsv"
    participants = pd.read_csv(participants_path, sep="\t", na_values=["n/a", "NA"])
    participants["age_years"] = pd.to_numeric(participants["age"], errors="coerce")
    participants["sex_at_birth"] = participants["sex"].replace({"n/a": pd.NA})
    return participants[["participant_id", "age_years", "sex_at_birth"]]


def _response_required(task: str, trial_type: Any) -> bool:
    allowed = REQUIRED_RESPONSE_BY_TASK[task]
    if allowed is None:
        return True
    return str(trial_type) in allowed


def _load_trial_table(dataset_root: Path, participants: pd.DataFrame) -> pd.DataFrame:
    event_files = sorted(dataset_root.glob("sub-*/ses-*/func/*_events.tsv"))
    if not event_files:
        raise RuntimeError(f"No DMCC event files found under {dataset_root}")

    trial_records: list[dict[str, Any]] = []
    for event_path in event_files:
        entities = _parse_bids_entities(event_path)
        task = entities["task"]
        if task not in TASK_CONFIGS:
            continue

        events = pd.read_csv(event_path, sep="\t", na_values=["n/a", "NA"])
        bold_json_path = event_path.with_name(
            event_path.name.replace("_events.tsv", "_bold.json")
        )
        sidecar = _read_json(bold_json_path)

        for column in [
            "onset",
            "duration",
            "response_time",
            "response_accuracy",
            "response_button",
            "trial_length",
        ]:
            if column in events.columns:
                events[column] = pd.to_numeric(events[column], errors="coerce")

        events["dataset"] = DATASET_NAME
        events["participant_id"] = entities["participant_id"]
        events["session_id"] = entities["session_id"]
        events["task"] = task
        events["task_canonical"] = TASK_CONFIGS[task]["task_canonical"]
        events["acquisition"] = entities["acquisition"]
        events["run"] = entities["run"]
        events["event_file"] = str(event_path)
        events["bold_json"] = str(bold_json_path)
        events["task_name_sidecar"] = sidecar.get("TaskName", task)
        events["tr_seconds"] = sidecar.get("RepetitionTime")
        events["multiband_acceleration_factor"] = sidecar.get(
            "MultibandAccelerationFactor"
        )
        events["phase_encoding_direction"] = sidecar.get("PhaseEncodingDirection")
        events["effective_echo_spacing"] = sidecar.get("EffectiveEchoSpacing")
        events["response_required"] = events["trial_type"].map(
            lambda value, task=task: _response_required(task, value)
        )

        if "response_button" not in events.columns:
            events["response_button"] = pd.NA
        if "response_accuracy" not in events.columns:
            events["response_accuracy"] = pd.NA
        if "response_time" not in events.columns:
            events["response_time"] = pd.NA
        if "duration" not in events.columns:
            events["duration"] = pd.NA
        if "onset" not in events.columns:
            events["onset"] = pd.NA

        trial_records.extend(events.to_dict(orient="records"))

    trials = pd.DataFrame.from_records(trial_records)
    trials = trials.merge(participants, on="participant_id", how="left")

    for column in OPTIONAL_EVENT_COLUMNS:
        if column not in trials.columns:
            trials[column] = pd.NA

    trials["response_recorded"] = (
        trials["response_time"].notna() | trials["response_button"].notna()
    )
    trials["valid_event_coding"] = (
        trials["onset"].notna()
        & trials["duration"].notna()
        & trials["trial_type"].notna()
    )
    trials["omission"] = trials["response_required"] & ~trials["response_recorded"]
    return trials


def _apply_trial_qc(trials: pd.DataFrame) -> pd.DataFrame:
    rt_source = trials.loc[
        trials["response_required"] & trials["response_time"].notna(),
        SUMMARY_GROUP_COLUMNS + ["response_time"],
    ]
    if rt_source.empty:
        trials["task_rt_median_s"] = np.nan
        trials["task_rt_mad_s"] = np.nan
    else:
        rt_stats = (
            rt_source.groupby(SUMMARY_GROUP_COLUMNS, dropna=False)["response_time"]
            .agg(task_rt_median_s="median", task_rt_mad_s=_mad)
            .reset_index()
        )
        trials = trials.merge(rt_stats, on=SUMMARY_GROUP_COLUMNS, how="left")

    upper_threshold = np.where(
        trials["task_rt_mad_s"].fillna(0.0) > 0.0,
        trials["task_rt_median_s"] + (3.0 * trials["task_rt_mad_s"]),
        np.inf,
    )
    trials["rt_too_fast"] = trials["response_time"].lt(0.150)
    trials["rt_too_slow"] = (
        trials["response_required"]
        & trials["response_time"].notna()
        & (trials["response_time"] > upper_threshold)
    )
    trials["trial_qc_pass"] = (
        trials["valid_event_coding"]
        & ~trials["omission"]
        & ~trials["rt_too_fast"]
        & ~trials["rt_too_slow"]
    )
    trials["analysis_accuracy_include"] = (
        trials["valid_event_coding"] & trials["response_accuracy"].notna()
    )
    trials["analysis_rt_include"] = (
        trials["trial_qc_pass"]
        & trials["response_required"]
        & trials["response_time"].notna()
        & (trials["response_accuracy"] == 1)
    )

    demand_labels: list[str] = []
    for _, row in trials.iterrows():
        config = TASK_CONFIGS[row["task"]]
        contrast_value = row.get(config["contrast_column"], pd.NA)
        if contrast_value in config["high_demand_trial_types"]:
            demand_labels.append("high")
        elif contrast_value in config["low_demand_trial_types"]:
            demand_labels.append("low")
        else:
            demand_labels.append("other")
    trials["demand_condition"] = demand_labels
    return trials


def _base_summary(group: pd.DataFrame) -> dict[str, Any]:
    analysis_accuracy = group.loc[
        group["analysis_accuracy_include"], "response_accuracy"
    ]
    analysis_rt = group.loc[group["analysis_rt_include"], "response_time"]
    response_required = group["response_required"]
    required_trials = int(response_required.sum())
    omissions = int(group["omission"].sum())

    summary: dict[str, Any] = {
        "n_trials_total": int(len(group)),
        "n_trials_qc_pass": int(group["trial_qc_pass"].sum()),
        "usable_trial_fraction": float(group["trial_qc_pass"].mean()),
        "n_response_required": required_trials,
        "n_omissions": omissions,
        "omission_rate": (
            float(omissions / required_trials) if required_trials > 0 else float("nan")
        ),
        "n_accuracy_trials": int(group["analysis_accuracy_include"].sum()),
        "accuracy_mean": _safe_mean(analysis_accuracy),
        "n_rt_trials": int(group["analysis_rt_include"].sum()),
        "rt_mean_s": _safe_mean(analysis_rt),
        "rt_median_s": _safe_median(analysis_rt),
        "rt_sd_s": _safe_std(analysis_rt),
        "task_end_s": float((group["onset"] + group["duration"]).max()),
        "trial_type_counts_json": _json_counts(group["trial_type"]),
        "demand_condition_counts_json": _json_counts(group["demand_condition"]),
    }
    for column in OPTIONAL_EVENT_COLUMNS:
        if column in group.columns:
            summary[f"{column}_counts_json"] = _json_counts(group[column])
    return summary


def _control_contrast_summary(group: pd.DataFrame) -> dict[str, Any]:
    task = str(group["task"].iloc[0])
    config = TASK_CONFIGS[task]
    contrast_column = str(config["contrast_column"])
    high_label = ",".join(sorted(config["high_demand_trial_types"]))
    low_label = ",".join(sorted(config["low_demand_trial_types"]))

    high = group.loc[group[contrast_column].isin(config["high_demand_trial_types"])]
    low = group.loc[group[contrast_column].isin(config["low_demand_trial_types"])]

    high_acc = _safe_mean(
        high.loc[high["analysis_accuracy_include"], "response_accuracy"]
    )
    low_acc = _safe_mean(low.loc[low["analysis_accuracy_include"], "response_accuracy"])
    high_rt = _safe_mean(high.loc[high["analysis_rt_include"], "response_time"])
    low_rt = _safe_mean(low.loc[low["analysis_rt_include"], "response_time"])

    high_ie = (
        float(high_rt / high_acc) if pd.notna(high_rt) and high_acc > 0 else np.nan
    )
    low_ie = float(low_rt / low_acc) if pd.notna(low_rt) and low_acc > 0 else np.nan
    rt_cost = (
        float(high_rt - low_rt) if pd.notna(high_rt) and pd.notna(low_rt) else np.nan
    )
    accuracy_cost = (
        float(low_acc - high_acc)
        if pd.notna(high_acc) and pd.notna(low_acc)
        else np.nan
    )
    ie_cost = (
        float(high_ie - low_ie) if pd.notna(high_ie) and pd.notna(low_ie) else np.nan
    )
    raw_score = -ie_cost if pd.notna(ie_cost) else np.nan

    summary = {
        "control_contrast_column": contrast_column,
        "control_high_demand_label": high_label,
        "control_low_demand_label": low_label,
        "control_high_n_trials": int(len(high)),
        "control_low_n_trials": int(len(low)),
        "control_high_accuracy_mean": high_acc,
        "control_low_accuracy_mean": low_acc,
        "control_high_rt_mean_s": high_rt,
        "control_low_rt_mean_s": low_rt,
        "control_high_ie_mean_s": high_ie,
        "control_low_ie_mean_s": low_ie,
        "control_rt_cost_s": rt_cost,
        "control_accuracy_cost": accuracy_cost,
        "control_ie_cost_s": ie_cost,
        "raw_score_ie_cost": raw_score,
        "raw_score_primary": raw_score,
        "raw_score_method": "inverse_efficiency_high_vs_low",
    }
    if task == "Axcpt":
        ax = group.loc[
            group["analysis_accuracy_include"] & (group["trial_type"] == "AX"),
            "response_accuracy",
        ]
        bx = group.loc[
            group["analysis_accuracy_include"] & (group["trial_type"] == "BX"),
            "response_accuracy",
        ]
        ay = group.loc[
            group["analysis_accuracy_include"] & (group["trial_type"] == "AY"),
            "response_accuracy",
        ]

        ax_hits = int((ax == 1).sum())
        n_ax = int(ax.notna().sum())
        bx_false_alarms = int((bx == 0).sum())
        n_bx = int(bx.notna().sum())
        ay_error_rate = float(1.0 - ay.mean()) if not ay.empty else np.nan
        bx_error_rate = float(1.0 - bx.mean()) if not bx.empty else np.nan

        if n_ax > 0 and n_bx > 0:
            hit_rate = (ax_hits + 0.5) / (n_ax + 1.0)
            false_alarm_rate = (bx_false_alarms + 0.5) / (n_bx + 1.0)
            dprime_context = STANDARD_NORMAL.inv_cdf(
                hit_rate
            ) - STANDARD_NORMAL.inv_cdf(false_alarm_rate)
        else:
            hit_rate = np.nan
            false_alarm_rate = np.nan
            dprime_context = np.nan

        ay_minus_bx_error = (
            float(ay_error_rate - bx_error_rate)
            if pd.notna(ay_error_rate) and pd.notna(bx_error_rate)
            else np.nan
        )
        summary.update(
            {
                "axcpt_hit_rate": hit_rate,
                "axcpt_false_alarm_rate": false_alarm_rate,
                "axcpt_dprime_context": dprime_context,
                "axcpt_ay_minus_bx_error": ay_minus_bx_error,
                "raw_score_primary": dprime_context,
                "raw_score_method": "dprime_context",
            }
        )

    return summary


def _summarize_groups(
    trials: pd.DataFrame,
    group_columns: list[str],
    include_control_contrast: bool = False,
    extra_first_columns: list[str] | None = None,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    extra_first_columns = extra_first_columns or []

    for keys, group in trials.groupby(group_columns, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(group_columns, keys, strict=True))

        for column in extra_first_columns:
            record[column] = _clean_scalar(group[column].iloc[0])

        record.update(_base_summary(group))
        if include_control_contrast:
            record.update(_control_contrast_summary(group))

        if "run" not in group_columns:
            record["n_runs"] = int(group["run"].nunique(dropna=True))
            record["acquisitions_json"] = _json_counts(group["acquisition"])
        records.append(record)

    return pd.DataFrame.from_records(records)


def _build_behavior_harmonized(
    trials: pd.DataFrame,
    task_level: pd.DataFrame,
) -> pd.DataFrame:
    session_records: list[dict[str, Any]] = []
    for keys, group in trials.groupby(SESSION_GROUP_COLUMNS, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(SESSION_GROUP_COLUMNS, keys, strict=True))
        record["site_id"] = pd.NA
        record["family_id"] = pd.NA
        record["age_years"] = _clean_scalar(group["age_years"].iloc[0])
        record["sex_at_birth"] = _clean_scalar(group["sex_at_birth"].iloc[0])
        record["education_years"] = pd.NA
        record["parent_education_years"] = pd.NA
        record["simple_rt_ms"] = pd.NA
        record["mean_fd"] = pd.NA
        record["mean_accuracy_all_tasks"] = _safe_mean(
            group.loc[group["analysis_accuracy_include"], "response_accuracy"]
        )
        required_trials = int(group["response_required"].sum())
        omissions = int(group["omission"].sum())
        record["mean_omission_rate"] = (
            float(omissions / required_trials) if required_trials > 0 else float("nan")
        )
        record["n_tasks_observed"] = int(group["task"].nunique())
        session_records.append(record)

    behavior = pd.DataFrame.from_records(session_records)

    raw_columns = [config["raw_column"] for config in TASK_CONFIGS.values()]
    task_scores = task_level[
        [
            "dataset",
            "participant_id",
            "session_id",
            "task_canonical",
            "raw_score_primary",
            "raw_score_method",
        ]
    ].copy()
    task_scores["raw_column"] = task_scores["task_canonical"].map(
        {
            config["task_canonical"]: config["raw_column"]
            for config in TASK_CONFIGS.values()
        }
    )

    pivoted = task_scores.pivot_table(
        index=SESSION_GROUP_COLUMNS,
        columns="raw_column",
        values="raw_score_primary",
        aggfunc="first",
    ).reset_index()
    pivoted.columns.name = None
    behavior = behavior.merge(pivoted, on=SESSION_GROUP_COLUMNS, how="left")

    mode_scores = task_scores.copy()
    mode_scores["mode_column"] = mode_scores["raw_column"] + "_score_mode"
    mode_pivoted = mode_scores.pivot_table(
        index=SESSION_GROUP_COLUMNS,
        columns="mode_column",
        values="raw_score_method",
        aggfunc="first",
    ).reset_index()
    mode_pivoted.columns.name = None
    behavior = behavior.merge(mode_pivoted, on=SESSION_GROUP_COLUMNS, how="left")

    for raw_column in raw_columns:
        if raw_column not in behavior.columns:
            behavior[raw_column] = np.nan

        v_column = raw_column.replace("_raw", "_v")
        behavior[v_column] = behavior.groupby(["dataset", "session_id"], dropna=False)[
            raw_column
        ].transform(_zscore_group)
        raw_mode_column = f"{raw_column}_score_mode"
        if raw_mode_column not in behavior.columns:
            behavior[raw_mode_column] = pd.NA
        behavior[f"{v_column}_score_mode"] = np.where(
            behavior[v_column].notna(),
            behavior[raw_mode_column].fillna("raw_fallback_primary")
            + "_zscore_within_dataset_session",
            np.where(
                behavior[raw_column].notna(),
                "pending_standardization_more_subjects_needed",
                pd.NA,
            ),
        )

    ordered_columns = [
        "dataset",
        "participant_id",
        "session_id",
        "site_id",
        "family_id",
        "age_years",
        "sex_at_birth",
        "education_years",
        "parent_education_years",
        "simple_rt_ms",
        "mean_accuracy_all_tasks",
        "mean_omission_rate",
        "mean_fd",
        "n_tasks_observed",
        "dmcc_stroop_v",
        "dmcc_axcpt_v",
        "dmcc_taskswitch_v",
        "dmcc_sternberg_v",
        "dmcc_stroop_raw",
        "dmcc_axcpt_raw",
        "dmcc_taskswitch_raw",
        "dmcc_sternberg_raw",
        "dmcc_stroop_raw_score_mode",
        "dmcc_axcpt_raw_score_mode",
        "dmcc_taskswitch_raw_score_mode",
        "dmcc_sternberg_raw_score_mode",
        "dmcc_stroop_v_score_mode",
        "dmcc_axcpt_v_score_mode",
        "dmcc_taskswitch_v_score_mode",
        "dmcc_sternberg_v_score_mode",
    ]
    return behavior.reindex(columns=ordered_columns)


def _write_table(
    df: pd.DataFrame, csv_path: Path, parquet_path: Path
) -> dict[str, Any]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    parquet_written = False
    parquet_error: str | None = None
    try:
        df.to_parquet(parquet_path, index=False)
        parquet_written = True
    except Exception as exc:  # pragma: no cover - environment dependent
        parquet_error = str(exc)

    return {
        "csv": str(csv_path),
        "parquet": str(parquet_path),
        "parquet_written": parquet_written,
        "parquet_error": parquet_error,
        "n_rows": int(len(df)),
        "n_columns": int(len(df.columns)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harmonize DMCC behavior tables from downloaded event files."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="Path to the downloaded DMCC metadata/events root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for harmonized outputs.",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    participants = _load_participants(dataset_root)
    trials = _apply_trial_qc(_load_trial_table(dataset_root, participants))

    run_level = _summarize_groups(
        trials=trials,
        group_columns=[
            "dataset",
            "participant_id",
            "session_id",
            "task",
            "task_canonical",
            "acquisition",
            "run",
        ],
        include_control_contrast=True,
        extra_first_columns=[
            "task_name_sidecar",
            "tr_seconds",
            "multiband_acceleration_factor",
            "phase_encoding_direction",
            "effective_echo_spacing",
            "age_years",
            "sex_at_birth",
            "event_file",
            "bold_json",
        ],
    )
    run_trial_type = _summarize_groups(
        trials=trials,
        group_columns=[
            "dataset",
            "participant_id",
            "session_id",
            "task",
            "task_canonical",
            "acquisition",
            "run",
            "trial_type",
            "demand_condition",
        ],
    )
    task_level = _summarize_groups(
        trials=trials,
        group_columns=[
            "dataset",
            "participant_id",
            "session_id",
            "task",
            "task_canonical",
        ],
        include_control_contrast=True,
        extra_first_columns=["age_years", "sex_at_birth"],
    )
    behavior_harmonized = _build_behavior_harmonized(trials, task_level)

    outputs = {
        "trial_level_qc": _write_table(
            trials,
            output_root / "trial_level_qc.csv",
            output_root / "trial_level_qc.parquet",
        ),
        "run_level_summary": _write_table(
            run_level,
            output_root / "run_level_summary.csv",
            output_root / "run_level_summary.parquet",
        ),
        "run_trial_type_summary": _write_table(
            run_trial_type,
            output_root / "run_trial_type_summary.csv",
            output_root / "run_trial_type_summary.parquet",
        ),
        "task_level_summary": _write_table(
            task_level,
            output_root / "task_level_summary.csv",
            output_root / "task_level_summary.parquet",
        ),
        "behavior_harmonized": _write_table(
            behavior_harmonized,
            output_root / "behavior_harmonized.csv",
            output_root / "behavior_harmonized.parquet",
        ),
    }

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": DATASET_NAME,
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "participant_count_in_participants_tsv": int(
            participants["participant_id"].nunique()
        ),
        "participant_count_in_downloaded_events": int(
            trials["participant_id"].nunique()
        ),
        "session_count_in_downloaded_events": int(
            trials[["participant_id", "session_id"]].drop_duplicates().shape[0]
        ),
        "event_file_count": int(trials["event_file"].nunique()),
        "tasks_observed": sorted(trials["task"].dropna().unique().tolist()),
        "task_to_canonical_mapping": {
            task: config["task_canonical"] for task, config in TASK_CONFIGS.items()
        },
        "raw_score_definitions": {
            "Axcpt": (
                "raw_score_primary = dprime_context = "
                "norm.ppf((AX_hits + 0.5) / (AX_total + 1)) - "
                "norm.ppf((BX_false_alarms + 0.5) / (BX_total + 1)); "
                "higher is better."
            ),
            "Cuedts": (
                "raw_score_primary = -(switch_inverse_efficiency - "
                "repeat_inverse_efficiency); higher is better."
            ),
            "Stern": (
                "raw_score_primary = -(RN_inverse_efficiency - "
                "NN_inverse_efficiency); higher is better."
            ),
            "Stroop": (
                "raw_score_primary = -(InCon_inverse_efficiency - "
                "Con_inverse_efficiency); higher is better."
            ),
        },
        "high_low_demand_mapping": {
            task: {
                "high": sorted(config["high_demand_trial_types"]),
                "low": sorted(config["low_demand_trial_types"]),
                "contrast_column": config["contrast_column"],
            }
            for task, config in TASK_CONFIGS.items()
        },
        "trial_qc": {
            "rt_min_seconds": 0.150,
            "rt_upper_rule": "participant-session-task median + 3*MAD",
            "omission_rule": "missing response on a response-required trial",
            "axcpt_no_go_trial_types": ["Ang", "Bng"],
        },
        "outputs": outputs,
        "note": (
            "This is a DMCC metadata/events harmonization pass. It does not fit "
            "diffusion models or produce finalized SEM-ready latent indicators."
        ),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
