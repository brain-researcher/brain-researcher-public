#!/usr/bin/env python3
"""Build a bounded calibration pack for balanced-lane method-rigor failures."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.neurokg.etl.loaders.gabriel_loader import (  # noqa: E402
    GabrielMeasurementLoader,
)
from brain_researcher.services.neurokg.etl.loaders.gabriel_measurements import (  # noqa: E402
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--quality-profile", default="balanced_marginal")
    parser.add_argument("--max-rejected", type=int, default=80)
    parser.add_argument("--max-accepted", type=int, default=40)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _resolve_manifest_path(value: str | Path | None, *, base_dir: Path) -> Path:
    if value is None:
        return base_dir
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _record_identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    run = record.get("run") if isinstance(record.get("run"), Mapping) else {}
    claim = record.get("claim") if isinstance(record.get("claim"), Mapping) else {}
    evidence = (
        record.get("evidence") if isinstance(record.get("evidence"), Mapping) else {}
    )
    return (
        str(run.get("run_id") or "").strip(),
        str(claim.get("id") or "").strip(),
        str(evidence.get("quote") or "").strip(),
    )


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _method_status(record: dict[str, Any], key: str) -> str:
    block = (record.get("method") or {}).get(key)
    if isinstance(block, dict):
        return str(block.get("status") or "unknown").strip().lower()
    return "unknown"


def _record_to_row(
    *,
    record: dict[str, Any],
    variables: Any,
    threshold: float,
    rejection_reasons: Sequence[str],
    bucket: str,
) -> dict[str, Any]:
    paper = dict(record.get("paper") or {})
    target = dict(record.get("target") or {})
    claim = dict(record.get("claim") or {})
    evidence = dict(record.get("evidence") or {})
    run = dict(record.get("run") or {})
    method = dict(record.get("method") or {})

    return {
        "bucket": bucket,
        "paper_id": str(paper.get("id") or "").strip(),
        "paper_title": str(paper.get("title") or "").strip(),
        "run_id": str(run.get("run_id") or "").strip(),
        "target_type": str(target.get("type") or "").strip(),
        "target_id": str(target.get("id") or "").strip(),
        "target_label": str(target.get("label") or "").strip(),
        "claim_id": str(claim.get("id") or "").strip(),
        "claim_text": str(claim.get("text") or "").strip(),
        "evidence_section": str(evidence.get("section") or "").strip(),
        "evidence_quote": str(evidence.get("quote") or "").strip(),
        "method_rigor": round(float(variables.method_rigor), 4),
        "method_rigor_gap": round(float(variables.method_rigor) - threshold, 4),
        "mention_strength": round(float(variables.mention_strength), 4),
        "mapping_confidence": round(float(variables.mapping_confidence), 4),
        "claim_strength": round(float(variables.claim_strength), 4),
        "evidence_quality": str(variables.evidence_quality),
        "evidence_quality_score": round(float(variables.evidence_quality_score), 4),
        "rejection_reasons": list(rejection_reasons),
        "rejection_reason_count": len(rejection_reasons),
        "preregistration_status": _method_status(record, "preregistration"),
        "threshold_correction_status": _method_status(record, "threshold_correction"),
        "sample_size_status": _method_status(record, "sample_size"),
        "sample_size_reported_n": (
            (method.get("sample_size") or {}).get("reported_n")
            if isinstance(method.get("sample_size"), dict)
            else None
        ),
        "roi_definition_status": _method_status(record, "roi_definition"),
        "operationalization_status": _method_status(record, "operationalization"),
        "open_data_or_code_status": _method_status(record, "open_data_or_code"),
        "method_detail_quote": (
            str((method.get("sample_size") or {}).get("quote") or "").strip()
            or str((method.get("threshold_correction") or {}).get("quote") or "").strip()
            or str((method.get("operationalization") or {}).get("quote") or "").strip()
            or str((method.get("roi_definition") or {}).get("quote") or "").strip()
            or str((method.get("open_data_or_code") or {}).get("quote") or "").strip()
        ),
    }


def _dominant_bucket(reasons: Sequence[str]) -> str:
    if "candidate_only_title_generic_reroute" in reasons:
        return "candidate_only_title_generic"
    if "benchmark_title_only_suppressed" in reasons:
        return "suppressed_title_only"
    filtered = sorted(
        reason for reason in reasons if reason != "title_only_low_rigor_evidence"
    )
    if filtered == ["method_rigor_below_threshold"]:
        return "rejected_method_only"
    if filtered == ["mapping_confidence_below_threshold", "method_rigor_below_threshold"]:
        return "review_mixed_method_mapping"
    if filtered == [
        "claim_strength_below_threshold",
        "mapping_confidence_below_threshold",
        "method_rigor_below_threshold",
    ]:
        return "review_mixed_method_claim_mapping"
    return "other"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.manifest.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = _resolve_manifest_path(
        manifest.get("paths", {}).get("run_dir") or manifest_path.parent,
        base_dir=manifest_path.parent,
    )
    review_queue_path = _resolve_manifest_path(
        (manifest.get("ingest") or {}).get("review_queue_path") or run_dir / "review_queue.jsonl",
        base_dir=run_dir,
    )
    quality_profile = str(args.quality_profile or "balanced_marginal").strip().lower()
    thresholds = GabrielMeasurementLoader.QUALITY_PROFILES[quality_profile]
    threshold = float(thresholds["method_rigor_min"])

    review_rows = list(_iter_jsonl(review_queue_path)) if review_queue_path.exists() else []
    rejected_run_ids: set[str] = set()
    rejected_rows: list[dict[str, Any]] = []
    rejection_counter: Counter[str] = Counter()
    seen_review_keys: set[tuple[str, str, str]] = set()
    duplicate_review_rows = 0

    for item in review_rows:
        reasons = [str(reason) for reason in (item.get("reasons") or [])]
        if "method_rigor_below_threshold" not in reasons:
            continue
        record = dict(item.get("record") or {})
        review_key = _record_identity(record)
        if review_key in seen_review_keys:
            duplicate_review_rows += 1
            continue
        seen_review_keys.add(review_key)
        run_id = str((record.get("run") or {}).get("run_id") or "").strip()
        if run_id:
            rejected_run_ids.add(run_id)
        vars_payload = item.get("variables") or {}
        variables = compute_gabriel_variables(record)
        if vars_payload:
            # trust stored method_rigor etc. when present; recomputation is still used
            variables = variables.__class__(
                mention_strength=float(vars_payload.get("mention_strength", variables.mention_strength)),
                mapping_confidence=float(vars_payload.get("mapping_confidence", variables.mapping_confidence)),
                claim_polarity=str(vars_payload.get("claim_polarity", variables.claim_polarity)),
                claim_strength=float(vars_payload.get("claim_strength", variables.claim_strength)),
                evidence_quality=str(vars_payload.get("evidence_quality", variables.evidence_quality)),
                evidence_quality_score=float(vars_payload.get("evidence_quality_score", variables.evidence_quality_score)),
                method_rigor=float(vars_payload.get("method_rigor", variables.method_rigor)),
                provenance_completeness=float(vars_payload.get("provenance_completeness", variables.provenance_completeness)),
            )
        bucket = _dominant_bucket(reasons)
        rejection_counter[bucket] += 1
        if bucket == "rejected_method_only":
            rejected_rows.append(
                _record_to_row(
                    record=record,
                    variables=variables,
                    threshold=threshold,
                    rejection_reasons=reasons,
                    bucket=bucket,
                )
            )

    rejected_rows.sort(
        key=lambda row: (
            abs(float(row["method_rigor_gap"])),
            row["paper_id"],
        )
    )
    rejected_rows = rejected_rows[: max(0, int(args.max_rejected))]

    accepted_controls: list[dict[str, Any]] = []
    shard_entries = list(manifest.get("shards") or [])
    if not shard_entries:
        shards_dir = run_dir / "shards"
        if shards_dir.exists():
            shard_entries = [{"path": str(path)} for path in sorted(shards_dir.glob("*.jsonl"))]

    for shard in shard_entries:
        shard_path = _resolve_manifest_path(shard.get("path") or "", base_dir=run_dir)
        if not shard_path.exists():
            continue
        for record in _iter_jsonl(shard_path):
            run_id = str((record.get("run") or {}).get("run_id") or "").strip()
            if run_id in rejected_run_ids:
                continue
            variables = compute_gabriel_variables(record)
            accepted, reasons = evaluate_high_precision_gate(variables, thresholds=thresholds)
            if not accepted:
                continue
            accepted_controls.append(
                _record_to_row(
                    record=record,
                    variables=variables,
                    threshold=threshold,
                    rejection_reasons=reasons,
                    bucket="accepted_near_threshold_control",
                )
            )

    accepted_controls.sort(
        key=lambda row: (
            abs(float(row["method_rigor_gap"])),
            row["paper_id"],
        )
    )
    accepted_controls = accepted_controls[: max(0, int(args.max_accepted))]

    rows = rejected_rows + accepted_controls
    summary = {
        "generated_at": _utc_now_iso(),
        "manifest_path": str(manifest_path),
        "review_queue_path": str(review_queue_path),
        "quality_profile": quality_profile,
        "method_rigor_min": threshold,
        "rejected_rows_total": len(rejected_rows),
        "accepted_controls_total": len(accepted_controls),
        "rows_total": len(rows),
        "review_rows_deduped": len(seen_review_keys),
        "duplicate_review_rows_skipped": duplicate_review_rows,
        "rejection_bucket_counts": dict(sorted(rejection_counter.items())),
        "method_audit_pack_jsonl": str((output_dir / "balanced_method_audit_pack.jsonl").resolve()),
        "method_audit_pack_tsv": str((output_dir / "balanced_method_audit_pack.tsv").resolve()),
    }

    _write_jsonl(output_dir / "balanced_method_audit_pack.jsonl", rows)
    _write_tsv(output_dir / "balanced_method_audit_pack.tsv", rows)
    (output_dir / "balanced_method_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
