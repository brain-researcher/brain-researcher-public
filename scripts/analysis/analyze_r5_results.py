#!/usr/bin/env python3
"""Analyze R5 manifest outputs and emit a comparison CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    return raw


def _resolve_run_dir(run_entry: dict[str, Any]) -> Path | None:
    response = _safe_dict(run_entry.get("response"))
    candidates = [response.get("run_dir"), run_entry.get("run_dir")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate).expanduser()
    return None


def _read_observation(run_dir: Path | None) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    obs_path = run_dir / "observation.json"
    if not obs_path.exists():
        return None
    try:
        raw = json.loads(obs_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return None
    return None


def _build_row(run_entry: dict[str, Any]) -> dict[str, Any]:
    response = _safe_dict(run_entry.get("response"))
    run_id = response.get("run_id") or response.get("job_id")
    run_dir = _resolve_run_dir(run_entry)
    observation = _read_observation(run_dir)

    violations = []
    tool_count = 0
    artifact_count = 0
    if observation:
        violations = observation.get("violations") or []
        run_card = _safe_dict(observation.get("run_card"))
        tools = run_card.get("tools") or []
        artifacts = observation.get("artifacts") or []
        tool_count = len(tools) if isinstance(tools, list) else 0
        artifact_count = len(artifacts) if isinstance(artifacts, list) else 0

    return {
        "run_key": run_entry.get("run_key"),
        "mode": run_entry.get("mode"),
        "submission_status": run_entry.get("status"),
        "run_id": run_id,
        "run_dir": str(run_dir) if run_dir else "",
        "observation_found": bool(observation),
        "violation_count": len(violations) if isinstance(violations, list) else 0,
        "tool_count": tool_count,
        "artifact_count": artifact_count,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to manifest.json produced by run_r5_experiment.py",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Optional explicit CSV output path (default: alongside manifest).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    manifest = _load_manifest(args.manifest.expanduser().resolve())
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise ValueError("manifest.runs must be a list")

    rows = [_build_row(run) for run in runs if isinstance(run, dict)]

    output_csv = (
        args.output_csv.expanduser().resolve()
        if args.output_csv
        else args.manifest.expanduser().resolve().with_name("r5_comparison.csv")
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "run_key",
        "mode",
        "submission_status",
        "run_id",
        "run_dir",
        "observation_found",
        "violation_count",
        "tool_count",
        "artifact_count",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote CSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
