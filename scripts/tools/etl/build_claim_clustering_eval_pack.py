#!/usr/bin/env python3
"""Build a bounded claim clustering + failure-taxonomy evaluation pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TITLE_ONLY_WARNINGS = {
    "title_only_evidence_present",
    "evidence_depth_title_only",
}
SEMANTIC_WARNINGS = {
    "claim_evidence_semantic_mismatch_present",
    "claim_evidence_semantic_mismatch",
}
STRUCTURAL_WARNINGS = {
    "verdict_structural_prerequisite_unmet",
    "verdict_semantic_prerequisite_unmet",
}
COMPOSITE_TOKENS = (
    "connectivity",
    "network",
    "networks",
    "analysis",
    "correlation",
    "dynamics",
    "reactivity",
)
METHOD_TOKENS = (
    "fmri",
    "eeg",
    "meg",
    "mri",
    "neurofeedback",
)
DISEASE_SCOPE_TOKENS = (
    "disease",
    "disorder",
    "cohort",
    "cohorts",
    "alzheimer",
    "depression",
    "ptsd",
    "trait",
    "traits",
)
CONTEXT_TOKENS = (
    "compared to",
    "during",
    "after",
    "before",
    "under ",
    "mediates",
    "boosts",
    "intermittent",
    "continuous",
)
REPLICATION_TOKENS = ("replication", "replicate", "reproduced", "reproduce")
FAILED_REPLICATION_TOKENS = ("failed replication", "failed to replicate")
NULL_RESULT_TOKENS = ("no effect", "no difference", "null result", "did not differ")
POLARITY_CONFUSION_TOKENS = (
    "increase",
    "decrease",
    "higher",
    "lower",
    "positive",
    "negative",
    "uniformly",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--heldout-manifest", type=Path, required=True)
    parser.add_argument("--adjudication-pack", type=Path, required=True)
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


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
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


def _normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_or_empty(value: Any) -> str:
    return str(value or "").strip()


def _collapse_unique(values: Iterable[str], *, mixed_label: str) -> str:
    cleaned = sorted({str(value).strip() for value in values if str(value).strip()})
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return mixed_label


def _normalize_claim_kind(*, text: str, polarity: str) -> str:
    lowered = _normalize_text(text)
    if any(token in lowered for token in FAILED_REPLICATION_TOKENS):
        return "failed_replication"
    if any(token in lowered for token in NULL_RESULT_TOKENS):
        return "null_result"
    if any(token in lowered for token in REPLICATION_TOKENS):
        return "replication"
    if any(token in lowered for token in ("contradiction", "contradicts", "conflict")):
        return "contradiction"
    return "claim"


def _target_after_adjudication_value(value: Any) -> str:
    if isinstance(value, dict):
        return _string_or_empty(value.get("target_id"))
    if isinstance(value, str) and ":" in value:
        return value.strip()
    return ""


def _extract_anchor_metadata(row: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    anchors = (
        (row.get("review_material") or {}).get("evidence_anchors") or []
        if isinstance(row.get("review_material"), dict)
        else []
    )
    by_claim: dict[str, dict[str, list[str]]] = {}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        claim_id = str(anchor.get("claim_id") or "").strip()
        if not claim_id:
            continue
        payload = by_claim.setdefault(
            claim_id,
            {"evidence_depths": [], "anchor_warnings": []},
        )
        depth = str(anchor.get("evidence_depth") or "").strip()
        if depth and depth not in payload["evidence_depths"]:
            payload["evidence_depths"].append(depth)
        for warning in _string_list(anchor.get("warnings")):
            if warning not in payload["anchor_warnings"]:
                payload["anchor_warnings"].append(warning)
    return by_claim


def _benchmark_eligibility(source_rows: list[dict[str, Any]]) -> str:
    if any(
        bool(row.get("accepted_under_gate")) and str(row.get("quality_profile")) == "high_precision"
        for row in source_rows
    ):
        return "benchmark_eligible_high_precision"
    if any(bool(row.get("accepted_under_gate")) for row in source_rows):
        return "bootstrap_only_pre_gate_b"
    return "review_queue_only"


def _failure_tags(row: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    warnings = {warning.lower() for warning in _string_list(row.get("warnings"))}
    evidence_depths = {depth.lower() for depth in _string_list(row.get("evidence_depths"))}
    combined = " ".join(
        [
            str(row.get("target_label") or ""),
            str(row.get("proposition_text") or ""),
            str(row.get("target_id") or ""),
        ]
    ).lower()

    if "title_only" in evidence_depths or warnings & TITLE_ONLY_WARNINGS:
        tags.add("title_only_or_insufficient_text")
    if "unverifiable_snippet" in evidence_depths:
        tags.add("title_only_or_insufficient_text")
    if warnings & SEMANTIC_WARNINGS:
        tags.add("semantic_composite_or_analysis_claim")
    if warnings & STRUCTURAL_WARNINGS:
        tags.add("granularity_mismatch")
    if any(token in combined for token in COMPOSITE_TOKENS):
        tags.add("semantic_composite_or_analysis_claim")
    if any(token in combined for token in METHOD_TOKENS):
        tags.add("modality_or_method_leakage")
    if any(token in combined for token in DISEASE_SCOPE_TOKENS):
        tags.add("population_or_disease_scope_mismatch")
    if any(token in combined for token in CONTEXT_TOKENS):
        tags.add("intervention_or_context_mismatch")
    target_after_adjudication = _string_or_empty(row.get("target_after_adjudication"))
    if target_after_adjudication and target_after_adjudication != _string_or_empty(
        row.get("target_id")
    ):
        tags.add("target_mismatch")
    return sorted(tags)


def _cluster_confidence(action: str) -> float:
    if action == "singleton":
        return 0.95
    if action == "merge_same_proposition":
        return 0.80
    if action == "merge_with_warning":
        return 0.55
    return 0.20


def _iter_source_claim_rows(
    path: Path,
    *,
    source_pack: str,
    stats: Counter[str],
) -> Iterable[dict[str, Any]]:
    for row in _iter_jsonl(path):
        stats["input_rows_total"] += 1
        top_warnings = _string_list(row.get("warnings"))
        anchor_meta = _extract_anchor_metadata(row)
        top_notes = _string_or_empty(row.get("notes"))
        top_why_now = _string_or_empty(row.get("why_now"))
        top_slice = _string_or_empty(row.get("slice"))
        top_adjudication_status = _string_or_empty(
            (row.get("adjudication") or {}).get("status")
            if isinstance(row.get("adjudication"), dict)
            else ""
        )
        target_after_adjudication = _target_after_adjudication_value(
            row.get("target_after_adjudication")
        )
        source_records = row.get("source_records") or []
        if not isinstance(source_records, list):
            continue
        for record in source_records:
            if not isinstance(record, dict):
                continue
            claim_id = str(record.get("claim_id") or "").strip()
            if not claim_id:
                stats["source_records_skipped_no_claim_id"] += 1
                continue
            stats["source_records_with_claim_id"] += 1
            per_claim = anchor_meta.get(claim_id) or {}
            yield {
                "source_pack": source_pack,
                "hypothesis_id": str(row.get("hypothesis_id") or "").strip(),
                "hypothesis_text": str(row.get("text") or "").strip(),
                "expected_verdict": str(row.get("expected_verdict") or "").strip(),
                "top_review_status": str(row.get("review_status") or "").strip(),
                "top_notes": top_notes,
                "top_why_now": top_why_now,
                "top_slice": top_slice,
                "top_adjudication_status": top_adjudication_status,
                "target_after_adjudication": target_after_adjudication,
                "top_warnings": top_warnings,
                "paper_id": str(record.get("paper_id") or "").strip(),
                "target_id": str(record.get("target_id") or "").strip(),
                "target_type": str(record.get("target_type") or "").strip(),
                "source_claim_id": claim_id,
                "span_id": str(record.get("span_id") or "").strip(),
                "polarity": str(record.get("polarity") or "").strip(),
                "quality_profile": str(record.get("gate_profile") or "").strip(),
                "accepted_under_gate": bool(record.get("accepted_under_gate")),
                "source_review_status": str(record.get("review_status") or "").strip(),
                "source_path": str(record.get("path") or "").strip(),
                "source_line_number": int(record.get("line_number") or 0),
                "evidence_depths": per_claim.get("evidence_depths") or [],
                "anchor_warnings": per_claim.get("anchor_warnings") or [],
            }


def build_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: Counter[str] = Counter()
    aggregated: dict[str, dict[str, Any]] = {}

    sources = [
        ("calibration_manifest", args.calibration_manifest.expanduser().resolve()),
        ("heldout_manifest", args.heldout_manifest.expanduser().resolve()),
        ("adjudication_pack", args.adjudication_pack.expanduser().resolve()),
    ]
    for source_pack, path in sources:
        for source_row in _iter_source_claim_rows(path, source_pack=source_pack, stats=stats):
            claim_id = source_row["source_claim_id"]
            entry = aggregated.setdefault(
                claim_id,
                {
                    "source_claim_id": claim_id,
                    "paper_id": source_row["paper_id"],
                    "target_id": source_row["target_id"],
                    "target_type": source_row["target_type"],
                    "target_label": source_row["target_id"].split(":", 1)[-1].replace("_", " "),
                    "polarity": source_row["polarity"],
                    "source_rows": [],
                    "hypothesis_ids": set(),
                    "hypothesis_texts": set(),
                    "expected_verdicts": set(),
                    "review_statuses": set(),
                    "source_packs": set(),
                    "source_paths": set(),
                    "evidence_depths": set(),
                    "warnings": set(),
                    "note_fragments": set(),
                    "adjudication_statuses": set(),
                    "target_after_adjudication_values": set(),
                },
            )
            entry["source_rows"].append(source_row)
            if source_row["hypothesis_id"]:
                entry["hypothesis_ids"].add(source_row["hypothesis_id"])
            if source_row["hypothesis_text"]:
                entry["hypothesis_texts"].add(source_row["hypothesis_text"])
            if source_row["expected_verdict"]:
                entry["expected_verdicts"].add(source_row["expected_verdict"])
            if source_row["top_review_status"]:
                entry["review_statuses"].add(source_row["top_review_status"])
            if source_row["source_review_status"]:
                entry["review_statuses"].add(source_row["source_review_status"])
            entry["source_packs"].add(source_row["source_pack"])
            if source_row["top_notes"]:
                entry["note_fragments"].add(source_row["top_notes"])
            if source_row["top_why_now"]:
                entry["note_fragments"].add(source_row["top_why_now"])
            if source_row["top_slice"]:
                entry["note_fragments"].add(f"slice={source_row['top_slice']}")
            if source_row["top_adjudication_status"]:
                entry["adjudication_statuses"].add(source_row["top_adjudication_status"])
            if source_row["target_after_adjudication"]:
                entry["target_after_adjudication_values"].add(
                    source_row["target_after_adjudication"]
                )
            if source_row["source_path"]:
                entry["source_paths"].add(
                    f"{source_row['source_path']}#{source_row['source_line_number']}"
                    if source_row["source_line_number"]
                    else source_row["source_path"]
                )
            entry["evidence_depths"].update(source_row["evidence_depths"])
            entry["warnings"].update(source_row["anchor_warnings"])
            entry["warnings"].update(source_row["top_warnings"])

    rows: list[dict[str, Any]] = []
    cluster_members: dict[str, list[int]] = defaultdict(list)
    for claim_id, entry in aggregated.items():
        proposition_text = max(entry["hypothesis_texts"] or {""}, key=len)
        proposition_signature = _normalize_text(proposition_text)
        claim_kind = _normalize_claim_kind(text=proposition_text, polarity=entry["polarity"])
        canonical_signature = "|".join(
            [
                _string_or_empty(entry["target_id"]),
                _string_or_empty(entry["target_type"]).lower(),
                claim_kind,
                proposition_signature,
            ]
        )
        proposed_canonical_claim_id = (
            f"canonical_claim:{_stable_hash(canonical_signature)}"
            if proposition_signature and entry["target_id"]
            else f"canonical_claim:{_stable_hash(claim_id)}"
        )
        row = {
            "source_claim_id": claim_id,
            "paper_id": entry["paper_id"],
            "target_id": entry["target_id"],
            "target_type": entry["target_type"],
            "target_label": entry["target_label"],
            "claim_text": proposition_text,
            "claim_kind": claim_kind,
            "polarity": entry["polarity"],
            "quality_profile": _collapse_unique(
                (source_row["quality_profile"] for source_row in entry["source_rows"]),
                mixed_label="mixed_quality_profile",
            ),
            "quality_profiles": sorted(
                {
                    str(source_row["quality_profile"])
                    for source_row in entry["source_rows"]
                    if str(source_row["quality_profile"])
                }
            ),
            "benchmark_eligibility": _benchmark_eligibility(entry["source_rows"]),
            "candidate_lane_present": False,
            "hypothesis_ids": sorted(entry["hypothesis_ids"]),
            "proposition_text": proposition_text,
            "expected_verdicts": sorted(entry["expected_verdicts"]),
            "review_status": _collapse_unique(
                entry["review_statuses"],
                mixed_label="mixed_review_status",
            ),
            "review_statuses": sorted(entry["review_statuses"]),
            "adjudication_status": _collapse_unique(
                entry["adjudication_statuses"],
                mixed_label="mixed_adjudication_status",
            )
            or "not_adjudicated",
            "source_packs": sorted(entry["source_packs"]),
            "source_paths": sorted(entry["source_paths"]),
            "evidence_depths": sorted(entry["evidence_depths"]),
            "warnings": sorted(entry["warnings"]),
            "notes": " | ".join(sorted(entry["note_fragments"])),
            "target_after_adjudication": _collapse_unique(
                entry["target_after_adjudication_values"],
                mixed_label="mixed_target_after_adjudication",
            ),
            "canonical_claim_id": proposed_canonical_claim_id,
            "proposed_canonical_claim_id": proposed_canonical_claim_id,
        }
        row["failure_tags"] = _failure_tags(row)
        rows.append(row)
        cluster_members[proposed_canonical_claim_id].append(len(rows) - 1)

    action_counts: Counter[str] = Counter()
    slice_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    eligibility_counts: Counter[str] = Counter()
    cluster_summary_counts: Counter[str] = Counter()
    for cluster_id, member_indices in cluster_members.items():
        cluster_rows = [rows[index] for index in member_indices]
        cluster_polarities = {
            str(cluster_row.get("polarity") or "").strip()
            for cluster_row in cluster_rows
            if str(cluster_row.get("polarity") or "").strip()
        }
        cluster_has_warnings = any(cluster_row["failure_tags"] for cluster_row in cluster_rows)
        if cluster_has_warnings:
            cluster_summary_counts["clusters_with_failure_tags"] += 1
        if len(cluster_polarities) > 1:
            cluster_summary_counts["clusters_with_opposing_polarity"] += 1
        if (
            len(
                {
                    source_pack
                    for cluster_row in cluster_rows
                    for source_pack in _string_list(cluster_row.get("source_packs"))
                }
            )
            > 1
        ):
            cluster_summary_counts["clusters_spanning_multiple_source_packs"] += 1
        for index in member_indices:
            row = rows[index]
            row_failure_tags = set(row["failure_tags"])
            if len(member_indices) > 1 and len(cluster_polarities) > 1:
                evaluation_slice = "same_target_opposing_stance"
                if any(
                    token in _normalize_text(row.get("claim_text"))
                    for token in POLARITY_CONFUSION_TOKENS
                ) or row_failure_tags & {
                    "semantic_composite_or_analysis_claim",
                    "title_only_or_insufficient_text",
                }:
                    row_failure_tags.add("polarity_or_antonym_confusion")
                proposed_action = (
                    "merge_with_warning"
                    if cluster_has_warnings or "polarity_or_antonym_confusion" in row_failure_tags
                    else "merge_same_proposition"
                )
            elif row_failure_tags:
                evaluation_slice = "failure_taxonomy_stress"
                proposed_action = "do_not_merge"
            else:
                evaluation_slice = "stable_single_paper_control"
                proposed_action = "singleton"
            row["failure_tags"] = sorted(row_failure_tags)
            row["evaluation_slice"] = evaluation_slice
            row["proposed_action"] = proposed_action
            row["cluster_member_count"] = len(member_indices)
            row["cluster_polarities"] = sorted(cluster_polarities)
            row["cluster_confidence"] = _cluster_confidence(proposed_action)
            action_counts[proposed_action] += 1
            slice_counts[evaluation_slice] += 1
            eligibility_counts[row["benchmark_eligibility"]] += 1
            for tag in row["failure_tags"]:
                failure_counts[tag] += 1

    rows.sort(
        key=lambda row: (
            row["evaluation_slice"],
            row["proposed_canonical_claim_id"],
            row["source_claim_id"],
        )
    )
    summary = {
        "generated_at": _utc_now_iso(),
        "input_paths": {
            "calibration_manifest": str(args.calibration_manifest.expanduser().resolve()),
            "heldout_manifest": str(args.heldout_manifest.expanduser().resolve()),
            "adjudication_pack": str(args.adjudication_pack.expanduser().resolve()),
        },
        "counts": {
            "input_rows_total": int(stats["input_rows_total"]),
            "source_records_with_claim_id": int(stats["source_records_with_claim_id"]),
            "source_records_skipped_no_claim_id": int(stats["source_records_skipped_no_claim_id"]),
            "rows_total": len(rows),
            "canonical_clusters_total": len(cluster_members),
            "multi_member_clusters": sum(
                1 for members in cluster_members.values() if len(members) > 1
            ),
            **{
                key: int(value)
                for key, value in sorted(cluster_summary_counts.items())
            },
            **{f"slice_{key}": int(value) for key, value in sorted(slice_counts.items())},
            **{f"action_{key}": int(value) for key, value in sorted(action_counts.items())},
            **{
                f"eligibility_{key}": int(value)
                for key, value in sorted(eligibility_counts.items())
            },
            **{f"failure_{key}": int(value) for key, value in sorted(failure_counts.items())},
        },
    }
    return rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows, summary = build_rows(args)
    pack_jsonl = output_dir / "claim_clustering_eval_pack.jsonl"
    pack_tsv = output_dir / "claim_clustering_eval_pack.tsv"
    summary_json = output_dir / "claim_clustering_eval_summary.json"

    _write_jsonl(pack_jsonl, rows)
    _write_tsv(
        pack_tsv,
        rows,
        [
            "evaluation_slice",
            "proposed_action",
            "source_claim_id",
            "paper_id",
            "target_type",
            "target_id",
            "claim_kind",
            "polarity",
            "benchmark_eligibility",
            "proposed_canonical_claim_id",
            "cluster_member_count",
            "cluster_confidence",
            "failure_tags",
            "warnings",
        ],
    )
    summary["artifacts"] = {
        "pack_jsonl": str(pack_jsonl),
        "pack_tsv": str(pack_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
