#!/usr/bin/env python3
"""Build the Layer B NiMADS/BrainMap reproduction manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, load_case_records, write_jsonl


DEFAULT_OUTPUT = Path("benchmarks/neurometabench/nimads_reproduction_manifest.jsonl")


def manifest_row(case: dict[str, Any]) -> dict[str, Any]:
    assets = case.get("nimads_assets") or {}
    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "topic": case.get("topic"),
        "task_layer": "layer_b_end_to_end_reproduction",
        "task_type": "end_to_end_reproduction",
        "project_key": assets.get("project_key"),
        "project_dir": assets.get("project_dir"),
        "raw_jsons": assets.get("raw_jsons") or [],
        "merged_studyset": assets.get("merged_studyset"),
        "merged_annotation": assets.get("merged_annotation"),
        "n_gt": case.get("n_gt"),
        "screening_criteria": case.get("screening_criteria") or [],
        "expected_outputs": [
            "included_studies",
            "coordinate_table",
            "nimare_ale_map",
            "spatial_report",
            "provenance_manifest",
        ],
        "metrics": [
            "study_set_f1",
            "coordinate_extraction_agreement",
            "spatial_map_correlation",
            "report_claim_map_consistency",
            "provenance_completeness",
        ],
    }


def build_manifest(cases_path: Path = DEFAULT_CASES_PATH, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    cases = [
        case
        for case in load_case_records(cases_path)
        if case.get("route") == "nimads_brainmap"
        or "layer_b_end_to_end_reproduction" in set(case.get("task_layers") or [])
    ]
    rows = [manifest_row(case) for case in cases]
    write_jsonl(rows, output)
    return {
        "output": str(output),
        "n_cases": len(rows),
        "case_ids": [row["case_id"] for row in rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_manifest(args.cases, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
