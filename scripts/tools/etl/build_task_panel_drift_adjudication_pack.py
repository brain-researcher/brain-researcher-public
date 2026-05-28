#!/usr/bin/env python3
"""Propose bucket-level adjudication actions for task-panel drift-review rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _propose_action(row: dict[str, Any]) -> tuple[str, str, str]:
    old_task_id = str(row.get("old_task_id") or "").strip()
    current_target_id = str(row.get("current_target_id") or "").strip()
    current_target_namespace = str(row.get("current_target_namespace") or "").strip()
    current_target_label = str(row.get("current_target_label") or "").strip()
    onvoc_label = str(row.get("onvoc_label") or "").strip()
    mapping_original = str(row.get("mapping_original") or "").strip()

    if (
        old_task_id == "task:onvoc:onvoc_0000466"
        and current_target_id == "neurostore_task:SL5Qq3YkFSAD:fmri:0"
        and current_target_label
        and current_target_label == onvoc_label == "Cognitive Inhibition"
    ):
        return (
            "keep_namespace_replacement",
            "namespace_only_same_public_label",
            "Treat the neurostore task as the canonical live replacement; do not clean up this row set.",
        )

    if current_target_namespace == "neurostore_task":
        return (
            "review_semantic_coarsening",
            "subfamily_or_onvoc_to_neurostore",
            "Likely namespace promotion mixed with task-granularity loss; review by transition cluster before migration.",
        )

    if current_target_namespace == "task:onvoc":
        if (
            old_task_id == "task:subfamily:sf_risk_ambiguity"
            and current_target_id == "task:onvoc:onvoc_0000428"
        ):
            if mapping_original == "concept:decision_making":
                return (
                    "review_default_reject",
                    "subfamily_collapsed_to_generic_decision_making",
                    "Most rows collapsed from a specific subfamily to generic Decision Making; keep only by explicit exception.",
                )
            return (
                "review_default_reject",
                "heterogeneous_decision_making_tail",
                "Tail concepts are mixed and should not be auto-accepted into generic Decision Making.",
            )

        return (
            "review_default_reject",
            "subfamily_collapsed_to_generic_onvoc",
            "Current task:onvoc target looks like a stale coarse fallback, not a safe canonical replacement.",
        )

    return (
        "review_unexpected_namespace",
        "unexpected_target_namespace",
        "Unexpected namespace outside the primary adjudication buckets; inspect manually.",
    )


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "proposed_action",
        "decision_reason",
        "review_bucket",
        "current_target_namespace",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "current_target_id",
        "mapping_original",
        "onvoc_label",
        "current_target_label",
        "decision_note",
        "paper_title",
    ]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(
                    str(row.get(column, "")).replace("\t", " ").replace("\n", " ")
                    for column in columns
                )
                + "\n"
            )


def build_summary(rows: Sequence[dict[str, Any]], review_pack_path: Path) -> dict[str, Any]:
    action_counts = Counter(row["proposed_action"] for row in rows)
    reason_counts = Counter(row["decision_reason"] for row in rows)
    bucket_action_counts = Counter(
        (row["review_bucket"], row["proposed_action"]) for row in rows
    )
    top_transitions = Counter(
        (row["old_task_id"], row["current_target_id"], row["proposed_action"])
        for row in rows
    )

    return {
        "generated_at": _utc_now_iso(),
        "review_pack_path": str(review_pack_path.resolve()),
        "counts": {
            "review_rows": len(rows),
        },
        "counts_by_action": action_counts.most_common(),
        "counts_by_reason": reason_counts.most_common(),
        "counts_by_bucket_action": [
            [bucket, action, count]
            for (bucket, action), count in bucket_action_counts.most_common()
        ],
        "top_transition_actions": [
            [old_task_id, current_target_id, action, count]
            for (old_task_id, current_target_id, action), count in top_transitions.most_common(
                30
            )
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    review_pack_path = args.review_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = list(_iter_jsonl(review_pack_path))
    adjudicated_rows: list[dict[str, Any]] = []
    for row in rows:
        proposed_action, decision_reason, decision_note = _propose_action(row)
        enriched = dict(row)
        enriched["proposed_action"] = proposed_action
        enriched["decision_reason"] = decision_reason
        enriched["decision_note"] = decision_note
        adjudicated_rows.append(enriched)

    summary = build_summary(adjudicated_rows, review_pack_path)

    _write_jsonl(output_dir / "drift_adjudication_pack.jsonl", adjudicated_rows)
    _write_tsv(output_dir / "drift_adjudication_pack.tsv", adjudicated_rows)
    for action in sorted({row["proposed_action"] for row in adjudicated_rows}):
        action_rows = [
            row for row in adjudicated_rows if row["proposed_action"] == action
        ]
        _write_jsonl(output_dir / f"{action}.jsonl", action_rows)
        _write_tsv(output_dir / f"{action}.tsv", action_rows)
    (output_dir / "drift_adjudication_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts_by_action"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
