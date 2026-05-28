#!/usr/bin/env python3
"""Run a constrained DMCC fMRIPrep preprocessing job for a small subject subset.

This script is intentionally conservative about speed-vs-validity tradeoffs:

- it uses a small participant subset,
- limits output spaces to MNI 2 mm plus T1w,
- disables FreeSurfer surface reconstruction with ``--fs-no-reconall``,
- skips full BIDS validation for already-curated local subsets, and
- avoids ``--sloppy`` unless explicitly requested.

The default runtime is Docker because the repo's default Neurodesk SIF path is
not mounted in this environment.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.services.tools.pipelines.params import (
    FMRIPrepParameters,
    build_fmriprep_command,
)

UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_bold_subset"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "fmriprep_fast4"
)
DEFAULT_IMAGE = "nipreps/fmriprep:23.2.3"
DEFAULT_OUTPUT_SPACES = ("MNI152NLin2009cAsym:res-2", "T1w")
DEFAULT_PARTICIPANTS = ("sub-f1027ao", "sub-f1031ax", "sub-f1550bc", "sub-f1552xo")


def _strip_sub_prefix(participant_id: str) -> str:
    return participant_id[4:] if participant_id.startswith("sub-") else participant_id


def _default_fs_license() -> Path | None:
    candidates = [
        os.environ.get("FS_LICENSE"),
        str(Path.home() / ".freesurfer_license.txt"),
        str(Path.home() / ".freesurfer" / "license.txt"),
        "/opt/freesurfer/license.txt",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate).expanduser().resolve()
    return None


def _select_participants(
    dataset_root: Path,
    participant_ids: list[str] | None,
    max_subjects: int,
) -> list[str]:
    if participant_ids:
        return sorted(dict.fromkeys(participant_ids))

    participants = sorted(p.name for p in dataset_root.glob("sub-*") if p.is_dir())
    if not participants:
        raise RuntimeError(f"No DMCC participant folders found under {dataset_root}")
    return participants[:max_subjects]


def _validate_t1w_inputs(dataset_root: Path, participants: list[str]) -> None:
    missing: list[str] = []
    for participant_id in participants:
        anat_dir = dataset_root / participant_id / "ses-wave1bas" / "anat"
        nii = list(anat_dir.glob("*_T1w.nii.gz"))
        js = list(anat_dir.glob("*_T1w.json"))
        if not nii or not js:
            missing.append(participant_id)
    if missing:
        raise RuntimeError(
            "Missing T1w anatomy for selected participants. Re-run "
            "download_dmcc_bold_subset.py with --include-t1w. Missing: "
            + ", ".join(missing)
        )


def _ensure_docker_image(image: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker is required for this fast DMCC fMRIPrep path.")
    inspect = subprocess.run(
        [docker, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspect.returncode == 0:
        return
    subprocess.run([docker, "pull", image], check=True)


def _build_docker_command(
    params: FMRIPrepParameters,
    *,
    image: str,
    templateflow_dir: Path,
) -> list[str]:
    container_params = FMRIPrepParameters(
        bids_dir="/data",
        output_dir="/out",
        analysis_level=params.analysis_level,
        participant_label=tuple(_strip_sub_prefix(p) for p in params.participant_label),
        work_dir="/work" if params.work_dir else None,
        fs_license_file=(
            "/opt/freesurfer/license.txt" if params.fs_license_file else None
        ),
        output_spaces=params.output_spaces,
        skip_bids_validation=params.skip_bids_validation,
        use_aroma=params.use_aroma,
        cifti_output=params.cifti_output,
        n_cpus=params.n_cpus,
        omp_nthreads=params.omp_nthreads,
        mem_mb=params.mem_mb,
        low_mem=params.low_mem,
        stop_on_first_crash=params.stop_on_first_crash,
        notrack=params.notrack,
        longitudinal=params.longitudinal,
        bids_filter_file="/bids_filter.json" if params.bids_filter_file else None,
        verbose=params.verbose,
        skull_strip_t1w=params.skull_strip_t1w,
        skull_strip_fixed_seed=params.skull_strip_fixed_seed,
        bold2t1w_init=params.bold2t1w_init,
        bold2t1w_dof=params.bold2t1w_dof,
        fd_spike_threshold=params.fd_spike_threshold,
        dvars_spike_threshold=params.dvars_spike_threshold,
        me_output_echos=params.me_output_echos,
        medial_surface_nan=params.medial_surface_nan,
        dummy_scans=params.dummy_scans,
        use_syn_sdc=params.use_syn_sdc,
        force_syn=params.force_syn,
        extra_args=params.extra_args,
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{params.bids_dir}:/data:ro",
        "-v",
        f"{params.output_dir}:/out:rw",
        "-v",
        f"{params.work_dir}:/work:rw",
        "-v",
        f"{params.fs_license_file}:/opt/freesurfer/license.txt:ro",
        "-v",
        f"{templateflow_dir}:/templateflow:rw",
        "-e",
        "FS_LICENSE=/opt/freesurfer/license.txt",
        "-e",
        "TEMPLATEFLOW_HOME=/templateflow",
        image,
        "/data",
        "/out",
        params.analysis_level,
    ]
    container_cmd = container_params.command(include_executable=False)
    # Skip positional args already added above: bids_dir, output_dir, analysis_level.
    cmd.extend(container_cmd[3:])
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a small-subset DMCC fMRIPrep job with speed-conscious defaults."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="Raw DMCC BIDS subset with both func and anat inputs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where fMRIPrep derivatives and manifests will be written.",
    )
    parser.add_argument(
        "--participant-id",
        action="append",
        default=None,
        help="Explicit participant IDs to process. Repeatable.",
    )
    parser.add_argument(
        "--max-subjects",
        type=int,
        default=len(DEFAULT_PARTICIPANTS),
        help="If participant IDs are not given, preprocess the first N sorted subjects.",
    )
    parser.add_argument(
        "--fs-license-file",
        type=Path,
        default=_default_fs_license(),
        help="Path to a valid FreeSurfer license file.",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=DEFAULT_IMAGE,
        help="Docker image tag for fMRIPrep.",
    )
    parser.add_argument(
        "--n-cpus",
        type=int,
        default=16,
        help="Total CPUs for fMRIPrep.",
    )
    parser.add_argument(
        "--omp-nthreads",
        type=int,
        default=8,
        help="OpenMP threads for fMRIPrep.",
    )
    parser.add_argument(
        "--mem-mb",
        type=int,
        default=64000,
        help="Memory budget in MB.",
    )
    parser.add_argument(
        "--sloppy",
        action="store_true",
        help="Enable fMRIPrep --sloppy. Use only for smoke tests.",
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Do not pull the Docker image if it is missing locally.",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    deriv_root = output_root / "derivatives" / "fmriprep"
    work_dir = output_root / "work"
    templateflow_dir = output_root / "templateflow"
    manifest_path = output_root / "fmriprep_fast_manifest.json"
    output_root.mkdir(parents=True, exist_ok=True)
    deriv_root.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    templateflow_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    fs_license_file = (
        args.fs_license_file.expanduser().resolve() if args.fs_license_file else None
    )
    if fs_license_file is None or not fs_license_file.exists():
        raise FileNotFoundError(
            "A valid FreeSurfer license file is required for fMRIPrep."
        )

    participants = _select_participants(
        dataset_root=dataset_root,
        participant_ids=args.participant_id,
        max_subjects=args.max_subjects,
    )
    _validate_t1w_inputs(dataset_root, participants)

    if not args.no_pull:
        _ensure_docker_image(args.image)

    extra_args: list[str] = ["--fs-no-reconall"]
    if args.sloppy:
        extra_args.append("--sloppy")

    participant_labels = tuple(_strip_sub_prefix(p) for p in participants)
    params = FMRIPrepParameters(
        bids_dir=str(dataset_root),
        output_dir=str(deriv_root),
        participant_label=participant_labels,
        work_dir=str(work_dir),
        fs_license_file=str(fs_license_file),
        output_spaces=DEFAULT_OUTPUT_SPACES,
        skip_bids_validation=True,
        n_cpus=args.n_cpus,
        omp_nthreads=args.omp_nthreads,
        mem_mb=args.mem_mb,
        stop_on_first_crash=True,
        notrack=True,
        extra_args=tuple(extra_args),
    )
    command_host = build_fmriprep_command(params)
    command_container = _build_docker_command(
        params,
        image=args.image,
        templateflow_dir=templateflow_dir,
    )

    manifest = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "derivatives_root": str(deriv_root),
        "work_dir": str(work_dir),
        "templateflow_dir": str(templateflow_dir),
        "participants": participants,
        "docker_image": args.image,
        "sloppy": bool(args.sloppy),
        "command_host": command_host,
        "command_container": command_container,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "starting", "manifest": str(manifest_path)}, indent=2))
    subprocess.run(command_container, check=True)
    manifest["status"] = "completed"
    manifest["completed_at_utc"] = datetime.now(tz=UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
