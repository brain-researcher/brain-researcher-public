#!/usr/bin/env python3
"""Build an actionable reroute pack for non-social rows still in the cleanup queue."""

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
    parser.add_argument("--cleanup-candidates", type=Path, required=True)
    parser.add_argument("--social-review-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "reroute_action",
        "reroute_lane",
        "review_decision",
        "decision_reason",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "current_target_id",
        "mapping_original",
        "paper_title",
        "next_step",
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


def _classify(review_decision: str) -> tuple[str, str, str]:
    if review_decision == "cue_reactivity_non_social":
        return (
            "reroute_review",
            "cue_reactivity",
            "Re-map into cue-reactivity / salience review lane before any cleanup.",
        )
    if review_decision == "language_pragmatics_non_social":
        return (
            "reroute_review",
            "language_pragmatics",
            "Re-map into language/pragmatics review lane before any cleanup.",
        )
    if review_decision == "generic_cognitive_sensory_non_social":
        return (
            "reroute_review",
            "generic_cognitive_sensory",
            "Re-map into generic cognitive/sensory review lane before any cleanup.",
        )
    if review_decision == "meta_review_noise":
        return (
            "cleanup_now",
            "meta_noise",
            "Meta/review-only row; safe cleanup candidate rather than reroute.",
        )
    return (
        "manual_review",
        "unexpected",
        "Unexpected review decision in cleanup queue; inspect before any action.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cleanup_candidates_path = args.cleanup_candidates.expanduser().resolve()
    social_review_pack_path = args.social_review_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    review_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _iter_jsonl(social_review_pack_path):
        key = (
            str(row.get("claim_id") or "").strip(),
            str(row.get("paper_id") or "").strip(),
            str(row.get("run_id") or "").strip(),
        )
        review_lookup[key] = row

    reroute_rows: list[dict[str, Any]] = []
    unmatched_cleanup_rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(cleanup_candidates_path):
        key = (
            str(row.get("claim_id") or "").strip(),
            str(row.get("paper_id") or "").strip(),
            str(row.get("run_id") or "").strip(),
        )
        review_row = review_lookup.get(key)
        if review_row is None:
            unmatched_cleanup_rows.append(row)
            continue
        review_decision = str(review_row.get("review_decision") or "").strip()
        reroute_action, reroute_lane, next_step = _classify(review_decision)
        enriched = dict(row)
        enriched["review_decision"] = review_decision
        enriched["decision_reason"] = str(review_row.get("decision_reason") or "").strip()
        enriched["decision_note"] = str(review_row.get("decision_note") or "").strip()
        enriched["reroute_action"] = reroute_action
        enriched["reroute_lane"] = reroute_lane
        enriched["next_step"] = next_step
        if "record" in review_row:
            enriched["record"] = review_row["record"]
        reroute_rows.append(enriched)

    action_counts = Counter(row["reroute_action"] for row in reroute_rows)
    lane_counts = Counter(row["reroute_lane"] for row in reroute_rows)
    mapping_counts = Counter(row["mapping_original"] for row in reroute_rows)

    _write_jsonl(output_dir / "social_reroute_pack.jsonl", reroute_rows)
    _write_tsv(output_dir / "social_reroute_pack.tsv", reroute_rows)
    for action in ("reroute_review", "cleanup_now", "manual_review"):
        action_rows = [row for row in reroute_rows if row["reroute_action"] == action]
        _write_jsonl(output_dir / f"{action}.jsonl", action_rows)
        _write_tsv(output_dir / f"{action}.tsv", action_rows)
    for lane in (
        "cue_reactivity",
        "language_pragmatics",
        "generic_cognitive_sensory",
        "meta_noise",
        "unexpected",
    ):
        lane_rows = [row for row in reroute_rows if row["reroute_lane"] == lane]
        _write_jsonl(output_dir / f"lane_{lane}.jsonl", lane_rows)
        _write_tsv(output_dir / f"lane_{lane}.tsv", lane_rows)
        lane_records = [row["record"] for row in lane_rows if "record" in row]
        _write_jsonl(output_dir / f"lane_{lane}_records.jsonl", lane_records)
    reroute_review_records = [
        row["record"]
        for row in reroute_rows
        if row["reroute_action"] == "reroute_review" and "record" in row
    ]
    _write_jsonl(output_dir / "reroute_review_records.jsonl", reroute_review_records)
    cleanup_now_ids = sorted(
        {row["claim_id"] for row in reroute_rows if row["reroute_action"] == "cleanup_now"}
    )
    (output_dir / "cleanup_now_claim_ids.txt").write_text(
        "\n".join(cleanup_now_ids) + ("\n" if cleanup_now_ids else ""),
        encoding="utf-8",
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "cleanup_candidates_path": str(cleanup_candidates_path),
        "social_review_pack_path": str(social_review_pack_path),
        "counts": {
            "cleanup_queue_rows": len(reroute_rows),
            "reroute_review": action_counts["reroute_review"],
            "cleanup_now": action_counts["cleanup_now"],
            "manual_review": action_counts["manual_review"],
            "unmatched_cleanup_rows": len(unmatched_cleanup_rows),
        },
        "counts_by_lane": lane_counts.most_common(),
        "counts_by_mapping_original": mapping_counts.most_common(),
        "artifacts": {
            "social_reroute_pack_jsonl": str(output_dir / "social_reroute_pack.jsonl"),
            "reroute_review_records_jsonl": str(
                output_dir / "reroute_review_records.jsonl"
            ),
            "lane_cue_reactivity_records_jsonl": str(
                output_dir / "lane_cue_reactivity_records.jsonl"
            ),
            "lane_language_pragmatics_records_jsonl": str(
                output_dir / "lane_language_pragmatics_records.jsonl"
            ),
            "lane_generic_cognitive_sensory_records_jsonl": str(
                output_dir / "lane_generic_cognitive_sensory_records.jsonl"
            ),
            "cleanup_now_jsonl": str(output_dir / "cleanup_now.jsonl"),
            "cleanup_now_claim_ids_txt": str(output_dir / "cleanup_now_claim_ids.txt"),
            "summary_json": str(output_dir / "social_reroute_summary.json"),
        },
    }
    (output_dir / "social_reroute_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
