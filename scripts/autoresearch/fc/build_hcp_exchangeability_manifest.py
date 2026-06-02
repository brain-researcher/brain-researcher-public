#!/usr/bin/env python3
"""Build an HCP family exchangeability manifest for Liu-component analyses.

The manifest aligns ConnectomeDB family metadata to the recovered 326-subject
pyspi order used by the frozen Liu-component benchmark. It also audits whether
the existing CV folds split families across train/test, because restricted
permutation cannot by itself repair family leakage in the fold design.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_PROJECT = Path("/data/brain_researcher/research/predictive/project")
DEFAULT_BEHAVIOR = Path(
    "/data/brain_researcher/research/predictive/inputs/hcp_behavior/"
    "HCP_YA_subjects_2026_03_31_18_06_54.csv"
)
DEFAULT_SUBJECT_ORDER = Path(
    "/data/brain_researcher/research/predictive/inputs/hcp_behavior/"
    "subjects_reinder326_recovered.txt"
)


def _read_subject_order(path: Path) -> list[str]:
    subjects = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return [str(int(float(subject))) if subject.replace(".", "", 1).isdigit() else subject for subject in subjects]


def _json_default(obj: Any) -> Any:
    try:
        import numpy as np

        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
    except Exception:
        pass
    return str(obj)


def build_manifest(
    *,
    behavior_csv: Path,
    subject_order_path: Path,
    fold_manifest_path: Path,
) -> dict[str, Any]:
    subject_order = _read_subject_order(subject_order_path)
    df = pd.read_csv(
        behavior_csv,
        dtype={
            "Subject": str,
            "Family_ID": str,
            "Mother_ID": str,
            "Father_ID": str,
            "ZygositySR": str,
            "ZygosityGT": str,
        },
    )
    df["Subject"] = df["Subject"].astype(str)
    by_subject = df.set_index("Subject", drop=False)
    missing = [subject for subject in subject_order if subject not in by_subject.index]
    if missing:
        raise ValueError(f"{len(missing)} subjects missing from behavior CSV: {missing[:10]}")

    subjects: list[dict[str, Any]] = []
    family_blocks: dict[str, list[int]] = defaultdict(list)
    for idx, subject_id in enumerate(subject_order):
        row = by_subject.loc[subject_id]
        family_id = str(row.get("Family_ID", "")).strip()
        if not family_id or family_id.lower() == "nan":
            family_id = f"singleton_subject_{subject_id}"
        family_blocks[family_id].append(idx)
        subjects.append(
            {
                "index": idx,
                "subject_id": subject_id,
                "family_id": family_id,
                "mother_id": None
                if pd.isna(row.get("Mother_ID"))
                else str(row.get("Mother_ID")),
                "father_id": None
                if pd.isna(row.get("Father_ID"))
                else str(row.get("Father_ID")),
                "zygosity_sr": None
                if pd.isna(row.get("ZygositySR"))
                else str(row.get("ZygositySR")),
                "zygosity_gt": None
                if pd.isna(row.get("ZygosityGT"))
                else str(row.get("ZygosityGT")),
            }
        )

    fold_payload = json.loads(fold_manifest_path.read_text())
    family_by_index = {subject["index"]: subject["family_id"] for subject in subjects}
    fold_audit = []
    for fold in fold_payload["folds"]:
        train = set(map(int, fold["train_indices"]))
        test = set(map(int, fold["test_indices"]))
        train_families = {family_by_index[idx] for idx in train}
        test_families = {family_by_index[idx] for idx in test}
        split_family_ids = sorted(train_families & test_families)
        test_with_family_in_train = [
            idx for idx in sorted(test) if family_by_index[idx] in train_families
        ]
        train_with_family_in_test = [
            idx for idx in sorted(train) if family_by_index[idx] in test_families
        ]
        fold_audit.append(
            {
                "fold_id": int(fold.get("fold_id", len(fold_audit) + 1)),
                "n_train": len(train),
                "n_test": len(test),
                "n_train_families": len(train_families),
                "n_test_families": len(test_families),
                "n_split_families": len(split_family_ids),
                "split_family_ids": split_family_ids,
                "n_test_subjects_with_family_in_train": len(test_with_family_in_train),
                "test_subject_indices_with_family_in_train": test_with_family_in_train,
                "n_train_subjects_with_family_in_test": len(train_with_family_in_test),
            }
        )

    size_hist = Counter(len(indices) for indices in family_blocks.values())
    return {
        "schema_version": "hcp_exchangeability_manifest_v1",
        "behavior_csv": str(behavior_csv),
        "subject_order_path": str(subject_order_path),
        "fold_manifest_path": str(fold_manifest_path),
        "n_subjects": len(subjects),
        "n_families": len(family_blocks),
        "columns_used": [
            "Subject",
            "Family_ID",
            "Mother_ID",
            "Father_ID",
            "ZygositySR",
            "ZygosityGT",
        ],
        "exchangeability_policy": {
            "name": "family_block_same_size_within_training_fold",
            "description": (
                "For each training fold and permutation seed, shuffle the full "
                "five-component target matrix at the Family_ID block level among "
                "blocks of the same within-training-fold size. Test labels are "
                "not permuted."
            ),
        },
        "family_size_histogram": {
            str(size): int(count) for size, count in sorted(size_hist.items())
        },
        "subjects": subjects,
        "family_blocks": {fam: idxs for fam, idxs in sorted(family_blocks.items())},
        "fold_family_leakage_audit": fold_audit,
        "global_fold_leakage_summary": {
            "max_split_families_per_fold": max(
                audit["n_split_families"] for audit in fold_audit
            ),
            "total_fold_split_family_instances": sum(
                audit["n_split_families"] for audit in fold_audit
            ),
            "total_test_subject_family_leakage_instances": sum(
                audit["n_test_subjects_with_family_in_train"] for audit in fold_audit
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--behavior-csv", type=Path, default=DEFAULT_BEHAVIOR)
    parser.add_argument("--subject-order", type=Path, default=DEFAULT_SUBJECT_ORDER)
    parser.add_argument(
        "--fold-manifest",
        type=Path,
        default=DEFAULT_PROJECT / "manifests" / "fold_manifest.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PROJECT / "manifests" / "hcp_exchangeability_manifest.json",
    )
    args = parser.parse_args()

    manifest = build_manifest(
        behavior_csv=args.behavior_csv,
        subject_order_path=args.subject_order,
        fold_manifest_path=args.fold_manifest,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, default=_json_default) + "\n")
    print(json.dumps(manifest["global_fold_leakage_summary"], indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
