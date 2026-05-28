from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(dict(row), sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _bucket_for(row: Mapping[str, Any]) -> tuple[str, str, str]:
    relation_hint = str(row.get("relation_hint") or "").strip()
    candidate_kg_id = str(row.get("candidate_kg_id") or "").strip()
    title = str(row.get("title") or "").strip()
    seed_id = str(row.get("seed_id") or "").strip()
    pair_summary = row.get("pair_summary") or {}
    has_pair = bool(pair_summary.get("has_pair", True))
    if not has_pair:
        return (
            "pair_incomplete_replay",
            "medium",
            "rerun_missing_lane_before_refinement",
        )
    if relation_hint == "SEARCH_EXPANDED":
        return (
            "search_expanded_bridge",
            "high",
            "tighten_entity_hints_and_claim_first_grounding",
        )
    if relation_hint == "BELONGS_TO_FAMILY":
        return (
            "family_hop_bridge",
            "medium",
            "translate_family_hop_to_exact_anchor",
        )
    if relation_hint == "MAPS_TO":
        return (
            "mapping_bridge",
            "medium",
            "replace_mapping_hop_with_exact_concept_seed",
        )
    if seed_id.startswith("ds:") or candidate_kg_id.startswith("4:") or title.startswith("4:"):
        return (
            "dataset_seed_entity_leakage",
            "low",
            "drop_from_candidate_sensitive_pack",
        )
    return (
        "other_bridge",
        "medium",
        "manual_refinement_review",
    )


def _build_goal(bucket: str) -> str:
    goals = {
        "search_expanded_bridge": "Keep the bridge idea but replace generic search-expanded hops with claim-first exact anchors.",
        "family_hop_bridge": "Translate family-level nodes into exact task or concept anchors before replaying.",
        "mapping_bridge": "Replace mapping-mediated bridges with exact concept/task seeds that preserve the same mechanism.",
        "pair_incomplete_replay": "Rerun the missing broad or strict lane before interpreting the bridge as a stable refinement target.",
        "dataset_seed_entity_leakage": "Remove dataset-driven anonymous element leakage from candidate-sensitive replay and move these rows to control-only handling.",
        "other_bridge": "Manual bounded review before any further replay use.",
    }
    return goals[bucket]


def build_refinement_pack(
    review_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in review_rows:
        grouped[str(row.get("candidate_card_id") or "")].append(row)

    pack_rows: list[dict[str, Any]] = []
    for candidate_card_id, rows in grouped.items():
        first = dict(rows[0])
        bucket, priority, action = _bucket_for(first)
        pack_rows.append(
            {
                "schema_version": "idea-mining-refinement-pack-v1",
                "candidate_card_id": candidate_card_id,
                "seed_id": str(first.get("seed_id") or ""),
                "title": str(first.get("title") or ""),
                "hypothesis": str(first.get("hypothesis") or ""),
                "candidate_kg_id": str(first.get("candidate_kg_id") or ""),
                "relation_hint": str(first.get("relation_hint") or ""),
                "run_spec_ids": sorted(str(row.get("run_spec_id") or "") for row in rows),
                "candidate_lane_modes_seen": sorted(
                    {str(row.get("candidate_lane_mode") or "") for row in rows}
                ),
                "verdicts_seen": sorted({str(row.get("verdict") or "") for row in rows}),
                "raw_total_range": [
                    min(int(row.get("raw_total", 0) or 0) for row in rows),
                    max(int(row.get("raw_total", 0) or 0) for row in rows),
                ],
                "refinement_bucket": bucket,
                "priority": priority,
                "recommended_action": action,
                "refinement_goal": _build_goal(bucket),
                "paired_delta_seen": any(bool(row.get("paired_broad_strict_delta")) for row in rows),
                "failure_tags": sorted(
                    {
                        str(tag)
                        for row in rows
                        for tag in (row.get("failure_tags") or [])
                        if str(tag).strip()
                    }
                ),
            }
        )

    pack_rows.sort(
        key=lambda row: (
            {"high": 0, "medium": 1, "low": 2}.get(str(row["priority"]), 9),
            str(row["refinement_bucket"]),
            str(row["candidate_card_id"]),
        )
    )

    summary = {
        "schema_version": "idea-mining-refinement-pack-summary-v1",
        "rows_total": len(pack_rows),
        "source_review_rows_total": len(review_rows),
        "bucket_counts": dict(Counter(str(row["refinement_bucket"]) for row in pack_rows)),
        "priority_counts": dict(Counter(str(row["priority"]) for row in pack_rows)),
        "recommended_action_counts": dict(
            Counter(str(row["recommended_action"]) for row in pack_rows)
        ),
        "drop_from_candidate_sensitive_pack_total": sum(
            1 for row in pack_rows if row["recommended_action"] == "drop_from_candidate_sensitive_pack"
        ),
    }
    return pack_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the idea-mining refinement pack from first-pass replay rows.")
    parser.add_argument("--review-rows-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    review_rows_path = Path(args.review_rows_jsonl).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    review_rows = _load_jsonl(review_rows_path)
    pack_rows, summary = build_refinement_pack(review_rows)
    _write_jsonl(output_dir / "idea_mining_refinement_pack_v1.jsonl", pack_rows)
    _write_json(output_dir / "idea_mining_refinement_pack_v1_summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
