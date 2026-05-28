#!/usr/bin/env python3
"""Validate artifact completeness across run directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _discover_run_dirs(root: Path) -> list[Path]:
    markers = [
        "observation.json",
        "analysis_bundle.json",
        "trajectory.json",
        "trace.jsonl",
        "provenance.json",
    ]
    dirs: set[Path] = set()
    for marker in markers:
        for file_path in root.rglob(marker):
            dirs.add(file_path.parent)
    return sorted(dirs)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("outputs"),
        help="Root directory containing run folders.",
    )
    parser.add_argument(
        "--job-profile",
        default="plan_execution",
        help="Artifact validator profile (default: plan_execution).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help="Minimum completeness ratio required to pass.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional output path for detailed JSON report.",
    )
    return parser


def main() -> int:
    from brain_researcher.core.artifact_validator import validate_run_artifacts

    args = _build_parser().parse_args()
    runs_dir = args.runs_dir.expanduser().resolve()
    if not runs_dir.exists():
        print(f"Runs directory does not exist: {runs_dir}")
        return 2

    run_dirs = _discover_run_dirs(runs_dir)
    if not run_dirs:
        print(f"No run directories discovered under: {runs_dir}")
        return 2

    results: list[dict[str, object]] = []
    for run_dir in run_dirs:
        violations = validate_run_artifacts(
            run_dir=run_dir,
            job_profile=args.job_profile,
            state="succeeded",
            assume_present=set(),
        )
        results.append(
            {
                "run_dir": str(run_dir),
                "complete": len(violations) == 0,
                "violation_count": len(violations),
                "violations": [v.model_dump(exclude_none=True) for v in violations],
            }
        )

    total = len(results)
    complete = sum(1 for row in results if row["complete"])
    ratio = complete / total if total else 0.0

    report = {
        "schema_version": "artifact-completeness-v1",
        "runs_dir": str(runs_dir),
        "job_profile": args.job_profile,
        "threshold": args.threshold,
        "total_runs": total,
        "complete_runs": complete,
        "ratio": ratio,
        "passed": ratio >= args.threshold,
        "results": results,
    }

    if args.json_out:
        output = args.json_out.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report: {output}")

    print(
        f"Artifact completeness: {complete}/{total} = {ratio:.3f} "
        f"(threshold={args.threshold:.3f})"
    )
    return 0 if ratio >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
