from pathlib import Path

from brain_researcher.core.artifact_validator import (
    build_artifact_contract_summary,
    infer_artifact_profile,
    required_artifacts_for_profile,
    validate_run_artifacts,
)


def _write_valid_artifact(path: Path) -> None:
    if path.name == "trace.jsonl":
        path.write_text('{"event_type":"test"}\n', encoding="utf-8")
    else:
        path.write_text("{}", encoding="utf-8")


def test_validate_run_artifacts_plan_execution_all_present(tmp_path: Path):
    for filename in (
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
        "observation.json",
        "analysis_bundle.json",
    ):
        _write_valid_artifact(tmp_path / filename)

    violations = validate_run_artifacts(
        run_dir=tmp_path,
        job_profile="plan_execution",
        state="succeeded",
    )
    assert violations == []


def test_validate_run_artifacts_reports_missing_file(tmp_path: Path):
    _write_valid_artifact(tmp_path / "provenance.json")
    _write_valid_artifact(tmp_path / "trajectory.json")
    _write_valid_artifact(tmp_path / "observation.json")
    _write_valid_artifact(tmp_path / "analysis_bundle.json")

    violations = validate_run_artifacts(
        run_dir=tmp_path,
        job_profile="plan_execution",
        state="succeeded",
    )
    codes = {v.code for v in violations}
    assert "ARTIFACT_MISSING_TRACE" in codes


def test_validate_run_artifacts_reports_empty_file(tmp_path: Path):
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    _write_valid_artifact(tmp_path / "provenance.json")
    _write_valid_artifact(tmp_path / "trajectory.json")
    _write_valid_artifact(tmp_path / "observation.json")
    _write_valid_artifact(tmp_path / "analysis_bundle.json")

    violations = validate_run_artifacts(
        run_dir=tmp_path,
        job_profile="default",
        state="succeeded",
    )
    codes = {v.code for v in violations}
    assert "ARTIFACT_EMPTY_TRACE" in codes
    trace_violation = next(v for v in violations if v.code == "ARTIFACT_EMPTY_TRACE")
    assert trace_violation.severity == "warn"
    assert trace_violation.blocking is False


def test_validate_run_artifacts_default_profile_requires_full_bundle(tmp_path: Path):
    _write_valid_artifact(tmp_path / "trace.jsonl")

    violations = validate_run_artifacts(
        run_dir=tmp_path,
        job_profile="default",
        state="succeeded",
    )
    codes = {v.code for v in violations}
    assert "ARTIFACT_MISSING_PROVENANCE" in codes
    assert "ARTIFACT_MISSING_TRAJECTORY" in codes
    assert "ARTIFACT_MISSING_OBSERVATION" in codes
    assert "ARTIFACT_MISSING_ANALYSIS_BUNDLE" in codes
    analysis_violation = next(
        v for v in violations if v.code == "ARTIFACT_MISSING_ANALYSIS_BUNDLE"
    )
    assert analysis_violation.severity == "error"
    assert analysis_violation.blocking is True


def test_infer_artifact_profile_prefers_plan_execution():
    profile = infer_artifact_profile(
        job_kind="plan",
        payload={"plan": {"steps": [{"tool": "workflow_preprocessing_qc"}]}},
    )
    assert profile == "plan_execution"


def test_required_artifacts_for_unknown_profile_falls_back_to_default():
    assert required_artifacts_for_profile("unknown_profile") == (
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
        "observation.json",
        "analysis_bundle.json",
    )


def test_external_review_bundle_makes_trace_files_optional():
    assert required_artifacts_for_profile("external_review_bundle") == (
        "observation.json",
        "analysis_bundle.json",
    )


def test_external_review_bundle_tracks_trace_omissions_as_still_evaluable(
    tmp_path: Path,
):
    _write_valid_artifact(tmp_path / "observation.json")
    _write_valid_artifact(tmp_path / "analysis_bundle.json")

    summary = build_artifact_contract_summary(
        run_dir=tmp_path,
        job_profile="external_review_bundle",
        state="succeeded",
    )

    assert summary["status"] == "ok"
    assert summary["reviewability"] == "fully_evaluable"
    assert summary["optional"] == [
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
    ]
    assert summary["missing_by_policy"]["still_evaluable"] == [
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
    ]


def test_build_artifact_contract_summary_reports_missing_and_empty(tmp_path: Path):
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    _write_valid_artifact(tmp_path / "provenance.json")
    _write_valid_artifact(tmp_path / "trajectory.json")
    _write_valid_artifact(tmp_path / "observation.json")
    _write_valid_artifact(tmp_path / "analysis_bundle.json")

    summary = build_artifact_contract_summary(
        run_dir=tmp_path,
        job_profile="default",
        state="succeeded",
    )

    assert summary["status"] == "degraded"
    assert summary["reviewability"] == "degraded_evaluable"
    assert summary["required"] == [
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
        "observation.json",
        "analysis_bundle.json",
    ]
    assert summary["present"] == [
        "provenance.json",
        "trajectory.json",
        "observation.json",
        "analysis_bundle.json",
    ]
    assert summary["missing"] == []
    assert summary["empty"] == ["trace.jsonl"]
    assert summary["missing_by_policy"]["degraded"] == ["trace.jsonl"]
    assert summary["complete_count"] == 4
    assert summary["total_required"] == 5
    assert summary["completeness_ratio"] == 0.8
    assert summary["violation_codes"] == ["ARTIFACT_EMPTY_TRACE"]


def test_build_artifact_contract_summary_failed_when_bundle_index_missing(
    tmp_path: Path,
):
    for filename in (
        "trace.jsonl",
        "provenance.json",
        "trajectory.json",
        "observation.json",
    ):
        _write_valid_artifact(tmp_path / filename)

    summary = build_artifact_contract_summary(
        run_dir=tmp_path,
        job_profile="run_bundle",
        state="succeeded",
    )

    assert summary["status"] == "failed"
    assert summary["reviewability"] == "not_evaluable"
    assert summary["missing_by_policy"]["fail"] == ["analysis_bundle.json"]
    assert summary["violation_codes"] == ["ARTIFACT_MISSING_ANALYSIS_BUNDLE"]


def test_build_artifact_contract_summary_invalid_json_uses_policy(tmp_path: Path):
    _write_valid_artifact(tmp_path / "trace.jsonl")
    _write_valid_artifact(tmp_path / "provenance.json")
    _write_valid_artifact(tmp_path / "trajectory.json")
    _write_valid_artifact(tmp_path / "observation.json")
    (tmp_path / "analysis_bundle.json").write_text("not json", encoding="utf-8")

    summary = build_artifact_contract_summary(
        run_dir=tmp_path,
        job_profile="run_bundle",
        state="succeeded",
    )

    assert summary["status"] == "failed"
    assert summary["invalid"] == ["analysis_bundle.json"]
    assert summary["missing_by_policy"]["fail"] == ["analysis_bundle.json"]
    assert summary["violation_codes"] == ["ARTIFACT_INVALID_ANALYSIS_BUNDLE"]


def test_build_artifact_contract_summary_skips_non_terminal_success(tmp_path: Path):
    summary = build_artifact_contract_summary(
        run_dir=tmp_path,
        job_profile="plan_execution",
        state="running",
    )

    assert summary["status"] == "skipped"
    assert summary["violation_codes"] == []
