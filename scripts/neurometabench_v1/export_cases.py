#!/usr/bin/env python3
"""Export normalized NeurometaBench v1 case records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    build_case_record,
    load_ground_truth_by_meta,
    load_meta_rows,
    write_jsonl,
)


def export_cases(data_dir: Path = DEFAULT_DATA_DIR, output: Path = DEFAULT_CASES_PATH) -> dict:
    rows = load_meta_rows(data_dir)
    gt_by_meta = load_ground_truth_by_meta(data_dir)
    cases = [build_case_record(row, data_dir, gt_by_meta) for row in rows]
    write_jsonl(cases, output)
    summary = {
        "output": str(output),
        "data_dir": str(data_dir),
        "n_cases": len(cases),
        "n_cases_with_gt": sum(1 for case in cases if case["has_gt"]),
        "n_gt_links": sum(case["n_gt"] for case in cases),
        "routes": {},
        "task_layers": {},
        "task_types": {},
    }
    for case in cases:
        route = case["route"]
        summary["routes"][route] = summary["routes"].get(route, 0) + 1
        summary["task_types"][case["task_type"]] = summary["task_types"].get(case["task_type"], 0) + 1
        for layer in case["task_layers"]:
            summary["task_layers"][layer] = summary["task_layers"].get(layer, 0) + 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args()
    print(json.dumps(export_cases(args.data_dir, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
