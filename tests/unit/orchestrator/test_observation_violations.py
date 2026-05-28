import json
from pathlib import Path

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.observation import load_or_build_observation


def test_observation_aggregates_step_violations(tmp_path: Path):
    # Prepare run directory with provenance containing step violations
    run_dir = tmp_path
    step_payload = {
        "id": "step_1",
        "state": "failed",
        "violations": [
            {
                "schema_version": "violation-v1",
                "code": "QC_MISSING_T1W",
                "message": "No T1w",
                "severity": "critical",
                "blocking": True,
            }
        ],
    }
    prov = {"steps": [step_payload]}
    (run_dir / "provenance.json").write_text(json.dumps(prov))

    record = JobRecord(
        job_id="job1",
        kind="tool",
        payload_json=json.dumps({}),
        state=JobState.FAILED.value,
        run_dir=str(run_dir),
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert spec.violations is not None
    assert len(spec.violations) == 1
    assert spec.violations[0]["code"] == "QC_MISSING_T1W"


def test_observation_merges_workflow_result_phases(tmp_path: Path):
    run_dir = tmp_path
    # No provenance; rely on workflow_result attached to payload
    workflow_result = {
        "steps": [
                {
                    "step_id": "s1",
                    "status": "succeeded",
                    "violations": [
                        {
                            "schema_version": "violation-v1",
                            "code": "QC_LOW_SNR",
                            "message": "Low SNR",
                            "severity": "warn",
                        }
                    ],
                    "preflight_result": {"status": "ok", "violations": []},
                    "postcheck_result": {
                        "status": "warn",
                        "violations": [
                            {
                            "schema_version": "violation-v1",
                            "code": "QC_LOW_SNR",
                            "message": "Low SNR",
                            "severity": "warn",
                        }
                    ],
                },
            }
        ]
    }
    payload = {"metadata": {"workflow_result": workflow_result}}

    record = JobRecord(
        job_id="job2",
        kind="plan",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED.value,
        run_dir=str(run_dir),
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert spec.steps and spec.steps[0]["postcheck_result"]["status"] == "warn"
    assert spec.violations is not None
    assert any(v["code"] == "QC_LOW_SNR" for v in spec.violations)


def test_observation_includes_plan_mask_reasons(tmp_path: Path):
    run_dir = tmp_path
    payload = {
        "plan": {
            "mask_reasons": [
                {
                    "schema_version": "violation-v1",
                    "code": "BUDGET_EXCEEDED",
                    "message": "too expensive",
                    "severity": "warn",
                }
            ]
        }
    }
    record = JobRecord(
        job_id="job3",
        kind="plan",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED.value,
        run_dir=str(run_dir),
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert spec.violations is not None
    assert any(v["code"] == "BUDGET_EXCEEDED" for v in spec.violations)


def test_observation_adds_artifact_contract_violations_for_succeeded_plan(tmp_path: Path):
    run_dir = tmp_path
    # Only one required plan-execution artifact exists.
    (run_dir / "provenance.json").write_text("{}", encoding="utf-8")

    payload = {"plan": {"steps": [{"tool": "workflow_preprocessing_qc", "params": {}}]}}
    record = JobRecord(
        job_id="job4",
        kind="plan",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED.value,
        run_dir=str(run_dir),
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert spec.violations is not None
    codes = {v["code"] for v in spec.violations}
    assert "ARTIFACT_MISSING_TRACE" in codes
    assert "ARTIFACT_MISSING_TRAJECTORY" in codes
    # observation.json is written after synthesis; it is intentionally assumed present.
    assert "ARTIFACT_MISSING_OBSERVATION" not in codes
    assert spec.diagnostics_summary is not None
    artifact_contract = spec.diagnostics_summary["artifact_contract"]
    assert artifact_contract["profile"] == "plan_execution"
    assert artifact_contract["status"] == "degraded"
    assert artifact_contract["missing"] == ["trace.jsonl", "trajectory.json"]
    assert "observation.json" in artifact_contract["present"]
