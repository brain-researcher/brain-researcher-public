#!/usr/bin/env python3
"""Close out the last residual balanced benchmark tail rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

HOLD_BUCKETS = {
    "broad_behavioral_trait_hold",
    "broad_biomarker_hold",
    "manual_concept_review",
}
RETRY_BUCKETS = {
    "task_region_parse_error",
    "task_region_title_only_after_regeneration",
}
CLOSEOUT_STAGE = "balanced_final_tail_closeout"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-ledger", type=Path, required=True)
    parser.add_argument("--retry-now-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--routing-bucket",
        default="benchmark_final_tail_candidate_only",
        help="Routing bucket written into candidate-only payloads.",
    )
    parser.add_argument(
        "--trigger-reason",
        default="final_tail_closeout_candidate_only",
        help="Trigger reason appended to candidate-only payloads.",
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


def _retry_terminal_resolution(row: dict[str, Any]) -> tuple[str, str]:
    target_type = _normalized_target_type(row)
    if target_type == "Region":
        return "retire_benchmark", "region_retry_exhausted_or_provider_blocked"
    if target_type:
        return "retire_benchmark", "non_region_retry_now_row_defaults_to_retire"
    return "retire_benchmark", "unknown_retry_now_target_defaults_to_retire"


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
            "source_review_bucket": str(
                row.get("source_review_bucket") or row.get("ledger_bucket") or ""
            ).strip(),
            "source_bucket_reason": str(
                row.get("source_bucket_reason") or row.get("blocking_reason") or ""
            ).strip(),
            "source_stage": str(row.get("source_stage") or "").strip(),
            "source_artifact_path": str(row.get("source_artifact_path") or "").strip(),
            "source_ledger_bucket": str(
                row.get("source_ledger_bucket") or row.get("ledger_bucket") or ""
            ).strip(),
            "source_retry_mode": str(row.get("retry_mode") or "").strip(),
            "closeout_stage": str(
                row.get("closeout_stage") or CLOSEOUT_STAGE
            ).strip(),
            "closeout_input_artifact_path": str(
                row.get("closeout_input_artifact_path") or ""
            ).strip(),
            "terminal_resolution_bucket": str(
                row.get("terminal_resolution_bucket") or ""
            ).strip(),
            "terminal_resolution_reason": str(
                row.get("terminal_resolution_reason") or ""
            ).strip(),
            "live_claim_present": bool(row.get("live_claim_present")),
            "live_target_id": str(row.get("live_target_id") or "").strip(),
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    residual_ledger = args.residual_ledger.expanduser().resolve()
    retry_now_pack = args.retry_now_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for row in _iter_jsonl(residual_ledger):
        bucket = str(row.get("ledger_bucket") or "").strip()
        if bucket not in HOLD_BUCKETS:
            continue
        payload = dict(row)
        payload["source_stage"] = str(
            payload.get("source_stage") or "balanced_residual_hold_unresolved_ledger"
        ).strip()
        payload["source_artifact_path"] = str(
            payload.get("source_artifact_path") or residual_ledger
        ).strip()
        payload["source_review_bucket"] = str(
            payload.get("source_review_bucket") or payload.get("ledger_bucket") or ""
        ).strip()
        payload["source_bucket_reason"] = str(
            payload.get("source_bucket_reason") or payload.get("blocking_reason") or ""
        ).strip()
        payload["terminal_resolution_bucket"] = "candidate_only"
        payload["terminal_resolution_reason"] = "broad_or_manual_concept_not_benchmark_ready"
        payload["recommended_next_action"] = "keep_in_candidate_only_lane"
        payload["closeout_stage"] = CLOSEOUT_STAGE
        payload["closeout_input_artifact_path"] = str(residual_ledger)
        rows.append(payload)
        counts["candidate_only"] += 1

    for row in _iter_jsonl(retry_now_pack):
        bucket = str(row.get("source_ledger_bucket") or "").strip()
        if bucket not in RETRY_BUCKETS:
            continue
        payload = dict(row)
        payload["source_stage"] = str(
            payload.get("source_stage") or "balanced_residual_retry_now_pack"
        ).strip()
        payload["source_artifact_path"] = str(
            payload.get("source_artifact_path") or retry_now_pack
        ).strip()
        payload["source_review_bucket"] = str(
            payload.get("source_review_bucket")
            or payload.get("source_ledger_bucket")
            or ""
        ).strip()
        payload["source_bucket_reason"] = str(
            payload.get("source_bucket_reason") or payload.get("blocking_reason") or ""
        ).strip()
        resolution_bucket, resolution_reason = _retry_terminal_resolution(payload)
        payload["terminal_resolution_bucket"] = resolution_bucket
        payload["terminal_resolution_reason"] = resolution_reason
        payload["recommended_next_action"] = "retire_from_benchmark_followup"
        payload["closeout_stage"] = CLOSEOUT_STAGE
        payload["closeout_input_artifact_path"] = str(retry_now_pack)
        rows.append(payload)
        counts["retire_benchmark"] += 1

    live_state = _resolve_live_claim_state(
        [str(row.get("claim_id") or "").strip() for row in rows if row.get("claim_id")]
    )
    for row in rows:
        live = live_state.get(str(row.get("claim_id") or "").strip())
        row["live_claim_present"] = live is not None
        row["live_target_id"] = None if live is None else str(live.get("live_target_id") or "").strip()
        row["live_paper_id"] = None if live is None else str(live.get("live_paper_id") or "").strip()

    candidate_only_queue = [
        _candidate_only_payload(
            row,
            routing_bucket=args.routing_bucket,
            trigger_reason=args.trigger_reason,
        )
        for row in rows
        if row.get("terminal_resolution_bucket") == "candidate_only"
    ]

    rows.sort(
        key=lambda row: (
            str(row.get("terminal_resolution_bucket") or ""),
            str(row.get("target_type") or ""),
            str(row.get("target_label") or "").lower(),
        )
    )

    _write_jsonl(output_dir / "final_tail_closeout_pack.jsonl", rows)
    _write_tsv(
        output_dir / "final_tail_closeout_pack.tsv",
        rows,
        [
            "terminal_resolution_bucket",
            "paper_id",
            "paper_title",
            "target_type",
            "target_id",
            "target_label",
            "claim_id",
            "live_claim_present",
            "live_target_id",
            "terminal_resolution_reason",
        ],
    )
    _write_jsonl(
        output_dir / "candidate_only.jsonl",
        [row for row in rows if row.get("terminal_resolution_bucket") == "candidate_only"],
    )
    _write_jsonl(
        output_dir / "retire_benchmark.jsonl",
        [row for row in rows if row.get("terminal_resolution_bucket") == "retire_benchmark"],
    )
    _write_jsonl(output_dir / "review_queue_candidate_only.jsonl", candidate_only_queue)

    summary = {
        "generated_at": _utc_now_iso(),
        "residual_ledger_path": str(residual_ledger),
        "retry_now_pack_path": str(retry_now_pack),
        "counts": {
            "rows_total": len(rows),
            **{key: counts[key] for key in sorted(counts)},
            "live_claim_present": sum(1 for row in rows if row.get("live_claim_present")),
        },
        "artifacts": {
            "closeout_pack_jsonl": str(output_dir / "final_tail_closeout_pack.jsonl"),
            "closeout_pack_tsv": str(output_dir / "final_tail_closeout_pack.tsv"),
            "candidate_only_jsonl": str(output_dir / "candidate_only.jsonl"),
            "retire_benchmark_jsonl": str(output_dir / "retire_benchmark.jsonl"),
            "review_queue_candidate_only_jsonl": str(output_dir / "review_queue_candidate_only.jsonl"),
            "summary_json": str(output_dir / "final_tail_closeout_summary.json"),
        },
    }
    (output_dir / "final_tail_closeout_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
