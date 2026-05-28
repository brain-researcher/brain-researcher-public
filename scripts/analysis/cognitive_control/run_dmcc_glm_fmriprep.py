#!/usr/bin/env python3
"""Run DMCC GLMs from common-space fMRIPrep outputs with confounds.

This script fixes the major flaw in the raw-space pilot pipeline: it only builds
task-level group maps from subject maps that are already in a shared template
space. It also uses confound regressors extracted from fMRIPrep derivatives.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn.glm.first_level import FirstLevelModel
from nilearn.glm.second_level import SecondLevelModel
from nilearn.image import mean_img

UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BIDS_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_bold_subset"
)
DEFAULT_FMRIPREP_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "fmriprep_fast4"
    / "derivatives"
    / "fmriprep"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "dmcc_glm_fmriprep"
)
TASK_ORDER = ["Axcpt", "Cuedts", "Stern", "Stroop"]
TASK_CONFIGS = {
    "Axcpt": {
        "contrast_name": "axcpt_control",
        "contrast_expression": "BX - BY",
        "glm_mode": "trial_type",
    },
    "Cuedts": {
        "contrast_name": "taskswitch_control",
        "contrast_expression": "switch - repeat",
        "glm_mode": "trial_switch",
    },
    "Stern": {
        "contrast_name": "sternberg_control",
        "contrast_expression": "RN - NN",
        "glm_mode": "trial_type",
    },
    "Stroop": {
        "contrast_name": "stroop_control",
        "contrast_expression": "InCon - Con",
        "glm_mode": "trial_type",
    },
}
MOTION_BASES = (
    "trans_x",
    "trans_y",
    "trans_z",
    "rot_x",
    "rot_y",
    "rot_z",
)


def _collect_preproc_bold_files(
    fmriprep_root: Path,
    task: str,
    max_subjects: int,
    space: str,
    resolution: str,
) -> list[Path]:
    pattern = (
        f"sub-*/ses-wave1bas/func/*task-{task}_*space-{space}_res-{resolution}_"
        "desc-preproc_bold.nii.gz"
    )
    files = sorted(fmriprep_root.glob(pattern))
    participants_seen: list[str] = []
    selected: list[Path] = []
    for path in files:
        participant = path.parts[-4]
        if participant not in participants_seen:
            if len(participants_seen) >= max_subjects:
                break
            participants_seen.append(participant)
        if participant in participants_seen:
            selected.append(path)
    return selected


def _prepare_events(events_path: Path, task: str, output_dir: Path) -> Path:
    events = pd.read_csv(events_path, sep="\t", na_values=["n/a", "NA"]).copy()
    output_dir.mkdir(parents=True, exist_ok=True)
    glm_mode = TASK_CONFIGS[task]["glm_mode"]
    if glm_mode == "trial_switch":
        events["trial_type"] = events["trial_switch"].fillna("boundary")
    elif glm_mode == "trial_type":
        events["trial_type"] = events["trial_type"].astype(str)
    else:
        raise ValueError(f"Unsupported GLM mode for task {task}: {glm_mode}")
    prepared = events.loc[
        :, [col for col in ("onset", "duration", "trial_type") if col in events.columns]
    ]
    prepared_path = output_dir / f"{events_path.stem}_glm_events.tsv"
    prepared.to_csv(prepared_path, sep="\t", index=False)
    return prepared_path


def _raw_events_for_preproc(bids_root: Path, preproc_bold: Path) -> Path:
    participant = preproc_bold.parts[-4]
    session = preproc_bold.parts[-3]
    func_dir = bids_root / participant / session / "func"
    prefix = preproc_bold.name.split("_space-")[0]
    events_path = func_dir / f"{prefix}_events.tsv"
    if not events_path.exists():
        raise FileNotFoundError(
            f"Missing raw events file for {preproc_bold}: {events_path}"
        )
    return events_path


def _confounds_for_preproc(preproc_bold: Path) -> Path:
    func_dir = preproc_bold.parent
    prefix = preproc_bold.name.split("_space-")[0]
    candidates = sorted(func_dir.glob(f"{prefix}*_desc-confounds_timeseries.tsv"))
    if not candidates:
        raise FileNotFoundError(f"Missing confounds TSV for {preproc_bold}")
    return candidates[0]


def _mask_for_preproc(preproc_bold: Path) -> Path | None:
    func_dir = preproc_bold.parent
    prefix = preproc_bold.name.split("_space-")[0]
    space_chunk = preproc_bold.name.split(prefix, 1)[1].split(
        "_desc-preproc_bold.nii.gz"
    )[0]
    candidate = func_dir / f"{prefix}{space_chunk}_desc-brain_mask.nii.gz"
    return candidate if candidate.exists() else None


def _select_confound_columns(df: pd.DataFrame) -> list[str]:
    selected: list[str] = []
    for base in MOTION_BASES:
        for suffix in ("", "_derivative1", "_power2", "_derivative1_power2"):
            column = f"{base}{suffix}"
            if column in df.columns:
                selected.append(column)
    acompcor = [col for col in df.columns if col.startswith("a_comp_cor")]
    selected.extend(acompcor[:6])
    selected.extend(col for col in df.columns if col.startswith("cosine"))
    selected.extend(
        col for col in df.columns if col.startswith("non_steady_state_outlier")
    )
    # Preserve order while removing duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for column in selected:
        if column in seen:
            continue
        seen.add(column)
        deduped.append(column)
    return deduped


def _prepare_confounds(
    confounds_path: Path, output_dir: Path
) -> tuple[Path, list[str]]:
    df = pd.read_csv(confounds_path, sep="\t", na_values=["n/a", "NA"])
    columns = _select_confound_columns(df)
    if not columns:
        raise RuntimeError(f"No usable confound columns found in {confounds_path}")
    prepared = df.loc[:, columns].fillna(0.0)
    prepared_path = output_dir / f"{confounds_path.stem}_selected_confounds.tsv"
    prepared.to_csv(prepared_path, sep="\t", index=False)
    return prepared_path, columns


def _subject_output_dir(output_root: Path, task: str, preproc_bold: Path) -> Path:
    participant = preproc_bold.parts[-4]
    session = preproc_bold.parts[-3]
    run_name = preproc_bold.name.replace("_desc-preproc_bold.nii.gz", "")
    return output_root / "first_level" / task / participant / session / run_name


def _subject_level_output_dir(
    output_root: Path, task: str, participant: str, session: str
) -> Path:
    return output_root / "subject_level" / task / participant / session


def _compute_first_level(
    preproc_bold: Path,
    task: str,
    bids_root: Path,
    output_root: Path,
    smoothing_fwhm: float,
) -> dict[str, object]:
    out_dir = _subject_output_dir(output_root, task, preproc_bold)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = _raw_events_for_preproc(bids_root, preproc_bold)
    prepared_events = _prepare_events(events_path, task, out_dir)
    confounds_path = _confounds_for_preproc(preproc_bold)
    prepared_confounds, confound_columns = _prepare_confounds(confounds_path, out_dir)
    mask_img = _mask_for_preproc(preproc_bold)

    img = nib.load(str(preproc_bold))
    zooms = img.header.get_zooms()
    t_r = float(zooms[3]) if len(zooms) >= 4 else 1.2
    events = pd.read_csv(prepared_events, sep="\t")
    confounds = pd.read_csv(prepared_confounds, sep="\t")

    model = FirstLevelModel(
        t_r=t_r,
        hrf_model="spm",
        drift_model="cosine",
        high_pass=0.01,
        mask_img=str(mask_img) if mask_img else None,
        smoothing_fwhm=smoothing_fwhm,
        standardize=True,
        noise_model="ar1",
        n_jobs=1,
    ).fit(str(preproc_bold), events=events, confounds=confounds)

    contrast_name = TASK_CONFIGS[task]["contrast_name"]
    contrast_expr = TASK_CONFIGS[task]["contrast_expression"]
    z_map = model.compute_contrast(contrast_expr, output_type="z_score")
    effect_map = model.compute_contrast(contrast_expr, output_type="effect_size")
    zmap_path = out_dir / f"{contrast_name}_zmap.nii.gz"
    effect_path = out_dir / f"{contrast_name}_effect_size.nii.gz"
    z_map.to_filename(zmap_path)
    effect_map.to_filename(effect_path)

    summary = {
        "task": task,
        "contrast_name": contrast_name,
        "contrast_expression": contrast_expr,
        "preproc_bold": str(preproc_bold),
        "events_path": str(events_path),
        "prepared_events_path": str(prepared_events),
        "confounds_path": str(confounds_path),
        "prepared_confounds_path": str(prepared_confounds),
        "selected_confounds": confound_columns,
        "mask_img": str(mask_img) if mask_img else None,
        "n_scans": int(model.design_matrices_[0].shape[0]),
        "design_columns": list(model.design_matrices_[0].columns),
        "effect_size_map": str(effect_path),
        "zmap": str(zmap_path),
    }
    summary_path = out_dir / "glm_first_level_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _mean_maps(map_paths: list[str], output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mean_img(map_paths, copy_header=True).to_filename(output_path)
    return str(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DMCC GLMs from common-space fMRIPrep outputs."
    )
    parser.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS_ROOT)
    parser.add_argument("--fmriprep-root", type=Path, default=DEFAULT_FMRIPREP_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--task", action="append", default=None)
    parser.add_argument("--max-subjects", type=int, default=4)
    parser.add_argument("--space", type=str, default="MNI152NLin2009cAsym")
    parser.add_argument("--resolution", type=str, default="2")
    parser.add_argument("--smoothing-fwhm", type=float, default=6.0)
    args = parser.parse_args()

    bids_root = args.bids_root.expanduser().resolve()
    fmriprep_root = args.fmriprep_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    tasks = args.task or TASK_ORDER
    invalid = sorted(set(tasks) - set(TASK_ORDER))
    if invalid:
        raise ValueError(f"Unsupported DMCC tasks requested: {invalid}")

    manifest: dict[str, object] = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "bids_root": str(bids_root),
        "fmriprep_root": str(fmriprep_root),
        "output_root": str(output_root),
        "tasks_requested": tasks,
        "space": args.space,
        "resolution": args.resolution,
        "tasks": {},
    }

    for task in tasks:
        preproc_bolds = _collect_preproc_bold_files(
            fmriprep_root=fmriprep_root,
            task=task,
            max_subjects=args.max_subjects,
            space=args.space,
            resolution=args.resolution,
        )
        task_manifest: dict[str, object] = {
            "n_preproc_bolds": len(preproc_bolds),
            "first_level_runs": [],
            "subject_level_maps": [],
            "group_result": None,
        }

        run_summaries: list[dict[str, object]] = []
        for preproc_bold in preproc_bolds:
            run_summaries.append(
                _compute_first_level(
                    preproc_bold=preproc_bold,
                    task=task,
                    bids_root=bids_root,
                    output_root=output_root,
                    smoothing_fwhm=args.smoothing_fwhm,
                )
            )
        task_manifest["first_level_runs"] = run_summaries

        subject_groups: dict[tuple[str, str], list[str]] = {}
        for summary in run_summaries:
            preproc_bold = Path(str(summary["preproc_bold"]))
            participant = preproc_bold.parts[-4]
            session = preproc_bold.parts[-3]
            subject_groups.setdefault((participant, session), []).append(
                str(summary["effect_size_map"])
            )

        subject_effect_maps: list[str] = []
        for (participant, session), maps in sorted(subject_groups.items()):
            subject_dir = _subject_level_output_dir(
                output_root, task, participant, session
            )
            effect_path = (
                subject_dir
                / f"{TASK_CONFIGS[task]['contrast_name']}_effect_size_mean.nii.gz"
            )
            subject_effect_maps.append(_mean_maps(maps, effect_path))
            task_manifest["subject_level_maps"].append(
                {
                    "participant_id": participant,
                    "session_id": session,
                    "run_count": len(maps),
                    "effect_size_map": str(effect_path),
                    "source_run_maps": maps,
                }
            )

        if subject_effect_maps:
            group_output = (
                output_root
                / "second_level"
                / task
                / TASK_CONFIGS[task]["contrast_name"]
            )
            group_output.mkdir(parents=True, exist_ok=True)
            design_matrix = pd.DataFrame(
                {"intercept": np.ones(len(subject_effect_maps))}
            )
            model = SecondLevelModel(
                smoothing_fwhm=args.smoothing_fwhm,
            ).fit(subject_effect_maps, design_matrix=design_matrix)
            z_map = model.compute_contrast("intercept", output_type="z_score")
            zmap_path = group_output / "group_zmap.nii.gz"
            z_map.to_filename(zmap_path)
            summary = {
                "n_subject_maps": len(subject_effect_maps),
                "contrast_name": TASK_CONFIGS[task]["contrast_name"],
                "contrast_expression": TASK_CONFIGS[task]["contrast_expression"],
                "subject_effect_maps": subject_effect_maps,
                "design_columns": ["intercept"],
                "group_zmap": str(zmap_path),
            }
            summary_path = group_output / "glm_second_level_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            task_manifest["group_result"] = summary

        manifest["tasks"][task] = task_manifest

    manifest_path = output_root / "dmcc_glm_fmriprep_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
