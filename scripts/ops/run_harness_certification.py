#!/usr/bin/env python3
"""Observability-first harness certification runner.

This certification flow keeps the full report bundle observable while locking a
single hard invariant: ``execution_recipe_zero_drift``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.core.artifact_validator import (  # noqa: E402
    build_artifact_contract_summary,
    infer_artifact_profile,
)
from brain_researcher.services.mcp import server as mcp_server  # noqa: E402
from scripts.tools.audit_execution_recipes import (  # noqa: E402
    build_audit as build_execution_recipe_audit,
)

DEFAULT_REPORT_ROOT = REPO_ROOT / "artifacts" / "harness_certification"
DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RUN_SCAN = 20
MODE = "observability_first"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, content: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")


def _run_subprocess(
    cmd: list[str],
    *,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _issue(
    *,
    severity: str,
    subject: str,
    code: str,
    message: str,
    expected: str,
    observed: str,
    owner_hint: str,
    evidence_source: str,
    category: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "subject": subject,
        "code": code,
        "message": message,
        "expected": expected,
        "observed": observed,
        "owner_hint": owner_hint,
        "evidence_source": evidence_source,
        "category": category,
    }


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _has_error_issues(items: list[dict[str, Any]]) -> bool:
    return any(str(item.get("severity") or "").lower() == "error" for item in items)


@contextmanager
def _temporary_env(overrides: dict[str, str | None]) -> Iterator[None]:
    snapshot = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, original in snapshot.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def run_command_check(
    *,
    name: str,
    argv: list[str],
    report_dir: Path,
    owner_hint: str,
    timeout_s: float = DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    static_dir = report_dir / "static_checks"
    stdout_path = static_dir / f"{name}.stdout.txt"
    stderr_path = static_dir / f"{name}.stderr.txt"

    try:
        proc = _run_subprocess(argv, timeout_s=timeout_s)
        _write_text(stdout_path, proc.stdout)
        _write_text(stderr_path, proc.stderr)
        status = "passed" if proc.returncode == 0 else "failed"
        result = {
            "name": name,
            "kind": "command",
            "status": status,
            "argv": argv,
            "returncode": proc.returncode,
            "timeout_seconds": timeout_s,
            "stdout_file": str(stdout_path.relative_to(report_dir)),
            "stderr_file": str(stderr_path.relative_to(report_dir)),
        }
        if proc.returncode == 0:
            return result, []
        return (
            result,
            [
                _issue(
                    severity="error",
                    subject=name,
                    code="static_check_failed",
                    message=f"{name} exited with status {proc.returncode}",
                    expected="command exits 0",
                    observed=f"exit_code={proc.returncode}",
                    owner_hint=owner_hint,
                    evidence_source=str(stderr_path.relative_to(report_dir)),
                    category="static_check",
                )
            ],
        )
    except subprocess.TimeoutExpired as exc:
        _write_text(stdout_path, exc.output if isinstance(exc.output, str) else "")
        _write_text(stderr_path, exc.stderr if isinstance(exc.stderr, str) else "")
        return (
            {
                "name": name,
                "kind": "command",
                "status": "failed",
                "argv": argv,
                "returncode": None,
                "timeout_seconds": timeout_s,
                "stdout_file": str(stdout_path.relative_to(report_dir)),
                "stderr_file": str(stderr_path.relative_to(report_dir)),
            },
            [
                _issue(
                    severity="error",
                    subject=name,
                    code="static_check_timeout",
                    message=f"{name} timed out after {timeout_s:.1f}s",
                    expected=f"command exits within {timeout_s:.1f}s",
                    observed="timeout",
                    owner_hint=owner_hint,
                    evidence_source=str(stderr_path.relative_to(report_dir)),
                    category="static_check",
                )
            ],
        )


def _execution_recipe_drift_issues(
    *,
    summary: dict[str, Any],
    report_dir: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    evidence = "static_checks/execution_recipe_audit.json"

    for workflow_id in summary.get("workflow_catalog_missing_from_surface") or []:
        issues.append(
            _issue(
                severity="error",
                subject=str(workflow_id),
                code="workflow_catalog_missing_from_surface",
                message=(
                    f"{workflow_id} is declared in workflow_catalog but missing "
                    "from workflow_search"
                ),
                expected="workflow surfaced by workflow_search",
                observed="missing_from_workflow_search",
                owner_hint="workflow-runtime",
                evidence_source=evidence,
                category="declaration_drift",
            )
        )

    mismatch_specs = (
        (
            "declared_story_kind_mismatches",
            "declared_story_kind_mismatch",
            "declared story kind matches inferred story kind",
            "story_kind_mismatch",
        ),
        (
            "declared_supported_target_mismatches",
            "declared_supported_target_mismatch",
            "declared supported recipe targets match inferred targets",
            "supported_target_mismatch",
        ),
        (
            "declared_primary_target_mismatches",
            "declared_primary_target_mismatch",
            "declared primary recipe target matches inferred target",
            "primary_target_mismatch",
        ),
    )
    for key, code, expected, observed in mismatch_specs:
        for subject in summary.get(key) or []:
            issues.append(
                _issue(
                    severity="error",
                    subject=str(subject),
                    code=code,
                    message=f"{subject} has {observed}",
                    expected=expected,
                    observed=observed,
                    owner_hint="workflow-runtime",
                    evidence_source=evidence,
                    category="declaration_drift",
                )
            )

    for flag, count in sorted((summary.get("flag_counts") or {}).items()):
        issues.append(
            _issue(
                severity="error",
                subject="execution_recipe_audit",
                code=str(flag),
                message=f"execution recipe audit flagged {flag} on {count} subject(s)",
                expected="zero audit flags",
                observed=f"count={count}",
                owner_hint="workflow-runtime",
                evidence_source=evidence,
                category="declaration_drift",
            )
        )
    return issues


def run_execution_recipe_audit(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = build_execution_recipe_audit()
    out_path = report_dir / "static_checks" / "execution_recipe_audit.json"
    write_json(out_path, payload)
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    issues = _execution_recipe_drift_issues(summary=summary, report_dir=report_dir)
    return (
        {
            "name": "execution_recipe_audit",
            "kind": "structured",
            "status": "failed" if issues else "passed",
            "summary": summary,
            "details_file": str(out_path.relative_to(report_dir)),
        },
        issues,
    )


def _dummy_value_for_param(name: str, schema: dict[str, Any], root: Path) -> Any:
    lower = name.lower()
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    if lower in {"dry_run", "preview"}:
        return True
    if lower in {"task"}:
        return "linebisection"
    if lower in {"atlas_name"}:
        return "Schaefer2018_100"
    if lower in {"connectivity_kind"}:
        return "correlation"
    if lower in {"labels", "group_labels"}:
        return [0, 1]
    if lower in {"seed_coords"}:
        return [0.0, -52.0, 18.0]

    value_type = str(schema.get("type") or "").lower()
    if value_type == "boolean":
        return False
    if value_type == "integer":
        return 1
    if value_type == "number":
        return 1.0
    if value_type == "array":
        if "img" in lower or "file" in lower or "path" in lower:
            file_path = root / f"{name}_0.txt"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("placeholder\n", encoding="utf-8")
            return [str(file_path)]
        return []

    if "output" in lower and ("dir" in lower or "path" in lower):
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    if lower.endswith("_dir") or lower in {"bids_dir", "fmriprep_dir", "work_dir"}:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    if lower.endswith("_path") or lower.endswith("_file") or lower in {"img", "atlas"}:
        file_path = root / f"{name}.txt"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder\n", encoding="utf-8")
        return str(file_path)
    return "demo"


def _build_probe_params(entry: dict[str, Any], root: Path) -> dict[str, Any]:
    params = entry.get("params") if isinstance(entry, dict) else None
    schema = params.get("schema") if isinstance(params, dict) else None
    if not isinstance(schema, dict):
        return {"output_dir": str(root / "output")}
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    required_names = [str(item) for item in required] if isinstance(required, list) else []

    probe: dict[str, Any] = {}
    for name in required_names:
        prop_schema = properties.get(name)
        prop_schema = prop_schema if isinstance(prop_schema, dict) else {}
        probe[name] = _dummy_value_for_param(name, prop_schema, root)

    if "dry_run" in properties and "dry_run" not in probe:
        probe["dry_run"] = True
    if "output_dir" in properties and "output_dir" not in probe:
        probe["output_dir"] = _dummy_value_for_param(
            "output_dir", properties.get("output_dir") or {}, root
        )
    return probe


@contextmanager
def _mcp_policy_context(*, allowed_roots: list[Path] | None = None) -> Iterator[Any]:
    original_roots = list(mcp_server.ALLOWED_ROOTS)
    merged = list(original_roots)
    for root in allowed_roots or []:
        resolved = Path(root).resolve()
        if resolved not in merged:
            merged.append(resolved)
    try:
        mcp_server.ALLOWED_ROOTS = merged
        yield mcp_server
    finally:
        mcp_server.ALLOWED_ROOTS = original_roots


def run_workflow_surface_parity_audit(
    report_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = [
        row
        for row in mcp_server._load_workflow_catalog()
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    issues: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="br-harness-surface-") as tmp:
        scratch_root = Path(tmp)
        with _mcp_policy_context(allowed_roots=[scratch_root]) as surface:
            search_resp = surface.workflow_search("", limit=max(500, len(catalog) + 50))
            search_rows = search_resp.get("workflows") if isinstance(search_resp, dict) else []
            search_rows = search_rows if isinstance(search_rows, list) else []
            search_by_id = {
                str(row.get("id") or "").strip(): row
                for row in search_rows
                if isinstance(row, dict) and str(row.get("id") or "").strip()
            }

            for entry in catalog:
                workflow_id = str(entry.get("id") or "").strip()
                if not workflow_id:
                    continue
                search_row = search_by_id.get(workflow_id)
                target_runtime = "python"
                if isinstance(search_row, dict):
                    target_runtime = str(
                        search_row.get("primary_target")
                        or ((search_row.get("supported_recipe_targets") or ["python"])[0])
                    ).strip() or "python"
                params = _build_probe_params(entry, scratch_root / workflow_id)
                recipe_resp = surface.get_execution_recipe(
                    workflow_id,
                    params=params,
                    target_runtime=target_runtime,
                )
                comparisons.append(
                    {
                        "workflow_id": workflow_id,
                        "runbook_catalog": entry.get("runbook"),
                        "runbook_search": search_row.get("runbook")
                        if isinstance(search_row, dict)
                        else None,
                        "runbook_recipe": recipe_resp.get("runbook")
                        if isinstance(recipe_resp, dict)
                        else None,
                        "artifact_contract_catalog": entry.get("artifact_contract"),
                        "artifact_contract_search": search_row.get("artifact_contract")
                        if isinstance(search_row, dict)
                        else None,
                        "artifact_contract_recipe": recipe_resp.get("artifact_contract")
                        if isinstance(recipe_resp, dict)
                        else None,
                        "recipe_ok": bool(
                            isinstance(recipe_resp, dict) and recipe_resp.get("ok") is True
                        ),
                        "target_runtime": target_runtime,
                    }
                )

                if search_row is None:
                    issues.append(
                        _issue(
                            severity="error",
                            subject=workflow_id,
                            code="workflow_search_missing_entry",
                            message=f"{workflow_id} missing from workflow_search",
                            expected="workflow_search row present",
                            observed="missing",
                            owner_hint="workflow-runtime",
                            evidence_source="static_checks/workflow_surface_parity.json",
                            category="declaration_drift",
                        )
                    )
                else:
                    if entry.get("runbook") != search_row.get("runbook"):
                        issues.append(
                            _issue(
                                severity="error",
                                subject=workflow_id,
                                code="workflow_search_runbook_mismatch",
                                message=f"{workflow_id} runbook differs between catalog and workflow_search",
                                expected=str(entry.get("runbook")),
                                observed=str(search_row.get("runbook")),
                                owner_hint="workflow-runtime",
                                evidence_source="static_checks/workflow_surface_parity.json",
                                category="declaration_drift",
                            )
                        )
                    if not _json_equal(
                        entry.get("artifact_contract"),
                        search_row.get("artifact_contract"),
                    ):
                        issues.append(
                            _issue(
                                severity="error",
                                subject=workflow_id,
                                code="workflow_search_artifact_contract_mismatch",
                                message=(
                                    f"{workflow_id} artifact_contract differs between "
                                    "catalog and workflow_search"
                                ),
                                expected=json.dumps(entry.get("artifact_contract"), sort_keys=True),
                                observed=json.dumps(
                                    search_row.get("artifact_contract"), sort_keys=True
                                ),
                                owner_hint="workflow-runtime",
                                evidence_source="static_checks/workflow_surface_parity.json",
                                category="declaration_drift",
                            )
                        )

                if not isinstance(recipe_resp, dict) or recipe_resp.get("ok") is not True:
                    issues.append(
                        _issue(
                            severity="error",
                            subject=workflow_id,
                            code="execution_recipe_unavailable",
                            message=f"{workflow_id} execution recipe unavailable in parity audit",
                            expected="recipe returned successfully",
                            observed=str(
                                recipe_resp.get("error")
                                if isinstance(recipe_resp, dict)
                                else "non_object_response"
                            ),
                            owner_hint="workflow-runtime",
                            evidence_source="static_checks/workflow_surface_parity.json",
                            category="declaration_drift",
                        )
                    )
                    continue

                if entry.get("runbook") != recipe_resp.get("runbook"):
                    issues.append(
                        _issue(
                            severity="error",
                            subject=workflow_id,
                            code="execution_recipe_runbook_mismatch",
                            message=f"{workflow_id} runbook differs between catalog and get_execution_recipe",
                            expected=str(entry.get("runbook")),
                            observed=str(recipe_resp.get("runbook")),
                            owner_hint="workflow-runtime",
                            evidence_source="static_checks/workflow_surface_parity.json",
                            category="declaration_drift",
                        )
                    )
                if not _json_equal(
                    entry.get("artifact_contract"),
                    recipe_resp.get("artifact_contract"),
                ):
                    issues.append(
                        _issue(
                            severity="error",
                            subject=workflow_id,
                            code="execution_recipe_artifact_contract_mismatch",
                            message=(
                                f"{workflow_id} artifact_contract differs between "
                                "catalog and get_execution_recipe"
                            ),
                            expected=json.dumps(entry.get("artifact_contract"), sort_keys=True),
                            observed=json.dumps(
                                recipe_resp.get("artifact_contract"), sort_keys=True
                            ),
                            owner_hint="workflow-runtime",
                            evidence_source="static_checks/workflow_surface_parity.json",
                            category="declaration_drift",
                        )
                    )

    payload = {
        "schema_version": "workflow-surface-parity-v1",
        "generated_at": utc_now_iso(),
        "workflow_count": len(catalog),
        "mismatch_count": len(issues),
        "comparisons": comparisons,
    }
    out_path = report_dir / "static_checks" / "workflow_surface_parity.json"
    write_json(out_path, payload)
    return (
        {
            "name": "workflow_surface_parity_audit",
            "kind": "structured",
            "status": "failed" if issues else "passed",
            "summary": {
                "workflow_count": len(catalog),
                "mismatch_count": len(issues),
            },
            "details_file": str(out_path.relative_to(report_dir)),
        },
        issues,
    )


def run_tool_kg_audit(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out_path = report_dir / "static_checks" / "tool_kg_audit.json"
    payload = {
        "schema_version": "tool-kg-audit-v1",
        "generated_at": utc_now_iso(),
        "status": "skipped",
        "reason": "not_enabled_in_local_runner",
    }
    write_json(out_path, payload)
    return (
        {
            "name": "tool_kg_audit",
            "kind": "structured",
            "status": "skipped",
            "details_file": str(out_path.relative_to(report_dir)),
        },
        [],
    )


def run_static_checks(
    report_dir: Path,
    *,
    skip_tool_kg_audit: bool = False,
    command_timeout_s: float = DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    command_specs = [
        (
            "validate_capabilities",
            [sys.executable, "scripts/ci/validate_capabilities.py"],
            "capabilities",
        ),
        (
            "workflow_catalog_coverage",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/workflows/test_workflow_catalog_coverage.py",
                "-q",
            ],
            "workflow-runtime",
        ),
    ]
    for name, argv, owner in command_specs:
        result, command_issues = run_command_check(
            name=name,
            argv=argv,
            report_dir=report_dir,
            owner_hint=owner,
            timeout_s=command_timeout_s,
        )
        results.append(result)
        issues.extend(command_issues)

    for runner in (run_execution_recipe_audit, run_workflow_surface_parity_audit):
        result, runner_issues = runner(report_dir)
        results.append(result)
        issues.extend(runner_issues)

    if skip_tool_kg_audit:
        results.append(
            {
                "name": "tool_kg_audit",
                "kind": "structured",
                "status": "skipped",
                "reason": "skip_tool_kg_audit=true",
            }
        )
    else:
        result, runner_issues = run_tool_kg_audit(report_dir)
        results.append(result)
        issues.extend(runner_issues)

    return results, issues


def _write_lane_result(report_dir: Path, lane_id: str, payload: dict[str, Any]) -> str:
    relpath = Path("gold_lanes") / f"{lane_id}.json"
    write_json(report_dir / relpath, payload)
    return str(relpath)


def _preprocessing_qc_preflight_lane(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    lane_id = "workflow_preprocessing_qc_preflight"
    with tempfile.TemporaryDirectory(prefix="br-harness-preflight-") as tmp:
        root = Path(tmp)
        bids_dir = root / "bids"
        output_dir = root / "out"
        work_dir = root / "work"
        bids_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        with _mcp_policy_context(allowed_roots=[root]) as surface:
            search_resp = surface.workflow_search("workflow_preprocessing_qc", limit=10)
            recipe_resp = surface.get_execution_recipe(
                "workflow_preprocessing_qc",
                params={
                    "bids_dir": str(bids_dir),
                    "output_dir": str(output_dir),
                    "dry_run": True,
                },
                target_runtime="neurodesk",
            )
            validate_resp = surface.pipeline_plan_validate(
                {
                    "steps": [
                        {
                            "step_id": "workflow_preprocessing_qc",
                            "tool": "workflow_preprocessing_qc",
                            "params": {
                                "bids_dir": str(bids_dir),
                                "output_dir": str(output_dir),
                                "dry_run": True,
                            },
                            "work_dir": str(work_dir),
                            "output_dir": str(output_dir),
                        }
                    ]
                }
            )

    ok = (
        isinstance(search_resp, dict)
        and search_resp.get("ok") is True
        and any(
            isinstance(row, dict) and row.get("id") == "workflow_preprocessing_qc"
            for row in (search_resp.get("workflows") or [])
        )
        and isinstance(recipe_resp, dict)
        and recipe_resp.get("ok") is True
        and isinstance(validate_resp, dict)
        and validate_resp.get("ok") is True
        and not any(
            isinstance(issue, dict) and issue.get("level") == "error"
            for issue in (validate_resp.get("issues") or [])
        )
    )
    payload = {
        "lane_id": lane_id,
        "search": search_resp,
        "recipe": recipe_resp,
        "validate": validate_resp,
    }
    details_file = _write_lane_result(report_dir, lane_id, payload)
    if ok:
        return (
            {
                "lane_id": lane_id,
                "status": "passed",
                "summary": "workflow_search + get_execution_recipe + pipeline_plan_validate passed",
                "details_file": details_file,
                "run_dir": None,
            },
            [],
            None,
        )
    issues = [
        _issue(
            severity="error",
            subject=lane_id,
            code="gold_lane_failed",
            message="workflow_preprocessing_qc preflight lane failed",
            expected="preflight lane passes",
            observed="failed",
            owner_hint="workflow-runtime",
            evidence_source=details_file,
            category="gold_lane",
        )
    ]
    return (
        {
            "lane_id": lane_id,
            "status": "failed",
            "summary": "preflight failed",
            "details_file": details_file,
            "run_dir": None,
        },
        issues,
        None,
    )


def _rest_connectome_python_lane(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    lane_id = "workflow_rest_connectome_e2e_python"
    with tempfile.TemporaryDirectory(prefix="br-harness-rest-") as tmp:
        root = Path(tmp)
        with _mcp_policy_context(allowed_roots=[root]) as surface:
            search_resp = surface.workflow_search("workflow_rest_connectome_e2e", limit=10)
            recipe_resp = surface.get_execution_recipe(
                "workflow_rest_connectome_e2e",
                params={
                    "img": str(root / "bold.nii.gz"),
                    "output_dir": str(root / "out"),
                },
                target_runtime="python",
            )
    ok = (
        isinstance(search_resp, dict)
        and search_resp.get("ok") is True
        and any(
            isinstance(row, dict) and row.get("id") == "workflow_rest_connectome_e2e"
            for row in (search_resp.get("workflows") or [])
        )
        and isinstance(recipe_resp, dict)
        and recipe_resp.get("ok") is True
    )
    payload = {
        "lane_id": lane_id,
        "search": search_resp,
        "recipe": recipe_resp,
    }
    details_file = _write_lane_result(report_dir, lane_id, payload)
    if ok:
        return (
            {
                "lane_id": lane_id,
                "status": "passed",
                "summary": "workflow_search + python recipe passed",
                "details_file": details_file,
                "run_dir": None,
            },
            [],
            None,
        )
    return (
        {
            "lane_id": lane_id,
            "status": "failed",
            "summary": "recipe probe failed",
            "details_file": details_file,
            "run_dir": None,
        },
        [
            _issue(
                severity="error",
                subject=lane_id,
                code="gold_lane_failed",
                message="workflow_rest_connectome_e2e recipe lane failed",
                expected="recipe lane passes",
                observed="failed",
                owner_hint="workflow-runtime",
                evidence_source=details_file,
                category="gold_lane",
            )
        ],
        None,
    )


def _write_single_tool_transform_fixture(root: Path) -> tuple[Path, list[str]]:
    import yaml

    transform_root = root / "regfusion"
    expected_files = [
        "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt",
        "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt",
    ]
    for filename in expected_files:
        path = transform_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("0 0 0\n", encoding="utf-8")

    payload = {
        "version": "harness-certification-v1",
        "families": [
            {
                "family_id": "templates_spaces_transforms",
                "title": "Templates, Spaces, and Transforms",
                "entries": [
                    {
                        "asset_name": "regfusion_transform_files",
                        "current_state": "present_not_standardized",
                        "evidence_paths": [str(transform_root)],
                        "why_it_matters": "Needed for registry-backed transform resolution.",
                    }
                ],
            }
        ],
    }
    path = root / "neuroimage_assets_backlog.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path, expected_files


def _wait_for_terminal_run(
    run_id: str,
    *,
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.05,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False, "error": "run_not_started"}
    while time.time() < deadline:
        last = mcp_server.run_get(run_id)
        if last.get("ok") is True:
            run = last.get("run")
            if isinstance(run, dict) and str(run.get("status") or "") in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                return last
        time.sleep(poll_interval_s)
    if isinstance(last, dict):
        last = dict(last)
        last["timeout"] = True
    return last


def _required_run_artifact_summary(run_dir: Path) -> dict[str, Any]:
    required = [
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
        "observation.json",
    ]
    present: list[str] = []
    missing: list[str] = []
    empty: list[str] = []
    for filename in required:
        path = run_dir / filename
        if not path.exists() or not path.is_file():
            missing.append(filename)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        if size == 0:
            empty.append(filename)
            continue
        present.append(filename)
    return {
        "required": required,
        "present": present,
        "missing": missing,
        "empty": empty,
        "status": "ok" if not missing and not empty else "degraded",
    }


def _expected_output_file_summary(output_dir: Path, filenames: list[str]) -> dict[str, Any]:
    present: list[str] = []
    missing: list[str] = []
    empty: list[str] = []
    for filename in filenames:
        path = output_dir / filename
        if not path.exists() or not path.is_file():
            missing.append(filename)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        if size == 0:
            empty.append(filename)
            continue
        present.append(filename)
    return {
        "required": filenames,
        "present": present,
        "missing": missing,
        "empty": empty,
        "status": "ok" if not missing and not empty else "degraded",
    }


def _single_tool_python_job_lane(
    report_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    lane_id = "single_tool_python_job"
    tool_id = "resolve_transform"
    params = {
        "source_space": "MNI152",
        "target_space": "fsLR",
        "resolution": "32k",
    }
    root = report_dir / "_fixtures" / lane_id
    root.mkdir(parents=True, exist_ok=True)
    registry_path, expected_output_files = _write_single_tool_transform_fixture(root)
    output_dir = root / "out"

    env_overrides = {
        "BR_NEUROIMAGE_ASSET_REGISTRY": str(registry_path),
        "BR_ATLAS_OUTPUT_ROOT": str(root / "unused_shared_atlases"),
        "BR_REFERENCE_ASSET_ROOTS": str(root / "unused_reference_assets"),
    }
    state_snapshot = {
        "RUN_ROOT": mcp_server.RUN_ROOT,
        "ALLOWED_ROOTS": list(mcp_server.ALLOWED_ROOTS),
        "ENABLE_TOOL_EXECUTE": mcp_server.ENABLE_TOOL_EXECUTE,
        "TOOL_EXECUTE_ALLOWLIST": set(mcp_server.TOOL_EXECUTE_ALLOWLIST),
        "AGENT_MULTIAGENT_ENABLED": mcp_server.AGENT_MULTIAGENT_ENABLED,
        "AGENT_CRITIC_TOOL_GATE": mcp_server.AGENT_CRITIC_TOOL_GATE,
    }

    try:
        with _temporary_env(env_overrides):
            from brain_researcher.services.tools.neuroimage_asset_registry import (
                clear_neuroimage_asset_registry_cache,
            )
            from brain_researcher.services.tools.reference_asset_registry import (
                clear_reference_asset_registry_cache,
            )

            clear_neuroimage_asset_registry_cache()
            clear_reference_asset_registry_cache()

            mcp_server.RUN_ROOT = root / "run_root"
            mcp_server.ALLOWED_ROOTS = [
                mcp_server.RUN_ROOT.resolve(),
                root.resolve(),
            ]
            mcp_server.ENABLE_TOOL_EXECUTE = True
            mcp_server.TOOL_EXECUTE_ALLOWLIST = {tool_id}
            mcp_server.AGENT_MULTIAGENT_ENABLED = False
            mcp_server.AGENT_CRITIC_TOOL_GATE = False
            mcp_server._ensure_dirs()

            tool_execute_resp = mcp_server.tool_execute(
                tool_id,
                params=params,
                work_dir=str(root / "work"),
                output_dir=str(output_dir),
            )
            run_id = str(tool_execute_resp.get("run_id") or "").strip()
            run_resp = _wait_for_terminal_run(run_id) if run_id else {
                "ok": False,
                "error": "missing_run_id",
            }
            bundle_resp = (
                mcp_server.run_bundle_get(run_id)
                if run_id
                else {"ok": False, "error": "missing_run_id"}
            )
            clear_neuroimage_asset_registry_cache()
            clear_reference_asset_registry_cache()
    finally:
        mcp_server.RUN_ROOT = state_snapshot["RUN_ROOT"]
        mcp_server.ALLOWED_ROOTS = state_snapshot["ALLOWED_ROOTS"]
        mcp_server.ENABLE_TOOL_EXECUTE = state_snapshot["ENABLE_TOOL_EXECUTE"]
        mcp_server.TOOL_EXECUTE_ALLOWLIST = state_snapshot["TOOL_EXECUTE_ALLOWLIST"]
        mcp_server.AGENT_MULTIAGENT_ENABLED = state_snapshot[
            "AGENT_MULTIAGENT_ENABLED"
        ]
        mcp_server.AGENT_CRITIC_TOOL_GATE = state_snapshot["AGENT_CRITIC_TOOL_GATE"]

    run = run_resp.get("run") if isinstance(run_resp, dict) else None
    run_dir_str = str(run_resp.get("run_dir") or "").strip() if isinstance(run_resp, dict) else ""
    run_dir = Path(run_dir_str) if run_dir_str else None
    step = (run.get("steps") or [None])[0] if isinstance(run, dict) else None
    required_artifacts = (
        _required_run_artifact_summary(run_dir) if isinstance(run_dir, Path) else None
    )
    output_files = _expected_output_file_summary(output_dir, expected_output_files)
    result_outputs: dict[str, Any] = {}
    result_summary: dict[str, Any] = {}
    if isinstance(tool_execute_resp, dict):
        result = tool_execute_resp.get("result")
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                outputs = data.get("outputs")
                if isinstance(outputs, dict):
                    result_outputs = outputs
                summary = data.get("summary")
                if isinstance(summary, dict):
                    result_summary = summary

    payload = {
        "lane_id": lane_id,
        "tool_id": tool_id,
        "params": params,
        "registry_path": str(registry_path),
        "tool_execute": tool_execute_resp,
        "run_get": run_resp,
        "run_bundle_get": bundle_resp,
        "required_run_artifacts": required_artifacts,
        "expected_output_files": output_files,
        "result_outputs": result_outputs,
        "result_summary": result_summary,
    }
    details_file = _write_lane_result(report_dir, lane_id, payload)

    ok = (
        isinstance(tool_execute_resp, dict)
        and tool_execute_resp.get("ok") is True
        and isinstance(run_resp, dict)
        and run_resp.get("ok") is True
        and isinstance(run, dict)
        and str(run.get("status") or "") == "succeeded"
        and isinstance(step, dict)
        and str(step.get("status") or "") == "succeeded"
        and isinstance(bundle_resp, dict)
        and bundle_resp.get("ok") is True
        and isinstance(required_artifacts, dict)
        and required_artifacts.get("status") == "ok"
        and output_files.get("status") == "ok"
        and str(result_summary.get("asset_id") or "")
        == "warp.regfusion.mni152nlin2009casym.fslr.32k"
        and str(result_summary.get("source") or "") == "registry_local_cache"
    )

    if ok:
        return (
            {
                "lane_id": lane_id,
                "status": "passed",
                "summary": (
                    "real tool_execute path passed with full traceability artifacts"
                ),
                "details_file": details_file,
                "run_dir": run_dir_str or None,
            },
            [],
            run_dir_str or None,
        )

    observed = "failed"
    if isinstance(run, dict):
        observed = str(run.get("status") or observed)
    elif isinstance(run_resp, dict) and run_resp.get("timeout"):
        observed = "timeout"
    elif isinstance(tool_execute_resp, dict) and tool_execute_resp.get("error"):
        observed = str(tool_execute_resp.get("error"))
    issues = [
        _issue(
            severity="error",
            subject=lane_id,
            code="gold_lane_failed",
            message="single-tool python execution lane failed",
            expected=(
                "tool_execute succeeds and writes trace.jsonl, provenance.json, "
                "trajectory.json, observation.json, plus regfusion transform outputs"
            ),
            observed=observed,
            owner_hint="mcp-surface",
            evidence_source=details_file,
            category="gold_lane",
        )
    ]
    return (
        {
            "lane_id": lane_id,
            "status": "failed",
            "summary": "single-tool python execution failed",
            "details_file": details_file,
            "run_dir": run_dir_str or None,
        },
        issues,
        run_dir_str or None,
    )


def _hosted_surface_discovery_lane(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    lane_id = "hosted_surface_discovery"
    info_resp = mcp_server.server_info()
    search_resp = mcp_server.workflow_search("", limit=5)
    payload = {"lane_id": lane_id, "server_info": info_resp, "workflow_search": search_resp}
    details_file = _write_lane_result(report_dir, lane_id, payload)
    ok = (
        isinstance(info_resp, dict)
        and info_resp.get("ok") is True
        and isinstance(search_resp, dict)
        and search_resp.get("ok") is True
    )
    if ok:
        return (
            {
                "lane_id": lane_id,
                "status": "passed",
                "summary": "hosted/read-only surface discovery passed",
                "details_file": details_file,
                "run_dir": None,
            },
            [],
            None,
        )
    return (
        {
            "lane_id": lane_id,
            "status": "failed",
            "summary": "hosted/read-only surface discovery failed",
            "details_file": details_file,
            "run_dir": None,
        },
        [
            _issue(
                severity="error",
                subject=lane_id,
                code="gold_lane_failed",
                message="hosted surface discovery failed",
                expected="server_info and workflow_search succeed",
                observed="failed",
                owner_hint="mcp-surface",
                evidence_source=details_file,
                category="gold_lane",
            )
        ],
        None,
    )


def run_gold_lanes(
    report_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    run_dirs: list[str] = []
    for lane in (
        _preprocessing_qc_preflight_lane,
        _rest_connectome_python_lane,
        _single_tool_python_job_lane,
        _hosted_surface_discovery_lane,
    ):
        result, lane_issues, run_dir = lane(report_dir)
        results.append(result)
        issues.extend(lane_issues)
        if run_dir:
            run_dirs.append(run_dir)
    return results, issues, run_dirs


def scan_artifact_contracts(
    *,
    report_dir: Path,
    max_run_scan: int = DEFAULT_MAX_RUN_SCAN,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_list_resp = mcp_server.run_list(
        limit=max_run_scan,
        include_research_logging=False,
    )
    runs = run_list_resp.get("runs") if isinstance(run_list_resp, dict) else None
    runs = runs if isinstance(runs, list) else []
    summaries: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    for row in runs:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        run_resp = mcp_server.run_get(run_id)
        if not isinstance(run_resp, dict) or run_resp.get("ok") is not True:
            continue
        run = run_resp.get("run")
        run_dir = str(run_resp.get("run_dir") or "").strip()
        if not isinstance(run, dict) or not run_dir:
            continue

        payload_json = run.get("payload_json")
        payload: dict[str, Any] | None = None
        if isinstance(payload_json, str) and payload_json.strip():
            try:
                decoded = json.loads(payload_json)
                payload = decoded if isinstance(decoded, dict) else None
            except Exception:
                payload = None

        profile = infer_artifact_profile(
            job_kind=str(run.get("kind") or "").strip() or None,
            payload=payload,
        )
        summary = build_artifact_contract_summary(
            run_dir=Path(run_dir),
            job_profile=profile,
            state=str(run.get("status") or ""),
        )
        summary["run_id"] = run_id
        summary["kind"] = run.get("kind")
        summaries.append(summary)
        status = str(summary.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        if status == "degraded":
            issues.append(
                _issue(
                    severity="error",
                    subject=run_id,
                    code="artifact_contract_incomplete",
                    message=f"{run_id} is missing required artifacts",
                    expected="all required artifacts present",
                    observed=(
                        f"missing={summary.get('missing')}, empty={summary.get('empty')}"
                    ),
                    owner_hint="orchestrator-runtime",
                    evidence_source="artifact_contract_scan.json",
                    category="artifact_contract",
                )
            )

    eligible = [row for row in summaries if row.get("status") != "skipped"]
    ok_count = sum(1 for row in eligible if row.get("status") == "ok")
    pass_rate = round(ok_count / len(eligible), 4) if eligible else None
    payload = {
        "schema_version": "artifact-contract-scan-v1",
        "generated_at": utc_now_iso(),
        "run_count": len(summaries),
        "eligible_run_count": len(eligible),
        "status_counts": status_counts,
        "pass_rate": pass_rate,
        "runs": summaries,
    }
    write_json(report_dir / "artifact_contract_scan.json", payload)
    return payload, issues


def build_scorecard(
    *,
    static_checks: list[dict[str, Any]],
    gold_lanes: list[dict[str, Any]],
    artifact_scan: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    static_failed = sum(1 for check in static_checks if check.get("status") == "failed")
    gold_failed = sum(1 for lane in gold_lanes if lane.get("status") == "failed")
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")

    audit_summary: dict[str, Any] | None = None
    for check in static_checks:
        if check.get("name") == "execution_recipe_audit":
            summary = check.get("summary")
            if isinstance(summary, dict):
                audit_summary = summary
            break

    if audit_summary is None:
        invariant = {
            "status": "missing",
            "ok": False,
            "message": "execution recipe audit summary missing from certification run",
            "flag_total": None,
            "declared_story_kind_mismatch_count": None,
            "declared_supported_target_mismatch_count": None,
            "declared_primary_target_mismatch_count": None,
            "workflow_catalog_missing_from_surface_count": None,
        }
    else:
        flag_total = sum(int(v) for v in (audit_summary.get("flag_counts") or {}).values())
        story_kind_count = len(audit_summary.get("declared_story_kind_mismatches") or [])
        supported_target_count = len(
            audit_summary.get("declared_supported_target_mismatches") or []
        )
        primary_target_count = len(
            audit_summary.get("declared_primary_target_mismatches") or []
        )
        missing_surface_count = len(
            audit_summary.get("workflow_catalog_missing_from_surface") or []
        )
        ok = (
            flag_total == 0
            and story_kind_count == 0
            and supported_target_count == 0
            and primary_target_count == 0
            and missing_surface_count == 0
        )
        invariant = {
            "status": "passed" if ok else "failed",
            "ok": ok,
            "flag_total": flag_total,
            "declared_story_kind_mismatch_count": story_kind_count,
            "declared_supported_target_mismatch_count": supported_target_count,
            "declared_primary_target_mismatch_count": primary_target_count,
            "workflow_catalog_missing_from_surface_count": missing_surface_count,
        }

    return {
        "schema_version": "harness-scorecard-v1",
        "generated_at": utc_now_iso(),
        "mode": MODE,
        "summary": {
            "static_total": len(static_checks),
            "static_failed": static_failed,
            "gold_total": len(gold_lanes),
            "gold_failed": gold_failed,
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "artifact_contract": artifact_scan,
        "invariants": {
            "execution_recipe_zero_drift": invariant,
        },
    }


def build_drift_report(
    *,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "harness-drift-report-v1",
        "generated_at": utc_now_iso(),
        "issue_count": len(issues),
        "issues": issues,
    }


def build_summary_markdown(
    *,
    scorecard: dict[str, Any],
    report: dict[str, Any],
) -> str:
    invariant = (
        (scorecard.get("invariants") or {}).get("execution_recipe_zero_drift") or {}
    )
    summary = report.get("summary") or {}
    lines = [
        "# Harness Certification",
        "",
        f"- Mode: observability-first certification (`{MODE}`)",
        "- Gate policy: observability-first overall; `execution_recipe_zero_drift` is the only hard gate in this workflow.",
        (
            f"- Locked invariants: `execution_recipe_zero_drift="
            f"{'passed' if invariant.get('ok') else 'failed'}`"
        ),
        f"- Static checks: {summary.get('static_failed', 0)}/{summary.get('static_total', 0)} failed",
        f"- Gold lanes: {summary.get('gold_failed', 0)}/{summary.get('gold_total', 0)} failed",
        f"- Issues: {summary.get('error_count', 0)} error(s), {summary.get('warning_count', 0)} warning(s)",
        f"- Artifact contract pass rate: {(scorecard.get('artifact_contract') or {}).get('pass_rate')}",
        "",
    ]

    top_errors = [issue for issue in (report.get("issues") or []) if issue.get("severity") == "error"][:5]
    if top_errors:
        lines.append("## Top Regressions")
        lines.append("")
        for issue in top_errors:
            lines.append(
                f"- `{issue.get('code')}` on `{issue.get('subject')}`: {issue.get('message')}"
            )
        lines.append("")

    lines.append("## Outputs")
    lines.append("")
    lines.append("- `report.json`: full certification bundle")
    lines.append("- `scorecard.json`: normalized scorecard + locked invariants")
    lines.append("- `drift_report.json`: structured drift issues")
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run observability-first harness certification.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--skip-tool-kg-audit", action="store_true")
    parser.add_argument(
        "--max-run-scan",
        type=int,
        default=DEFAULT_MAX_RUN_SCAN,
    )
    parser.add_argument(
        "--static-check-timeout-seconds",
        type=float,
        default=DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS,
    )
    return parser


def run_certification(args: argparse.Namespace) -> tuple[int, Path, dict[str, Any]]:
    report_dir = Path(args.output_root) / utc_stamp()
    report_dir.mkdir(parents=True, exist_ok=True)

    static_checks, static_issues = run_static_checks(
        report_dir,
        skip_tool_kg_audit=bool(args.skip_tool_kg_audit),
        command_timeout_s=float(args.static_check_timeout_seconds),
    )
    gold_lanes, gold_issues, _run_dirs = run_gold_lanes(report_dir)
    artifact_scan, artifact_issues = scan_artifact_contracts(
        report_dir=report_dir,
        max_run_scan=int(args.max_run_scan),
    )

    issues = [*static_issues, *gold_issues, *artifact_issues]
    scorecard = build_scorecard(
        static_checks=static_checks,
        gold_lanes=gold_lanes,
        artifact_scan=artifact_scan,
        issues=issues,
    )
    drift_report = build_drift_report(issues=issues)

    invariant = (
        (scorecard.get("invariants") or {}).get("execution_recipe_zero_drift") or {}
    )
    locked_invariant_failures = [
        name
        for name, payload in (scorecard.get("invariants") or {}).items()
        if isinstance(payload, dict) and not payload.get("ok")
    ]
    report = {
        "schema_version": "harness-certification-report-v1",
        "generated_at": utc_now_iso(),
        "mode": MODE,
        "gate_policy": {
            "mode": "observability_first",
            "hard_gates": ["execution_recipe_zero_drift"],
        },
        "static_checks": static_checks,
        "gold_lanes": gold_lanes,
        "artifact_contract_scan": artifact_scan,
        "issues": issues,
        "summary": {
            "static_total": len(static_checks),
            "static_failed": sum(1 for check in static_checks if check.get("status") == "failed"),
            "gold_total": len(gold_lanes),
            "gold_failed": sum(1 for lane in gold_lanes if lane.get("status") == "failed"),
            "issue_count": len(issues),
            "error_count": sum(1 for issue in issues if issue.get("severity") == "error"),
            "warning_count": sum(1 for issue in issues if issue.get("severity") == "warning"),
            "execution_recipe_zero_drift_ok": bool(invariant.get("ok")),
            "locked_invariant_failures": locked_invariant_failures,
        },
    }

    write_json(report_dir / "scorecard.json", scorecard)
    write_json(report_dir / "drift_report.json", drift_report)
    write_json(report_dir / "report.json", report)
    (report_dir / "summary.md").write_text(
        build_summary_markdown(scorecard=scorecard, report=report),
        encoding="utf-8",
    )
    return 0, report_dir, report


def main() -> int:
    args = build_arg_parser().parse_args()
    exit_code, _report_dir, _report = run_certification(args)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
