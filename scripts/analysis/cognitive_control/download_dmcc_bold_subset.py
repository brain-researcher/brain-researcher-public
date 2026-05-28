#!/usr/bin/env python3
"""Download a selective DMCC raw subset from OpenNeuro.

This script keeps the DMCC task-fMRI path lightweight by downloading only the
participants, tasks, and file types needed for GLM validation or follow-on
preprocessing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import openneuro


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SELECTOR_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_behavior_only"
)
DEFAULT_TARGET_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_bold_subset"
)
DMCC_TAG = "1.0.7"
TASK_ORDER = ["Axcpt", "Cuedts", "Stern", "Stroop"]
S3_ROOT = "s3://openneuro.org/ds003465"


def _select_participants(
    selector_root: Path,
    participant_ids: list[str] | None,
    max_subjects: int,
) -> list[str]:
    if participant_ids:
        return sorted(dict.fromkeys(participant_ids))

    participants = sorted(p.name for p in selector_root.glob("sub-*") if p.is_dir())
    if not participants:
        raise RuntimeError(
            f"No participant directories found under selector root: {selector_root}"
        )
    return participants[:max_subjects]


def _collect_bold_relpaths(
    selector_root: Path,
    participants: list[str],
    tasks: list[str],
) -> list[str]:
    relpaths: list[str] = []
    for participant_id in participants:
        func_dir = selector_root / participant_id / "ses-wave1bas" / "func"
        if not func_dir.exists():
            continue
        for task in tasks:
            for sidecar_path in sorted(func_dir.glob(f"*task-{task}_*bold.json")):
                bold_relpath = sidecar_path.relative_to(selector_root).as_posix().replace(
                    "_bold.json", "_bold.nii.gz"
                )
                relpaths.append(bold_relpath)
    return relpaths


def _collect_t1w_relpaths(
    selector_root: Path,
    participants: list[str],
) -> list[str]:
    relpaths: list[str] = []
    for participant_id in participants:
        anat_dir = selector_root / participant_id / "ses-wave1bas" / "anat"
        if not anat_dir.exists():
            continue
        for t1w_json in sorted(anat_dir.glob("*_T1w.json")):
            relpaths.append(
                t1w_json.relative_to(selector_root).as_posix().replace(
                    "_T1w.json", "_T1w.nii.gz"
                )
            )
    return relpaths


def _download_s3_file(s3_relpath: str, target_root: Path) -> Path:
    aws = shutil.which("aws")
    if aws is None:
        raise RuntimeError(
            "aws CLI is required for direct DMCC BOLD downloads but was not found in PATH."
        )

    destination = target_root / s3_relpath
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == 0:
        destination.unlink()

    source = f"{S3_ROOT}/{s3_relpath}"
    subprocess.run(
        [aws, "s3", "cp", "--no-sign-request", source, str(destination)],
        check=True,
    )

    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError(f"Downloaded DMCC BOLD file is missing or empty: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a selective DMCC raw BOLD subset from OpenNeuro."
    )
    parser.add_argument(
        "--selector-root",
        type=Path,
        default=DEFAULT_SELECTOR_ROOT,
        help="Local DMCC metadata/events root used to choose participant IDs.",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=DEFAULT_TARGET_ROOT,
        help="Output directory for the raw BOLD subset.",
    )
    parser.add_argument(
        "--max-subjects",
        type=int,
        default=1,
        help="Number of sorted participants to download if --participant-id is not provided.",
    )
    parser.add_argument(
        "--participant-id",
        action="append",
        default=None,
        help="Explicit participant ID(s) such as sub-f1027ao. Repeatable.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=None,
        help="Task(s) to download. Repeatable. Defaults to all four DMCC tasks.",
    )
    parser.add_argument(
        "--max-concurrent-downloads",
        type=int,
        default=4,
        help="Maximum number of concurrent file downloads.",
    )
    parser.add_argument(
        "--include-t1w",
        action="store_true",
        help="Also download T1w anatomical NIfTIs and JSON sidecars for selected subjects.",
    )
    args = parser.parse_args()

    selector_root = args.selector_root.expanduser().resolve()
    target_root = args.target_root.expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    tasks = args.task or TASK_ORDER
    invalid_tasks = sorted(set(tasks) - set(TASK_ORDER))
    if invalid_tasks:
        raise ValueError(f"Unsupported DMCC tasks requested: {invalid_tasks}")

    participants = _select_participants(
        selector_root=selector_root,
        participant_ids=args.participant_id,
        max_subjects=args.max_subjects,
    )

    include = [
        "dataset_description.json",
        "participants.tsv",
        "participants.json",
        "README",
        "CHANGES",
        "task-*_events.json",
    ]
    for participant_id in participants:
        for task in tasks:
            include.extend(
                [
                    f"{participant_id}/ses-wave1bas/func/*task-{task}_*bold.json",
                    f"{participant_id}/ses-wave1bas/func/*task-{task}_*events.tsv",
                ]
            )
        if args.include_t1w:
            include.extend(
                [
                    f"{participant_id}/ses-wave1bas/anat/*_T1w.json",
                ]
            )

    openneuro.download(
        dataset="ds003465",
        tag=DMCC_TAG,
        target_dir=target_root,
        include=include,
        verify_hash=False,
        verify_size=True,
        max_concurrent_downloads=args.max_concurrent_downloads,
    )

    bold_relpaths = _collect_bold_relpaths(
        selector_root=selector_root,
        participants=participants,
        tasks=tasks,
    )
    bold_outputs = [
        str(_download_s3_file(s3_relpath=relpath, target_root=target_root))
        for relpath in bold_relpaths
    ]
    t1w_relpaths: list[str] = []
    t1w_outputs: list[str] = []
    if args.include_t1w:
        t1w_relpaths = _collect_t1w_relpaths(
            selector_root=selector_root,
            participants=participants,
        )
        t1w_outputs = [
            str(_download_s3_file(s3_relpath=relpath, target_root=target_root))
            for relpath in t1w_relpaths
        ]

    manifest = {
        "dataset": "ds003465",
        "tag": DMCC_TAG,
        "selector_root": str(selector_root),
        "target_root": str(target_root),
        "participants": participants,
        "tasks": tasks,
        "include_t1w": bool(args.include_t1w),
        "include": include,
        "bold_relpaths": bold_relpaths,
        "bold_outputs": bold_outputs,
        "t1w_relpaths": t1w_relpaths,
        "t1w_outputs": t1w_outputs,
    }
    manifest_path = target_root / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
