#!/usr/bin/env python3
"""Screen DMCC participants for next-wave raw download and preprocessing.

This script combines local task metadata completeness with raw OpenNeuro object
availability so we can select the next batch of DMCC subjects that actually
have:

1. all four task-fMRI tasks represented locally, and
2. T1w plus task BOLD NIfTIs available on S3, and
3. not already processed in the current fMRIPrep derivatives tree.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SELECTOR_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "downloads"
    / "dmcc_behavior_only"
)
DEFAULT_PROCESSED_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "fmriprep_fast4"
    / "derivatives"
    / "fmriprep"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "dmcc_subject_screening"
)
TASK_ORDER = ["Axcpt", "Cuedts", "Stern", "Stroop"]
S3_ROOT = "s3://openneuro.org/ds003465"


def _list_processed_subjects(processed_root: Path) -> set[str]:
    return {path.name for path in processed_root.glob("sub-*") if path.is_dir()}


def _scan_local_subject(selector_root: Path, participant_id: str) -> dict[str, Any]:
    func_dir = selector_root / participant_id / "ses-wave1bas" / "func"
    row: dict[str, Any] = {"participant_id": participant_id}

    tasks_complete = True
    for task in TASK_ORDER:
        n_bold_json = len(list(func_dir.glob(f"*task-{task}_*bold.json")))
        n_events = len(list(func_dir.glob(f"*task-{task}_*events.tsv")))
        row[f"local_{task.lower()}_bold_json_count"] = n_bold_json
        row[f"local_{task.lower()}_events_count"] = n_events
        tasks_complete = tasks_complete and n_bold_json >= 2 and n_events >= 2

    row["local_tasks_complete"] = tasks_complete
    return row


def _ls_s3(prefix: str) -> tuple[int, list[str], str]:
    aws = shutil.which("aws")
    if aws is None:
        raise RuntimeError("aws CLI is required to verify DMCC raw S3 objects.")

    proc = subprocess.run(
        [aws, "s3", "ls", "--no-sign-request", prefix],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.splitlines(), proc.stderr.strip()


def _verify_s3_subject(participant_id: str) -> dict[str, Any]:
    anat_prefix = f"{S3_ROOT}/{participant_id}/ses-wave1bas/anat/"
    func_prefix = f"{S3_ROOT}/{participant_id}/ses-wave1bas/func/"

    anat_rc, anat_lines, anat_stderr = _ls_s3(anat_prefix)
    func_rc, func_lines, func_stderr = _ls_s3(func_prefix)

    row: dict[str, Any] = {
        "participant_id": participant_id,
        "s3_anat_prefix_ok": anat_rc == 0,
        "s3_func_prefix_ok": func_rc == 0,
        "s3_anat_stderr": anat_stderr,
        "s3_func_stderr": func_stderr,
        "s3_t1w_json_exists": any(line.rstrip().endswith("_T1w.json") for line in anat_lines),
        "s3_t1w_nifti_exists": any(
            line.rstrip().endswith("_T1w.nii.gz") for line in anat_lines
        ),
        "s3_bold_nifti_count": sum(
            line.rstrip().endswith("_bold.nii.gz") for line in func_lines
        ),
    }

    func_names = [line.split()[-1] for line in func_lines if line.strip()]
    for task in TASK_ORDER:
        task_count = sum(
            f"task-{task}_" in name and name.endswith("_bold.nii.gz")
            for name in func_names
        )
        row[f"s3_{task.lower()}_bold_nifti_count"] = task_count

    row["s3_tasks_complete"] = all(
        row[f"s3_{task.lower()}_bold_nifti_count"] >= 2 for task in TASK_ORDER
    )
    row["s3_ready"] = row["s3_t1w_nifti_exists"] and row["s3_tasks_complete"]
    return row


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Screen DMCC subjects for local 4-task completeness and raw S3 "
            "T1w/BOLD availability."
        )
    )
    parser.add_argument(
        "--selector-root",
        type=Path,
        default=DEFAULT_SELECTOR_ROOT,
        help="Local DMCC metadata/events root used to assess task completeness.",
    )
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
        help="Existing fMRIPrep derivatives root used to exclude processed subjects.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for screening tables and summary files.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="Parallel S3 verification workers.",
    )
    parser.add_argument(
        "--next-batch-size",
        type=int,
        default=8,
        help="Number of sorted candidates to mark as the recommended next batch.",
    )
    parser.add_argument(
        "--verify-s3",
        action="store_true",
        help="Verify T1w and BOLD raw object availability from OpenNeuro S3.",
    )
    args = parser.parse_args()

    selector_root = args.selector_root.expanduser().resolve()
    processed_root = args.processed_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    processed = _list_processed_subjects(processed_root)
    local_rows = [
        _scan_local_subject(selector_root=selector_root, participant_id=sub_dir.name)
        for sub_dir in sorted(selector_root.glob("sub-*"))
        if sub_dir.is_dir()
    ]

    for row in local_rows:
        row["already_processed"] = row["participant_id"] in processed

    eligible_local_ids = [
        row["participant_id"]
        for row in local_rows
        if row["local_tasks_complete"] and not row["already_processed"]
    ]

    s3_rows_by_subject: dict[str, dict[str, Any]] = {}
    if args.verify_s3 and eligible_local_ids:
        with ThreadPoolExecutor(max_workers=max(args.jobs, 1)) as pool:
            for s3_row in pool.map(_verify_s3_subject, eligible_local_ids):
                s3_rows_by_subject[s3_row["participant_id"]] = s3_row

    combined_rows: list[dict[str, Any]] = []
    for row in local_rows:
        combined = dict(row)
        s3_row = s3_rows_by_subject.get(row["participant_id"])
        if s3_row is None:
            combined["s3_ready"] = None
        else:
            combined.update(s3_row)
        combined["ready_for_next_batch"] = bool(
            combined["local_tasks_complete"]
            and not combined["already_processed"]
            and combined.get("s3_ready", False)
        )
        combined_rows.append(combined)

    next_batch = [
        row["participant_id"]
        for row in combined_rows
        if row["ready_for_next_batch"]
    ][: args.next_batch_size]

    summary = {
        "selector_root": str(selector_root),
        "processed_root": str(processed_root),
        "n_subjects_total": len(combined_rows),
        "n_already_processed": sum(row["already_processed"] for row in combined_rows),
        "n_local_tasks_complete": sum(
            row["local_tasks_complete"] for row in combined_rows
        ),
        "n_s3_ready": sum(bool(row.get("s3_ready")) for row in combined_rows),
        "n_ready_for_next_batch": sum(
            row["ready_for_next_batch"] for row in combined_rows
        ),
        "next_batch_size": args.next_batch_size,
        "next_batch_participants": next_batch,
        "excluded_due_to_missing_s3_t1w": [
            row["participant_id"]
            for row in combined_rows
            if row["local_tasks_complete"]
            and not row["already_processed"]
            and row.get("s3_ready") is False
            and not row.get("s3_t1w_nifti_exists", False)
        ],
    }

    csv_path = output_root / "dmcc_subject_screening.csv"
    summary_path = output_root / "summary.json"
    next_batch_path = output_root / "next_batch.txt"

    _write_csv(combined_rows, csv_path)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    next_batch_path.write_text("\n".join(next_batch) + ("\n" if next_batch else ""), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "csv": str(csv_path),
                "summary": str(summary_path),
                "next_batch": next_batch,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
