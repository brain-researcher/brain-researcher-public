#!/usr/bin/env python3
"""Build a DMCC behavior-imaging bridge table for unity-vs-diversity analyses.

The bridge is intentionally pragmatic:

- it reads an existing harmonized behavioral table,
- discovers first-level DMCC GLM run outputs under a GLM root,
- aggregates run-level summaries to participant/session/task rows,
- merges those task-level imaging summaries back onto the behavior table, and
- writes both a wide bridge CSV and a JSON manifest.

The wide bridge table is the primary artifact. It keeps one row per
participant/session from the behavior table and appends task-specific imaging
columns such as run counts, n_scans summaries, contrast names, and z-map paths.
An auxiliary long task-level table is also written to make downstream inspection
and debugging straightforward.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BEHAVIOR_CSV = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "harmonized_behavior"
    / "dmcc_behavior_only"
    / "behavior_harmonized.csv"
)
DEFAULT_GLM_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "dmcc_glm_subject1_all_tasks"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "behavior_imaging_bridge"
)
FIRST_LEVEL_MARKER = "first_level"
MERGE_KEYS = ["dataset", "participant_id", "session_id"]
TASK_ORDER = ["Axcpt", "Cuedts", "Stern", "Stroop"]
GLM_MANIFEST_FILENAMES = ("dmcc_glm_manifest.json", "dmcc_glm_fmriprep_manifest.json")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _flatten_list(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _parse_bids_run_context(path: Path) -> dict[str, str]:
    parts = path.parts
    if FIRST_LEVEL_MARKER not in parts:
        raise ValueError(f"Path does not look like a first-level DMCC output: {path}")
    idx = parts.index(FIRST_LEVEL_MARKER)
    try:
        task = parts[idx + 1]
        participant_id = parts[idx + 2]
        session_id = parts[idx + 3]
        run_dir = parts[idx + 4]
    except IndexError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unexpected DMCC GLM path layout: {path}") from exc
    return {
        "task": task,
        "participant_id": participant_id,
        "session_id": session_id,
        "run_dir": run_dir,
    }


def _discover_glm_manifest_path(glm_root: Path) -> Path | None:
    for filename in GLM_MANIFEST_FILENAMES:
        candidate = glm_root / filename
        if candidate.exists():
            return candidate
    return None


def _discover_glm_manifest(glm_root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    manifest_path = _discover_glm_manifest_path(glm_root)
    if manifest_path is None:
        return None, None
    return manifest_path, _read_json(manifest_path)


def _discover_first_level_records(glm_root: Path) -> list[dict[str, Any]]:
    summary_paths = sorted(glm_root.rglob("glm_first_level_summary.json"))
    records: list[dict[str, Any]] = []
    for summary_path in summary_paths:
        summary = _read_json(summary_path)
        context = _parse_bids_run_context(summary_path)
        run_dir = summary_path.parent
        zmap_paths = sorted(run_dir.glob("*_zmap.nii.gz"))
        contrast_names = list(summary.get("contrasts") or [])
        primary_contrast_name = None
        if zmap_paths:
            primary_contrast_name = zmap_paths[0].name.replace("_zmap.nii.gz", "")
        elif contrast_names:
            primary_contrast_name = str(contrast_names[0])

        record = {
            "dataset": "dmcc",
            "task": context["task"],
            "participant_id": context["participant_id"],
            "session_id": context["session_id"],
            "run_dir": str(run_dir),
            "run_name": context["run_dir"],
            "summary_path": str(summary_path),
            "zmap_paths": [str(path) for path in zmap_paths],
            "primary_zmap_path": str(zmap_paths[0]) if zmap_paths else None,
            "contrast_names": contrast_names,
            "primary_contrast_name": primary_contrast_name,
            "n_scans": summary.get("n_scans"),
            "hrf_model": summary.get("hrf_model"),
            "noise_model": summary.get("noise_model"),
            "design_columns": summary.get("design_columns") or [],
            "used_nilearn_package": summary.get("used_nilearn_package"),
        }
        records.append(record)
    return records


def _aggregate_task_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=[
                "dataset",
                "participant_id",
                "session_id",
                "task",
                "run_count",
                "n_scans_total",
                "n_scans_mean",
                "n_scans_min",
                "n_scans_max",
                "contrast_names_json",
                "primary_contrast_name",
                "zmap_paths_json",
                "summary_paths_json",
                "run_dirs_json",
                "run_names_json",
            ]
        )

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[
            (
                str(record["dataset"]),
                str(record["participant_id"]),
                str(record["session_id"]),
                str(record["task"]),
            )
        ].append(record)

    rows: list[dict[str, Any]] = []
    for (dataset, participant_id, session_id, task), task_records in sorted(
        grouped.items()
    ):
        scan_values = [
            int(record["n_scans"])
            for record in task_records
            if record.get("n_scans") is not None and pd.notna(record.get("n_scans"))
        ]
        contrast_names = _flatten_list(
            [
                contrast
                for record in task_records
                for contrast in (record.get("contrast_names") or [])
                if contrast is not None
            ]
        )
        primary_contrast_candidates = [
            record.get("primary_contrast_name")
            for record in task_records
            if record.get("primary_contrast_name")
        ]
        primary_contrast_name = None
        if len(set(primary_contrast_candidates)) == 1:
            primary_contrast_name = primary_contrast_candidates[0]
        elif primary_contrast_candidates:
            primary_contrast_name = sorted(
                {str(value) for value in primary_contrast_candidates}
            )[0]

        rows.append(
            {
                "dataset": dataset,
                "participant_id": participant_id,
                "session_id": session_id,
                "task": task,
                "run_count": len(task_records),
                "n_scans_total": int(sum(scan_values)) if scan_values else None,
                "n_scans_mean": (
                    float(sum(scan_values) / len(scan_values)) if scan_values else None
                ),
                "n_scans_min": int(min(scan_values)) if scan_values else None,
                "n_scans_max": int(max(scan_values)) if scan_values else None,
                "contrast_name_count": len(contrast_names),
                "contrast_names_json": _json_dumps(contrast_names),
                "primary_contrast_name": primary_contrast_name,
                "zmap_paths_json": _json_dumps(
                    _flatten_list(
                        [
                            zmap
                            for record in task_records
                            for zmap in (record.get("zmap_paths") or [])
                            if zmap is not None
                        ]
                    )
                ),
                "summary_paths_json": _json_dumps(
                    [record["summary_path"] for record in task_records]
                ),
                "run_dirs_json": _json_dumps(
                    [record["run_dir"] for record in task_records]
                ),
                "run_names_json": _json_dumps(
                    [record["run_name"] for record in task_records]
                ),
            }
        )

    return pd.DataFrame(rows)


def _task_prefix(task: str) -> str:
    return f"imaging_{task.lower()}"


def _pivot_task_rows(task_rows: pd.DataFrame) -> pd.DataFrame:
    if task_rows.empty:
        return task_rows

    metric_columns = [
        "run_count",
        "n_scans_total",
        "n_scans_mean",
        "n_scans_min",
        "n_scans_max",
        "contrast_name_count",
        "primary_contrast_name",
        "contrast_names_json",
        "zmap_paths_json",
        "summary_paths_json",
        "run_dirs_json",
        "run_names_json",
    ]
    pivoted = task_rows.loc[:, MERGE_KEYS + ["task"] + metric_columns].copy()
    for metric in metric_columns:
        pivoted[f"{_task_prefix('placeholder')}_{metric}"] = None  # overwritten below
    pivoted = pivoted.drop(
        columns=[f"{_task_prefix('placeholder')}_{metric}" for metric in metric_columns]
    )

    prefixed_frames: list[pd.DataFrame] = []
    for task in TASK_ORDER:
        subset = task_rows.loc[
            task_rows["task"] == task, MERGE_KEYS + metric_columns
        ].copy()
        if subset.empty:
            continue
        rename_map = {
            metric: f"{_task_prefix(task)}_{metric}" for metric in metric_columns
        }
        subset = subset.rename(columns=rename_map)
        prefixed_frames.append(subset)

    if not prefixed_frames:
        return task_rows.loc[:, MERGE_KEYS].drop_duplicates().copy()

    merged = prefixed_frames[0]
    for frame in prefixed_frames[1:]:
        merged = merged.merge(frame, on=MERGE_KEYS, how="outer")
    return merged


def _build_wide_bridge(
    behavior_df: pd.DataFrame, task_rows: pd.DataFrame
) -> pd.DataFrame:
    wide = behavior_df.copy()
    if task_rows.empty:
        wide["imaging_task_count"] = 0
        wide["imaging_run_count_total"] = 0
        wide["imaging_tasks_available_json"] = "[]"
        return wide

    task_wide = _pivot_task_rows(task_rows)
    wide = wide.merge(task_wide, on=MERGE_KEYS, how="left")

    run_count_columns = [
        column
        for column in wide.columns
        if column.startswith("imaging_") and column.endswith("_run_count")
    ]
    task_available_columns = [
        column for column in run_count_columns if column != "imaging_run_count_total"
    ]
    wide["imaging_task_count"] = (
        wide[task_available_columns].fillna(0).astype(float).gt(0).sum(axis=1)
        if task_available_columns
        else 0
    )
    wide["imaging_run_count_total"] = (
        wide[task_available_columns].fillna(0).astype(float).sum(axis=1)
        if task_available_columns
        else 0
    )
    wide["imaging_tasks_available_json"] = wide.apply(
        lambda row: _json_dumps(
            [
                task
                for task in TASK_ORDER
                if pd.notna(row.get(f"{_task_prefix(task)}_run_count"))
                and float(row.get(f"{_task_prefix(task)}_run_count") or 0.0) > 0
            ]
        ),
        axis=1,
    )
    return wide


def _validate_behavior_table(behavior_df: pd.DataFrame) -> None:
    missing = [column for column in MERGE_KEYS if column not in behavior_df.columns]
    if missing:
        raise ValueError(f"Behavior table is missing required columns: {missing}")
    duplicate_mask = behavior_df.duplicated(subset=MERGE_KEYS, keep=False)
    if duplicate_mask.any():
        dupes = behavior_df.loc[duplicate_mask, MERGE_KEYS]
        raise ValueError(
            "Behavior table must be unique by participant/session. "
            f"Duplicate rows:\n{dupes.to_string(index=False)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a DMCC behavior-imaging bridge table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--behavior-csv",
        type=Path,
        default=DEFAULT_BEHAVIOR_CSV,
        help="Harmonized DMCC behavior table to join against.",
    )
    parser.add_argument(
        "--glm-root",
        type=Path,
        default=DEFAULT_GLM_ROOT,
        help="Root of a DMCC GLM output tree.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where the bridge outputs will be written.",
    )
    parser.add_argument(
        "--bridge-name",
        type=str,
        default=None,
        help="Optional output folder/file name. Defaults to the GLM root name.",
    )
    args = parser.parse_args()

    behavior_csv = args.behavior_csv.expanduser().resolve()
    glm_root = args.glm_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()

    if not behavior_csv.exists():
        raise FileNotFoundError(f"Behavior CSV not found: {behavior_csv}")
    if not glm_root.exists():
        raise FileNotFoundError(f"GLM root not found: {glm_root}")

    behavior_df = pd.read_csv(behavior_csv)
    _validate_behavior_table(behavior_df)

    glm_manifest_path, glm_manifest = _discover_glm_manifest(glm_root)
    records = _discover_first_level_records(glm_root)
    if not records:
        raise RuntimeError(f"No first-level summaries discovered under {glm_root}")

    task_rows = _aggregate_task_records(records)
    bridge_df = _build_wide_bridge(behavior_df, task_rows)

    bridge_name = args.bridge_name or glm_root.name
    bridge_dir = output_root / bridge_name
    bridge_dir.mkdir(parents=True, exist_ok=True)

    bridge_csv_path = bridge_dir / "dmcc_behavior_imaging_bridge.csv"
    task_csv_path = bridge_dir / "dmcc_behavior_imaging_bridge_task_level.csv"
    manifest_path = bridge_dir / "manifest.json"

    bridge_df.to_csv(bridge_csv_path, index=False)
    task_rows.to_csv(task_csv_path, index=False)

    task_summaries: dict[str, dict[str, Any]] = {}
    for task in (
        sorted(task_rows["task"].dropna().unique().tolist())
        if not task_rows.empty
        else []
    ):
        subset = task_rows.loc[task_rows["task"] == task].copy()
        task_summaries[task] = {
            "participant_session_rows": int(len(subset)),
            "run_count_total": (
                int(subset["run_count"].sum()) if not subset.empty else 0
            ),
            "contrast_names": sorted(
                {
                    name
                    for cell in subset["contrast_names_json"].dropna().astype(str)
                    for name in json.loads(cell)
                }
            ),
            "n_scans_total": (
                int(subset["n_scans_total"].dropna().sum())
                if subset["n_scans_total"].notna().any()
                else None
            ),
            "zmap_paths": [
                path
                for cell in subset["zmap_paths_json"].dropna().astype(str)
                for path in json.loads(cell)
            ],
        }

    manifest = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "behavior_csv": str(behavior_csv),
        "glm_root": str(glm_root),
        "glm_manifest_path": (
            str(glm_manifest_path) if glm_manifest_path is not None else None
        ),
        "glm_manifest_present": glm_manifest is not None,
        "output_root": str(output_root),
        "bridge_dir": str(bridge_dir),
        "bridge_csv": str(bridge_csv_path),
        "task_level_csv": str(task_csv_path),
        "behavior_rows": int(len(behavior_df)),
        "bridge_rows": int(len(bridge_df)),
        "task_level_rows": int(len(task_rows)),
        "glm_first_level_summary_count": int(len(records)),
        "tasks_observed": (
            sorted(task_rows["task"].dropna().unique().tolist())
            if not task_rows.empty
            else []
        ),
        "task_summaries": task_summaries,
    }
    if glm_manifest is not None:
        manifest["glm_manifest"] = {
            "tasks_requested": glm_manifest.get("tasks_requested"),
            "run_second_level": glm_manifest.get("run_second_level"),
            "max_subjects": glm_manifest.get("max_subjects"),
        }

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "bridge_csv": str(bridge_csv_path),
                "manifest": str(manifest_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
