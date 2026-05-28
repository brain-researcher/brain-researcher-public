"""Unit tests for scripts/ops/run_harness_certification.py."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from scripts.ops import run_harness_certification as mod


def test_run_execution_recipe_audit_reports_workflows_missing_from_surface(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        mod,
        "build_execution_recipe_audit",
        lambda: {
            "summary": {
                "flag_counts": {},
                "declared_story_kind_mismatches": [],
                "declared_supported_target_mismatches": [],
                "declared_primary_target_mismatches": [],
                "workflow_catalog_missing_from_surface": [
                    "workflow_missing_surface"
                ],
            }
        },
    )

    result, issues = mod.run_execution_recipe_audit(tmp_path)

    assert result["status"] == "failed"
    assert (tmp_path / "static_checks" / "execution_recipe_audit.json").exists()
    assert issues == [
        {
            "severity": "error",
            "subject": "workflow_missing_surface",
            "code": "workflow_catalog_missing_from_surface",
            "message": (
                "workflow_missing_surface is declared in workflow_catalog but "
                "missing from workflow_search"
            ),
            "expected": "workflow surfaced by workflow_search",
            "observed": "missing_from_workflow_search",
            "owner_hint": "workflow-runtime",
            "evidence_source": "static_checks/execution_recipe_audit.json",
            "category": "declaration_drift",
        }
    ]


def test_run_certification_writes_scorecard_drift_report_and_summary(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_static_checks(
        report_dir: Path,
        *,
        skip_tool_kg_audit: bool = False,
        command_timeout_s: float = mod.DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS,
    ):
        captured["report_dir"] = report_dir
        captured["skip_tool_kg_audit"] = skip_tool_kg_audit
        captured["command_timeout_s"] = command_timeout_s
        return (
            [
                {
                    "name": "validate_capabilities",
                    "kind": "command",
                    "status": "passed",
                },
                {
                    "name": "execution_recipe_audit",
                    "kind": "structured",
                    "status": "passed",
                    "summary": {
                        "flag_counts": {},
                        "declared_story_kind_mismatches": [],
                        "declared_supported_target_mismatches": [],
                        "declared_primary_target_mismatches": [],
                        "workflow_catalog_missing_from_surface": [],
                    },
                },
            ],
            [],
        )

    monkeypatch.setattr(mod, "utc_stamp", lambda: "20260310T000000Z")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "2026-03-10T00:00:00+00:00")
    monkeypatch.setattr(mod, "run_static_checks", fake_run_static_checks)
    monkeypatch.setattr(
        mod,
        "run_gold_lanes",
        lambda report_dir: (
            [
                {
                    "lane_id": "workflow_preprocessing_qc_preflight",
                    "status": "passed",
                    "summary": "ok",
                    "details_file": "gold_lanes/workflow_preprocessing_qc_preflight.json",
                    "run_dir": None,
                }
            ],
            [],
            [],
        ),
    )
    monkeypatch.setattr(
        mod,
        "scan_artifact_contracts",
        lambda **kwargs: (
            {
                "schema_version": "artifact-contract-scan-v1",
                "run_count": 1,
                "status_counts": {"ok": 1},
                "eligible_run_count": 1,
                "pass_rate": 1.0,
                "runs": [],
            },
            [],
        ),
    )

    args = mod.build_arg_parser().parse_args(
        ["--output-root", str(tmp_path), "--skip-tool-kg-audit"]
    )
    exit_code, report_dir, report = mod.run_certification(args)

    assert exit_code == 0
    assert captured["skip_tool_kg_audit"] is True
    assert captured["command_timeout_s"] == mod.DEFAULT_STATIC_CHECK_TIMEOUT_SECONDS
    assert report_dir == tmp_path / "20260310T000000Z"
    assert report["summary"]["error_count"] == 0

    scorecard_path = report_dir / "scorecard.json"
    drift_report_path = report_dir / "drift_report.json"
    summary_path = report_dir / "summary.md"
    report_path = report_dir / "report.json"

    assert scorecard_path.exists()
    assert drift_report_path.exists()
    assert summary_path.exists()
    assert report_path.exists()

    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    drift_report = json.loads(drift_report_path.read_text(encoding="utf-8"))
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary_text = summary_path.read_text(encoding="utf-8")

    assert scorecard["schema_version"] == "harness-scorecard-v1"
    assert scorecard["invariants"]["execution_recipe_zero_drift"]["ok"] is True
    assert scorecard["artifact_contract"]["pass_rate"] == 1.0
    assert drift_report["schema_version"] == "harness-drift-report-v1"
    assert drift_report["issues"] == []
    assert report_payload["summary"]["gold_failed"] == 0
    assert report_payload["summary"]["execution_recipe_zero_drift_ok"] is True
    assert "# Harness Certification" in summary_text


def test_run_command_check_reports_timeout(monkeypatch, tmp_path: Path) -> None:
    def raise_timeout(*args, **kwargs):
        raise mod.subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=15.0,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(mod, "_run_subprocess", raise_timeout)

    result, issues = mod.run_command_check(
        name="workflow_catalog_coverage",
        argv=["python", "-m", "pytest", "tests/unit/workflows/test_workflow_catalog_coverage.py"],
        report_dir=tmp_path,
        owner_hint="workflow-runtime",
        timeout_s=15.0,
    )

    assert result["status"] == "failed"
    assert result["timeout_seconds"] == 15.0
    assert issues[0]["code"] == "static_check_timeout"
    assert (tmp_path / "static_checks" / "workflow_catalog_coverage.stdout.txt").exists()


def test_workflow_surface_parity_audit_reports_search_and_recipe_mismatches(
    monkeypatch, tmp_path: Path
) -> None:
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_demo",
                "runbook": "docs/runbooks/workflow_demo.md",
                "artifact_contract": {"required_outputs": ["expected.txt"]},
                "params": {
                    "schema": {
                        "type": "object",
                        "required": ["output_dir"],
                        "properties": {"output_dir": {"type": "string"}},
                    }
                },
            }
        ],
    )

    class StubSurface:
        def workflow_search(self, query: str, limit: int = 500):
            del query, limit
            return {
                "ok": True,
                "workflows": [
                    {
                        "id": "workflow_demo",
                        "runbook": "docs/runbooks/workflow_demo_search.md",
                        "artifact_contract": {"required_outputs": ["search.txt"]},
                        "execution_recipe_available": True,
                        "supported_recipe_targets": ["python"],
                        "primary_target": "python",
                    }
                ],
            }

        def get_execution_recipe(
            self, workflow_id: str, *, params: dict[str, object], target_runtime: str
        ):
            assert workflow_id == "workflow_demo"
            assert target_runtime == "python"
            assert "output_dir" in params
            return {
                "ok": True,
                "runbook": "docs/runbooks/workflow_demo.md",
                "artifact_contract": {"required_outputs": ["recipe.txt"]},
            }

    @contextmanager
    def fake_policy_context(*args, **kwargs):
        del args, kwargs
        yield StubSurface()

    monkeypatch.setattr(mod, "_mcp_policy_context", fake_policy_context)

    result, issues = mod.run_workflow_surface_parity_audit(tmp_path)

    assert result["status"] == "failed"
    codes = {issue["code"] for issue in issues}
    assert "workflow_search_runbook_mismatch" in codes
    assert "workflow_search_artifact_contract_mismatch" in codes
    assert "execution_recipe_artifact_contract_mismatch" in codes
    assert (tmp_path / "static_checks" / "workflow_surface_parity.json").exists()


def test_single_tool_python_job_lane_executes_real_tool_job(tmp_path: Path) -> None:
    result, issues, run_dir = mod._single_tool_python_job_lane(tmp_path)

    assert result["lane_id"] == "single_tool_python_job"
    assert result["status"] == "passed"
    assert issues == []
    assert run_dir is not None

    details_path = tmp_path / result["details_file"]
    assert details_path.exists()
    payload = json.loads(details_path.read_text(encoding="utf-8"))
    assert payload["tool_id"] == "resolve_transform"
    assert payload["required_run_artifacts"]["status"] == "ok"
    assert payload["expected_output_files"]["status"] == "ok"
    assert payload["result_summary"]["asset_id"] == (
        "warp.regfusion.mni152nlin2009casym.fslr.32k"
    )
    assert Path(run_dir).exists()


def test_build_scorecard_records_execution_recipe_zero_drift_invariant() -> None:
    scorecard = mod.build_scorecard(
        static_checks=[
            {
                "name": "execution_recipe_audit",
                "status": "passed",
                "summary": {
                    "flag_counts": {},
                    "declared_story_kind_mismatches": [],
                    "declared_supported_target_mismatches": [],
                    "declared_primary_target_mismatches": [],
                    "workflow_catalog_missing_from_surface": [],
                },
            }
        ],
        gold_lanes=[],
        artifact_scan={"run_count": 0, "eligible_run_count": 0, "status_counts": {}},
        issues=[],
    )

    invariant = scorecard["invariants"]["execution_recipe_zero_drift"]
    assert invariant["ok"] is True
    assert invariant["flag_total"] == 0
    assert invariant["declared_story_kind_mismatch_count"] == 0
    assert invariant["declared_supported_target_mismatch_count"] == 0
    assert invariant["declared_primary_target_mismatch_count"] == 0
    assert invariant["workflow_catalog_missing_from_surface_count"] == 0


def test_build_scorecard_flags_execution_recipe_zero_drift_regression() -> None:
    scorecard = mod.build_scorecard(
        static_checks=[
            {
                "name": "execution_recipe_audit",
                "status": "failed",
                "summary": {
                    "flag_counts": {"missing_declaration": 2},
                    "declared_story_kind_mismatches": ["workflow_demo"],
                    "declared_supported_target_mismatches": [],
                    "declared_primary_target_mismatches": [],
                    "workflow_catalog_missing_from_surface": [],
                },
            }
        ],
        gold_lanes=[],
        artifact_scan={"run_count": 0, "eligible_run_count": 0, "status_counts": {}},
        issues=[],
    )

    invariant = scorecard["invariants"]["execution_recipe_zero_drift"]
    assert invariant["ok"] is False
    assert invariant["status"] == "failed"
    assert invariant["flag_total"] == 2
    assert invariant["declared_story_kind_mismatch_count"] == 1
