#!/usr/bin/env python3
"""Build a Layer B study/coordinate mismatch autopsy table.

This script inspects existing Layer B comparison artifacts. It does not rerun
agents and does not modify producer bundles.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.run_layer_b_comparison import (
    COORDINATE_SPACE_FIELDS,
    _coordinate_counter,
    _coordinate_space_signature,
    _extract_local_study_ids,
    _first_row_value,
    _read_csv_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIR = (
    REPO_ROOT
    / "benchmarks"
    / "neurometabench"
    / "experiments"
    / "agent_condition_matrix"
    / "layer_b_medium_gemini_glm_codex_anchor_contract_20260507"
)
MISMATCH_AXES = {
    "local_study_set_pass": "local_study_set_mismatch",
    "coordinate_canonical_pass": "coordinate_canonical_mismatch",
    "scientific_similarity_pass": "scientific_similarity_failed",
}


def _repo_path(path: str | Path | None) -> Path | None:
    if path is None or str(path).strip() == "":
        return None
    out = Path(path)
    if not out.is_absolute():
        out = REPO_ROOT / out
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _as_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() == "true"


def _comparison_case_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    cases: dict[tuple[str, str], dict[str, Any]] = {}
    for condition in summary.get("conditions", []):
        condition_name = str(condition.get("name") or "")
        for case in condition.get("cases", []):
            meta_pmid = str(case.get("meta_pmid") or "")
            if condition_name and meta_pmid:
                cases[(condition_name, meta_pmid)] = case
    return cases


def _control_case_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}
    for condition in summary.get("conditions", []):
        if condition.get("name") != "pure_nimare":
            continue
        for case in condition.get("cases", []):
            meta_pmid = str(case.get("meta_pmid") or "")
            if meta_pmid:
                controls[meta_pmid] = case
    return controls


def _artifact_path(case: dict[str, Any] | None, artifact: str) -> Path | None:
    if not case:
        return None
    info = (case.get("required_artifacts") or {}).get(artifact) or {}
    return _repo_path(info.get("path"))


def _schema(path: Path | None) -> list[str]:
    fields, _rows = _read_csv_rows(path)
    return fields


def _examples(values: set[Any], limit: int) -> list[Any]:
    return sorted(values, key=lambda item: str(item))[:limit]


def _counter_keys(counter: Counter[tuple[str, ...]]) -> set[tuple[str, ...]]:
    return set(counter.keys())


def _space_alias_examples(path: Path | None, *, limit: int) -> list[dict[str, Any]]:
    _fields, rows = _read_csv_rows(path)
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        raw = (_first_row_value(row, COORDINATE_SPACE_FIELDS) or "").strip()
        if raw:
            counts[(raw, _coordinate_space_signature(raw))] += 1
    return [
        {"raw": raw, "normalized": normalized, "count": count}
        for (raw, normalized), count in counts.most_common(limit)
    ]


def _coordinate_mismatch_summary(
    *,
    predicted_path: Path | None,
    control_path: Path | None,
    limit: int,
) -> dict[str, Any]:
    predicted = _coordinate_counter(predicted_path)
    control = _coordinate_counter(control_path)
    predicted_keys = _counter_keys(predicted)
    control_keys = _counter_keys(control)
    predicted_only = predicted_keys - control_keys
    control_only = control_keys - predicted_keys

    predicted_by_xyz_space: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    control_by_xyz_space: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for signature in predicted_only:
        predicted_by_xyz_space.setdefault(signature[2:], []).append(signature)
    for signature in control_only:
        control_by_xyz_space.setdefault(signature[2:], []).append(signature)

    same_xyz_space_keys = set(predicted_by_xyz_space) & set(control_by_xyz_space)
    same_xyz_space_examples = []
    for xyz_space in sorted(same_xyz_space_keys, key=str)[:limit]:
        same_xyz_space_examples.append(
            {
                "xyz_space": list(xyz_space),
                "predicted_signatures": [
                    list(item)
                    for item in sorted(predicted_by_xyz_space[xyz_space], key=str)[:limit]
                ],
                "control_signatures": [
                    list(item)
                    for item in sorted(control_by_xyz_space[xyz_space], key=str)[:limit]
                ],
            }
        )

    return {
        "n_predicted_unique": len(predicted_keys),
        "n_control_unique": len(control_keys),
        "n_predicted_only": len(predicted_only),
        "n_control_only": len(control_only),
        "n_same_xyz_space_but_key_mismatch": len(same_xyz_space_keys),
        "predicted_only_examples": [list(item) for item in _examples(predicted_only, limit)],
        "control_only_examples": [list(item) for item in _examples(control_only, limit)],
        "same_xyz_space_but_key_mismatch_examples": same_xyz_space_examples,
    }


def _failure_type(row: dict[str, str]) -> str:
    recoverable = str(row.get("recoverable_failure_type") or "").strip()
    if recoverable:
        return recoverable
    failed_axes = {
        axis.strip()
        for axis in str(row.get("failed_axes") or "").split(";")
        if axis.strip()
    }
    for axis, label in MISMATCH_AXES.items():
        if axis in failed_axes:
            return label
    return ";".join(sorted(failed_axes))


def _is_interesting(row: dict[str, str]) -> bool:
    if not _as_bool(row.get("harness_clean_pass")):
        return False
    if _as_bool(row.get("correct_strict")):
        return False
    failed_axes = str(row.get("failed_axes") or "")
    recoverable = str(row.get("recoverable_failure_type") or "")
    haystack = f"{failed_axes};{recoverable}"
    return any(axis in haystack for axis in MISMATCH_AXES) or any(
        label in haystack for label in MISMATCH_AXES.values()
    )


def _likely_issue(row: dict[str, str], coord: dict[str, Any], missing: set[str], extra: set[str]) -> str:
    local_f1 = _as_float(row.get("local_study_set_f1"))
    coord_f1 = _as_float(row.get("coordinate_canonical_f1"))
    spatial = _as_float(row.get("spatial_correlation"))
    dice = _as_float(row.get("dice_top5"))
    failed = str(row.get("failed_axes") or "")
    if "scientific_similarity_pass" in failed and (
        (spatial is not None and spatial < 0.95) or (dice is not None and dice < 0.8)
    ):
        return "producer_science_or_map_difference"
    if coord_f1 == 0.0 and coord.get("n_same_xyz_space_but_key_mismatch", 0) > 0:
        return "coordinate_canonicalization_study_or_analysis_key_mismatch"
    if coord_f1 == 0.0 and spatial is not None and spatial >= 0.99 and dice is not None and dice >= 0.99:
        return "coordinate_canonicalization_not_spatial_failure"
    if local_f1 is not None and local_f1 < 0.98 and not missing and extra:
        return "study_key_overinclusive_or_alias_mismatch"
    if missing:
        return "producer_missing_control_studies_or_key_alias"
    return "needs_manual_review"


def build_autopsy(
    *,
    run_dir: Path,
    diagnostic_csv: Path,
    comparison_summary: Path,
    max_examples: int,
) -> list[dict[str, str]]:
    diagnostic_rows = _read_csv_dicts(diagnostic_csv)
    summary = _read_json(comparison_summary)
    cases = _comparison_case_map(summary)
    controls = _control_case_map(summary)
    out: list[dict[str, str]] = []

    for row in diagnostic_rows:
        if not _is_interesting(row):
            continue
        condition = row.get("condition", "")
        meta_pmid = row.get("meta_pmid", "")
        case = cases.get((condition, meta_pmid))
        control = controls.get(meta_pmid)
        included = _artifact_path(case, "included_studies")
        control_included = _artifact_path(control, "included_studies")
        coordinates = _artifact_path(case, "coordinate_table")
        control_coordinates = _artifact_path(control, "coordinate_table")

        predicted_studies = _extract_local_study_ids(included)
        control_studies = _extract_local_study_ids(control_included)
        missing = control_studies - predicted_studies
        extra = predicted_studies - control_studies
        coord = _coordinate_mismatch_summary(
            predicted_path=coordinates,
            control_path=control_coordinates,
            limit=max_examples,
        )
        schema = {
            "included_studies": _schema(included),
            "coordinate_table": _schema(coordinates),
            "control_included_studies": _schema(control_included),
            "control_coordinate_table": _schema(control_coordinates),
        }
        space_alias = {
            "predicted": _space_alias_examples(coordinates, limit=max_examples),
            "control": _space_alias_examples(control_coordinates, limit=max_examples),
        }

        out.append(
            {
                "run_dir": str(run_dir.relative_to(REPO_ROOT)),
                "condition": condition,
                "system": row.get("system", ""),
                "topic": row.get("topic", ""),
                "meta_pmid": meta_pmid,
                "br_condition": row.get("br_condition", ""),
                "failure_type": _failure_type(row),
                "failed_axes": row.get("failed_axes", ""),
                "likely_issue": _likely_issue(row, coord, missing, extra),
                "local_study_f1": row.get("local_study_set_f1", ""),
                "coord_f1": row.get("coordinate_canonical_f1", ""),
                "normalized_science_score": row.get("normalized_science_score", ""),
                "spatial_correlation": row.get("spatial_correlation", ""),
                "dice_top5": row.get("dice_top5", ""),
                "n_included_studies": row.get("n_included_studies", ""),
                "n_coordinate_rows": row.get("n_coordinate_rows", ""),
                "control_n_local_study_keys": str(len(control_studies)),
                "predicted_n_local_study_keys": str(len(predicted_studies)),
                "n_missing_study_keys": str(len(missing)),
                "n_extra_study_keys": str(len(extra)),
                "missing_study_keys": _json_text(_examples(missing, max_examples)),
                "extra_study_keys": _json_text(_examples(extra, max_examples)),
                "coordinate_pred_only_count": str(coord["n_predicted_only"]),
                "coordinate_control_only_count": str(coord["n_control_only"]),
                "coordinate_same_xyz_space_but_key_mismatch_count": str(
                    coord["n_same_xyz_space_but_key_mismatch"]
                ),
                "coordinate_key_mismatch_examples": _json_text(
                    {
                        "predicted_only": coord["predicted_only_examples"],
                        "control_only": coord["control_only_examples"],
                        "same_xyz_space_but_key_mismatch": coord[
                            "same_xyz_space_but_key_mismatch_examples"
                        ],
                    }
                ),
                "space_alias_examples": _json_text(space_alias),
                "table_schema_columns": _json_text(schema),
                "case_output_dir": str(included.parent.relative_to(REPO_ROOT))
                if included
                else "",
                "control_case_dir": str(control_included.parent.relative_to(REPO_ROOT))
                if control_included
                else "",
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "condition",
        "topic",
        "meta_pmid",
        "failure_type",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, *, rows: list[dict[str, str]], csv_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_issue = Counter(row["likely_issue"] for row in rows)
    by_failure = Counter(row["failure_type"] for row in rows)
    lines = [
        "# Layer B Study/Coordinate Mismatch Autopsy",
        "",
        "This report is generated from existing comparison artifacts only. It does not rerun agents.",
        "",
        f"CSV: `{csv_path.relative_to(REPO_ROOT)}`",
        "",
        "## Scope",
        "",
        f"- Interesting rows: `{len(rows)}`",
        "- Selection: `harness_clean_pass=true`, `correct_strict!=true`, and failed axes involving local study set, coordinate canonicalization, or scientific similarity.",
        "",
        "## Failure Types",
        "",
        "| Failure type | Rows |",
        "|---|---:|",
    ]
    for key, count in by_failure.most_common():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Likely Issue Buckets", "", "| Likely issue | Rows |", "|---|---:|"])
    for key, count in by_issue.most_common():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| Condition | PMID | Topic | BR | Failure | Likely issue | Local F1 | Coord F1 | Spatial r | Dice top5 | Missing studies | Extra studies | Coord key-only mismatches |",
            "|---|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {condition} | {meta_pmid} | {topic} | {br_condition} | {failure_type} | {likely_issue} | {local_study_f1} | {coord_f1} | {spatial_correlation} | {dice_top5} | {n_missing_study_keys} | {n_extra_study_keys} | {coordinate_same_xyz_space_but_key_mismatch_count} |".format(
                **{
                    key: str(value).replace("|", "\\|")
                    for key, value in row.items()
                }
            )
        )
    lines.extend(
        [
            "",
            "## Initial Interpretation",
            "",
            "- Rows with perfect or near-perfect spatial metrics but low coordinate canonical F1 are canonicalization failures until proven otherwise.",
            "- Rows with `n_missing_study_keys=0` but many `n_extra_study_keys` are likely overinclusive local-study key extraction or alias mismatch, not necessarily missing science.",
            "- Rows with low spatial correlation or Dice remain producer/science artifact candidates and should be inspected before relaxing evaluator thresholds.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--diagnostic-csv", type=Path)
    parser.add_argument("--comparison-summary", type=Path)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--max-examples", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = _repo_path(args.run_dir) or DEFAULT_RUN_DIR
    diagnostic_csv = _repo_path(args.diagnostic_csv) or (run_dir / "diagnostic_axes.csv")
    comparison_summary = _repo_path(args.comparison_summary) or (
        run_dir / "evaluation_anchor_contract" / "layer_b_comparison_summary.json"
    )
    if not comparison_summary.exists():
        comparison_summary = run_dir / "evaluation" / "layer_b_comparison_summary.json"
    output_csv = _repo_path(args.output_csv) or (
        run_dir / "study_coordinate_mismatch_autopsy.csv"
    )
    output_md = _repo_path(args.output_md) or (
        run_dir / "STUDY_COORDINATE_MISMATCH_AUTOPSY.md"
    )

    rows = build_autopsy(
        run_dir=run_dir,
        diagnostic_csv=diagnostic_csv,
        comparison_summary=comparison_summary,
        max_examples=max(1, args.max_examples),
    )
    write_csv(output_csv, rows)
    write_markdown(output_md, rows=rows, csv_path=output_csv)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "output_csv": str(output_csv.relative_to(REPO_ROOT)),
                "output_md": str(output_md.relative_to(REPO_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
