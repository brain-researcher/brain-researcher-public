#!/usr/bin/env python3
"""Finalize empirically blocked benchmark rows into a candidate-only reroute pack."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unresolved-rows", type=Path, required=True)
    parser.add_argument("--source-review-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--routing-bucket",
        default="benchmark_terminal_candidate_only",
        help="Routing bucket written into candidate-only payloads.",
    )
    parser.add_argument(
        "--trigger-reason",
        default="empirically_blocked_no_non_title_text_candidate_only",
        help="Trigger reason appended to reroute payloads.",
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


def _candidate_only_payload(
    row: dict[str, Any],
    *,
    routing_bucket: str,
    trigger_reason: str,
) -> dict[str, Any]:
    reasons = list(row.get("rejection_reasons") or [])
    reasons.append(trigger_reason)
    deduped_reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
    now = _utc_now_iso()
    return {
        "queued_at": now,
        "reasons": deduped_reasons,
        "variables": {
            "mention_strength": 0.0,
            "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
            "claim_polarity": "uncertain",
            "claim_strength": float(row.get("claim_strength") or 0.0),
            "evidence_quality": "title_only_hold",
            "evidence_quality_score": 0.0,
            "method_rigor": float(row.get("method_rigor") or 0.0),
            "provenance_completeness": 1.0,
        },
        "record": {
            "paper": {
                "id": str(row.get("paper_id") or "").strip(),
                "title": str(row.get("paper_title") or "").strip(),
            },
            "claim": {
                "id": str(row.get("claim_id") or "").strip(),
            },
            "target": {
                "type": str(row.get("target_type") or "").strip(),
                "id": str(row.get("target_id") or "").strip(),
                "label": str(row.get("target_label") or "").strip(),
            },
            "evidence": {
                "section": str(row.get("evidence_section") or "").strip(),
            },
            "run": {
                "run_id": str(row.get("run_id") or "").strip(),
            },
            "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
            "source_bucket_reason": str(
                row.get("source_bucket_reason") or row.get("bucket_reason") or ""
            ).strip(),
            "source_stage": str(row.get("source_stage") or "").strip(),
            "source_artifact_path": str(row.get("source_artifact_path") or "").strip(),
            "source_join_status": str(row.get("source_join_status") or "").strip(),
            "terminal_resolution_bucket": str(
                row.get("terminal_resolution_bucket") or ""
            ).strip(),
            "terminal_resolution_reason": str(
                row.get("terminal_resolution_reason") or ""
            ).strip(),
            "timestamp": now,
        },
        "routing": {
            "lane": "candidate_only",
            "bucket": str(routing_bucket).strip(),
            "policy": "do_not_promote_to_benchmark",
            "trigger_reason": str(trigger_reason).strip(),
            "target_id": str(row.get("target_id") or "").strip(),
            "target_label": str(row.get("target_label") or "").strip(),
        },
    }


def _normalized_target_type(row: dict[str, Any]) -> str:
    target_type = str(row.get("target_type") or "").strip()
    if target_type:
        return target_type
    target_id = str(row.get("target_id") or "").strip()
    if target_id.startswith("task:"):
        return "Task"
    if target_id.startswith("region:"):
        return "Region"
    if target_id.startswith("concept:"):
        return "Concept"
    return ""


def _classify_terminal_resolution(row: dict[str, Any]) -> tuple[str, str]:
    source_join_status = str(row.get("source_join_status") or "").strip()
    if source_join_status == "missing":
        return "retire_benchmark", "missing_terminal_source_review_join_defaults_to_retire"
    if source_join_status == "duplicate":
        return "retire_benchmark", "ambiguous_terminal_source_review_join_defaults_to_retire"
    target_type = _normalized_target_type(row)
    if target_type == "Region":
        return "retire_benchmark", "anatomy_only_title_row_empirically_blocked_after_fulltext_retry"
    if target_type in {"Task", "Concept"}:
        return "candidate_only", "specific_non_region_title_row_empirically_blocked_after_fulltext_retry"
    return "retire_benchmark", "missing_or_unknown_terminal_target_defaults_to_retire"


def _resolve_live_claim_state(claim_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not claim_ids:
        return {}
    try:
        db = require_neo4j_db(preload_cache=False)
    except Exception:
        return {}
    try:
        rows = db.execute_query(
            """
            MATCH (c:Claim)
            WHERE c.id IN $claim_ids
            RETURN c.id AS claim_id, c.target_id AS live_target_id, c.paper_id AS live_paper_id
            """,
            {"claim_ids": list(claim_ids)},
        )
    finally:
        db.close()
    return {str(row.get("claim_id") or "").strip(): row for row in rows}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    unresolved_rows = args.unresolved_rows.expanduser().resolve()
    source_review_pack = args.source_review_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_source_keys: set[tuple[str, str]] = set()
    for row in _iter_jsonl(source_review_pack):
        key = (str(row.get("paper_id") or "").strip(), str(row.get("target_id") or "").strip())
        if key[0] and key[1]:
            if key in source_by_key:
                duplicate_source_keys.add(key)
            source_by_key[key] = row

    split_rows: list[dict[str, Any]] = []
    candidate_only_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for unresolved in _iter_jsonl(unresolved_rows):
        key = (
            str(unresolved.get("paper_id") or "").strip(),
            str(unresolved.get("target_id") or "").strip(),
        )
        source = source_by_key.get(key)
        source_join_status = "matched"
        if key in duplicate_source_keys:
            source = None
            source_join_status = "duplicate"
        elif source is None:
            source_join_status = "missing"
        payload = dict(source or {})
        payload.update(
            {
                "paper_id": key[0],
                "paper_title": str(unresolved.get("paper_title") or payload.get("paper_title") or "").strip(),
                "target_id": key[1],
                "target_label": str(unresolved.get("target_label") or payload.get("target_label") or "").strip(),
                "target_type": _normalized_target_type(
                    {
                        "target_type": payload.get("target_type"),
                        "target_id": key[1],
                    }
                ),
                "terminal_source_reason": str(unresolved.get("reason") or "").strip(),
                "source_join_status": source_join_status,
                "source_stage": str(payload.get("source_stage") or "").strip(),
                "source_artifact_path": str(
                    payload.get("source_artifact_path") or source_review_pack
                ).strip(),
                "source_review_bucket": str(
                    payload.get("source_review_bucket")
                    or unresolved.get("source_review_bucket")
                    or unresolved.get("source_ledger_bucket")
                    or ""
                ).strip(),
                "source_bucket_reason": str(
                    payload.get("source_bucket_reason")
                    or payload.get("bucket_reason")
                    or unresolved.get("source_bucket_reason")
                    or unresolved.get("blocking_reason")
                    or ""
                ).strip(),
            }
        )
        resolution_bucket, resolution_reason = _classify_terminal_resolution(payload)
        payload["terminal_resolution_bucket"] = resolution_bucket
        payload["terminal_resolution_reason"] = resolution_reason
        payload["recommended_next_action"] = (
            "keep_in_candidate_only_lane"
            if resolution_bucket == "candidate_only"
            else "retire_from_benchmark_followup"
        )
        split_rows.append(payload)
        counts[resolution_bucket] += 1
        if resolution_bucket == "candidate_only":
            candidate_only_rows.append(
                _candidate_only_payload(
                    payload,
                    routing_bucket=args.routing_bucket,
                    trigger_reason=args.trigger_reason,
                )
            )

    claim_state = _resolve_live_claim_state(
        [str(row.get("claim_id") or "").strip() for row in split_rows if row.get("claim_id")]
    )
    for row in split_rows:
        live = claim_state.get(str(row.get("claim_id") or "").strip())
        row["live_claim_present"] = live is not None
        row["live_target_id"] = None if live is None else str(live.get("live_target_id") or "").strip()
        row["live_paper_id"] = None if live is None else str(live.get("live_paper_id") or "").strip()

    split_rows.sort(key=lambda row: (str(row.get("target_type") or ""), str(row.get("target_label") or "").lower()))

    _write_jsonl(output_dir / "terminal_resolution_pack.jsonl", split_rows)
    _write_tsv(
        output_dir / "terminal_resolution_pack.tsv",
        split_rows,
        [
            "terminal_resolution_bucket",
            "paper_id",
            "paper_title",
            "target_type",
            "target_id",
            "target_label",
            "claim_id",
            "run_id",
            "live_claim_present",
            "live_target_id",
            "terminal_resolution_reason",
        ],
    )
    _write_jsonl(
        output_dir / "candidate_only.jsonl",
        [row for row in split_rows if row.get("terminal_resolution_bucket") == "candidate_only"],
    )
    _write_jsonl(
        output_dir / "retire_benchmark.jsonl",
        [row for row in split_rows if row.get("terminal_resolution_bucket") == "retire_benchmark"],
    )
    _write_jsonl(output_dir / "review_queue_candidate_only.jsonl", candidate_only_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "unresolved_rows_path": str(unresolved_rows),
        "source_review_pack_path": str(source_review_pack),
        "counts": {
            "rows_total": len(split_rows),
            **{key: counts[key] for key in sorted(counts)},
            "live_claim_present": sum(1 for row in split_rows if row.get("live_claim_present")),
        },
        "artifacts": {
            "terminal_resolution_pack_jsonl": str(output_dir / "terminal_resolution_pack.jsonl"),
            "terminal_resolution_pack_tsv": str(output_dir / "terminal_resolution_pack.tsv"),
            "candidate_only_jsonl": str(output_dir / "candidate_only.jsonl"),
            "review_queue_candidate_only_jsonl": str(output_dir / "review_queue_candidate_only.jsonl"),
            "summary_json": str(output_dir / "terminal_candidate_only_summary.json"),
        },
    }
    (output_dir / "terminal_candidate_only_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
