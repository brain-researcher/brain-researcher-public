#!/usr/bin/env python3
"""Build a human-reviewable decision pack from the dataset task review pack.

This script is intentionally conservative. It does NOT auto-apply mappings; it
only produces a TSV with suggested actions so a reviewer can decide what to
change in configs (synonyms/blacklist/keyword rules).

Inputs:
  - artifacts/dataset_task_review/review_pack.tsv (from build_dataset_task_review_pack.py)

Outputs:
  - artifacts/dataset_task_review/decision_pack.tsv
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReviewRow:
    dataset_id: str
    dataset_name: str
    source_repo: str
    normalized_task: str
    raw_examples: str
    count_in_dataset: int
    total_count: int
    other_tasks_in_dataset: str
    task_json_summary: str


_BLOCK_RE = re.compile(r"\bblock\s*\d+\b", flags=re.IGNORECASE)


def _suggest_action(normalized: str) -> tuple[str, str, str]:
    """Return (suggested_action, suggested_canonical, rationale)."""
    value = (normalized or "").strip().lower()
    if not value:
        return ("keep_unmatched", "", "empty token")

    if value == "change point helicopter fmri":
        return (
            "map",
            "predictive-inference helicopter task",
            "KG contains canonical 'predictive-inference helicopter task' (MEASURES); token looks like an alias.",
        )

    if _BLOCK_RE.search(value):
        return (
            "keep_unmatched_phase_label",
            "",
            "Looks like a phase/block label; avoid polluting KG without explicit evidence it is a reusable task concept.",
        )

    if value in {"repmem1", "repmem2b", "cmiyc"}:
        return (
            "keep_unmatched_shortcode",
            "",
            "Dataset-specific short code; requires dataset context/README to map safely.",
        )

    if value in {"modulate"}:
        return (
            "keep_unmatched_generic",
            "",
            "Too generic without dataset context; mapping risks false positives.",
        )

    if value == "eyemag":
        return (
            "review_map_candidate",
            "Eye Gaze Processing Task",
            "Appears to be eye-tracking related in review pack; verify before mapping.",
        )

    if "imagery of facial expressions" in value:
        return (
            "review_map_candidate",
            "Neurofeedback Paradigm",
            "Neurofeedback/control-run phrasing; verify whether this should map to neurofeedback vs a face/emotion task.",
        )

    return ("keep_unmatched", "", "insufficient evidence for mapping/blacklisting")


def _load_review_pack(path: Path) -> list[ReviewRow]:
    if not path.exists():
        raise FileNotFoundError(path)

    rows: list[ReviewRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for raw in reader:
            rows.append(
                ReviewRow(
                    dataset_id=(raw.get("dataset_id") or "").strip(),
                    dataset_name=(raw.get("dataset_name") or "").strip(),
                    source_repo=(raw.get("source_repo") or "").strip(),
                    normalized_task=(raw.get("normalized_task") or "").strip(),
                    raw_examples=(raw.get("raw_examples") or "").strip(),
                    count_in_dataset=int(raw.get("count_in_dataset") or 0),
                    total_count=int(raw.get("total_count") or 0),
                    other_tasks_in_dataset=(raw.get("other_tasks_in_dataset") or "").strip(),
                    task_json_summary=(raw.get("task_json_summary") or "").strip(),
                )
            )
    return rows


def _shorten(text: str, max_len: int = 240) -> str:
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build dataset task decision pack TSV from the review pack."
    )
    parser.add_argument(
        "--review-pack",
        type=Path,
        default=Path("artifacts/dataset_task_review/review_pack.tsv"),
        help="Path to review_pack.tsv produced by build_dataset_task_review_pack.py",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/dataset_task_review/decision_pack.tsv"),
        help="Output TSV path",
    )
    args = parser.parse_args()

    rows = _load_review_pack(args.review_pack)
    by_token: dict[str, list[ReviewRow]] = defaultdict(list)
    for row in rows:
        if row.normalized_task:
            by_token[row.normalized_task].append(row)

    records: list[dict[str, str]] = []
    for token, token_rows in by_token.items():
        total_count = max((r.total_count for r in token_rows), default=0)
        dataset_ids = sorted({r.dataset_id for r in token_rows if r.dataset_id})
        dataset_names = sorted({r.dataset_name for r in token_rows if r.dataset_name})
        suggested_action, suggested_canonical, rationale = _suggest_action(token)

        records.append(
            {
                "normalized_task": token,
                "total_count": str(total_count),
                "n_datasets": str(len(dataset_ids)),
                "dataset_ids": ",".join(dataset_ids),
                "dataset_names": _shorten(" | ".join(dataset_names), 320),
                "example_raw_task": token_rows[0].raw_examples if token_rows else "",
                "other_tasks_in_dataset": _shorten(
                    " | ".join(
                        sorted(
                            {
                                r.other_tasks_in_dataset
                                for r in token_rows
                                if r.other_tasks_in_dataset
                            }
                        )
                    ),
                    320,
                ),
                "task_json_summary": _shorten(
                    " | ".join(
                        sorted({r.task_json_summary for r in token_rows if r.task_json_summary})
                    ),
                    360,
                ),
                "suggested_action": suggested_action,
                "suggested_canonical": suggested_canonical,
                "rationale": rationale,
            }
        )

    records.sort(
        key=lambda r: (
            -int(r["total_count"] or 0),
            -int(r["n_datasets"] or 0),
            r["normalized_task"],
        )
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "normalized_task",
                "total_count",
                "n_datasets",
                "dataset_ids",
                "dataset_names",
                "example_raw_task",
                "other_tasks_in_dataset",
                "task_json_summary",
                "suggested_action",
                "suggested_canonical",
                "rationale",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote decision pack to {args.out}")


if __name__ == "__main__":
    main()
