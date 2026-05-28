#!/usr/bin/env python3
"""Summarize corrected DMCC behavior-imaging bridge outputs.

This script reads the corrected fMRIPrep-based DMCC bridge table, derives
subject/task imaging summary metrics from subject-level effect maps, optionally
joins SEM factor scores, and writes merged bridge-level summary artifacts.

The outputs are descriptive. They are intended to support downstream inspection
and pilot analyses, not to serve as confirmatory neural adjudication.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import warnings

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets, image


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BRIDGE_CSV = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "behavior_imaging_bridge"
    / "dmcc_glm_fmriprep_subject4"
    / "dmcc_behavior_imaging_bridge.csv"
)
DEFAULT_GLM_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "dmcc_glm_fmriprep_subject4"
)
DEFAULT_SEM_FACTOR_SCORES_CSV = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "semopy_cfa"
    / "dmcc_glm_fmriprep_subject4_bridge"
    / "factor_scores.csv"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "behavior_imaging_summary"
)
MERGE_KEYS = ["dataset", "participant_id", "session_id"]
TASK_SPECS: dict[str, dict[str, str]] = {
    "Axcpt": {"prefix": "axcpt", "behavior_col": "dmcc_axcpt_v"},
    "Cuedts": {"prefix": "cuedts", "behavior_col": "dmcc_taskswitch_v"},
    "Stern": {"prefix": "stern", "behavior_col": "dmcc_sternberg_v"},
    "Stroop": {"prefix": "stroop", "behavior_col": "dmcc_stroop_v"},
}
BEHAVIOR_COLUMNS = [spec["behavior_col"] for spec in TASK_SPECS.values()]
YEO7_NETWORK_LABELS = {
    1: "visual",
    2: "somatomotor",
    3: "dorsal_attention",
    4: "ventral_attention",
    5: "limbic",
    6: "frontoparietal",
    7: "default",
}
MD_MASK_LABEL = "loo_task_conjunction"
MD_MASK_METHOD = "leave_one_subject_out_min_across_tasks_top_positive_percentile"
MD_MASK_PERCENTILE_CANDIDATES = [99.0, 98.0, 97.0, 95.0]
MD_MASK_MIN_VOXELS = 250


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _serialize_frame_dict(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) != 1:
        raise ValueError("Expected a one-row DataFrame for stats serialization.")
    return {str(key): _clean_scalar(value) for key, value in frame.iloc[0].to_dict().items()}


def _safe_corr(x: pd.Series, y: pd.Series, method: str) -> tuple[int, float | None]:
    frame = pd.concat([x, y], axis=1).dropna()
    if len(frame) < 3:
        return len(frame), None
    try:
        correlation = frame.iloc[:, 0].corr(frame.iloc[:, 1], method=method)
    except Exception:
        correlation = None
    if correlation is not None and pd.isna(correlation):
        correlation = None
    return len(frame), correlation


def _compute_spatial_corr(subject_values: np.ndarray, group_values: np.ndarray) -> float | None:
    joint_mask = np.isfinite(subject_values) & np.isfinite(group_values)
    if not np.any(joint_mask):
        return None
    x = subject_values[joint_mask].astype(np.float64, copy=False)
    y = group_values[joint_mask].astype(np.float64, copy=False)
    x_std = float(np.std(x))
    y_std = float(np.std(y))
    if x_std == 0.0 or y_std == 0.0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _discover_group_maps(glm_root: Path) -> dict[str, Path]:
    group_maps: dict[str, Path] = {}
    summary_paths = sorted(glm_root.rglob("glm_second_level_summary.json"))
    for summary_path in summary_paths:
        parts = summary_path.parts
        if "second_level" not in parts:
            continue
        task = parts[parts.index("second_level") + 1]
        local_group_map = summary_path.parent / "group_zmap.nii.gz"
        if local_group_map.exists():
            group_maps[task] = local_group_map.resolve()
            continue
        summary = _read_json(summary_path)
        candidate = Path(str(summary.get("group_zmap", "")))
        if candidate.exists():
            group_maps[task] = candidate.resolve()
    return group_maps


def _fetch_yeo7_thick_atlas_path() -> Path:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        atlas = datasets.fetch_atlas_yeo_2011()
    return Path(str(atlas["thick_7"])).resolve()


def _atlas_cache_key(img: nib.spatialimages.SpatialImage) -> tuple[Any, ...]:
    return (
        tuple(int(value) for value in img.shape[:3]),
        tuple(float(value) for value in np.round(np.asarray(img.affine).reshape(-1), 6)),
    )


def _get_resampled_yeo7_labels(
    target_img: nib.spatialimages.SpatialImage,
    atlas_path: Path,
    cache: dict[tuple[Any, ...], np.ndarray],
) -> np.ndarray:
    cache_key = _atlas_cache_key(target_img)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    atlas_img = nib.load(str(atlas_path))
    resampled = image.resample_to_img(
        atlas_img,
        target_img,
        interpolation="nearest",
        force_resample=True,
        copy_header=True,
    )
    label_data = np.asanyarray(resampled.dataobj)
    if label_data.ndim == 4:
        label_data = label_data[..., 0]
    labels = np.rint(label_data).astype(np.int16, copy=False)
    cache[cache_key] = labels
    return labels


def _discover_effect_map_records(glm_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    effect_paths = sorted(glm_root.rglob("*_effect_size_mean.nii.gz"))
    for effect_path in effect_paths:
        try:
            relative = effect_path.relative_to(glm_root / "subject_level")
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) != 4:
            continue
        task, participant_id, session_id, _filename = parts
        if task not in TASK_SPECS:
            continue
        records.append(
            {
                "dataset": "dmcc",
                "task": task,
                "participant_id": participant_id,
                "session_id": session_id,
                "effect_map_path": str(effect_path.resolve()),
            }
        )
    return records


def _preload_effect_arrays(effect_records: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for record in effect_records:
        arrays[record["effect_map_path"]] = np.asanyarray(
            nib.load(record["effect_map_path"]).dataobj, dtype=np.float64
        )
    return arrays


def _compute_leave_one_out_maps(
    effect_records: list[dict[str, Any]], effect_arrays: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    by_task: dict[str, list[str]] = {}
    for record in effect_records:
        by_task.setdefault(record["task"], []).append(record["effect_map_path"])

    loo_maps: dict[str, np.ndarray] = {}
    for task, effect_paths in by_task.items():
        if len(effect_paths) < 2:
            for effect_path in effect_paths:
                loo_maps[effect_path] = np.full_like(effect_arrays[effect_path], np.nan, dtype=np.float64)
            continue
        stacked = np.stack([effect_arrays[path] for path in effect_paths], axis=0)
        task_sum = np.sum(stacked, axis=0)
        task_count = float(len(effect_paths))
        for index, effect_path in enumerate(effect_paths):
            loo_maps[effect_path] = (task_sum - stacked[index]) / (task_count - 1.0)
    return loo_maps


def _discover_subject_level_rows(glm_root: Path, bridge_df: pd.DataFrame) -> pd.DataFrame:
    group_maps = _discover_group_maps(glm_root)
    effect_records = _discover_effect_map_records(glm_root)
    effect_arrays = _preload_effect_arrays(effect_records)
    loo_maps = _compute_leave_one_out_maps(effect_records, effect_arrays)
    bridge_lookup = bridge_df.set_index(MERGE_KEYS)
    rows: list[dict[str, Any]] = []

    for record in effect_records:
        dataset = str(record["dataset"])
        task = str(record["task"])
        participant_id = str(record["participant_id"])
        session_id = str(record["session_id"])
        effect_path = Path(str(record["effect_map_path"]))
        key = (dataset, participant_id, session_id)
        behavior_row = None
        if key in bridge_lookup.index:
            behavior_row = bridge_lookup.loc[key]
        behavior_col = TASK_SPECS[task]["behavior_col"]
        behavior_value = None
        if behavior_row is not None and behavior_col in behavior_row.index:
            behavior_value = behavior_row[behavior_col]

        effect_data = effect_arrays[str(effect_path)]
        effect_values = effect_data[np.isfinite(effect_data)]
        if effect_values.size == 0:
            continue

        group_map_path = group_maps.get(task)
        group_spatial_r = None
        loo_group_spatial_r = None
        if group_map_path is not None:
            group_img = nib.load(str(group_map_path))
            group_data = np.asanyarray(group_img.dataobj, dtype=np.float64)
            if group_data.shape == effect_data.shape:
                group_spatial_r = _compute_spatial_corr(effect_data.reshape(-1), group_data.reshape(-1))
        loo_group_data = loo_maps.get(str(effect_path))
        if loo_group_data is not None and loo_group_data.shape == effect_data.shape:
            loo_group_spatial_r = _compute_spatial_corr(
                effect_data.reshape(-1), loo_group_data.reshape(-1)
            )

        rows.append(
            {
                "dataset": dataset,
                "participant_id": participant_id,
                "session_id": session_id,
                "task": task,
                "task_prefix": TASK_SPECS[task]["prefix"],
                "behavior_col": behavior_col,
                "behavior_value": behavior_value,
                "effect_map_path": str(effect_path.resolve()),
                "group_zmap_path": str(group_map_path) if group_map_path is not None else None,
                "voxel_count": int(effect_values.size),
                "effect_mean": float(np.mean(effect_values)),
                "effect_std": float(np.std(effect_values)),
                "effect_abs_mean": float(np.mean(np.abs(effect_values))),
                "effect_abs_p95": float(np.percentile(np.abs(effect_values), 95)),
                "effect_positive_fraction": float(np.mean(effect_values > 0)),
                "effect_negative_fraction": float(np.mean(effect_values < 0)),
                "group_spatial_r": group_spatial_r,
                "loo_group_spatial_r": loo_group_spatial_r,
            }
        )

    return pd.DataFrame(rows)


def _discover_network_level_rows(imaging_df: pd.DataFrame) -> pd.DataFrame:
    if imaging_df.empty:
        return pd.DataFrame(
            columns=[
                "dataset",
                "participant_id",
                "session_id",
                "task",
                "task_prefix",
                "network_id",
                "network_label",
                "effect_mean",
                "effect_abs_mean",
                "effect_abs_p95",
                "effect_positive_fraction",
                "effect_negative_fraction",
                "voxel_count",
            ]
        )

    atlas_path = _fetch_yeo7_thick_atlas_path()
    atlas_cache: dict[tuple[Any, ...], np.ndarray] = {}
    rows: list[dict[str, Any]] = []

    for imaging_row in imaging_df.to_dict(orient="records"):
        effect_img = nib.load(str(imaging_row["effect_map_path"]))
        effect_data = np.asanyarray(effect_img.dataobj, dtype=np.float64)
        finite_mask = np.isfinite(effect_data)
        yeo_labels = _get_resampled_yeo7_labels(effect_img, atlas_path, atlas_cache)

        for network_id, network_label in YEO7_NETWORK_LABELS.items():
            mask = finite_mask & (yeo_labels == network_id)
            if not np.any(mask):
                continue
            values = effect_data[mask]
            rows.append(
                {
                    "dataset": imaging_row["dataset"],
                    "participant_id": imaging_row["participant_id"],
                    "session_id": imaging_row["session_id"],
                    "task": imaging_row["task"],
                    "task_prefix": imaging_row["task_prefix"],
                    "network_id": network_id,
                    "network_label": network_label,
                    "effect_mean": float(np.mean(values)),
                    "effect_abs_mean": float(np.mean(np.abs(values))),
                    "effect_abs_p95": float(np.percentile(np.abs(values), 95)),
                    "effect_positive_fraction": float(np.mean(values > 0)),
                    "effect_negative_fraction": float(np.mean(values < 0)),
                    "voxel_count": int(values.size),
                }
            )

    return pd.DataFrame(rows)


def _discover_md_mask_rows(imaging_df: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    if imaging_df.empty:
        return pd.DataFrame(
            columns=[
                "dataset",
                "participant_id",
                "session_id",
                "task",
                "task_prefix",
                "mask_label",
                "mask_method",
                "mask_path",
                "mask_voxel_count",
                "threshold_percentile",
                "threshold_value",
                "training_subject_count",
                "training_task_count",
                "effect_mean",
                "effect_abs_mean",
                "effect_abs_p95",
                "effect_positive_fraction",
                "effect_negative_fraction",
                "voxel_count",
            ]
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    effect_path_to_img: dict[str, nib.spatialimages.SpatialImage] = {}
    effect_path_to_data: dict[str, np.ndarray] = {}
    for effect_path in imaging_df["effect_map_path"].dropna().unique().tolist():
        img = nib.load(str(effect_path))
        effect_path_to_img[str(effect_path)] = img
        effect_path_to_data[str(effect_path)] = np.asanyarray(img.dataobj, dtype=np.float64)

    subject_keys = (
        imaging_df[MERGE_KEYS]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    rows: list[dict[str, Any]] = []
    for dataset, participant_id, session_id in subject_keys:
        held_out_mask = (
            (imaging_df["dataset"] == dataset)
            & (imaging_df["participant_id"] == participant_id)
            & (imaging_df["session_id"] == session_id)
        )
        held_out_rows = imaging_df.loc[held_out_mask].copy()
        if held_out_rows.empty:
            continue

        task_mean_maps: list[np.ndarray] = []
        training_subjects: set[str] = set()
        for task in TASK_SPECS:
            training_rows = imaging_df.loc[
                (imaging_df["task"] == task) & (~held_out_mask)
            ]
            if training_rows.empty:
                task_mean_maps = []
                break
            training_subjects.update(training_rows["participant_id"].astype(str).tolist())
            stacked = np.stack(
                [effect_path_to_data[str(path)] for path in training_rows["effect_map_path"]],
                axis=0,
            )
            task_mean_maps.append(np.mean(stacked, axis=0))
        if len(task_mean_maps) != len(TASK_SPECS):
            continue

        task_stack = np.stack(task_mean_maps, axis=0)
        valid_mask = np.all(np.isfinite(task_stack), axis=0)
        conjunction_map = np.min(task_stack, axis=0)
        positive_values = conjunction_map[valid_mask & (conjunction_map > 0)]
        if positive_values.size == 0:
            continue

        chosen_percentile = None
        chosen_threshold = None
        conjunction_mask = None
        for percentile in MD_MASK_PERCENTILE_CANDIDATES:
            threshold = float(np.percentile(positive_values, percentile))
            candidate_mask = valid_mask & (conjunction_map >= threshold) & (conjunction_map > 0)
            if int(np.count_nonzero(candidate_mask)) >= MD_MASK_MIN_VOXELS:
                chosen_percentile = float(percentile)
                chosen_threshold = threshold
                conjunction_mask = candidate_mask
                break
        if conjunction_mask is None:
            percentile = float(MD_MASK_PERCENTILE_CANDIDATES[-1])
            threshold = float(np.percentile(positive_values, percentile))
            conjunction_mask = valid_mask & (conjunction_map >= threshold) & (conjunction_map > 0)
            chosen_percentile = percentile
            chosen_threshold = threshold

        template_path = str(held_out_rows.iloc[0]["effect_map_path"])
        template_img = effect_path_to_img[template_path]
        subject_mask_dir = output_dir / str(participant_id) / str(session_id)
        subject_mask_dir.mkdir(parents=True, exist_ok=True)
        mask_path = subject_mask_dir / f"{MD_MASK_LABEL}_mask.nii.gz"
        mask_img = nib.Nifti1Image(
            conjunction_mask.astype(np.uint8),
            template_img.affine,
            template_img.header,
        )
        nib.save(mask_img, str(mask_path))

        for imaging_row in held_out_rows.to_dict(orient="records"):
            effect_data = effect_path_to_data[str(imaging_row["effect_map_path"])]
            values = effect_data[np.isfinite(effect_data) & conjunction_mask]
            if values.size == 0:
                continue
            rows.append(
                {
                    "dataset": imaging_row["dataset"],
                    "participant_id": imaging_row["participant_id"],
                    "session_id": imaging_row["session_id"],
                    "task": imaging_row["task"],
                    "task_prefix": imaging_row["task_prefix"],
                    "mask_label": MD_MASK_LABEL,
                    "mask_method": MD_MASK_METHOD,
                    "mask_path": str(mask_path.resolve()),
                    "mask_voxel_count": int(np.count_nonzero(conjunction_mask)),
                    "threshold_percentile": chosen_percentile,
                    "threshold_value": chosen_threshold,
                    "training_subject_count": int(len(training_subjects)),
                    "training_task_count": int(len(TASK_SPECS)),
                    "effect_mean": float(np.mean(values)),
                    "effect_abs_mean": float(np.mean(np.abs(values))),
                    "effect_abs_p95": float(np.percentile(np.abs(values), 95)),
                    "effect_positive_fraction": float(np.mean(values > 0)),
                    "effect_negative_fraction": float(np.mean(values < 0)),
                    "voxel_count": int(values.size),
                }
            )

    return pd.DataFrame(rows)


def _build_wide_imaging_metrics(imaging_df: pd.DataFrame) -> pd.DataFrame:
    if imaging_df.empty:
        return pd.DataFrame(columns=MERGE_KEYS)

    rows: list[dict[str, Any]] = []
    for merge_key, frame in imaging_df.groupby(MERGE_KEYS, sort=True):
        row = dict(zip(MERGE_KEYS, merge_key, strict=True))
        for task, spec in TASK_SPECS.items():
            prefix = spec["prefix"]
            subset = frame.loc[frame["task"] == task]
            if subset.empty:
                continue
            if len(subset) != 1:
                raise RuntimeError(f"Expected one imaging row for {merge_key} {task}, found {len(subset)}")
            imaging_row = subset.iloc[0]
            row[f"imaging_{prefix}_effect_map_path"] = imaging_row["effect_map_path"]
            row[f"imaging_{prefix}_group_zmap_path"] = imaging_row["group_zmap_path"]
            row[f"imaging_{prefix}_voxel_count"] = imaging_row["voxel_count"]
            row[f"imaging_{prefix}_effect_mean"] = imaging_row["effect_mean"]
            row[f"imaging_{prefix}_effect_std"] = imaging_row["effect_std"]
            row[f"imaging_{prefix}_effect_abs_mean"] = imaging_row["effect_abs_mean"]
            row[f"imaging_{prefix}_effect_abs_p95"] = imaging_row["effect_abs_p95"]
            row[f"imaging_{prefix}_effect_positive_fraction"] = imaging_row["effect_positive_fraction"]
            row[f"imaging_{prefix}_effect_negative_fraction"] = imaging_row["effect_negative_fraction"]
            row[f"imaging_{prefix}_group_spatial_r"] = imaging_row["group_spatial_r"]
            row[f"imaging_{prefix}_loo_group_spatial_r"] = imaging_row["loo_group_spatial_r"]
        rows.append(row)

    wide_df = pd.DataFrame(rows)
    aggregate_columns = {
        "imaging_effect_abs_mean_mean": [
            f"imaging_{spec['prefix']}_effect_abs_mean" for spec in TASK_SPECS.values()
        ],
        "imaging_effect_abs_p95_mean": [
            f"imaging_{spec['prefix']}_effect_abs_p95" for spec in TASK_SPECS.values()
        ],
        "imaging_group_spatial_r_mean": [
            f"imaging_{spec['prefix']}_group_spatial_r" for spec in TASK_SPECS.values()
        ],
        "imaging_loo_group_spatial_r_mean": [
            f"imaging_{spec['prefix']}_loo_group_spatial_r" for spec in TASK_SPECS.values()
        ],
    }
    for new_column, source_columns in aggregate_columns.items():
        present_columns = [column for column in source_columns if column in wide_df.columns]
        if present_columns:
            wide_df[new_column] = wide_df[present_columns].mean(axis=1)
    return wide_df


def _build_wide_network_metrics(network_df: pd.DataFrame) -> pd.DataFrame:
    if network_df.empty:
        return pd.DataFrame(columns=MERGE_KEYS)

    rows: list[dict[str, Any]] = []
    for merge_key, frame in network_df.groupby(MERGE_KEYS, sort=True):
        row = dict(zip(MERGE_KEYS, merge_key, strict=True))
        for network_label in YEO7_NETWORK_LABELS.values():
            network_frame = frame.loc[frame["network_label"] == network_label]
            if network_frame.empty:
                continue
            row[f"imaging_yeo7_{network_label}_effect_mean_mean"] = float(
                network_frame["effect_mean"].mean()
            )
            row[f"imaging_yeo7_{network_label}_effect_abs_mean_mean"] = float(
                network_frame["effect_abs_mean"].mean()
            )
            row[f"imaging_yeo7_{network_label}_effect_abs_p95_mean"] = float(
                network_frame["effect_abs_p95"].mean()
            )

        for task, spec in TASK_SPECS.items():
            prefix = spec["prefix"]
            task_frame = frame.loc[frame["task"] == task]
            if task_frame.empty:
                continue
            for network_label in YEO7_NETWORK_LABELS.values():
                network_frame = task_frame.loc[task_frame["network_label"] == network_label]
                if network_frame.empty:
                    continue
                network_row = network_frame.iloc[0]
                row[f"imaging_{prefix}_yeo7_{network_label}_effect_mean"] = network_row["effect_mean"]
                row[f"imaging_{prefix}_yeo7_{network_label}_effect_abs_mean"] = network_row["effect_abs_mean"]
                row[f"imaging_{prefix}_yeo7_{network_label}_effect_abs_p95"] = network_row["effect_abs_p95"]
                row[f"imaging_{prefix}_yeo7_{network_label}_voxel_count"] = network_row["voxel_count"]
        rows.append(row)

    return pd.DataFrame(rows)


def _build_wide_md_metrics(md_df: pd.DataFrame) -> pd.DataFrame:
    if md_df.empty:
        return pd.DataFrame(columns=MERGE_KEYS)

    rows: list[dict[str, Any]] = []
    for merge_key, frame in md_df.groupby(MERGE_KEYS, sort=True):
        row = dict(zip(MERGE_KEYS, merge_key, strict=True))
        row["imaging_md_mask_label"] = str(frame["mask_label"].iloc[0])
        row["imaging_md_mask_method"] = str(frame["mask_method"].iloc[0])
        row["imaging_md_mask_path"] = str(frame["mask_path"].iloc[0])
        row["imaging_md_mask_voxel_count"] = int(frame["mask_voxel_count"].iloc[0])
        row["imaging_md_threshold_percentile"] = float(frame["threshold_percentile"].iloc[0])
        row["imaging_md_threshold_value"] = float(frame["threshold_value"].iloc[0])
        row["imaging_md_effect_mean_mean"] = float(frame["effect_mean"].mean())
        row["imaging_md_effect_abs_mean_mean"] = float(frame["effect_abs_mean"].mean())
        row["imaging_md_effect_abs_p95_mean"] = float(frame["effect_abs_p95"].mean())

        for task, spec in TASK_SPECS.items():
            prefix = spec["prefix"]
            task_frame = frame.loc[frame["task"] == task]
            if task_frame.empty:
                continue
            task_row = task_frame.iloc[0]
            row[f"imaging_{prefix}_md_effect_mean"] = task_row["effect_mean"]
            row[f"imaging_{prefix}_md_effect_abs_mean"] = task_row["effect_abs_mean"]
            row[f"imaging_{prefix}_md_effect_abs_p95"] = task_row["effect_abs_p95"]
            row[f"imaging_{prefix}_md_voxel_count"] = task_row["voxel_count"]
        rows.append(row)

    return pd.DataFrame(rows)


def _load_sem_factor_scores(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=MERGE_KEYS)
    df = pd.read_csv(path)
    factor_columns = [column for column in df.columns if column not in {*MERGE_KEYS, "input_row_index"}]
    if not factor_columns:
        return pd.DataFrame(columns=MERGE_KEYS)
    return df[MERGE_KEYS + factor_columns].copy()


def _build_correlation_rows(merged_df: pd.DataFrame, factor_columns: list[str]) -> pd.DataFrame:
    imaged_df = merged_df.loc[merged_df["imaging_task_count"].fillna(0) > 0].copy()
    if imaged_df.empty:
        return pd.DataFrame(
            columns=[
                "analysis_family",
                "left_variable",
                "right_variable",
                "n_complete",
                "pearson_r",
                "spearman_rho",
            ]
        )

    correlation_rows: list[dict[str, Any]] = []

    imaged_df["behavior_common_mean_v"] = imaged_df[BEHAVIOR_COLUMNS].mean(axis=1)

    for task, spec in TASK_SPECS.items():
        prefix = spec["prefix"]
        behavior_col = spec["behavior_col"]
        imaging_columns = [
            f"imaging_{prefix}_effect_abs_mean",
            f"imaging_{prefix}_effect_abs_p95",
            f"imaging_{prefix}_loo_group_spatial_r",
        ]
        for imaging_col in imaging_columns:
            if imaging_col not in imaged_df.columns:
                continue
            n_complete, pearson_r = _safe_corr(imaged_df[behavior_col], imaged_df[imaging_col], "pearson")
            _, spearman_rho = _safe_corr(imaged_df[behavior_col], imaged_df[imaging_col], "spearman")
            correlation_rows.append(
                {
                    "analysis_family": "task_matched",
                    "left_variable": behavior_col,
                    "right_variable": imaging_col,
                    "n_complete": n_complete,
                    "pearson_r": pearson_r,
                    "spearman_rho": spearman_rho,
                }
            )

    aggregate_pairs = [
        ("behavior_common_mean_v", "imaging_effect_abs_mean_mean"),
        ("behavior_common_mean_v", "imaging_effect_abs_p95_mean"),
        ("behavior_common_mean_v", "imaging_loo_group_spatial_r_mean"),
    ]
    for factor_column in factor_columns:
        aggregate_pairs.extend(
            [
                (factor_column, "imaging_effect_abs_mean_mean"),
                (factor_column, "imaging_effect_abs_p95_mean"),
                (factor_column, "imaging_loo_group_spatial_r_mean"),
            ]
        )

    for left_variable, right_variable in aggregate_pairs:
        if left_variable not in imaged_df.columns or right_variable not in imaged_df.columns:
            continue
        n_complete, pearson_r = _safe_corr(imaged_df[left_variable], imaged_df[right_variable], "pearson")
        _, spearman_rho = _safe_corr(imaged_df[left_variable], imaged_df[right_variable], "spearman")
        correlation_rows.append(
            {
                "analysis_family": "aggregate",
                "left_variable": left_variable,
                "right_variable": right_variable,
                "n_complete": n_complete,
                "pearson_r": pearson_r,
                "spearman_rho": spearman_rho,
            }
        )

    return pd.DataFrame(correlation_rows)


def _build_network_correlation_rows(
    merged_df: pd.DataFrame, factor_columns: list[str]
) -> pd.DataFrame:
    imaged_df = merged_df.loc[merged_df["imaging_task_count"].fillna(0) > 0].copy()
    if imaged_df.empty:
        return pd.DataFrame(
            columns=[
                "analysis_family",
                "left_variable",
                "right_variable",
                "n_complete",
                "pearson_r",
                "spearman_rho",
            ]
        )

    correlation_rows: list[dict[str, Any]] = []
    imaged_df["behavior_common_mean_v"] = imaged_df[BEHAVIOR_COLUMNS].mean(axis=1)

    for task, spec in TASK_SPECS.items():
        prefix = spec["prefix"]
        behavior_col = spec["behavior_col"]
        for network_label in YEO7_NETWORK_LABELS.values():
            imaging_columns = [
                f"imaging_{prefix}_yeo7_{network_label}_effect_mean",
                f"imaging_{prefix}_yeo7_{network_label}_effect_abs_mean",
            ]
            for imaging_col in imaging_columns:
                if imaging_col not in imaged_df.columns:
                    continue
                n_complete, pearson_r = _safe_corr(
                    imaged_df[behavior_col], imaged_df[imaging_col], "pearson"
                )
                _, spearman_rho = _safe_corr(
                    imaged_df[behavior_col], imaged_df[imaging_col], "spearman"
                )
                correlation_rows.append(
                    {
                        "analysis_family": "task_network",
                        "left_variable": behavior_col,
                        "right_variable": imaging_col,
                        "n_complete": n_complete,
                        "pearson_r": pearson_r,
                        "spearman_rho": spearman_rho,
                    }
                )

    aggregate_pairs = []
    for network_label in YEO7_NETWORK_LABELS.values():
        aggregate_pairs.extend(
            [
                ("behavior_common_mean_v", f"imaging_yeo7_{network_label}_effect_mean_mean"),
                ("behavior_common_mean_v", f"imaging_yeo7_{network_label}_effect_abs_mean_mean"),
            ]
        )
        for factor_column in factor_columns:
            aggregate_pairs.extend(
                [
                    (factor_column, f"imaging_yeo7_{network_label}_effect_mean_mean"),
                    (factor_column, f"imaging_yeo7_{network_label}_effect_abs_mean_mean"),
                ]
            )

    for left_variable, right_variable in aggregate_pairs:
        if left_variable not in imaged_df.columns or right_variable not in imaged_df.columns:
            continue
        n_complete, pearson_r = _safe_corr(
            imaged_df[left_variable], imaged_df[right_variable], "pearson"
        )
        _, spearman_rho = _safe_corr(
            imaged_df[left_variable], imaged_df[right_variable], "spearman"
        )
        correlation_rows.append(
            {
                "analysis_family": "aggregate_network",
                "left_variable": left_variable,
                "right_variable": right_variable,
                "n_complete": n_complete,
                "pearson_r": pearson_r,
                "spearman_rho": spearman_rho,
            }
        )

    return pd.DataFrame(correlation_rows)


def _build_md_correlation_rows(merged_df: pd.DataFrame, factor_columns: list[str]) -> pd.DataFrame:
    imaged_df = merged_df.loc[merged_df["imaging_task_count"].fillna(0) > 0].copy()
    if imaged_df.empty:
        return pd.DataFrame(
            columns=[
                "analysis_family",
                "left_variable",
                "right_variable",
                "n_complete",
                "pearson_r",
                "spearman_rho",
            ]
        )

    correlation_rows: list[dict[str, Any]] = []
    imaged_df["behavior_common_mean_v"] = imaged_df[BEHAVIOR_COLUMNS].mean(axis=1)

    for task, spec in TASK_SPECS.items():
        prefix = spec["prefix"]
        behavior_col = spec["behavior_col"]
        imaging_columns = [
            f"imaging_{prefix}_md_effect_mean",
            f"imaging_{prefix}_md_effect_abs_mean",
            f"imaging_{prefix}_md_effect_abs_p95",
        ]
        for imaging_col in imaging_columns:
            if imaging_col not in imaged_df.columns:
                continue
            n_complete, pearson_r = _safe_corr(
                imaged_df[behavior_col], imaged_df[imaging_col], "pearson"
            )
            _, spearman_rho = _safe_corr(
                imaged_df[behavior_col], imaged_df[imaging_col], "spearman"
            )
            correlation_rows.append(
                {
                    "analysis_family": "task_md_mask",
                    "left_variable": behavior_col,
                    "right_variable": imaging_col,
                    "n_complete": n_complete,
                    "pearson_r": pearson_r,
                    "spearman_rho": spearman_rho,
                }
            )

    aggregate_pairs = [
        ("behavior_common_mean_v", "imaging_md_effect_mean_mean"),
        ("behavior_common_mean_v", "imaging_md_effect_abs_mean_mean"),
        ("behavior_common_mean_v", "imaging_md_effect_abs_p95_mean"),
    ]
    for factor_column in factor_columns:
        aggregate_pairs.extend(
            [
                (factor_column, "imaging_md_effect_mean_mean"),
                (factor_column, "imaging_md_effect_abs_mean_mean"),
                (factor_column, "imaging_md_effect_abs_p95_mean"),
            ]
        )

    for left_variable, right_variable in aggregate_pairs:
        if left_variable not in imaged_df.columns or right_variable not in imaged_df.columns:
            continue
        n_complete, pearson_r = _safe_corr(
            imaged_df[left_variable], imaged_df[right_variable], "pearson"
        )
        _, spearman_rho = _safe_corr(
            imaged_df[left_variable], imaged_df[right_variable], "spearman"
        )
        correlation_rows.append(
            {
                "analysis_family": "aggregate_md_mask",
                "left_variable": left_variable,
                "right_variable": right_variable,
                "n_complete": n_complete,
                "pearson_r": pearson_r,
                "spearman_rho": spearman_rho,
            }
        )

    return pd.DataFrame(correlation_rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize corrected DMCC behavior-imaging bridge outputs."
    )
    parser.add_argument(
        "--bridge-csv",
        type=Path,
        default=DEFAULT_BRIDGE_CSV,
        help="Path to the corrected DMCC behavior-imaging bridge CSV.",
    )
    parser.add_argument(
        "--glm-root",
        type=Path,
        default=DEFAULT_GLM_ROOT,
        help="Path to the corrected DMCC GLM root with subject-level effect maps.",
    )
    parser.add_argument(
        "--sem-factor-scores-csv",
        type=Path,
        default=DEFAULT_SEM_FACTOR_SCORES_CSV,
        help="Optional SEM factor scores CSV to merge onto the bridge.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where behavior-imaging summary outputs will be written.",
    )
    parser.add_argument(
        "--summary-name",
        type=str,
        default=None,
        help="Optional output subdirectory name. Defaults to the GLM root name.",
    )
    args = parser.parse_args()

    bridge_csv = args.bridge_csv.expanduser().resolve()
    glm_root = args.glm_root.expanduser().resolve()
    sem_factor_scores_csv = args.sem_factor_scores_csv.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    summary_name = args.summary_name or glm_root.name
    summary_dir = output_root / summary_name
    summary_dir.mkdir(parents=True, exist_ok=True)

    if not bridge_csv.exists():
        raise FileNotFoundError(f"Bridge CSV not found: {bridge_csv}")
    if not glm_root.exists():
        raise FileNotFoundError(f"GLM root not found: {glm_root}")

    bridge_df = pd.read_csv(bridge_csv)
    imaging_df = _discover_subject_level_rows(glm_root, bridge_df)
    imaging_wide_df = _build_wide_imaging_metrics(imaging_df)
    network_df = _discover_network_level_rows(imaging_df)
    network_wide_df = _build_wide_network_metrics(network_df)
    md_mask_dir = summary_dir / "loo_md_masks"
    md_df = _discover_md_mask_rows(imaging_df, md_mask_dir)
    md_wide_df = _build_wide_md_metrics(md_df)
    md_mask_definitions_df = (
        md_df[
            [
                "dataset",
                "participant_id",
                "session_id",
                "mask_label",
                "mask_method",
                "mask_path",
                "mask_voxel_count",
                "threshold_percentile",
                "threshold_value",
                "training_subject_count",
                "training_task_count",
            ]
        ]
        .drop_duplicates()
        .reset_index(drop=True)
        if not md_df.empty
        else pd.DataFrame(
            columns=[
                "dataset",
                "participant_id",
                "session_id",
                "mask_label",
                "mask_method",
                "mask_path",
                "mask_voxel_count",
                "threshold_percentile",
                "threshold_value",
                "training_subject_count",
                "training_task_count",
            ]
        )
    )

    merged_df = bridge_df.merge(imaging_wide_df, on=MERGE_KEYS, how="left")
    merged_df = merged_df.merge(network_wide_df, on=MERGE_KEYS, how="left")
    merged_df = merged_df.merge(md_wide_df, on=MERGE_KEYS, how="left")
    merged_df["behavior_common_mean_v"] = merged_df[BEHAVIOR_COLUMNS].mean(axis=1)
    sem_df = _load_sem_factor_scores(sem_factor_scores_csv)
    factor_columns = [
        column for column in sem_df.columns if column not in MERGE_KEYS
    ]
    if not sem_df.empty:
        merged_df = merged_df.merge(sem_df, on=MERGE_KEYS, how="left")

    correlation_df = _build_correlation_rows(merged_df, factor_columns)
    network_correlation_df = _build_network_correlation_rows(merged_df, factor_columns)
    md_correlation_df = _build_md_correlation_rows(merged_df, factor_columns)

    imaging_long_path = summary_dir / "dmcc_behavior_imaging_subject_task_metrics.csv"
    network_long_path = summary_dir / "dmcc_behavior_imaging_subject_task_network_metrics.csv"
    md_long_path = summary_dir / "dmcc_behavior_imaging_subject_task_md_mask_metrics.csv"
    md_mask_definitions_path = summary_dir / "dmcc_behavior_imaging_md_mask_definitions.csv"
    imaging_wide_path = summary_dir / "dmcc_behavior_imaging_summary_bridge.csv"
    correlations_path = summary_dir / "behavior_imaging_correlations.csv"
    network_correlations_path = summary_dir / "behavior_imaging_network_correlations.csv"
    md_correlations_path = summary_dir / "behavior_imaging_md_mask_correlations.csv"
    imaged_subset_path = summary_dir / "imaged_subset_summary.csv"
    manifest_path = summary_dir / "manifest.json"
    summary_path = summary_dir / "summary.json"

    imaging_df.to_csv(imaging_long_path, index=False)
    network_df.to_csv(network_long_path, index=False)
    md_df.to_csv(md_long_path, index=False)
    md_mask_definitions_df.to_csv(md_mask_definitions_path, index=False)
    merged_df.to_csv(imaging_wide_path, index=False)
    correlation_df.to_csv(correlations_path, index=False)
    network_correlation_df.to_csv(network_correlations_path, index=False)
    md_correlation_df.to_csv(md_correlations_path, index=False)
    merged_df.loc[merged_df["imaging_task_count"].fillna(0) > 0].to_csv(
        imaged_subset_path, index=False
    )

    imaged_rows = merged_df.loc[merged_df["imaging_task_count"].fillna(0) > 0].copy()
    summary = {
        "bridge_csv": str(bridge_csv),
        "glm_root": str(glm_root),
        "sem_factor_scores_csv": str(sem_factor_scores_csv) if sem_factor_scores_csv.exists() else None,
        "n_bridge_rows": int(len(bridge_df)),
        "n_imaging_task_rows": int(len(imaging_df)),
        "n_network_rows": int(len(network_df)),
        "n_md_mask_rows": int(len(md_df)),
        "n_imaged_participant_sessions": int(len(imaged_rows)),
        "tasks_observed": sorted(imaging_df["task"].dropna().unique().tolist()) if not imaging_df.empty else [],
        "factor_columns_merged": factor_columns,
        "yeo7_networks": list(YEO7_NETWORK_LABELS.values()),
        "md_mask_label": MD_MASK_LABEL,
        "md_mask_method": MD_MASK_METHOD,
    }
    if not imaged_rows.empty:
        aggregate_snapshot = imaged_rows[
            [
                column
                for column in [
                    "behavior_common_mean_v",
                    "imaging_effect_abs_mean_mean",
                    "imaging_effect_abs_p95_mean",
                    "imaging_group_spatial_r_mean",
                    "imaging_loo_group_spatial_r_mean",
                    "imaging_yeo7_frontoparietal_effect_abs_mean_mean",
                    "imaging_yeo7_default_effect_abs_mean_mean",
                    "imaging_yeo7_dorsal_attention_effect_abs_mean_mean",
                    "imaging_md_effect_abs_mean_mean",
                    "imaging_md_mask_voxel_count",
                    "imaging_md_threshold_value",
                ]
                if column in imaged_rows.columns
            ]
        ].agg(["mean", "std"])
        summary["aggregate_snapshot"] = {
            key: _serialize_frame_dict(value.to_frame().T)
            for key, value in aggregate_snapshot.iterrows()
        }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    manifest = {
        "imaging_long_csv": str(imaging_long_path),
        "network_long_csv": str(network_long_path),
        "md_long_csv": str(md_long_path),
        "md_mask_definitions_csv": str(md_mask_definitions_path),
        "imaging_summary_bridge_csv": str(imaging_wide_path),
        "behavior_imaging_correlations_csv": str(correlations_path),
        "behavior_imaging_network_correlations_csv": str(network_correlations_path),
        "behavior_imaging_md_correlations_csv": str(md_correlations_path),
        "imaged_subset_summary_csv": str(imaged_subset_path),
        "summary_json": str(summary_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
