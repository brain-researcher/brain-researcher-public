#!/usr/bin/env python3
"""Materialize adjudicated concept-hold rows into a candidate-only queue."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adjudication-rows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--accept-all",
        action="store_true",
        help="Reroute all input rows instead of filtering to proposed_action=reroute_candidate_only.",
    )
    parser.add_argument(
        "--routing-bucket",
        default="concept_hold_candidate_only",
        help="Routing bucket written into candidate-only payloads.",
    )
    parser.add_argument(
        "--trigger-reason",
        default="adjudicated_candidate_only_concept_hold",
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
                row.get("adjudication_bucket") or row.get("source_review_bucket") or ""
            ).strip(),
            "source_bucket_reason": str(
                row.get("bucket_reason") or row.get("source_bucket_reason") or ""
            ).strip(),
            "upstream_review_bucket": str(
                row.get("source_review_bucket") or ""
            ).strip(),
            "upstream_bucket_reason": str(
                row.get("source_bucket_reason") or ""
            ).strip(),
            "source_stage": str(
                row.get("source_stage") or "balanced_concept_hold_adjudication"
            ).strip(),
            "source_artifact_path": str(row.get("source_artifact_path") or "").strip(),
            "adjudication_bucket": str(row.get("adjudication_bucket") or "").strip(),
            "bucket_reason": str(row.get("bucket_reason") or "").strip(),
            "proposed_action": str(row.get("proposed_action") or "").strip(),
            "recommended_next_action": str(
                row.get("recommended_next_action") or row.get("proposed_action") or ""
            ).strip(),
            "review_questions": list(row.get("review_questions") or []),
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
    adjudication_rows = args.adjudication_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rerouted_rows = []
    for row in _iter_jsonl(adjudication_rows):
        if (
            not args.accept_all
            and str(row.get("proposed_action") or "").strip() != "reroute_candidate_only"
        ):
            continue
        rerouted_rows.append(
            _candidate_only_payload(
                row,
                routing_bucket=args.routing_bucket,
                trigger_reason=args.trigger_reason,
            )
        )

    queue_path = output_dir / "review_queue_candidate_only.jsonl"
    _write_jsonl(queue_path, rerouted_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "adjudication_rows_path": str(adjudication_rows),
        "counts": {
            "rows_total": len(rerouted_rows),
        },
        "artifacts": {
            "review_queue_candidate_only_jsonl": str(queue_path),
            "summary_json": str(output_dir / "candidate_only_reroute_summary.json"),
        },
    }
    (output_dir / "candidate_only_reroute_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
