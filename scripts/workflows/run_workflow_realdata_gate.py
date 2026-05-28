#!/usr/bin/env python3
"""Run real-data workflow smoke tests as a strict acceptance gate.

Default profile is ``strict41``:
- Load all workflow IDs from ``configs/workflows/workflow_catalog.yaml``.
- Exclude ``workflow_asl_perfusion`` (needs an external ASL BIDS root in most envs).
- Execute one mapped real-data smoke test per workflow.
- Treat ``skipped`` as gate failures when ``--strict`` is enabled (default).

Outputs:
- JSON report with per-workflow status, timing, skip reasons, logs, and junit stats.
- Markdown summary for quick triage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import yaml

WORKFLOW_EXEC_RE = re.compile(
    r"execute_tool\(\s*[\"'](workflow_[A-Za-z0-9_]+)[\"']", re.MULTILINE
)
STATUS_ASSERT_RE = re.compile(r"assert\s+\w+\.status\s*==\s*[\"']success[\"']")
ARTIFACT_ASSERT_RE = re.compile(
    r"assert\s+.*(\.exists\(|st_size|outputs\.|\['outputs'\])"
)

DEFAULT_STRICT41_EXCLUDES = {"workflow_asl_perfusion"}


@dataclass
class JUnitSummary:
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    skip_reasons: list[str] | None = None


@dataclass
class WorkflowRunResult:
    workflow_id: str
    test_file: str | None
    status: str
    gate_passed: bool
    elapsed_sec: float
    return_code: int | None
    timed_out: bool
    junit: JUnitSummary
    has_status_assert: bool
    has_artifact_assert: bool
    log_file: str | None
    junit_file: str | None
    note: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_workflow_ids(catalog_path: Path) -> list[str]:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    workflows = data.get("workflows") or []
    ids: list[str] = []
    for row in workflows:
        if not isinstance(row, dict):
            continue
        wf_id = str(row.get("id") or "").strip()
        if wf_id:
            ids.append(wf_id)
    return ids


def collect_realdata_tests(tests_root: Path) -> list[Path]:
    return sorted(tests_root.glob("test_workflow*_smoke.py"))


def extract_executed_workflow_ids(text: str) -> list[str]:
    return WORKFLOW_EXEC_RE.findall(text)


def infer_primary_workflow_for_test(test_file: Path) -> str | None:
    text = test_file.read_text(encoding="utf-8", errors="ignore")
    executed = extract_executed_workflow_ids(text)
    if not executed:
        return None
    return executed[-1]


def detect_test_contract(test_file: Path) -> tuple[bool, bool]:
    text = test_file.read_text(encoding="utf-8", errors="ignore")
    has_status_assert = bool(STATUS_ASSERT_RE.search(text))
    has_artifact_assert = bool(ARTIFACT_ASSERT_RE.search(text))
    return has_status_assert, has_artifact_assert


def _mapping_priority(workflow_id: str, test_file: Path) -> tuple[int, str]:
    stem = test_file.stem
    base = workflow_id.replace("workflow_", "", 1)
    score = 0
    if stem.startswith(f"test_{workflow_id}"):
        score += 8
    if stem.startswith(f"test_workflow_{base}"):
        score += 5
    if base in stem:
        score += 2
    return score, stem


def build_primary_workflow_test_map(test_files: Iterable[Path]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for test_file in test_files:
        workflow_id = infer_primary_workflow_for_test(test_file)
        if not workflow_id:
            continue

        existing = mapping.get(workflow_id)
        if existing is None:
            mapping[workflow_id] = test_file
            continue

        if _mapping_priority(workflow_id, test_file) > _mapping_priority(
            workflow_id, existing
        ):
            mapping[workflow_id] = test_file

    return mapping


def parse_junit_summary(junit_path: Path) -> JUnitSummary:
    if not junit_path.exists():
        return JUnitSummary(skip_reasons=[])

    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return JUnitSummary(skip_reasons=[])

    suites: list[ET.Element]
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = [s for s in root.findall("testsuite")]

    tests = failures = errors = skipped = 0
    skip_reasons: list[str] = []

    for suite in suites:
        tests += int(suite.attrib.get("tests", 0) or 0)
        failures += int(suite.attrib.get("failures", 0) or 0)
        errors += int(suite.attrib.get("errors", 0) or 0)
        skipped += int(suite.attrib.get("skipped", 0) or 0)

        for case in suite.findall("testcase"):
            skipped_node = case.find("skipped")
            if skipped_node is not None:
                message = (
                    skipped_node.attrib.get("message")
                    or (skipped_node.text or "").strip()
                )
                if message:
                    skip_reasons.append(message)

    # De-duplicate while preserving order.
    uniq_reasons: list[str] = []
    seen: set[str] = set()
    for reason in skip_reasons:
        reason = reason.strip()
        if not reason or reason in seen:
            continue
        uniq_reasons.append(reason)
        seen.add(reason)

    return JUnitSummary(
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        skip_reasons=uniq_reasons,
    )


def _tail(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _first_existing(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def bootstrap_realdata_env(repo_root: Path, env: dict[str, str]) -> dict[str, str]:
    """Populate common real-data env vars when unset.

    The goal is to make local execution robust without requiring users to
    export a long env-var list manually.
    """

    defaults: dict[str, str] = {}
    home = Path.home()

    ds114_bids = _first_existing(
        [
            home / "projects" / "dataset" / "openneuro" / "ds000114",
            repo_root / "out" / "openneuro_local" / "ds000114" / "bids",
        ]
    )
    ds117_bids = _first_existing(
        [
            home / "projects" / "dataset" / "openneuro" / "ds000117",
            repo_root / "out" / "openneuro_local" / "ds000117" / "bids",
        ]
    )
    ds114_fmriprep = _first_existing(
        [
            repo_root
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-fmriprep",
            home
            / "projects"
            / "dataset"
            / "OpenNeuroDerivatives"
            / "fmriprep"
            / "ds000114",
        ]
    )

    ds114_openneuro_root: Path | None = None
    if ds114_bids is not None:
        ds114_openneuro_root = (
            ds114_bids.parent if ds114_bids.name == "bids" else ds114_bids
        )

    def _set_default(name: str, value: Path | None) -> None:
        if name in env:
            return
        if value is None:
            return
        env[name] = str(value)
        defaults[name] = str(value)

    _set_default("BR_DS000114_BIDS_ROOT", ds114_bids)
    _set_default("BR_DS000117_BIDS_ROOT", ds117_bids)
    _set_default("BR_DS000114_FMRIPREP_ROOT", ds114_fmriprep)
    _set_default("BR_DS000114_OPENNEURO_ROOT", ds114_openneuro_root)

    # FitLins smoke test uses dedicated env keys; mirror DS000114 defaults.
    _set_default("BR_FITLINS_BIDS_ROOT", ds114_bids)
    _set_default("BR_FITLINS_FMRIPREP_ROOT", ds114_fmriprep)

    return defaults


def run_single_workflow_test(
    *,
    repo_root: Path,
    workflow_id: str,
    test_file: Path,
    python_executable: str,
    timeout_sec: int,
    log_file: Path,
    junit_file: Path,
    extra_pytest_args: Sequence[str],
    env: dict[str, str],
    strict: bool,
) -> WorkflowRunResult:
    has_status_assert, has_artifact_assert = detect_test_contract(test_file)

    cmd = [
        python_executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "realdata",
        str(test_file),
        "--maxfail=1",
        "--disable-warnings",
        f"--junitxml={junit_file}",
    ]
    cmd.extend(extra_pytest_args)

    start = time.time()
    timed_out = False
    return_code: int | None = None
    stdout = ""
    stderr = ""

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
        return_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

    elapsed_sec = round(time.time() - start, 3)

    full_log = (
        f"# CMD\n{' '.join(cmd)}\n\n"
        f"# RETURN_CODE\n{return_code}\n\n"
        f"# STDOUT\n{stdout}\n\n"
        f"# STDERR\n{stderr}\n"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(full_log, encoding="utf-8")

    junit = parse_junit_summary(junit_file)

    if timed_out:
        status = "timeout"
    elif (return_code or 0) != 0 or junit.failures > 0 or junit.errors > 0:
        status = "failed"
    elif junit.skipped > 0:
        status = "skipped"
    elif junit.tests > 0:
        status = "passed"
    else:
        status = "error"

    gate_passed = status == "passed" or (not strict and status == "skipped")

    note: str | None = None
    if not has_artifact_assert:
        note = "test has no explicit artifact-existence assertion"
    if status == "failed" and not note:
        note = _tail(stderr.strip() or stdout.strip(), 600)
    if status == "skipped" and junit.skip_reasons:
        note = junit.skip_reasons[0]

    return WorkflowRunResult(
        workflow_id=workflow_id,
        test_file=str(test_file),
        status=status,
        gate_passed=gate_passed,
        elapsed_sec=elapsed_sec,
        return_code=return_code,
        timed_out=timed_out,
        junit=junit,
        has_status_assert=has_status_assert,
        has_artifact_assert=has_artifact_assert,
        log_file=str(log_file),
        junit_file=str(junit_file),
        note=note,
    )


def summarize(results: Sequence[WorkflowRunResult]) -> dict[str, int]:
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "passed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "timeout": sum(1 for r in results if r.status == "timeout"),
        "error": sum(1 for r in results if r.status == "error"),
        "gate_passed": sum(1 for r in results if r.gate_passed),
        "missing_artifact_assert": sum(1 for r in results if not r.has_artifact_assert),
        "missing_status_assert": sum(1 for r in results if not r.has_status_assert),
    }


def write_markdown_report(
    report_path: Path,
    *,
    profile: str,
    strict: bool,
    started_at: str,
    finished_at: str,
    elapsed_sec: float,
    summary: dict[str, int],
    results: Sequence[WorkflowRunResult],
) -> None:
    lines: list[str] = [
        "# Workflow Real-Data Gate Report",
        "",
        f"- Profile: `{profile}`",
        f"- Strict: `{strict}`",
        f"- Started: `{started_at}`",
        f"- Finished: `{finished_at}`",
        f"- Elapsed: `{elapsed_sec:.3f}s`",
        "",
        "## Summary",
        "",
        f"- Total: **{summary['total']}**",
        f"- Passed: **{summary['passed']}**",
        f"- Failed: **{summary['failed']}**",
        f"- Skipped: **{summary['skipped']}**",
        f"- Timeout: **{summary['timeout']}**",
        f"- Error: **{summary['error']}**",
        f"- Gate-passed: **{summary['gate_passed']}**",
        f"- Missing artifact assertions: **{summary['missing_artifact_assert']}**",
        f"- Missing status assertions: **{summary['missing_status_assert']}**",
        "",
        "## Per Workflow",
        "",
    ]

    for row in results:
        lines.extend(
            [
                f"### {row.workflow_id}",
                f"- status: `{row.status}` | gate_passed=`{row.gate_passed}` | elapsed={row.elapsed_sec:.3f}s",
                f"- test: `{row.test_file}`",
                f"- junit: tests={row.junit.tests}, failures={row.junit.failures}, errors={row.junit.errors}, skipped={row.junit.skipped}",
                f"- contract: status_assert={row.has_status_assert}, artifact_assert={row.has_artifact_assert}",
                f"- log: `{row.log_file}`",
                f"- note: `{row.note or ''}`",
                "",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    repo_root_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Run strict real-data workflow acceptance gate"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root_default,
        help="Repository root",
    )
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=repo_root_default / "configs" / "workflows" / "workflow_catalog.yaml",
        help="Workflow catalog path",
    )
    parser.add_argument(
        "--tests-root",
        type=Path,
        default=repo_root_default / "tests" / "integration" / "realdata",
        help="Real-data tests directory",
    )
    parser.add_argument(
        "--profile",
        choices=["strict41", "all42"],
        default="strict41",
        help="Target workflow profile",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Run only these workflow IDs (can be repeated)",
    )
    parser.add_argument(
        "--exclude-workflow-id",
        action="append",
        default=[],
        help="Exclude workflow IDs (can be repeated)",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When true, skipped tests fail the gate",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=1800,
        help="Timeout per workflow test",
    )
    parser.add_argument(
        "--max-workflows",
        type=int,
        default=0,
        help="Optional cap for quick smoke runs (0 = all selected)",
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=repo_root_default / "review_reports",
        help="Directory where a timestamped report folder is created",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run pytest",
    )
    parser.add_argument(
        "--extra-pytest-arg",
        action="append",
        default=[],
        help="Extra argument passed to each pytest invocation (can be repeated)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve mapping and output selected workflow list without execution",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    repo_root = args.repo_root.resolve()
    catalog_path = args.catalog_path.resolve()
    tests_root = args.tests_root.resolve()

    workflow_ids = load_workflow_ids(catalog_path)
    if not workflow_ids:
        raise SystemExit(f"No workflows found in catalog: {catalog_path}")

    selected = list(workflow_ids)
    if args.workflow_id:
        only = {w.strip() for w in args.workflow_id if w.strip()}
        selected = [w for w in workflow_ids if w in only]

    excluded: set[str] = set()
    if args.profile == "strict41":
        excluded |= DEFAULT_STRICT41_EXCLUDES
    excluded |= {w.strip() for w in args.exclude_workflow_id if w.strip()}
    selected = [w for w in selected if w not in excluded]

    if args.max_workflows and args.max_workflows > 0:
        selected = selected[: args.max_workflows]

    test_files = collect_realdata_tests(tests_root)
    primary_map = build_primary_workflow_test_map(test_files)

    missing = [wf for wf in selected if wf not in primary_map]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base_dirname = f"workflow_realdata_gate_{stamp}_{os.getpid()}"
    report_dir = args.report_root / base_dirname
    nonce = 0
    while report_dir.exists():
        nonce += 1
        report_dir = args.report_root / f"{base_dirname}_{nonce}"
    logs_dir = report_dir / "logs"
    junit_dir = report_dir / "junit"

    report_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    junit_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        payload = {
            "profile": args.profile,
            "strict": bool(args.strict),
            "catalog_count": len(workflow_ids),
            "selected_count": len(selected),
            "selected": selected,
            "excluded": sorted(excluded),
            "missing_tests": missing,
            "mapping": {
                wf: str(primary_map.get(wf)) for wf in selected if wf in primary_map
            },
        }
        out = report_dir / "dry_run.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        print(f"Wrote: {out}")
        return 0 if not missing else 1

    env = os.environ.copy()
    auto_env = bootstrap_realdata_env(repo_root, env)

    started_at = utc_now()
    t0 = time.time()
    results: list[WorkflowRunResult] = []

    for idx, workflow_id in enumerate(selected, start=1):
        test_file = primary_map.get(workflow_id)
        if test_file is None:
            results.append(
                WorkflowRunResult(
                    workflow_id=workflow_id,
                    test_file=None,
                    status="error",
                    gate_passed=False,
                    elapsed_sec=0.0,
                    return_code=None,
                    timed_out=False,
                    junit=JUnitSummary(skip_reasons=[]),
                    has_status_assert=False,
                    has_artifact_assert=False,
                    log_file=None,
                    junit_file=None,
                    note="no mapped realdata smoke test",
                )
            )
            print(
                f"[{idx:02d}/{len(selected):02d}] {workflow_id}: ERROR (no mapped test)",
                flush=True,
            )
            continue

        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", workflow_id)
        log_file = logs_dir / f"{idx:02d}_{safe_name}.log"
        junit_file = junit_dir / f"{idx:02d}_{safe_name}.xml"

        print(
            f"[{idx:02d}/{len(selected):02d}] {workflow_id} -> {test_file.name}",
            flush=True,
        )
        row = run_single_workflow_test(
            repo_root=repo_root,
            workflow_id=workflow_id,
            test_file=test_file,
            python_executable=args.python,
            timeout_sec=int(args.timeout_sec),
            log_file=log_file,
            junit_file=junit_file,
            extra_pytest_args=list(args.extra_pytest_arg),
            env=env,
            strict=bool(args.strict),
        )
        results.append(row)
        print(
            f"  status={row.status} gate_passed={row.gate_passed} "
            f"tests={row.junit.tests} skipped={row.junit.skipped} elapsed={row.elapsed_sec:.2f}s",
            flush=True,
        )

    finished_at = utc_now()
    elapsed_sec = round(time.time() - t0, 3)
    summary = summarize(results)

    payload = {
        "meta": {
            "profile": args.profile,
            "strict": bool(args.strict),
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_sec": elapsed_sec,
            "repo_root": str(repo_root),
            "catalog_path": str(catalog_path),
            "tests_root": str(tests_root),
            "selected_count": len(selected),
            "catalog_count": len(workflow_ids),
            "excluded": sorted(excluded),
            "timeout_sec": int(args.timeout_sec),
            "report_dir": str(report_dir),
            "auto_env_defaults": auto_env,
        },
        "summary": summary,
        "results": [
            {
                **{k: v for k, v in asdict(r).items() if k != "junit"},
                "junit": asdict(r.junit),
            }
            for r in results
        ],
    }

    json_report = report_dir / "report.json"
    md_report = report_dir / "report.md"
    json_report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown_report(
        md_report,
        profile=args.profile,
        strict=bool(args.strict),
        started_at=started_at,
        finished_at=finished_at,
        elapsed_sec=elapsed_sec,
        summary=summary,
        results=results,
    )

    print("\n=== WORKFLOW REALDATA GATE SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"JSON report: {json_report}")
    print(f"Markdown report: {md_report}")

    if summary["gate_passed"] == summary["total"] and summary["total"] > 0:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
