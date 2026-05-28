#!/usr/bin/env python3
"""Run an R5 experiment config and write a reproducible manifest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_sha() -> str | None:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return None


def _pip_freeze() -> list[str]:
    try:
        output = subprocess.check_output(
            ["python3", "-m", "pip", "freeze"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
        return [line.strip() for line in output.splitlines() if line.strip()]
    except Exception:
        return []


def _load_config(path: Path):
    from brain_researcher.core.contracts import ExperimentConfigV1

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ExperimentConfigV1.model_validate(data)


def _build_plan(run: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(run["dataset_id"])
    workflow_id = str(run["workflow_id"])
    params = dict(run.get("parameters") or {})

    step_args = {
        "dataset_id": dataset_id,
        "analysis_id": "dynamic_workflow",
        "pipeline_id": workflow_id,
        **params,
    }
    return {
        "type": "dataset_analysis",
        "intent": f"R5 experiment run ({run['run_key']})",
        "pipeline": "preprocessing",
        "dataset_id": dataset_id,
        "template_id": f"dynamic_workflow/{workflow_id}",
        "parameters": step_args,
        "steps": [
            {
                "tool": workflow_id,
                "args": step_args,
            }
        ],
    }


def _submit_run(orchestrator_base: str, plan: dict[str, Any], timeout: float) -> dict[str, Any]:
    base = orchestrator_base.rstrip("/")
    response = requests.post(
        f"{base}/api/runs",
        json={"plan": plan},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {"raw": data}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/r5_baseline.yaml"),
        help="Experiment config YAML (experiment-config-v1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/r5_experiments/latest"),
        help="Output directory for manifest and payload snapshots.",
    )
    parser.add_argument(
        "--orchestrator-base",
        default=(
            os.getenv("BR_ORCHESTRATOR_URL")
            or os.getenv("ORCHESTRATOR_URL")
            or "http://localhost:3001"
        ),
        help="Base URL for orchestrator API.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout seconds for each run submission.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build manifest payloads without submitting runs.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config = _load_config(args.config)

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    environment = {
        "captured_at": _utc_now_iso(),
        "git_sha": _git_sha(),
        "pip_freeze": _pip_freeze(),
        "orchestrator_base": args.orchestrator_base.rstrip("/"),
    }

    run_records: list[dict[str, Any]] = []
    for run in config.runs:
        run_spec = run.model_dump(mode="json")
        plan = _build_plan(run_spec)
        payload_path = output_dir / f"{run.run_key}.plan.json"
        payload_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

        if args.dry_run:
            run_records.append(
                {
                    "run_key": run.run_key,
                    "mode": run.mode,
                    "status": "planned",
                    "plan_path": str(payload_path),
                }
            )
            continue

        try:
            resp = _submit_run(args.orchestrator_base, plan, timeout=args.timeout)
            run_records.append(
                {
                    "run_key": run.run_key,
                    "mode": run.mode,
                    "status": "submitted",
                    "response": resp,
                    "plan_path": str(payload_path),
                }
            )
        except Exception as exc:
            run_records.append(
                {
                    "run_key": run.run_key,
                    "mode": run.mode,
                    "status": "submission_error",
                    "error": str(exc),
                    "plan_path": str(payload_path),
                }
            )

    manifest = {
        "schema_version": "r5-experiment-manifest-v1",
        "generated_at": _utc_now_iso(),
        "config": config.model_dump(mode="json"),
        "environment": environment,
        "runs": run_records,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
