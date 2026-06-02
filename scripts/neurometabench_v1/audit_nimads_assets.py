#!/usr/bin/env python3
"""Audit NeuroMetaBench Layer B NiMADS assets before reproduction work."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.build_nimads_reproduction_manifest import DEFAULT_OUTPUT
from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, read_jsonl


DEFAULT_AUDIT_JSON = Path("benchmarks/neurometabench/experiments/nimads_asset_audit.json")
DEFAULT_AUDIT_MD = Path("benchmarks/neurometabench/experiments/nimads_asset_audit.md")


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _is_pmid_like(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"\d{6,9}", text))


def _iter_analyses(studyset: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for study in studyset.get("studies") or []:
        for analysis in study.get("analyses") or []:
            rows.append((study, analysis))
    return rows


def summarize_studyset(path: Path | None) -> dict[str, Any]:
    studyset = _read_json(path)
    studies = studyset.get("studies") or []
    analyses = _iter_analyses(studyset)

    study_ids = [str(study.get("id") or "").strip() for study in studies]
    pmid_like_study_ids = [study_id for study_id in study_ids if _is_pmid_like(study_id)]
    spaces: Counter[str] = Counter()
    n_points = 0
    n_analyses_with_points = 0
    n_studies_with_points = 0
    sample_sizes: list[Any] = []

    for study in studies:
        study_has_points = False
        for analysis in study.get("analyses") or []:
            points = analysis.get("points") or []
            if points:
                n_analyses_with_points += 1
                study_has_points = True
            n_points += len(points)
            for point in points:
                spaces[str(point.get("space") or "unknown")] += 1
            metadata = analysis.get("metadata") or {}
            sample_sizes.extend(metadata.get("sample_sizes") or [])
        if study_has_points:
            n_studies_with_points += 1

    if not studies:
        study_id_status = "missing_studyset"
    elif len(studies) <= 2 and not pmid_like_study_ids:
        study_id_status = "aggregate_or_nonpmid"
    elif pmid_like_study_ids:
        study_id_status = "pmid_like"
    else:
        study_id_status = "nonpmid_study_labels"

    return {
        "exists": bool(studyset),
        "n_studies": len(studies),
        "n_studies_with_points": n_studies_with_points,
        "n_analyses": len(analyses),
        "n_analyses_with_points": n_analyses_with_points,
        "n_points": n_points,
        "coordinate_spaces": dict(sorted(spaces.items())),
        "n_pmid_like_study_ids": len(pmid_like_study_ids),
        "study_id_status": study_id_status,
        "study_id_examples": study_ids[:8],
        "sample_size_values": sorted({str(x) for x in sample_sizes})[:12],
        "n_sample_size_values": len(sample_sizes),
        "analysis_id_examples": [str(analysis.get("id") or "") for _, analysis in analyses[:8]],
    }


def summarize_annotation(path: Path | None, analysis_ids: set[str]) -> dict[str, Any]:
    annotation = _read_json(path)
    notes = annotation.get("notes") or []
    note_keys = sorted((annotation.get("note_keys") or {}).keys())
    covered = {str(note.get("analysis") or "") for note in notes if note.get("analysis")}
    n_true_notes = 0
    for note in notes:
        values = (note.get("note") or {}).values()
        if any(bool(value) for value in values):
            n_true_notes += 1
    return {
        "exists": bool(annotation),
        "n_notes": len(notes),
        "note_keys": note_keys,
        "n_note_keys": len(note_keys),
        "n_notes_with_any_true": n_true_notes,
        "n_analyses_covered": len(covered & analysis_ids),
        "analysis_coverage_rate": round(len(covered & analysis_ids) / len(analysis_ids), 6)
        if analysis_ids
        else 0.0,
    }


def audit_row(row: dict[str, Any], case_by_pmid: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta_pmid = str(row.get("meta_pmid") or "")
    case = case_by_pmid.get(meta_pmid, {})
    studyset_path = Path(row["merged_studyset"]) if row.get("merged_studyset") else None
    annotation_path = Path(row["merged_annotation"]) if row.get("merged_annotation") else None
    studyset = _read_json(studyset_path)
    analysis_ids = {
        str(analysis.get("id") or "")
        for _, analysis in _iter_analyses(studyset)
        if analysis.get("id")
    }
    studyset_summary = summarize_studyset(studyset_path)
    annotation_summary = summarize_annotation(annotation_path, analysis_ids)

    gt_pmids = [str(pmid) for pmid in (case.get("gt_pmids") or [])]
    study_id_examples = set(studyset_summary["study_id_examples"])
    # Re-read all study ids for overlap, not just examples.
    all_study_ids = {
        str(study.get("id") or "").strip()
        for study in (studyset.get("studies") or [])
        if str(study.get("id") or "").strip()
    }
    gt_overlap = sorted(set(gt_pmids) & all_study_ids, key=lambda item: (int(item), item) if item.isdigit() else (10**20, item))
    coordinate_spaces = set(studyset_summary["coordinate_spaces"].keys())
    has_coordinates = studyset_summary["n_points"] > 0

    if not has_coordinates:
        path_b_status = "blocked_no_coordinates"
    elif studyset_summary["n_studies"] <= 2 and studyset_summary["study_id_status"] == "aggregate_or_nonpmid":
        path_b_status = "map_ready_but_not_study_level"
    elif gt_pmids and not gt_overlap and studyset_summary["study_id_status"] != "pmid_like":
        path_b_status = "map_ready_needs_pmid_mapping"
    else:
        path_b_status = "map_ready"

    return {
        "case_id": row.get("case_id"),
        "meta_pmid": meta_pmid,
        "topic": row.get("topic"),
        "project_key": row.get("project_key"),
        "case_gt_pmids_n": len(gt_pmids),
        "case_has_gt_pmids": bool(gt_pmids),
        "manifest_n_gt": row.get("n_gt"),
        "raw_jsons_n": len(row.get("raw_jsons") or []),
        "merged_studyset": str(studyset_path) if studyset_path else None,
        "merged_annotation": str(annotation_path) if annotation_path else None,
        "studyset": studyset_summary,
        "annotation": annotation_summary,
        "gt_overlap_with_nimads_study_ids_n": len(gt_overlap),
        "gt_overlap_with_nimads_study_ids_examples": gt_overlap[:12],
        "coordinate_space_status": "mixed" if len(coordinate_spaces) > 1 else next(iter(coordinate_spaces), "none"),
        "has_coordinate_gt": has_coordinates,
        "has_annotation_labels": bool(annotation_summary["n_note_keys"]),
        "path_b_status": path_b_status,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row["path_b_status"] for row in rows)
    space_statuses = Counter(row["coordinate_space_status"] for row in rows)
    return {
        "n_cases": len(rows),
        "n_cases_with_case_gt_pmids": sum(1 for row in rows if row["case_has_gt_pmids"]),
        "n_cases_with_coordinate_gt": sum(1 for row in rows if row["has_coordinate_gt"]),
        "n_cases_with_annotation_labels": sum(1 for row in rows if row["has_annotation_labels"]),
        "n_cases_with_pmid_like_nimads_study_ids": sum(
            1 for row in rows if row["studyset"]["study_id_status"] == "pmid_like"
        ),
        "path_b_status_counts": dict(sorted(statuses.items())),
        "coordinate_space_status_counts": dict(sorted(space_statuses.items())),
        "total_nimads_studies": sum(row["studyset"]["n_studies"] for row in rows),
        "total_nimads_analyses": sum(row["studyset"]["n_analyses"] for row in rows),
        "total_nimads_points": sum(row["studyset"]["n_points"] for row in rows),
    }


def write_markdown(result: dict[str, Any], output: Path) -> None:
    lines = [
        "# NeuroMetaBench NiMADS Asset Audit",
        "",
        "This audit separates case-level PMID ground truth from NiMADS coordinate ground truth.",
        "",
        "## Summary",
        "",
    ]
    for key, value in result["summary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| PMID | Topic | Case GT PMIDs | NiMADS studies | Analyses | Points | Space | Annotation keys | Status |",
            "|---|---|---:|---:|---:|---:|---|---:|---|",
        ]
    )
    for row in result["cases"]:
        lines.append(
            "| {meta_pmid} | {topic} | {gt} | {studies} | {analyses} | {points} | {space} | {keys} | {status} |".format(
                meta_pmid=row["meta_pmid"],
                topic=str(row.get("topic") or "").replace("|", "/"),
                gt=row["case_gt_pmids_n"],
                studies=row["studyset"]["n_studies"],
                analyses=row["studyset"]["n_analyses"],
                points=row["studyset"]["n_points"],
                space=row["coordinate_space_status"],
                keys=row["annotation"]["n_note_keys"],
                status=row["path_b_status"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `case_gt_pmids_n` is the screening/study-set GT from `cases.v1.jsonl`.",
            "- `has_coordinate_gt` means the merged NiMADS studyset contains coordinates that can serve as coordinate-level gold.",
            "- `map_ready_but_not_study_level` means a map can likely be generated, but the merged studyset does not preserve per-PMID study identity.",
            "- `map_ready_needs_pmid_mapping` means coordinates exist, but study-set F1 against PMID GT needs an additional PMID mapping layer.",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(
    cases_path: Path = DEFAULT_CASES_PATH,
    manifest_path: Path = DEFAULT_OUTPUT,
    output_json: Path = DEFAULT_AUDIT_JSON,
    output_md: Path = DEFAULT_AUDIT_MD,
) -> dict[str, Any]:
    cases = read_jsonl(cases_path)
    case_by_pmid = {str(case.get("meta_pmid") or ""): case for case in cases}
    rows = [audit_row(row, case_by_pmid) for row in read_jsonl(manifest_path)]
    result = {
        "inputs": {
            "cases": str(cases_path),
            "manifest": str(manifest_path),
        },
        "summary": summarize(rows),
        "cases": rows,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(result, output_md)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_AUDIT_MD)
    args = parser.parse_args()
    result = run_audit(args.cases, args.manifest, args.output_json, args.output_md)
    print(json.dumps({"summary": result["summary"], "output_json": str(args.output_json), "output_md": str(args.output_md)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
