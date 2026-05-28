#!/usr/bin/env python3
"""Run first-level and optional second-level GLM on a DMCC raw subset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nilearn.image import index_img, resample_to_img  # noqa: E402

from brain_researcher.services.tools.params.nilearn_analysis import (  # noqa: E402
    GLMFirstLevelParameters,
    GLMSecondLevelParameters,
    run_glm_first_level,
    run_glm_second_level,
)


DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_bold_subset"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "dmcc_glm"
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


def _collect_bold_files(dataset_root: Path, task: str, max_subjects: int) -> list[Path]:
    files = sorted(
        dataset_root.glob(f"sub-*/ses-wave1bas/func/*task-{task}_*bold.nii.gz")
    )
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


def _subject_output_dir(output_root: Path, bold_path: Path) -> Path:
    subject = bold_path.parts[-4]
    session = bold_path.parts[-3]
    task_name = bold_path.name.split("_task-")[1].split("_")[0]
    run_name = bold_path.name.replace("_bold.nii.gz", "")
    return output_root / "first_level" / task_name / subject / session / run_name


def _prepare_group_maps(map_paths: list[str], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = Path(map_paths[0])
    reference_img = nib.load(str(reference_path))
    if len(reference_img.shape) == 4 and reference_img.shape[-1] == 1:
        reference_img = index_img(str(reference_path), 0)

    prepared: list[str] = []
    for idx, map_path in enumerate(map_paths):
        img = nib.load(map_path)
        out_path = output_dir / f"group_input_{idx:03d}.nii.gz"
        if len(img.shape) == 4 and img.shape[-1] == 1:
            img = index_img(map_path, 0)
        if img.shape != reference_img.shape or not np.allclose(
            img.affine, reference_img.affine
        ):
            img = resample_to_img(
                img,
                reference_img,
                interpolation="continuous",
                force_resample=True,
                copy_header=True,
            )
        nib.save(img, str(out_path))
        prepared.append(str(out_path))
    return prepared


def _assess_group_map_compatibility(
    map_paths: list[str], affine_atol: float = 1e-3
) -> dict[str, object]:
    if not map_paths:
        return {
            "compatible": False,
            "reason": "No contrast maps were provided.",
            "n_maps": 0,
        }

    reference_img = nib.load(map_paths[0])
    reference_shape = tuple(int(x) for x in reference_img.shape[:3])
    reference_affine = reference_img.affine
    origins: list[np.ndarray] = []
    incompatible_shapes: list[str] = []
    incompatible_affines: list[str] = []

    for map_path in map_paths:
        img = nib.load(map_path)
        origins.append(np.asarray(img.affine[:3, 3], dtype=float))
        if tuple(int(x) for x in img.shape[:3]) != reference_shape:
            incompatible_shapes.append(map_path)
        if not np.allclose(img.affine, reference_affine, atol=affine_atol):
            incompatible_affines.append(map_path)

    origin_stack = np.vstack(origins)
    origin_span = origin_stack.max(axis=0) - origin_stack.min(axis=0)
    compatible = not incompatible_shapes and not incompatible_affines
    reason = "All maps share a common shape and affine."
    if not compatible:
        reason = (
            "Input contrast maps do not share a common affine/grid. "
            "This usually means the maps are still in native subject space."
        )

    return {
        "compatible": compatible,
        "reason": reason,
        "n_maps": len(map_paths),
        "reference_shape": list(reference_shape),
        "origin_min_mm": origin_stack.min(axis=0).round(3).tolist(),
        "origin_max_mm": origin_stack.max(axis=0).round(3).tolist(),
        "origin_span_mm": origin_span.round(3).tolist(),
        "incompatible_shape_paths": incompatible_shapes,
        "incompatible_affine_paths": incompatible_affines,
    }


def _prepare_events_for_glm(events_path: Path, task: str, output_dir: Path) -> Path:
    events = pd.read_csv(events_path, sep="\t", na_values=["n/a", "NA"]).copy()
    output_dir.mkdir(parents=True, exist_ok=True)

    glm_mode = TASK_CONFIGS[task]["glm_mode"]
    prepared = events.copy()
    if glm_mode == "trial_switch":
        prepared["trial_type"] = prepared["trial_switch"].fillna("boundary")
    elif glm_mode == "trial_type":
        prepared["trial_type"] = prepared["trial_type"].astype(str)
    else:
        raise ValueError(f"Unsupported GLM mode for task {task}: {glm_mode}")

    keep_columns = [col for col in ("onset", "duration", "trial_type") if col in prepared.columns]
    prepared = prepared.loc[:, keep_columns]

    prepared_path = output_dir / f"{events_path.stem}_glm_events.tsv"
    prepared.to_csv(prepared_path, sep="\t", index=False)
    return prepared_path


def _bold_sidecar_path(bold_path: Path) -> Path:
    return bold_path.with_name(bold_path.name.replace("_bold.nii.gz", "_bold.json"))


def _events_path_for_bold(bold_path: Path) -> Path:
    return bold_path.with_name(bold_path.name.replace("_bold.nii.gz", "_events.tsv"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DMCC first-level and optional second-level GLM."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="Path to the DMCC raw subset root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for GLM outputs.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=None,
        help="Task(s) to process. Repeatable. Defaults to all DMCC tasks.",
    )
    parser.add_argument(
        "--max-subjects",
        type=int,
        default=1,
        help="Maximum number of participants per task to process.",
    )
    parser.add_argument(
        "--run-second-level",
        action="store_true",
        help="If set, run second-level intercept maps when at least two first-level maps exist.",
    )
    parser.add_argument(
        "--force-second-level-native-space",
        action="store_true",
        help=(
            "Allow second-level modeling even when first-level maps do not share a "
            "common affine/grid. This is only for rough debugging and should not be "
            "used for substantive group inference."
        ),
    )
    parser.add_argument(
        "--smoothing-fwhm",
        type=float,
        default=6.0,
        help="Smoothing kernel size in mm.",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    tasks = args.task or TASK_ORDER
    invalid_tasks = sorted(set(tasks) - set(TASK_ORDER))
    if invalid_tasks:
        raise ValueError(f"Unsupported DMCC tasks requested: {invalid_tasks}")

    manifest: dict[str, object] = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "tasks_requested": tasks,
        "max_subjects": int(args.max_subjects),
        "run_second_level": bool(args.run_second_level),
        "tasks": {},
    }

    for task in tasks:
        bold_files = _collect_bold_files(
            dataset_root=dataset_root, task=task, max_subjects=args.max_subjects
        )
        task_manifest: dict[str, object] = {
            "n_bold_files": len(bold_files),
            "contrast_name": TASK_CONFIGS[task]["contrast_name"],
            "contrast_expression": TASK_CONFIGS[task]["contrast_expression"],
            "first_level_runs": [],
            "group_result": None,
        }
        contrast_maps: list[str] = []

        for bold_path in bold_files:
            out_dir = _subject_output_dir(output_root, bold_path)
            events_path = _events_path_for_bold(bold_path)
            sidecar_path = _bold_sidecar_path(bold_path)
            if not events_path.exists():
                raise FileNotFoundError(f"Missing events file for {bold_path}: {events_path}")
            if not sidecar_path.exists():
                raise FileNotFoundError(f"Missing sidecar for {bold_path}: {sidecar_path}")

            prepared_events = _prepare_events_for_glm(events_path, task, out_dir)
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            contrast_name = TASK_CONFIGS[task]["contrast_name"]
            contrast_expression = TASK_CONFIGS[task]["contrast_expression"]

            params = GLMFirstLevelParameters(
                img=str(bold_path),
                events=str(prepared_events),
                output_dir=str(out_dir),
                t_r=sidecar.get("RepetitionTime"),
                hrf_model="spm",
                drift_model="cosine",
                high_pass=0.01,
                mask_img=None,
                smoothing_fwhm=args.smoothing_fwhm,
                standardize=True,
                noise_model="ar1",
                n_jobs=1,
                contrasts={contrast_name: contrast_expression},
            )
            result = run_glm_first_level(params)
            summary_path = Path(result["outputs"]["summary"])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary.update(
                {
                    "bold_path": str(bold_path),
                    "events_path": str(events_path),
                    "prepared_events_path": str(prepared_events),
                    "sidecar_path": str(sidecar_path),
                }
            )
            task_manifest["first_level_runs"].append(summary)

            candidate_map = out_dir / f"{contrast_name}_zmap.nii.gz"
            if candidate_map.exists():
                contrast_maps.append(str(candidate_map))

        compatibility = _assess_group_map_compatibility(contrast_maps)
        task_manifest["group_spatial_compatibility"] = compatibility

        if args.run_second_level and len(contrast_maps) >= 2:
            if (
                not bool(compatibility["compatible"])
                and not args.force_second_level_native_space
            ):
                task_manifest["group_result"] = None
                task_manifest["group_input_maps"] = contrast_maps
                task_manifest["group_skipped_reason"] = (
                    "Second-level modeling skipped because first-level maps do not "
                    "share a common affine/grid. Re-run with common-space "
                    "preprocessed inputs, or override with "
                    "--force-second-level-native-space for debugging only."
                )
                manifest["tasks"][task] = task_manifest
                continue
            group_output = (
                output_root / "second_level" / task / TASK_CONFIGS[task]["contrast_name"]
            )
            group_output.mkdir(parents=True, exist_ok=True)
            group_input_maps = _prepare_group_maps(contrast_maps, group_output / "harmonized")
            group_params = GLMSecondLevelParameters(
                contrast_maps=tuple(group_input_maps),
                output_dir=str(group_output),
                design_matrix=None,
                contrast="intercept",
                mask_img=None,
                smoothing_fwhm=args.smoothing_fwhm,
                model_type="ols",
            )
            task_manifest["group_result"] = run_glm_second_level(group_params)
            task_manifest["group_input_maps"] = group_input_maps
            if not bool(compatibility["compatible"]):
                task_manifest["group_warning"] = (
                    "Second-level model was forced on maps without a common "
                    "affine/grid. Interpret the resulting group map as debugging "
                    "output only."
                )
        else:
            task_manifest["group_input_maps"] = contrast_maps

        manifest["tasks"][task] = task_manifest

    manifest_path = output_root / "dmcc_glm_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
