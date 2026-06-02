"""Summarize Layer B final-artifact quality metrics.

Unlike BR-anchor/compliance summaries, this script deliberately ignores
``br_reconciliation_anchors.json``. The goal is to compare final artifacts that
both with-BR and without-BR agents could produce: provenance manifests, reports,
metrics, study tables, coordinate tables, and maps.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _rate(numer: float, denom: float) -> float | None:
    if denom <= 0:
        return None
    return numer / denom


def _fmt(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.3f}"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            return list(reader.fieldnames or []), list(reader)
    except Exception:
        return [], []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _json_text(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(data)


def _final_artifact_text(case_dir: Path) -> str:
    parts: list[str] = []
    for name in (
        "metrics.json",
        "provenance_manifest.json",
        "spatial_report.md",
        "included_studies.csv",
        "coordinate_table.csv",
    ):
        path = case_dir / name
        if path.exists() and path.is_file():
            try:
                parts.append(path.read_text(errors="replace"))
            except Exception:
                pass
    return "\n".join(parts)


def _flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            out.extend(_flatten_strings(k))
            out.extend(_flatten_strings(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_flatten_strings(v))
    return out


def _metric_bool(metrics: dict[str, Any], row: dict[str, str], key: str) -> bool:
    if key in metrics:
        parsed = _bool(metrics.get(key))
        if parsed is not None:
            return parsed
    parsed = _bool(row.get(key))
    return bool(parsed)


def _science_equivalent(row: dict[str, str], metrics: dict[str, Any]) -> bool:
    # Prefer the producer metrics JSON for map_generated/degraded flags because
    # older fallback text scans can false-positive on "Degraded fallback: False".
    map_generated = _metric_bool(metrics, row, "map_generated")
    degraded = _metric_bool(metrics, row, "degraded_fallback_map")
    return (
        map_generated
        and not degraded
        and _float(row.get("local_study_set_f1")) >= 0.98
        and _float(row.get("coordinate_canonical_f1")) >= 0.98
        and _float(row.get("spatial_correlation")) >= 0.80
        and _float(row.get("dice_top5")) >= 0.50
    )


def _source_traceability_score(provenance: dict[str, Any], metrics: dict[str, Any]) -> tuple[float, dict[str, bool]]:
    source_blob = provenance.get("source_assets")
    source_used = provenance.get("source_assets_used")
    all_strings = _flatten_strings(source_blob) + _flatten_strings(source_used)
    joined = "\n".join(all_strings).lower()
    project_key = str(metrics.get("project_key") or "").strip()
    checks = {
        "source_assets_present": bool(source_blob or source_used),
        "case_manifest_named": "case.json" in joined or "input_manifest.json" in joined,
        "nimads_source_named": "nimads" in joined
        or "nimads_studyset" in joined
        or "nimads_annotation" in joined,
        "source_dataset_or_project_named": bool(project_key)
        or "raw_json" in joined
        or "merged" in joined
        or any(s.endswith(".json") and "case.json" not in s and "input_manifest.json" not in s for s in all_strings),
    }
    return sum(checks.values()) / len(checks), checks


def _coordinate_space_score(
    coord_header: list[str],
    coord_rows: list[dict[str, str]],
    metrics: dict[str, Any],
    text: str,
) -> tuple[float, dict[str, bool]]:
    space_cols = [c for c in coord_header if c.lower() in {"space", "coordinate_space", "source_space"}]
    filled_rate = 0.0
    if space_cols and coord_rows:
        col = space_cols[0]
        filled_rate = sum(bool(str(r.get(col, "")).strip()) for r in coord_rows) / len(coord_rows)
    checks = {
        "coordinate_table_space_filled": filled_rate >= 0.95,
        "metrics_source_coordinate_spaces_present": bool(metrics.get("source_coordinate_spaces")),
        "report_or_provenance_mentions_space": bool(
            re.search(r"\b(MNI|MNI152|TAL|Talairach|coordinate[_ -]?space)\b", text, re.I)
        ),
    }
    return sum(checks.values()) / len(checks), checks


def _sample_size_score(
    coord_header: list[str],
    coord_rows: list[dict[str, str]],
    text: str,
) -> tuple[float, dict[str, bool]]:
    sample_cols = [c for c in coord_header if c.lower() in {"sample_size", "sample_n", "n"}]
    filled_rate = 0.0
    if sample_cols and coord_rows:
        col = sample_cols[0]
        filled_rate = sum(bool(str(r.get(col, "")).strip()) for r in coord_rows) / len(coord_rows)
    checks = {
        "coordinate_table_sample_size_filled": filled_rate >= 0.95,
        "report_or_provenance_mentions_sample_size": bool(
            re.search(r"\b(sample[_ -]?size|sample_n|\\bN\\s*=)", text, re.I)
        ),
    }
    return sum(checks.values()) / len(checks), checks


def _public_identifier_score(text: str) -> tuple[float, dict[str, bool]]:
    checks = {
        "pmid_label_present": bool(re.search(r"\b(PMID|study_pmid|meta_pmid)\b", text)),
        "doi_present": bool(re.search(r"\bdoi\b|10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text, re.I)),
        "pmcid_present": bool(re.search(r"\bPMC\d+\b|\bpmcid\b", text, re.I)),
    }
    return sum(checks.values()) / len(checks), checks


def _artifact_consistency_score(
    inc_rows: list[dict[str, str]],
    coord_rows: list[dict[str, str]],
    metrics: dict[str, Any],
    text: str,
) -> tuple[float, dict[str, bool]]:
    coord_count = len(coord_rows)
    study_count = len(inc_rows)

    metric_coord_values = [
        metrics.get("coordinate_rows"),
        metrics.get("n_coordinate_rows"),
        (metrics.get("ale") or {}).get("n_dataset_coordinates")
        if isinstance(metrics.get("ale"), dict)
        else None,
    ]
    metric_study_values = [
        metrics.get("study_rows"),
        metrics.get("n_included_studies"),
        metrics.get("n_nimads_studies"),
    ]

    def has_count(values: list[Any], expected: int) -> bool:
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                if int(float(str(value))) == expected:
                    return True
            except Exception:
                continue
        return False

    checks = {
        "metrics_coordinate_count_matches_csv": has_count(metric_coord_values, coord_count),
        "metrics_study_count_matches_csv": has_count(metric_study_values, study_count),
        "report_mentions_coordinate_count": str(coord_count) in text,
        "report_mentions_study_count": str(study_count) in text,
    }
    return sum(checks.values()) / len(checks), checks


def _score_row(row: dict[str, str]) -> dict[str, Any]:
    case_dir = Path(row.get("case_output_dir", ""))
    inc_header, inc_rows = _read_table(case_dir / "included_studies.csv")
    coord_header, coord_rows = _read_table(case_dir / "coordinate_table.csv")
    metrics = _read_json(case_dir / "metrics.json")
    provenance = _read_json(case_dir / "provenance_manifest.json")
    text = _final_artifact_text(case_dir)

    source_score, source_checks = _source_traceability_score(provenance, metrics)
    space_score, space_checks = _coordinate_space_score(coord_header, coord_rows, metrics, text)
    sample_score, sample_checks = _sample_size_score(coord_header, coord_rows, text)
    public_id_score, public_id_checks = _public_identifier_score(text)
    consistency_score, consistency_checks = _artifact_consistency_score(
        inc_rows, coord_rows, metrics, text
    )

    final_quality_score = (
        0.25 * source_score
        + 0.20 * space_score
        + 0.15 * sample_score
        + 0.15 * public_id_score
        + 0.25 * consistency_score
    )

    return {
        "condition": row.get("condition"),
        "system_key": row.get("system_key"),
        "system": row.get("system"),
        "br_condition": row.get("br_condition"),
        "meta_pmid": row.get("meta_pmid"),
        "topic": row.get("topic"),
        "case_output_dir": row.get("case_output_dir"),
        "science_equivalent": _science_equivalent(row, metrics),
        "strict_success": _bool(row.get("correct_strict")) is True,
        "source_traceability_score": source_score,
        "coordinate_space_documentation_score": space_score,
        "sample_size_documentation_score": sample_score,
        "public_identifier_documentation_score": public_id_score,
        "artifact_count_consistency_score": consistency_score,
        "final_artifact_quality_score": final_quality_score,
        "checks": {
            "source_traceability": source_checks,
            "coordinate_space": space_checks,
            "sample_size": sample_checks,
            "public_identifier": public_id_checks,
            "artifact_consistency": consistency_checks,
        },
    }


def _key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("condition", ""), row.get("meta_pmid", ""))


def _pair_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row.get("system_key", ""), row.get("meta_pmid", ""))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _delta_summary(pairs: list[tuple[dict[str, Any], dict[str, Any]]], metric: str) -> dict[str, Any]:
    values = [with_row[metric] - without_row[metric] for with_row, without_row in pairs]
    return {
        "metric": metric,
        "pairs": len(values),
        "mean_with": _mean([w[metric] for w, _ in pairs]),
        "mean_without": _mean([wo[metric] for _, wo in pairs]),
        "mean_delta": _mean(values),
        "positive_pairs": sum(v > 1e-9 for v in values),
        "negative_pairs": sum(v < -1e-9 for v in values),
        "tie_pairs": sum(abs(v) <= 1e-9 for v in values),
        "max_delta": max(values) if values else None,
        "min_delta": min(values) if values else None,
    }


def summarize(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in scored_rows:
        by_pair[_pair_key(row)][row.get("br_condition", "")] = row
    pairs = [
        (pair["with_br"], pair["without_br"])
        for pair in by_pair.values()
        if "with_br" in pair and "without_br" in pair
    ]
    science_gated_pairs = [p for p in pairs if p[0]["science_equivalent"]]

    metrics = [
        "source_traceability_score",
        "coordinate_space_documentation_score",
        "sample_size_documentation_score",
        "public_identifier_documentation_score",
        "artifact_count_consistency_score",
        "final_artifact_quality_score",
    ]

    system_rows: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in science_gated_pairs:
        system_rows[pair[0].get("system", "")].append(pair)

    return {
        "row_counts": {
            "rows": len(scored_rows),
            "paired_cells": len(pairs),
            "science_gated_pairs": len(science_gated_pairs),
            "with_br_science_equivalent": sum(
                row["science_equivalent"]
                for row in scored_rows
                if row.get("br_condition") == "with_br"
            ),
            "without_br_science_equivalent": sum(
                row["science_equivalent"]
                for row in scored_rows
                if row.get("br_condition") == "without_br"
            ),
            "with_br_strict_success": sum(
                row["strict_success"]
                for row in scored_rows
                if row.get("br_condition") == "with_br"
            ),
            "without_br_strict_success": sum(
                row["strict_success"]
                for row in scored_rows
                if row.get("br_condition") == "without_br"
            ),
        },
        "metric_deltas": [_delta_summary(science_gated_pairs, metric) for metric in metrics],
        "by_system": {
            system: {
                "pairs": len(pairs_for_system),
                "final_artifact_quality_delta": _delta_summary(
                    pairs_for_system, "final_artifact_quality_score"
                ),
                "source_traceability_delta": _delta_summary(
                    pairs_for_system, "source_traceability_score"
                ),
                "coordinate_space_delta": _delta_summary(
                    pairs_for_system, "coordinate_space_documentation_score"
                ),
            }
            for system, pairs_for_system in sorted(system_rows.items())
        },
    }


def write_rows_csv(scored_rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "condition",
        "system",
        "br_condition",
        "meta_pmid",
        "topic",
        "science_equivalent",
        "strict_success",
        "source_traceability_score",
        "coordinate_space_documentation_score",
        "sample_size_documentation_score",
        "public_identifier_documentation_score",
        "artifact_count_consistency_score",
        "final_artifact_quality_score",
        "case_output_dir",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in scored_rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_summary_csv(summary: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "metric",
                "pairs",
                "mean_with",
                "mean_without",
                "mean_delta",
                "positive_pairs",
                "negative_pairs",
                "tie_pairs",
            ],
        )
        writer.writeheader()
        for item in summary["metric_deltas"]:
            writer.writerow({k: item.get(k) for k in writer.fieldnames})


def write_md(summary: dict[str, Any], path: Path) -> None:
    labels = {
        "source_traceability_score": "Source traceability score",
        "coordinate_space_documentation_score": "Coordinate-space documentation score",
        "sample_size_documentation_score": "Sample-size documentation score",
        "public_identifier_documentation_score": "Public identifier documentation score",
        "artifact_count_consistency_score": "Artifact count consistency score",
        "final_artifact_quality_score": "Final artifact quality score",
    }
    counts = summary["row_counts"]
    lines = [
        "# Layer B Final Artifact Quality Metrics",
        "",
        "This summary ignores `br_reconciliation_anchors.json` and scores only final artifacts available to both with-BR and without-BR conditions.",
        "",
        "## Row Counts",
        "",
        f"- Rows: `{counts['rows']}`",
        f"- Paired system-case cells: `{counts['paired_cells']}`",
        f"- Science-gated pairs: `{counts['science_gated_pairs']}`",
        f"- With-BR science-equivalent rows: `{counts['with_br_science_equivalent']}`",
        f"- Without-BR science-equivalent rows: `{counts['without_br_science_equivalent']}`",
        f"- With-BR strict rows: `{counts['with_br_strict_success']}`",
        f"- Without-BR strict rows: `{counts['without_br_strict_success']}`",
        "",
        "## Paired Final Artifact Quality Deltas",
        "",
        "Deltas are `with-BR - without-BR`, restricted to pairs where the with-BR row preserves scientific reproduction.",
        "",
        "| Metric | With-BR mean | Without-BR mean | Mean delta | Positive | Negative | Tie | Pairs |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["metric_deltas"]:
        lines.append(
            "| {metric} | {with_mean} | {without_mean} | {delta} | {pos} | {neg} | {tie} | {pairs} |".format(
                metric=labels.get(item["metric"], item["metric"]),
                with_mean=_fmt(item["mean_with"]),
                without_mean=_fmt(item["mean_without"]),
                delta=_fmt(item["mean_delta"]),
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
            "| System | Pairs | Final quality delta | Source traceability delta | Coordinate-space delta |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for system, item in summary["by_system"].items():
        lines.append(
            "| {system} | {pairs} | {quality} | {source} | {space} |".format(
                system=system,
                pairs=item["pairs"],
                quality=_fmt(item["final_artifact_quality_delta"]["mean_delta"]),
                source=_fmt(item["source_traceability_delta"]["mean_delta"]),
                space=_fmt(item["coordinate_space_delta"]["mean_delta"]),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- These metrics are capability-adjacent because no BR-only anchor artifact is used.",
            "- They still reflect prompt and artifact-contract behavior; they are not pure model capability.",
            "- Public identifier and sample-size fields are sparse in current Layer B artifacts, so those columns should be interpreted as instrumentation-limited.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-csv", action="append", required=True)
    parser.add_argument("--replacement-csv", action="append", default=[])
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-rows-csv", required=True)
    parser.add_argument("--output-summary-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for raw_path in args.diagnostic_csv:
        for row in _read_csv_rows(Path(raw_path)):
            rows_by_key[_key(row)] = row
    for raw_path in args.replacement_csv:
        for row in _read_csv_rows(Path(raw_path)):
            rows_by_key[_key(row)] = row

    scored_rows = [_score_row(row) for row in rows_by_key.values()]
    summary = summarize(scored_rows)

    output_json = Path(args.output_json)
    output_rows_csv = Path(args.output_rows_csv)
    output_summary_csv = Path(args.output_summary_csv)
    output_md = Path(args.output_md)
    for p in (output_json, output_rows_csv, output_summary_csv, output_md):
        p.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps({"summary": summary, "rows": scored_rows}, indent=2, sort_keys=True)
    )
    write_rows_csv(scored_rows, output_rows_csv)
    write_summary_csv(summary, output_summary_csv)
    write_md(summary, output_md)
    print(
        json.dumps(
            {
                "rows": summary["row_counts"]["rows"],
                "paired_cells": summary["row_counts"]["paired_cells"],
                "science_gated_pairs": summary["row_counts"]["science_gated_pairs"],
                "output_json": str(output_json),
                "output_rows_csv": str(output_rows_csv),
                "output_summary_csv": str(output_summary_csv),
                "output_md": str(output_md),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
