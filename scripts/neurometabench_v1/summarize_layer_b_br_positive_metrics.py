"""Summarize BR-positive Layer B metrics from diagnostic rows.

This script is post-hoc. It reads one or more diagnostic CSV files produced by
``derive_layer_b_diagnostics.py`` and, optionally, replacement diagnostic rows
for targeted retries. It does not rerun agents or mutate evaluator outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


APPROVED_ANCHOR_FIELDS = {
    "study_id",
    "study_pmid",
    "doi",
    "pmcid",
    "source_asset",
    "source_file",
    "sample_size",
    "coordinate_space",
    "original_study_ids",
    "analysis_id",
}

SAFE_ANCHOR_TARGETS = {
    "spatial_report.md",
    "provenance_manifest.json",
    "br_reconciliation_anchors.json",
}

CORE_SCIENCE_TABLES = {
    "coordinate_table.csv",
    "included_studies.csv",
}


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _row_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("condition", ""), row.get("meta_pmid", ""))


def _pair_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("system_key", ""), row.get("meta_pmid", ""))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _science_gate_pass(row: dict[str, str]) -> bool:
    return (
        _bool(row.get("map_generated"))
        and not _bool(row.get("degraded_fallback_map"))
        and _float(row.get("local_study_set_f1")) >= 0.98
        and _float(row.get("coordinate_canonical_f1")) >= 0.98
        and _float(row.get("spatial_correlation")) >= 0.80
        and _float(row.get("dice_top5")) >= 0.50
    )


def _load_anchors(case_output_dir: str) -> list[dict[str, Any]]:
    if not case_output_dir:
        return []
    path = Path(case_output_dir) / "br_reconciliation_anchors.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    anchors = data.get("anchors", [])
    if not isinstance(anchors, list):
        return []
    return [a for a in anchors if isinstance(a, dict)]


def _artifact_text(case_dir: Path, target_artifact: str) -> str:
    target = Path(target_artifact)
    if not target.is_absolute():
        target = case_dir / target_artifact
    if not target.exists() or not target.is_file():
        return ""
    try:
        return target.read_text(errors="replace")
    except Exception:
        return ""


def _anchor_is_valid(anchor: dict[str, Any]) -> bool:
    return (
        str(anchor.get("target_artifact", "")).strip() != ""
        and str(anchor.get("target_field", "")).strip() in APPROVED_ANCHOR_FIELDS
        and str(anchor.get("canonical_value", "")).strip() != ""
        and str(anchor.get("evidence_source", "")).strip() != ""
        and str(anchor.get("confidence", "")).strip() != ""
    )


def _anchor_is_consumed(case_dir: Path, anchor: dict[str, Any]) -> bool:
    value = str(anchor.get("canonical_value", "")).strip()
    if not value:
        return False
    target_artifact = str(anchor.get("target_artifact", "")).strip()
    target_text = _artifact_text(case_dir, target_artifact)
    if value in target_text:
        return True
    # Some agents consume audit-only anchors in report/provenance even when the
    # target artifact is imprecise. Count these as consumed but keep the exact
    # target-field checks separate.
    for fallback in ("spatial_report.md", "provenance_manifest.json"):
        if value in _artifact_text(case_dir, fallback):
            return True
    return False


def _anchor_is_report_linked(anchor: dict[str, Any], consumed: bool) -> bool:
    if not consumed:
        return False
    target = Path(str(anchor.get("target_artifact", ""))).name
    return target == "spatial_report.md"


def _anchor_is_safe(anchor: dict[str, Any], consumed: bool) -> bool:
    if not consumed:
        return False
    target = Path(str(anchor.get("target_artifact", ""))).name
    changed = _bool(anchor.get("changed_bundle"))
    if target in SAFE_ANCHOR_TARGETS:
        return True
    if target in CORE_SCIENCE_TABLES:
        # A consumed anchor into a science table is only considered safe when it
        # is audit-only. Whether it filled a genuinely blank value is not
        # instrumented in current rows, so changed core-table writes stay unsafe.
        return not changed
    return True


def _anchor_stats(row: dict[str, str]) -> dict[str, Any]:
    case_dir = Path(row.get("case_output_dir", ""))
    anchors = _load_anchors(row.get("case_output_dir", ""))
    valid = []
    consumed = []
    report_linked = []
    safe = []
    unsafe_core = []
    fields = Counter()
    consumed_fields = Counter()
    for anchor in anchors:
        if _anchor_is_valid(anchor):
            valid.append(anchor)
            fields[str(anchor.get("target_field"))] += 1
            is_consumed = _anchor_is_consumed(case_dir, anchor)
            if is_consumed:
                consumed.append(anchor)
                consumed_fields[str(anchor.get("target_field"))] += 1
            if _anchor_is_report_linked(anchor, is_consumed):
                report_linked.append(anchor)
            if _anchor_is_safe(anchor, is_consumed):
                safe.append(anchor)
            else:
                target = Path(str(anchor.get("target_artifact", ""))).name
                if is_consumed and target in CORE_SCIENCE_TABLES:
                    unsafe_core.append(anchor)
    return {
        "anchor_count": len(anchors),
        "valid_anchor_count": len(valid),
        "consumed_valid_anchor_count": len(consumed),
        "report_linked_anchor_count": len(report_linked),
        "safe_consumed_anchor_count": len(safe),
        "unsafe_core_consumed_anchor_count": len(unsafe_core),
        "fields": dict(fields),
        "consumed_fields": dict(consumed_fields),
    }


def _rate(numer: float, denom: float) -> float | None:
    if denom <= 0:
        return None
    return numer / denom


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.3f}"


def _metric_delta(with_row: dict[str, str], without_row: dict[str, str], key: str) -> float:
    return _float(with_row.get(key)) - _float(without_row.get(key))


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    for row in rows:
        row["_science_gate_pass"] = "true" if _science_gate_pass(row) else "false"
        row["_anchor_stats"] = _anchor_stats(row)

    with_br = [r for r in rows if r.get("br_condition") == "with_br"]
    without_br = [r for r in rows if r.get("br_condition") == "without_br"]
    science_with_br = [r for r in with_br if _bool(r.get("_science_gate_pass"))]

    anchor_totals = Counter()
    field_row_coverage: dict[str, int] = Counter()
    consumed_field_row_coverage: dict[str, int] = Counter()
    for row in science_with_br:
        stats = row["_anchor_stats"]
        anchor_totals["anchors"] += stats["anchor_count"]
        anchor_totals["valid"] += stats["valid_anchor_count"]
        anchor_totals["consumed"] += stats["consumed_valid_anchor_count"]
        anchor_totals["report_linked"] += stats["report_linked_anchor_count"]
        anchor_totals["safe_consumed"] += stats["safe_consumed_anchor_count"]
        anchor_totals["unsafe_core_consumed"] += stats[
            "unsafe_core_consumed_anchor_count"
        ]
        for field in stats["fields"]:
            field_row_coverage[field] += 1
        for field in stats["consumed_fields"]:
            consumed_field_row_coverage[field] += 1

    by_pair: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_pair[_pair_key(row)][row.get("br_condition", "")] = row
    pairs = [
        (key, pair["with_br"], pair["without_br"])
        for key, pair in by_pair.items()
        if "with_br" in pair and "without_br" in pair
    ]
    science_pairs = [
        (key, with_row, without_row)
        for key, with_row, without_row in pairs
        if _bool(with_row.get("_science_gate_pass"))
    ]

    delta_specs = [
        ("Public Identifier Resolution Gain", "public_identifier_coverage"),
        ("Source Asset Traceability Gain", "source_provenance_coverage"),
        ("Original/Local Study ID Preservation Gain", "local_identifier_coverage"),
        ("Sample Size Provenance Gain", "sample_size_coverage"),
        ("Cross-Artifact Claim Consistency Gain", "claim_consistency_score"),
        ("Overall Study/Source Reconciliation Gain", "br_reconciliation_score"),
    ]
    deltas = []
    for label, col in delta_specs:
        values = [_metric_delta(w, wo, col) for _, w, wo in science_pairs]
        deltas.append(
            {
                "metric": label,
                "column": col,
                "pairs": len(values),
                "mean_delta": sum(values) / len(values) if values else None,
                "positive_pairs": sum(v > 1e-9 for v in values),
                "negative_pairs": sum(v < -1e-9 for v in values),
                "tie_pairs": sum(abs(v) <= 1e-9 for v in values),
                "max_delta": max(values) if values else None,
                "min_delta": min(values) if values else None,
            }
        )

    systems: dict[str, dict[str, Any]] = {}
    for system in sorted({r.get("system", "") for r in rows}):
        sys_with = [r for r in with_br if r.get("system") == system]
        sys_science = [r for r in science_with_br if r.get("system") == system]
        sys_pairs = [
            (w, wo)
            for _, w, wo in science_pairs
            if w.get("system") == system
        ]
        systems[system] = {
            "with_br_rows": len(sys_with),
            "science_gate_pass": sum(_bool(r.get("_science_gate_pass")) for r in sys_with),
            "strict_success": sum(_bool(r.get("correct_strict")) for r in sys_with),
            "br_effective_use_pass": sum(
                _bool(r.get("br_effective_use_pass")) for r in sys_science
            ),
            "valid_anchor_rate": _rate(
                sum(r["_anchor_stats"]["valid_anchor_count"] for r in sys_science),
                sum(r["_anchor_stats"]["anchor_count"] for r in sys_science),
            ),
            "consumed_anchor_rate": _rate(
                sum(r["_anchor_stats"]["consumed_valid_anchor_count"] for r in sys_science),
                sum(r["_anchor_stats"]["valid_anchor_count"] for r in sys_science),
            ),
            "safe_consumed_anchor_rate": _rate(
                sum(r["_anchor_stats"]["safe_consumed_anchor_count"] for r in sys_science),
                sum(r["_anchor_stats"]["consumed_valid_anchor_count"] for r in sys_science),
            ),
            "mean_reconciliation_delta": (
                sum(_metric_delta(w, wo, "br_reconciliation_score") for w, wo in sys_pairs)
                / len(sys_pairs)
                if sys_pairs
                else None
            ),
        }

    return {
        "row_counts": {
            "rows": len(rows),
            "with_br_rows": len(with_br),
            "without_br_rows": len(without_br),
            "paired_cells": len(pairs),
            "science_gated_with_br_rows": len(science_with_br),
            "strict_with_br_rows": sum(_bool(r.get("correct_strict")) for r in with_br),
            "strict_without_br_rows": sum(_bool(r.get("correct_strict")) for r in without_br),
        },
        "evidence_pipeline": {
            "br_retrieval_or_audit_present_rate": _rate(
                sum(
                    _bool(r.get("br_trace_retrieved_or_audited_anchor_present"))
                    for r in science_with_br
                ),
                len(science_with_br),
            ),
            "br_effective_use_rate": _rate(
                sum(_bool(r.get("br_effective_use_pass")) for r in science_with_br),
                len(science_with_br),
            ),
            "valid_br_anchor_rate": _rate(
                anchor_totals["valid"], anchor_totals["anchors"]
            ),
            "consumed_valid_br_anchor_rate": _rate(
                anchor_totals["consumed"], anchor_totals["valid"]
            ),
            "report_linked_br_anchor_rate": _rate(
                anchor_totals["report_linked"], anchor_totals["consumed"]
            ),
            "safe_consumed_br_anchor_rate": _rate(
                anchor_totals["safe_consumed"], anchor_totals["consumed"]
            ),
            "anchor_totals": dict(anchor_totals),
        },
        "field_mapping": {
            "row_denominator": len(science_with_br),
            "valid_anchor_field_row_coverage": dict(sorted(field_row_coverage.items())),
            "consumed_anchor_field_row_coverage": dict(
                sorted(consumed_field_row_coverage.items())
            ),
        },
        "paired_reconciliation_deltas": deltas,
        "by_system": systems,
    }


def write_csv(summary: dict[str, Any], output_csv: Path) -> None:
    rows = []
    pipeline = summary["evidence_pipeline"]
    for key, value in pipeline.items():
        if key == "anchor_totals":
            continue
        rows.append({"section": "evidence_pipeline", "metric": key, "value": value})
    for item in summary["paired_reconciliation_deltas"]:
        rows.append(
            {
                "section": "paired_reconciliation_delta",
                "metric": item["metric"],
                "value": item["mean_delta"],
                "positive_pairs": item["positive_pairs"],
                "negative_pairs": item["negative_pairs"],
                "tie_pairs": item["tie_pairs"],
                "pairs": item["pairs"],
            }
        )
    for field, count in summary["field_mapping"][
        "consumed_anchor_field_row_coverage"
    ].items():
        rows.append(
            {
                "section": "consumed_anchor_field_coverage",
                "metric": field,
                "value": count,
                "pairs": summary["field_mapping"]["row_denominator"],
            }
        )
    with output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "section",
                "metric",
                "value",
                "positive_pairs",
                "negative_pairs",
                "tie_pairs",
                "pairs",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_md(summary: dict[str, Any], output_md: Path) -> None:
    counts = summary["row_counts"]
    pipeline = summary["evidence_pipeline"]
    field_mapping = summary["field_mapping"]
    lines = [
        "# Layer B BR-Positive Metrics",
        "",
        "Post-hoc summary from diagnostic CSV rows. Agents were not rerun.",
        "",
        "## Row Counts",
        "",
        f"- Rows: `{counts['rows']}`",
        f"- Paired system-case cells: `{counts['paired_cells']}`",
        f"- With-BR rows: `{counts['with_br_rows']}`",
        f"- Science-gated with-BR rows: `{counts['science_gated_with_br_rows']}`",
        f"- Strict with-BR rows: `{counts['strict_with_br_rows']}`",
        f"- Strict without-BR rows: `{counts['strict_without_br_rows']}`",
        "",
        "## Evidence Pipeline Metrics",
        "",
        "| Metric | Value | Numerator / denominator |",
        "|---|---:|---:|",
    ]
    totals = pipeline["anchor_totals"]
    pipeline_rows = [
        (
            "BR retrieval/audit evidence present rate",
            pipeline["br_retrieval_or_audit_present_rate"],
            "",
        ),
        ("BR effective use rate", pipeline["br_effective_use_rate"], ""),
        (
            "Valid BR anchor rate",
            pipeline["valid_br_anchor_rate"],
            f"{totals.get('valid', 0)} / {totals.get('anchors', 0)}",
        ),
        (
            "Consumed valid BR anchor rate",
            pipeline["consumed_valid_br_anchor_rate"],
            f"{totals.get('consumed', 0)} / {totals.get('valid', 0)}",
        ),
        (
            "Report-linked consumed BR anchor rate",
            pipeline["report_linked_br_anchor_rate"],
            f"{totals.get('report_linked', 0)} / {totals.get('consumed', 0)}",
        ),
        (
            "Safe consumed BR anchor rate",
            pipeline["safe_consumed_br_anchor_rate"],
            f"{totals.get('safe_consumed', 0)} / {totals.get('consumed', 0)}",
        ),
    ]
    for label, value, frac in pipeline_rows:
        lines.append(f"| {label} | {_fmt_rate(value)} | {frac} |")

    lines.extend(
        [
            "",
            "## Consumed Anchor Field Coverage",
            "",
            f"Denominator: `{field_mapping['row_denominator']}` science-gated with-BR rows.",
            "",
            "| Target field | Rows with consumed anchor | Rate |",
            "|---|---:|---:|",
        ]
    )
    denom = field_mapping["row_denominator"]
    for field, count in field_mapping["consumed_anchor_field_row_coverage"].items():
        lines.append(f"| {field} | {count} | {_fmt_rate(_rate(count, denom))} |")

    lines.extend(
        [
            "",
            "## Paired Reconciliation Deltas",
            "",
            "Deltas are computed as `with-BR - without-BR` over pairs whose with-BR row passes the science gate.",
            "",
            "| Metric | Mean delta | Positive | Negative | Tie | Pairs |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["paired_reconciliation_deltas"]:
        lines.append(
            "| {metric} | {delta} | {pos} | {neg} | {tie} | {pairs} |".format(
                metric=item["metric"],
                delta=_fmt_rate(item["mean_delta"]),
                pos=item["positive_pairs"],
                neg=item["negative_pairs"],
                tie=item["tie_pairs"],
                pairs=item["pairs"],
            )
        )

    lines.extend(
        [
            "",
            "## By System",
            "",
            "| System | With-BR rows | Science gate | Strict | BR effective | Valid anchor | Consumed anchor | Safe consumed | Recon delta |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for system, item in summary["by_system"].items():
        lines.append(
            "| {system} | {rows} | {science} | {strict} | {br_eff} | {valid} | {consumed} | {safe} | {delta} |".format(
                system=system,
                rows=item["with_br_rows"],
                science=item["science_gate_pass"],
                strict=item["strict_success"],
                br_eff=item["br_effective_use_pass"],
                valid=_fmt_rate(item["valid_anchor_rate"]),
                consumed=_fmt_rate(item["consumed_anchor_rate"]),
                safe=_fmt_rate(item["safe_consumed_anchor_rate"]),
                delta=_fmt_rate(item["mean_reconciliation_delta"]),
            )
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Positive BR metrics are gated on the with-BR row preserving scientific reproduction.",
            "- Report-linked consumed anchors are a current proxy for claim-linked evidence; explicit claim-to-anchor IDs are not instrumented yet.",
            "- Source/study reconciliation submetrics use currently exported coverage columns; field-specific anchor coverage is reported separately.",
            "",
        ]
    )
    output_md.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-csv", action="append", required=True)
    parser.add_argument(
        "--replacement-csv",
        action="append",
        default=[],
        help="Diagnostic CSV rows that replace rows with matching condition/meta_pmid.",
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for raw_path in args.diagnostic_csv:
        for row in _read_csv_rows(Path(raw_path)):
            rows_by_key[_row_key(row)] = row
    for raw_path in args.replacement_csv:
        for row in _read_csv_rows(Path(raw_path)):
            rows_by_key[_row_key(row)] = row

    rows = list(rows_by_key.values())
    summary = summarize(rows)

    output_json = Path(args.output_json)
    output_csv = Path(args.output_csv)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2, sort_keys=True))
    write_csv(summary, output_csv)
    write_md(summary, output_md)
    print(
        json.dumps(
            {
                "rows": summary["row_counts"]["rows"],
                "paired_cells": summary["row_counts"]["paired_cells"],
                "science_gated_with_br_rows": summary["row_counts"][
                    "science_gated_with_br_rows"
                ],
                "output_json": str(output_json),
                "output_csv": str(output_csv),
                "output_md": str(output_md),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
