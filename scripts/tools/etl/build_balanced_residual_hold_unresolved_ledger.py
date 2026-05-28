#!/usr/bin/env python3
"""Build a unified residual hold + unresolved ledger for benchmark-blocked rows."""

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
    parser.add_argument("--task-region-unresolved", type=Path, required=True)
    parser.add_argument("--task-region-parse-errors", type=Path, required=True)
    parser.add_argument("--task-region-title-only-rejected", type=Path, required=True)
    parser.add_argument("--specific-concept-unresolved", type=Path, required=True)
    parser.add_argument("--biomarker-unresolved", type=Path, required=True)
    parser.add_argument("--broad-biomarker-hold", type=Path, required=True)
    parser.add_argument("--broad-trait-hold", type=Path, required=True)
    parser.add_argument("--manual-concept-review", type=Path, required=True)
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


def _base_payload(row: dict[str, Any]) -> dict[str, Any]:
    target_id = str(row.get("target_id") or "").strip()
    target_type = str(row.get("target_type") or "").strip()
    if not target_type:
        if target_id.startswith("task:"):
            target_type = "Task"
        elif target_id.startswith("region:"):
            target_type = "Region"
        elif target_id.startswith("concept:"):
            target_type = "Concept"
    return {
        "paper_id": str(row.get("paper_id") or "").strip(),
        "paper_title": str(row.get("paper_title") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "target_type": target_type,
        "target_id": target_id,
        "target_label": str(row.get("target_label") or "").strip(),
        "evidence_section": str(row.get("evidence_section") or "").strip(),
        "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
        "claim_strength": float(row.get("claim_strength") or 0.0),
        "method_rigor": float(row.get("method_rigor") or 0.0),
        "rejection_reasons": list(row.get("rejection_reasons") or []),
    }


def _hold_payload(
    row: dict[str, Any],
    *,
    ledger_bucket: str,
    source_stage: str,
    source_artifact_path: Path,
    recommended_next_action: str,
    blocking_reason: str,
) -> dict[str, Any]:
    payload = _base_payload(row)
    payload.update(
        {
            "entry_kind": "hold",
            "ledger_bucket": ledger_bucket,
            "source_stage": source_stage,
            "source_artifact_path": str(source_artifact_path),
            "source_review_bucket": str(
                row.get("policy_bucket")
                or row.get("adjudication_bucket")
                or row.get("source_review_bucket")
                or ""
            ).strip(),
            "source_bucket_reason": str(
                row.get("bucket_reason")
                or row.get("source_bucket_reason")
                or ""
            ).strip(),
            "blocking_reason": blocking_reason,
            "recommended_next_action": recommended_next_action,
            "retry_mode": "manual_or_policy",
        }
    )
    return payload


def _unresolved_payload(
    row: dict[str, Any],
    *,
    ledger_bucket: str,
    source_stage: str,
    source_artifact_path: Path,
    recommended_next_action: str,
    blocking_reason: str,
    retry_mode: str,
) -> dict[str, Any]:
    payload = _base_payload(row)
    payload.update(
        {
            "entry_kind": "unresolved",
            "ledger_bucket": ledger_bucket,
            "source_stage": source_stage,
            "source_artifact_path": str(source_artifact_path),
            "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
            "source_bucket_reason": str(row.get("source_bucket_reason") or "").strip(),
            "blocking_reason": blocking_reason,
            "recommended_next_action": recommended_next_action,
            "retry_mode": retry_mode,
            "source_reason": str(row.get("reason") or row.get("error") or "").strip(),
        }
    )
    return payload


def _parse_error_retry_policy(row: dict[str, Any]) -> tuple[str, str]:
    failure_reason = str(row.get("failure_reason") or "").strip().lower()
    if failure_reason in {"parse_error", ""}:
        return (
            "retry_with_json_repair_hardening",
            "parse_error_during_task_region_regeneration",
        )
    if failure_reason in {"empty_response", "timeout", "quota_or_rate_limit", "llm_error"}:
        return (
            "retry_with_provider_or_transport_hardening",
            f"{failure_reason}_during_task_region_regeneration",
        )
    return (
        "retry_with_regeneration_failure_triage",
        f"{failure_reason}_during_task_region_regeneration",
    )


def build_ledger_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    task_region_unresolved = args.task_region_unresolved.expanduser().resolve()
    for row in _iter_jsonl(task_region_unresolved):
        rows.append(
            _unresolved_payload(
                row,
                ledger_bucket="task_region_unresolved_no_non_title_text",
                source_stage="balanced_title_only_regeneration_run",
                source_artifact_path=task_region_unresolved,
                recommended_next_action="retry_with_fulltext_or_retire_benchmark",
                blocking_reason="no_non_title_text_after_task_region_regeneration",
                retry_mode="conditional_retry",
            )
        )

    task_region_parse_errors = args.task_region_parse_errors.expanduser().resolve()
    for row in _iter_jsonl(task_region_parse_errors):
        recommended_next_action, blocking_reason = _parse_error_retry_policy(row)
        rows.append(
            _unresolved_payload(
                row,
                ledger_bucket="task_region_parse_error",
                source_stage="balanced_title_only_regeneration_run",
                source_artifact_path=task_region_parse_errors,
                recommended_next_action=recommended_next_action,
                blocking_reason=blocking_reason,
                retry_mode="retry_now",
            )
        )

    task_region_title_only_rejected = args.task_region_title_only_rejected.expanduser().resolve()
    for row in _iter_jsonl(task_region_title_only_rejected):
        rows.append(
            _unresolved_payload(
                row,
                ledger_bucket="task_region_title_only_after_regeneration",
                source_stage="balanced_title_only_regeneration_run",
                source_artifact_path=task_region_title_only_rejected,
                recommended_next_action="retry_with_prompt_hardening_or_retire",
                blocking_reason="llm_returned_title_only_after_regeneration",
                retry_mode="retry_now",
            )
        )

    specific_concept_unresolved = args.specific_concept_unresolved.expanduser().resolve()
    for row in _iter_jsonl(specific_concept_unresolved):
        rows.append(
            _unresolved_payload(
                row,
                ledger_bucket="specific_concept_unresolved_no_non_title_text",
                source_stage="balanced_specific_concept_regeneration_run",
                source_artifact_path=specific_concept_unresolved,
                recommended_next_action="retry_with_fulltext_or_candidate_only",
                blocking_reason="no_non_title_text_after_specific_concept_regeneration",
                retry_mode="conditional_retry",
            )
        )

    biomarker_unresolved = args.biomarker_unresolved.expanduser().resolve()
    for row in _iter_jsonl(biomarker_unresolved):
        rows.append(
            _unresolved_payload(
                row,
                ledger_bucket="biomarker_unresolved_no_non_title_text",
                source_stage="balanced_biomarker_regeneration_run",
                source_artifact_path=biomarker_unresolved,
                recommended_next_action="retry_with_fulltext_or_hold",
                blocking_reason="no_non_title_text_after_biomarker_regeneration",
                retry_mode="conditional_retry",
            )
        )

    broad_biomarker_hold = args.broad_biomarker_hold.expanduser().resolve()
    for row in _iter_jsonl(broad_biomarker_hold):
        rows.append(
            _hold_payload(
                row,
                ledger_bucket="broad_biomarker_hold",
                source_stage="balanced_biomarker_policy",
                source_artifact_path=broad_biomarker_hold,
                recommended_next_action="manual_scope_review_or_candidate_only_policy",
                blocking_reason="broad_biomarker_title_concept_not_benchmark_ready",
            )
        )

    broad_trait_hold = args.broad_trait_hold.expanduser().resolve()
    for row in _iter_jsonl(broad_trait_hold):
        rows.append(
            _hold_payload(
                row,
                ledger_bucket="broad_behavioral_trait_hold",
                source_stage="balanced_behavioral_policy",
                source_artifact_path=broad_trait_hold,
                recommended_next_action="manual_scope_review_or_candidate_only_policy",
                blocking_reason="broad_behavioral_trait_title_concept_not_benchmark_ready",
            )
        )

    manual_concept_review = args.manual_concept_review.expanduser().resolve()
    for row in _iter_jsonl(manual_concept_review):
        rows.append(
            _hold_payload(
                row,
                ledger_bucket="manual_concept_review",
                source_stage="balanced_concept_hold_adjudication",
                source_artifact_path=manual_concept_review,
                recommended_next_action="manual_semantic_adjudication",
                blocking_reason="concept_semantics_need_manual_decision_before_regeneration",
            )
        )

    rows.sort(
        key=lambda row: (
            row["entry_kind"],
            row["ledger_bucket"],
            row["target_label"].lower(),
            row["paper_id"],
        )
    )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = build_ledger_rows(args)
    hold_rows = [row for row in rows if row["entry_kind"] == "hold"]
    unresolved_rows = [row for row in rows if row["entry_kind"] == "unresolved"]

    bucket_counts: Counter[str] = Counter(row["ledger_bucket"] for row in rows)
    action_counts: Counter[str] = Counter(row["recommended_next_action"] for row in rows)
    retry_counts: Counter[str] = Counter(row["retry_mode"] for row in rows)
    kind_counts: Counter[str] = Counter(row["entry_kind"] for row in rows)
    target_type_counts: Counter[str] = Counter(row["target_type"] for row in rows)

    _write_jsonl(output_dir / "residual_ledger.jsonl", rows)
    _write_jsonl(output_dir / "hold_rows.jsonl", hold_rows)
    _write_jsonl(output_dir / "unresolved_rows.jsonl", unresolved_rows)
    _write_tsv(
        output_dir / "residual_ledger.tsv",
        rows,
        [
            "entry_kind",
            "ledger_bucket",
            "recommended_next_action",
            "retry_mode",
            "paper_id",
            "paper_title",
            "target_type",
            "target_id",
            "target_label",
            "claim_id",
            "source_stage",
            "blocking_reason",
        ],
    )

    for bucket in sorted(bucket_counts):
        bucket_rows = [row for row in rows if row["ledger_bucket"] == bucket]
        _write_jsonl(output_dir / f"{bucket}.jsonl", bucket_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "counts": {
            "rows_total": len(rows),
            "hold_rows_total": len(hold_rows),
            "unresolved_rows_total": len(unresolved_rows),
            **{f"entry_kind_{kind}": kind_counts[kind] for kind in sorted(kind_counts)},
            **{
                f"target_type_{target_type.lower()}": target_type_counts[target_type]
                for target_type in sorted(target_type_counts)
            },
            **{bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)},
            **{
                f"action_{action}": action_counts[action]
                for action in sorted(action_counts)
            },
            **{f"retry_{mode}": retry_counts[mode] for mode in sorted(retry_counts)},
        },
        "artifacts": {
            "residual_ledger_jsonl": str(output_dir / "residual_ledger.jsonl"),
            "residual_ledger_tsv": str(output_dir / "residual_ledger.tsv"),
            "hold_rows_jsonl": str(output_dir / "hold_rows.jsonl"),
            "unresolved_rows_jsonl": str(output_dir / "unresolved_rows.jsonl"),
            "summary_json": str(output_dir / "residual_ledger_summary.json"),
        },
        "inputs": {
            "task_region_unresolved": str(args.task_region_unresolved.expanduser().resolve()),
            "task_region_parse_errors": str(args.task_region_parse_errors.expanduser().resolve()),
            "task_region_title_only_rejected": str(
                args.task_region_title_only_rejected.expanduser().resolve()
            ),
            "specific_concept_unresolved": str(
                args.specific_concept_unresolved.expanduser().resolve()
            ),
            "biomarker_unresolved": str(args.biomarker_unresolved.expanduser().resolve()),
            "broad_biomarker_hold": str(args.broad_biomarker_hold.expanduser().resolve()),
            "broad_trait_hold": str(args.broad_trait_hold.expanduser().resolve()),
            "manual_concept_review": str(args.manual_concept_review.expanduser().resolve()),
        },
        "excludes": [
            "candidate-only rerouted rows already removed from benchmark follow-up",
            "successful benchmark promotions already accepted through live balanced_marginal ingest",
        ],
    }
    (output_dir / "residual_ledger_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
