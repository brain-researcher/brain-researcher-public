#!/usr/bin/env python3
"""Build a bounded B2 reviewed-seed task manifest from adjudicated claim packs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_MANIFEST_ID = "claim_snapshot_v4_b2_review_seed_conflict_expanded_20260314"
TASK_FAMILY = "B2_failure_aware_claim_inclusion_exclusion_reasoning"
TASK_VARIANT = "reviewed_seed_v2_conflict_expanded"
TASK_CHARTER_SOURCE = (
    "/app/brain_researcher/docs/planning/task_charter.md"
)
LABEL_SPACE = [
    "retain_singleton",
    "retain_singleton_with_warning",
    "retain_conflict_cluster_with_warning",
    "exclude_from_snapshot",
]
DEFAULT_INPUTS: list[tuple[str, Path]] = [
    (
        "v1",
        Path(
            "/app/brain_researcher/data/br-kg/raw/gabriel/eval/claim_snapshot_v1/bounded_v1_20260314/claim_clustering_adjudication_pack.jsonl"
        ),
    ),
    (
        "v2",
        Path(
            "/app/brain_researcher/data/br-kg/raw/gabriel/eval/claim_snapshot_v2/off400_seed_reviewed_20260314/claim_snapshot_v2_expansion_review_pack.jsonl"
        ),
    ),
    (
        "v3",
        Path(
            "/app/brain_researcher/data/br-kg/raw/gabriel/eval/claim_snapshot_v3/off400_bridge_reviewed_20260314/claim_snapshot_v3_review_pack.jsonl"
        ),
    ),
    (
        "v4",
        Path(
            "/app/brain_researcher/data/br-kg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_review_pack.jsonl"
        ),
    ),
    (
        "v5_conflict",
        Path(
            "/app/brain_researcher/data/br-kg/raw/gabriel/eval/claim_snapshot_v4_b2_conflict_expansion/off400_live_attention_20260314/claim_snapshot_v4_b2_conflict_expansion_pack.jsonl"
        ),
    ),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--extra-review-pack",
        action="append",
        default=[],
        help="Extra reviewed pack in the form review_stage=/abs/or/rel/path.jsonl",
    )
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


def _resolve_inputs(args: argparse.Namespace) -> list[tuple[str, Path]]:
    inputs = list(DEFAULT_INPUTS)
    for raw in list(args.extra_review_pack or []):
        review_stage, sep, raw_path = str(raw).partition("=")
        if not sep or not review_stage.strip() or not raw_path.strip():
            raise SystemExit(
                "Fail-closed B2 task manifest mismatch: "
                f"invalid --extra-review-pack {raw!r}; expected review_stage=path"
            )
        inputs.append((review_stage.strip(), Path(raw_path).expanduser().resolve()))
    return inputs


def build_outputs(
    inputs: Sequence[tuple[str, Path]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    resolved_inputs = list(inputs or DEFAULT_INPUTS)
    latest_by_source_claim_id: dict[str, tuple[str, str, dict[str, Any]]] = {}
    raw_rows_total = 0
    duplicate_overwrites = 0

    for review_stage, path in resolved_inputs:
        for row in _iter_jsonl(path):
            raw_rows_total += 1
            source_claim_id = str(row.get("source_claim_id") or "").strip()
            if not source_claim_id:
                raise SystemExit("Fail-closed B2 task manifest mismatch: missing source_claim_id")
            if source_claim_id in latest_by_source_claim_id:
                duplicate_overwrites += 1
            latest_by_source_claim_id[source_claim_id] = (review_stage, str(path), row)

    examples: list[dict[str, Any]] = []
    label_counter: Counter[str] = Counter()
    target_type_counter: Counter[str] = Counter()
    review_stage_counter: Counter[str] = Counter()
    failure_tag_counter: Counter[str] = Counter()

    for source_claim_id, (review_stage, source_path, row) in sorted(latest_by_source_claim_id.items()):
        gold_label = str(row.get("adjudicated_action") or "").strip()
        if gold_label not in LABEL_SPACE:
            raise SystemExit(
                "Fail-closed B2 task manifest mismatch: "
                f"unknown adjudicated_action {gold_label!r} for {source_claim_id}"
            )
        review_stage_counter[review_stage] += 1
        label_counter[gold_label] += 1
        target_type = str(row.get("target_type") or "").strip()
        if target_type:
            target_type_counter[target_type] += 1
        failure_tags = [tag for tag in list(row.get("failure_tags") or []) if tag]
        failure_tag_counter.update(failure_tags)
        examples.append(
            {
                "task_manifest_id": TASK_MANIFEST_ID,
                "task_family": TASK_FAMILY,
                "task_variant": TASK_VARIANT,
                "example_id": source_claim_id,
                "input_unit": "paper_local_claim_row",
                "review_stage": review_stage,
                "gold_label": gold_label,
                "source_claim_id": source_claim_id,
                "paper_id": row.get("paper_id"),
                "canonical_claim_id": row.get("canonical_claim_id"),
                "target_id": row.get("target_id"),
                "target_type": row.get("target_type"),
                "claim_text": row.get("claim_text"),
                "claim_kind": row.get("claim_kind"),
                "polarity": row.get("polarity"),
                "quality_profile": row.get("quality_profile"),
                "benchmark_eligibility": row.get("benchmark_eligibility"),
                "candidate_lane_present": bool(row.get("candidate_lane_present")),
                "failure_tags": failure_tags,
                "adjudication_status": row.get("adjudication_status"),
                "adjudication_bucket": row.get("adjudication_bucket"),
                "snapshot_role": row.get("snapshot_role"),
                "decision_reason": row.get("decision_reason"),
                "review_status": row.get("review_status"),
                "evaluation_slice": row.get("evaluation_slice"),
                "source_pack_path": source_path,
            }
        )

    manifest = {
        "task_manifest_id": TASK_MANIFEST_ID,
        "status": "materialized",
        "task_family": TASK_FAMILY,
        "task_variant": TASK_VARIANT,
        "input_unit": "paper_local_claim_row",
        "task_objective": (
            "Decide whether a reviewed paper-local claim row should be retained in the "
            "reviewed snapshot and with what warning level."
        ),
        "label_space": LABEL_SPACE,
        "task_charter_source": TASK_CHARTER_SOURCE,
        "notes": {
            "seed_only": True,
            "dedupe_strategy": "latest_review_stage_wins",
            "review_stage_order": [stage for stage, _ in resolved_inputs],
        },
        "input_review_packs": [
            {"review_stage": review_stage, "path": str(path)}
            for review_stage, path in resolved_inputs
        ],
    }
    summary = {
        "generated_at": _utc_now_iso(),
        "task_manifest_id": TASK_MANIFEST_ID,
        "task_family": TASK_FAMILY,
        "task_variant": TASK_VARIANT,
        "counts": {
            "raw_rows_total": raw_rows_total,
            "deduped_examples_total": len(examples),
            "duplicate_overwrites_total": duplicate_overwrites,
            "label_retain_singleton": label_counter["retain_singleton"],
            "label_retain_singleton_with_warning": label_counter["retain_singleton_with_warning"],
            "label_retain_conflict_cluster_with_warning": label_counter[
                "retain_conflict_cluster_with_warning"
            ],
            "label_exclude_from_snapshot": label_counter["exclude_from_snapshot"],
            "target_type_Concept": target_type_counter["Concept"],
            "target_type_Region": target_type_counter["Region"],
            "target_type_Task": target_type_counter["Task"],
            **{
                f"review_stage_{review_stage}": review_stage_counter[review_stage]
                for review_stage, _ in resolved_inputs
            },
        },
        "failure_tags_top": dict(failure_tag_counter.most_common(10)),
        "notes": {
            "bounded_reviewed_seed": True,
            "not_split_materialized": True,
        },
    }
    return manifest, examples, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest, examples, summary = build_outputs(_resolve_inputs(args))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "claim_snapshot_v4_b2_task_manifest.json"
    examples_path = args.output_dir / "claim_snapshot_v4_b2_examples.jsonl"
    summary_path = args.output_dir / "claim_snapshot_v4_b2_task_summary.json"
    manifest["artifacts"] = {
        "examples_jsonl": str(examples_path),
        "summary_json": str(summary_path),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(examples_path, examples)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
