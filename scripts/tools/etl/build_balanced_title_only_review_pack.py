#!/usr/bin/env python3
"""Build a bounded review pack for remaining title-only benchmark rows."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (  # noqa: E402
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (  # noqa: E402
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

GENERIC_CONCEPT_TOKENS = {
    "neural",
    "brain",
    "functional",
    "connectivity",
    "activation",
    "activity",
    "response",
    "responses",
    "network",
    "networks",
    "correlate",
    "correlates",
    "correlation",
    "correlations",
    "circuit",
    "circuits",
    "volume",
    "homogeneity",
    "gray",
    "matter",
    "code",
    "codes",
}
GENERIC_CONCEPT_PHRASES = (
    "functional connectivity",
    "brain activity",
    "brain activation",
    "brain functional connectivity",
    "neural activation",
    "neural response",
    "neural responses",
    "neural correlates",
    "neural connectivity",
    "effective connectivity",
    "regional homogeneity",
    "gray matter volume",
    "brain atrophy",
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+", flags=re.IGNORECASE)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--quality-profile", default="balanced_marginal")
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
        "review_bucket",
        "bucket_reason",
        "target_type",
        "target_id",
        "target_label",
        "paper_id",
        "paper_title",
        "claim_id",
        "run_id",
        "method_rigor",
        "mapping_confidence",
        "claim_strength",
        "rejection_reasons",
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


def _normalized_label(value: Any) -> str:
    return " ".join(TOKEN_PATTERN.findall(str(value or "").lower()))


def _generic_token_hits(label: str) -> list[str]:
    tokens = set(TOKEN_PATTERN.findall(label))
    return sorted(token for token in GENERIC_CONCEPT_TOKENS if token in tokens)


def _classify_title_only_row(record: dict[str, Any]) -> tuple[str, str, list[str]]:
    target = dict(record.get("target") or {})
    target_type = str(target.get("type") or "").strip()
    target_id = str(target.get("id") or "").strip().lower()
    label = _normalized_label(target.get("label"))

    if target_type in {"Task", "Region"}:
        return (
            "salvage_task_or_region",
            "specific_task_or_region_target",
            [target_type.lower()],
        )

    if target_type != "Concept":
        return (
            "review_miscellaneous",
            "unexpected_non_task_region_concept_type",
            [target_type.lower() or "missing_type"],
        )

    if target_id in GabrielMeasurementLoader.TITLE_ONLY_GENERIC_CONCEPT_IDS:
        return (
            "generic_concept_remainder",
            "title_generic_exact_id",
            [target_id],
        )

    phrase_hits = [phrase for phrase in GENERIC_CONCEPT_PHRASES if phrase in label]
    token_hits = _generic_token_hits(label)
    token_count = len(TOKEN_PATTERN.findall(label))
    if phrase_hits:
        return (
            "generic_concept_remainder",
            "generic_concept_phrase_match",
            phrase_hits,
        )
    if len(token_hits) >= 2 and token_count <= 5:
        return (
            "generic_concept_remainder",
            "dense_generic_concept_tokens",
            token_hits,
        )
    if token_hits and label.startswith(("neural ", "brain ", "functional ", "effective ")):
        return (
            "generic_concept_remainder",
            "generic_concept_prefix",
            token_hits,
        )
    return (
        "substantive_concept_hold",
        "substantive_concept_title_row",
        token_hits,
    )


def _row_identity(record: dict[str, Any]) -> dict[str, str]:
    paper = dict(record.get("paper") or {})
    claim = dict(record.get("claim") or {})
    run = dict(record.get("run") or {})
    target = dict(record.get("target") or {})
    return {
        "paper_id": str(paper.get("id") or "").strip(),
        "paper_title": str(paper.get("title") or "").strip(),
        "claim_id": str(claim.get("id") or "").strip(),
        "run_id": str(run.get("run_id") or "").strip(),
        "target_type": str(target.get("type") or "").strip(),
        "target_id": str(target.get("id") or "").strip(),
        "target_label": str(target.get("label") or "").strip(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    review_queue_path = args.review_queue.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    quality_profile = str(args.quality_profile or "balanced_marginal").strip().lower()
    thresholds = GabrielMeasurementLoader.QUALITY_PROFILES[quality_profile]

    rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    reason_combo_counts: Counter[tuple[str, ...]] = Counter()
    type_counts: Counter[str] = Counter()

    for item in _iter_jsonl(review_queue_path):
        record = dict(item.get("record") or {})
        variables = compute_gabriel_variables(record)
        _accepted, reasons = evaluate_high_precision_gate(variables, thresholds=thresholds)
        reasons = GabrielMeasurementLoader._apply_review_only_overrides(
            record,
            variables,
            list(reasons),
            quality_profile=quality_profile,
        )
        routing = GabrielMeasurementLoader._determine_review_routing(
            record,
            reasons,
            quality_profile=quality_profile,
        )
        if "benchmark_title_only_suppressed" not in reasons:
            continue
        if routing is not None:
            continue

        review_bucket, bucket_reason, signal_hits = _classify_title_only_row(record)
        identity = _row_identity(record)
        row = {
            **identity,
            "review_bucket": review_bucket,
            "bucket_reason": bucket_reason,
            "signal_hits": signal_hits,
            "method_rigor": round(float(variables.method_rigor), 4),
            "mapping_confidence": round(float(variables.mapping_confidence), 4),
            "claim_strength": round(float(variables.claim_strength), 4),
            "evidence_quality": str(variables.evidence_quality),
            "evidence_section": str(
                (record.get("evidence") or {}).get("section") or ""
            ).strip(),
            "rejection_reasons": list(reasons),
        }
        rows.append(row)
        bucket_counts[review_bucket] += 1
        type_counts[identity["target_type"]] += 1
        reason_combo_counts[tuple(sorted(reasons))] += 1

    rows.sort(
        key=lambda row: (
            row["review_bucket"],
            row["target_type"],
            row["target_label"].lower(),
            row["paper_id"],
        )
    )

    _write_jsonl(output_dir / "title_only_review_pack.jsonl", rows)
    _write_tsv(output_dir / "title_only_review_pack.tsv", rows)
    for bucket in (
        "salvage_task_or_region",
        "substantive_concept_hold",
        "generic_concept_remainder",
        "review_miscellaneous",
    ):
        bucket_rows = [row for row in rows if row["review_bucket"] == bucket]
        _write_jsonl(output_dir / f"{bucket}.jsonl", bucket_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "review_queue_path": str(review_queue_path),
        "quality_profile": quality_profile,
        "counts": {
            "title_only_rows_reviewed": len(rows),
            "salvage_task_or_region": bucket_counts["salvage_task_or_region"],
            "substantive_concept_hold": bucket_counts["substantive_concept_hold"],
            "generic_concept_remainder": bucket_counts["generic_concept_remainder"],
            "review_miscellaneous": bucket_counts["review_miscellaneous"],
        },
        "counts_by_target_type": dict(type_counts),
        "counts_by_reason_combo": [
            [list(combo), count] for combo, count in reason_combo_counts.most_common()
        ],
        "counts_by_target_label": [
            [row_type, row_label, count]
            for (row_type, row_label), count in Counter(
                (row["target_type"], row["target_label"]) for row in rows
            ).most_common()
        ],
        "artifacts": {
            "review_pack_jsonl": str(output_dir / "title_only_review_pack.jsonl"),
            "review_pack_tsv": str(output_dir / "title_only_review_pack.tsv"),
            "summary_json": str(output_dir / "title_only_review_summary.json"),
        },
    }
    (output_dir / "title_only_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
