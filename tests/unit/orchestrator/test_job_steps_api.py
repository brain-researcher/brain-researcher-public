"""
Tests for the step summary API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.jobs_steps_api import router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def _build_client(job_store: MemoryJobStore) -> TestClient:
    app = FastAPI()
    app.state.job_store = job_store
    app.include_router(router)
    return TestClient(app)


def _create_job(
    *,
    job_id: str,
    state: JobState,
    run_dir: Path | None = None,
    provenance_path: str | None = None,
    payload_json: str = "{}",
    error_message: str | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        kind="dag",
        payload_json=payload_json,
        state=state.value,
        run_dir=str(run_dir) if run_dir else None,
        provenance_path=provenance_path,
        error_message=error_message,
    )


def test_get_job_steps_returns_child_summaries(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)

    child_runs = [
        {
            "step_id": "prep",
            "name": "Pre-process structural scans",
            "state": "succeeded",
            "execution_time_ms": 1234,
            "run_dir": str(run_dir / "steps" / "prep"),
        },
        {
            "step_id": "glm",
            "name": "Fit GLM",
            "state": "failed",
            "error": "bet exited 1",
            "run_dir": str(run_dir / "steps" / "glm"),
        },
    ]
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "schema_version": "run-v0.2",
                "state": "succeeded",
                "child_runs": child_runs,
            }
        ),
        encoding="utf-8",
    )

    job = _create_job(
        job_id="job-123",
        state=JobState.SUCCEEDED,
        run_dir=run_dir,
        provenance_path="provenance.json",
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.job_id
    assert payload["state"] == "succeeded"
    assert len(payload["steps"]) == 2
    assert payload["steps"][0]["step_id"] == "prep"
    assert payload["steps"][1]["error"] == "bet exited 1"


def test_get_job_steps_ignores_payload_steps_when_provenance_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "provenance.json").write_text(
        json.dumps({"child_runs": [{"step_id": "from-provenance", "state": "succeeded"}]}),
        encoding="utf-8",
    )

    job = _create_job(
        job_id="job-with-provenance",
        state=JobState.SUCCEEDED,
        run_dir=run_dir,
        provenance_path="provenance.json",
        payload_json=json.dumps(
            {
                "steps": [
                    {
                        "id": "payload-step",
                        "status": "failed",
                        "attempt": "not-an-int",
                    }
                ]
            }
        ),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")

    assert response.status_code == 200
    assert response.json()["steps"][0]["step_id"] == "from-provenance"


def test_get_job_steps_missing_job_returns_404() -> None:
    client = _build_client(MemoryJobStore())
    response = client.get("/api/jobs/missing/steps")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job missing not found"


def test_get_job_steps_no_provenance_returns_empty(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)

    job = _create_job(
        job_id="running-job",
        state=JobState.RUNNING,
        run_dir=run_dir,
        provenance_path="provenance.json",
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.job_id
    assert payload["steps"] == []


def test_get_job_steps_falls_back_to_payload_steps_when_provenance_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)

    job = _create_job(
        job_id="failed-plan-job",
        state=JobState.FAILED,
        run_dir=run_dir,
        provenance_path="provenance.json",
        payload_json=json.dumps(
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "1. workflow_rest_connectome_e2e",
                        "status": "failed",
                        "preview": "ValueError: File not found",
                    }
                ]
            }
        ),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["steps"] == [
        {
            "step_id": "step_001",
            "name": "1. workflow_rest_connectome_e2e",
            "state": "failed",
            "created_at": None,
            "started_at": None,
            "finished_at": None,
            "attempt": 1,
            "max_attempts": 3,
            "retry_reason": None,
            "cache_marker": None,
            "cache_key": None,
            "execution_time_ms": None,
            "run_dir": None,
            "error": "ValueError: File not found",
            "provenance_path": None,
            "violations": [],
            "preflight_result": None,
            "exec_result": None,
            "postcheck_result": None,
        }
    ]


def test_get_job_steps_failed_without_step_trace_returns_failed_synthetic_step(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)

    job = _create_job(
        job_id="failed-before-steps",
        state=JobState.FAILED,
        run_dir=run_dir,
        provenance_path="provenance.json",
        error_message="Plan is missing executable steps",
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["steps"][0]["step_id"] == "job_failed"
    assert payload["steps"][0]["state"] == "failed"
    assert payload["steps"][0]["error"] == "Plan is missing executable steps"
    assert payload["steps"][0]["run_dir"] is None


def test_get_job_steps_failed_pending_payload_step_is_not_reported_pending(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)

    job = _create_job(
        job_id="failed-pending-placeholder",
        state=JobState.FAILED,
        run_dir=run_dir,
        provenance_path="provenance.json",
        payload_json=json.dumps(
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "1. workflow_rest_connectome_e2e",
                        "status": "pending",
                    }
                ]
            }
        ),
        error_message="ToolExecutor unavailable for plan execution",
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["steps"][0]["step_id"] == "step_001"
    assert payload["steps"][0]["state"] == "failed"
    assert payload["steps"][0]["error"] == "ToolExecutor unavailable for plan execution"


def test_get_job_steps_malformed_provenance_returns_500(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "provenance.json").write_text("{invalid json", encoding="utf-8")

    job = _create_job(
        job_id="bad-provenance",
        state=JobState.SUCCEEDED,
        run_dir=run_dir,
        provenance_path="provenance.json",
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    response = client.get(f"/api/jobs/{job.job_id}/steps")
    assert response.status_code == 500
    assert response.json()["detail"] == "Malformed provenance document for job"
