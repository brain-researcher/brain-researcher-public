#!/usr/bin/env python3
"""Run a small Nilearn GLM pilot on OpenNeuro ds000114.

This is an infrastructure validation script, not a cognitive-control analysis.
It exercises the existing first- and second-level GLM helpers against a real
task fMRI dataset so the neuroimaging side of the cognitive-control pipeline
can be validated before HCP / ABCD / DMCC data are mounted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import nibabel as nib
import numpy as np

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


DEFAULT_DATASET_ROOT = Path("/app/data/openneuro/ds000114")
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "pilot_glm"
)


def _collect_bold_files(
    dataset_root: Path,
    task: str,
    max_subjects: int,
    include_retest: bool,
) -> list[Path]:
    session_glob = "*" if include_retest else "ses-test"
    files = sorted(
        dataset_root.glob(f"sub-*/{session_glob}/func/*task-{task}_bold.nii.gz")
    )
    if include_retest:
        return files[: max_subjects * 2]
    return files[:max_subjects]


def _subject_output_dir(output_root: Path, bold_path: Path) -> Path:
    subject = bold_path.parts[-4]
    session = bold_path.parts[-3]
    task_name = bold_path.name.split("_task-")[1].split("_bold")[0]
    return output_root / "first_level" / task_name / subject / session


def _prepare_group_maps(map_paths: list[str], output_dir: Path) -> list[str]:
    """Coerce maps to a shared 3D field of view for second-level GLM."""
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
            img = resample_to_img(img, reference_img, interpolation="continuous")
        nib.save(img, str(out_path))
        prepared.append(str(out_path))
    return prepared


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pilot first- and second-level GLM on OpenNeuro ds000114."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="Path to the OpenNeuro ds000114 root.",
    )
    parser.add_argument(
        "--task",
        default="fingerfootlips",
        help="Task name without the task- prefix.",
    )
    parser.add_argument(
        "--contrast-name",
        default="Finger",
        help="First-level contrast map basename to carry into group analysis.",
    )
    parser.add_argument(
        "--max-subjects",
        type=int,
        default=4,
        help="Maximum number of subject sessions to process.",
    )
    parser.add_argument(
        "--include-retest",
        action="store_true",
        help="If set, include ses-retest files as additional sessions.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for pilot outputs.",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    events_file = dataset_root / f"task-{args.task}_events.tsv"
    if not events_file.exists():
        raise FileNotFoundError(f"Events file not found: {events_file}")

    bold_files = _collect_bold_files(
        dataset_root=dataset_root,
        task=args.task,
        max_subjects=args.max_subjects,
        include_retest=args.include_retest,
    )
    if not bold_files:
        raise RuntimeError(
            f"No BOLD files found for task '{args.task}' under {dataset_root}"
        )

    first_level_summaries: list[dict[str, object]] = []
    contrast_maps: list[str] = []

    for bold_path in bold_files:
        out_dir = _subject_output_dir(output_root, bold_path)
        params = GLMFirstLevelParameters(
            img=str(bold_path),
            events=str(events_file),
            output_dir=str(out_dir),
            t_r=None,
            hrf_model="spm",
            drift_model="cosine",
            high_pass=0.01,
            mask_img=None,
            smoothing_fwhm=6.0,
            standardize=True,
            noise_model="ar1",
            n_jobs=1,
            contrasts=None,
        )
        result = run_glm_first_level(params)
        summary_path = Path(result["outputs"]["summary"])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["bold_path"] = str(bold_path)
        first_level_summaries.append(summary)

        candidate_map = out_dir / f"{args.contrast_name}_zmap.nii.gz"
        if candidate_map.exists():
            contrast_maps.append(str(candidate_map))

    if not contrast_maps:
        raise RuntimeError(
            f"No contrast maps named '{args.contrast_name}_zmap.nii.gz' were produced. "
            "Check the design columns in the first-level summaries."
        )

    group_output = output_root / "second_level" / args.task / args.contrast_name
    group_output.mkdir(parents=True, exist_ok=True)
    group_input_maps = _prepare_group_maps(contrast_maps, group_output / "harmonized")
    group_params = GLMSecondLevelParameters(
        contrast_maps=tuple(group_input_maps),
        output_dir=str(group_output),
        design_matrix=None,
        contrast="intercept",
        mask_img=None,
        smoothing_fwhm=6.0,
        model_type="ols",
    )
    group_result = run_glm_second_level(group_params)

    manifest = {
        "dataset_root": str(dataset_root),
        "task": args.task,
        "contrast_name": args.contrast_name,
        "events_file": str(events_file),
        "n_first_level_runs": len(first_level_summaries),
        "n_group_maps": len(group_input_maps),
        "group_input_maps": group_input_maps,
        "first_level_summaries": first_level_summaries,
        "group_result": group_result,
        "note": (
            "This pilot validates the Nilearn GLM plumbing only. "
            "It must not be interpreted as a cognitive-control result."
        ),
    }
    manifest_path = output_root / "pilot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
