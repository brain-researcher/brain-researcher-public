#!/usr/bin/env python3
"""Run the on-demand minimal execute gate for external neuroimaging repo workflows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.workflows.run_workflow_realdata_gate import (
    bootstrap_realdata_env,
    parse_junit_summary,
)


DEFAULT_WORKFLOWS = [
    "workflow_preprocessing_qc",
    "workflow_fmriprep_preprocessing",
    "workflow_mriqc",
    "workflow_qsiprep",
    "workflow_smriprep",
    "workflow_qsirecon",
    "workflow_fastsurfer",
]

TEST_NODE_BY_WORKFLOW = {
    "workflow_preprocessing_qc": "test_workflow_preprocessing_qc_minimal_execute_gate",
    "workflow_fmriprep_preprocessing": "test_workflow_fmriprep_preprocessing_minimal_execute_gate",
    "workflow_mriqc": "test_workflow_mriqc_minimal_execute_gate",
    "workflow_qsiprep": "test_workflow_qsiprep_minimal_execute_gate",
    "workflow_smriprep": "test_workflow_smriprep_minimal_execute_gate",
    "workflow_qsirecon": "test_workflow_qsirecon_minimal_execute_gate",
    "workflow_fastsurfer": "test_workflow_fastsurfer_minimal_execute_gate",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the minimal real-execution gate for external repo workflows"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Workflow IDs to run (default: all minimal execute-gate workflows)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run pytest",
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=REPO_ROOT / "review_reports",
        help="Directory for logs and junit output",
    )
    parser.add_argument(
        "--extra-pytest-arg",
        action="append",
        default=[],
        help="Extra pytest args passed through to the execute gate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved pytest command and environment without executing it",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail the gate when selected tests are skipped",
    )
    return parser.parse_args(argv)


def _selected_workflows(raw: list[str]) -> list[str]:
    selected = [item.strip() for item in raw if item.strip()]
    return selected or list(DEFAULT_WORKFLOWS)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    test_file = (
        repo_root
        / "tests"
        / "integration"
        / "realdata"
        / "test_workflow_external_repo_minimal_execute_gate.py"
    )
    selected = _selected_workflows(list(args.workflow_id))

    env = os.environ.copy()
    auto_env_defaults = bootstrap_realdata_env(repo_root, env)
    env["BR_ENABLE_EXTERNAL_REPO_EXEC_GATE"] = "1"
    env["BR_EXTERNAL_REPO_EXEC_GATE_WORKFLOWS"] = ",".join(selected)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_dir = args.report_root / f"external_repo_execute_gate_{stamp}_{os.getpid()}"
    report_dir.mkdir(parents=True, exist_ok=True)
    junit_path = report_dir / "junit.xml"
    log_path = report_dir / "pytest.log"

    selected_nodes = [
        f"{test_file}::{TEST_NODE_BY_WORKFLOW[workflow_id]}"
        for workflow_id in selected
        if workflow_id in TEST_NODE_BY_WORKFLOW
    ]
    if len(selected_nodes) != len(selected):
        missing = sorted(set(selected) - set(TEST_NODE_BY_WORKFLOW))
        raise SystemExit(f"No execute-gate node mapping for workflows: {missing}")

    cmd = [
        args.python,
        "-m",
        "pytest",
        "--override-ini",
        "addopts=",
        "-q",
        "-m",
        "realdata",
        "-rs",
        f"--junitxml={junit_path}",
    ]
    cmd.extend(selected_nodes)
    cmd.extend(args.extra_pytest_arg)

    payload = {
        "repo_root": str(repo_root),
        "test_file": str(test_file),
        "selected_workflows": selected,
        "selected_nodes": selected_nodes,
        "pytest_command": cmd,
        "report_dir": str(report_dir),
        "junit_path": str(junit_path),
        "log_path": str(log_path),
        "auto_env_defaults": auto_env_defaults,
        "env_overrides": {
            "BR_ENABLE_EXTERNAL_REPO_EXEC_GATE": env[
                "BR_ENABLE_EXTERNAL_REPO_EXEC_GATE"
            ],
            "BR_EXTERNAL_REPO_EXEC_GATE_WORKFLOWS": env[
                "BR_EXTERNAL_REPO_EXEC_GATE_WORKFLOWS"
            ],
        },
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        text=True,
        capture_output=True,
    )
    log_path.write_text(
        f"# CMD\n{' '.join(cmd)}\n\n# RETURN_CODE\n{proc.returncode}\n\n# STDOUT\n{proc.stdout}\n\n# STDERR\n{proc.stderr}\n",
        encoding="utf-8",
    )

    junit = parse_junit_summary(junit_path)
    payload.update(
        {
            "return_code": proc.returncode,
            "strict": bool(args.strict),
            "junit": {
                "tests": junit.tests,
                "failures": junit.failures,
                "errors": junit.errors,
                "skipped": junit.skipped,
                "skip_reasons": junit.skip_reasons or [],
            },
        }
    )
    (report_dir / "report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    print(json.dumps(payload, indent=2))
    if proc.returncode != 0:
        return proc.returncode
    if args.strict and junit.skipped > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
