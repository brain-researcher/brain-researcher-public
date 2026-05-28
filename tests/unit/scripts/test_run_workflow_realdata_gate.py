"""Unit tests for scripts/workflows/run_workflow_realdata_gate.py."""

from __future__ import annotations

from pathlib import Path

from scripts.workflows.run_workflow_realdata_gate import (
    JUnitSummary,
    bootstrap_realdata_env,
    build_primary_workflow_test_map,
    detect_test_contract,
    extract_executed_workflow_ids,
    infer_primary_workflow_for_test,
    load_workflow_ids,
    parse_junit_summary,
    summarize,
)


def test_extract_and_infer_primary_workflow(tmp_path: Path) -> None:
    test_file = tmp_path / "test_workflow_combo_smoke.py"
    test_file.write_text(
        """
from brain_researcher.services.tools.runner import execute_tool


def test_it(tmp_path):
    execute_tool("workflow_seed_based_connectivity", {"output_dir": str(tmp_path / "seed")})
    execute_tool("workflow_spatial_correlation", {"output_dir": str(tmp_path / "spatial")})
""",
        encoding="utf-8",
    )

    text = test_file.read_text(encoding="utf-8")
    executed = extract_executed_workflow_ids(text)
    assert executed == [
        "workflow_seed_based_connectivity",
        "workflow_spatial_correlation",
    ]
    assert infer_primary_workflow_for_test(test_file) == "workflow_spatial_correlation"


def test_build_primary_workflow_test_map_prefers_more_specific_filename(
    tmp_path: Path,
) -> None:
    generic = tmp_path / "test_workflow_misc_smoke.py"
    specific = tmp_path / "test_workflow_seed_based_connectivity_ds000114_smoke.py"

    body = (
        "from brain_researcher.services.tools.runner import execute_tool\n"
        "def test_it(tmp_path):\n"
        '    execute_tool("workflow_seed_based_connectivity", {"output_dir": str(tmp_path)})\n'
    )
    generic.write_text(body, encoding="utf-8")
    specific.write_text(body, encoding="utf-8")

    mapping = build_primary_workflow_test_map([generic, specific])
    assert mapping["workflow_seed_based_connectivity"] == specific


def test_parse_junit_summary_collects_skip_reason(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """
<testsuite tests="1" failures="0" errors="0" skipped="1">
  <testcase classname="x" name="test_x">
    <skipped message="dataset missing" />
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    summary = parse_junit_summary(junit)
    assert isinstance(summary, JUnitSummary)
    assert summary.tests == 1
    assert summary.failures == 0
    assert summary.errors == 0
    assert summary.skipped == 1
    assert summary.skip_reasons == ["dataset missing"]


def test_detect_test_contract(tmp_path: Path) -> None:
    with_artifact = tmp_path / "test_with_artifact.py"
    with_artifact.write_text(
        """
def test_x(res, out):
    assert res.status == "success"
    assert (out / "file.txt").exists()
""".strip(),
        encoding="utf-8",
    )

    without_artifact = tmp_path / "test_without_artifact.py"
    without_artifact.write_text(
        """
def test_x(res):
    assert res.status == "success"
""".strip(),
        encoding="utf-8",
    )

    assert detect_test_contract(with_artifact) == (True, True)
    assert detect_test_contract(without_artifact) == (True, False)


def test_load_workflow_ids(tmp_path: Path) -> None:
    catalog = tmp_path / "workflow_catalog.yaml"
    catalog.write_text(
        """
workflows:
  - id: workflow_one
  - id: workflow_two
""".strip(),
        encoding="utf-8",
    )

    assert load_workflow_ids(catalog) == ["workflow_one", "workflow_two"]


def test_summarize_counts() -> None:
    from scripts.workflows.run_workflow_realdata_gate import WorkflowRunResult

    rows = [
        WorkflowRunResult(
            workflow_id="workflow_a",
            test_file="a.py",
            status="passed",
            gate_passed=True,
            elapsed_sec=1.0,
            return_code=0,
            timed_out=False,
            junit=JUnitSummary(
                tests=1, failures=0, errors=0, skipped=0, skip_reasons=[]
            ),
            has_status_assert=True,
            has_artifact_assert=True,
            log_file="a.log",
            junit_file="a.xml",
        ),
        WorkflowRunResult(
            workflow_id="workflow_b",
            test_file="b.py",
            status="skipped",
            gate_passed=False,
            elapsed_sec=1.0,
            return_code=0,
            timed_out=False,
            junit=JUnitSummary(
                tests=1, failures=0, errors=0, skipped=1, skip_reasons=["missing"]
            ),
            has_status_assert=True,
            has_artifact_assert=False,
            log_file="b.log",
            junit_file="b.xml",
        ),
    ]

    got = summarize(rows)
    assert got["total"] == 2
    assert got["passed"] == 1
    assert got["skipped"] == 1
    assert got["gate_passed"] == 1
    assert got["missing_artifact_assert"] == 1


def test_bootstrap_realdata_env_sets_defaults(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (home / "projects/dataset/openneuro/ds000114").mkdir(parents=True)
    (home / "projects/dataset/openneuro/ds000117").mkdir(parents=True)
    (
        repo / "outputs/_a4_ds000114_linebisection/derivatives_local/ds000114-fmriprep"
    ).mkdir(parents=True)

    monkeypatch.setattr("scripts.workflows.run_workflow_realdata_gate.Path.home", lambda: home)
    env: dict[str, str] = {}
    defaults = bootstrap_realdata_env(repo, env)

    assert env["BR_DS000114_BIDS_ROOT"].endswith("ds000114")
    assert env["BR_DS000117_BIDS_ROOT"].endswith("ds000117")
    assert env["BR_DS000114_FMRIPREP_ROOT"].endswith("ds000114-fmriprep")
    assert env["BR_DS000114_OPENNEURO_ROOT"].endswith("ds000114")
    assert env["BR_FITLINS_BIDS_ROOT"] == env["BR_DS000114_BIDS_ROOT"]
    assert env["BR_FITLINS_FMRIPREP_ROOT"] == env["BR_DS000114_FMRIPREP_ROOT"]
    assert defaults["BR_DS000114_BIDS_ROOT"] == env["BR_DS000114_BIDS_ROOT"]
