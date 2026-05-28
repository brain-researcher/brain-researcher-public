"""Unit tests for /api/analyses/* endpoints (P0 alias for jobs)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.config.run_artifacts import RecorderConfig
from brain_researcher.services.orchestrator.analyses_endpoints import api_router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(api_router)
    app.state.job_store = MemoryJobStore(total_gpu_slots=0)
    return app


def _write_minimal_run_dir(base_dir: Path) -> Path:
    run_dir = base_dir / "run-1"
    run_dir.mkdir()

    (run_dir / "output.txt").write_text("ok", encoding="utf-8")
    (run_dir / "trajectory.json").write_text(
        '{"schema_version":"ATIF-v1.4"}', encoding="utf-8"
    )
    (run_dir / "provenance.json").write_text(
        json.dumps({"schema_version": "provenance-v1"}), encoding="utf-8"
    )
    return run_dir


@pytest.mark.asyncio
async def test_get_analysis_bundle_returns_analysis_bundle(tmp_path: Path, app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    run_dir = _write_minimal_run_dir(tmp_path)

    payload = {
        "artifacts": [
            {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
        ],
        "metadata": {"name": "Example analysis"},
    }
    await job_store.enqueue(
        JobRecord(
            job_id="job_analysis_001",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="run-1",
            run_dir=str(run_dir),
        )
    )

    mock_config = RecorderConfig()
    mock_config.root = tmp_path
    with patch(
        "brain_researcher.services.orchestrator.analyses_endpoints.get_recorder_config",
        return_value=mock_config,
    ):
        with TestClient(app) as client:
            resp = client.get("/api/analyses/job_analysis_001")
            assert resp.status_code == 200
            data = resp.json()

    assert data["schema_version"] == "analysis-bundle-v1"
    assert data["job_id"] == "job_analysis_001"
    assert data["run_id"] == "run-1"
    assert data["files"]["observation_json"] == "observation.json"
    assert data["files"]["trajectory_json"] == "trajectory.json"

    artifacts = data.get("artifacts") or []
    assert artifacts
    assert artifacts[0]["checksum_status"] == "ok"
    assert artifacts[0]["checksum"].startswith("sha256:")


@pytest.mark.asyncio
async def test_analysis_stream_replays_events_and_terminates(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    await job_store.enqueue(
        JobRecord(
            job_id="job_test_analysis_stream_001",
            kind="test",
            payload_json="{}",
            state=JobState.QUEUED,
        )
    )
    await job_store.append_event(
        "job_test_analysis_stream_001", "job.started", payload={"status": "running"}
    )
    await job_store.append_event(
        "job_test_analysis_stream_001",
        "analysis.completed",
        payload={"status": "succeeded"},
    )

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/analyses/job_test_analysis_stream_001/stream"
            "?since=0&include_initial_state=false",
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    assert "event: job.started" in content
    assert "event: analysis.completed" in content


@pytest.mark.asyncio
async def test_list_analyses_exposes_client_plan_metadata_without_run_dir(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    payload = {
        "prompt": "Run GLM on ds000001",
        "metadata": {
            "thread_id": "thread_abc123",
            "project_id": "proj_alpha",
            "client_plan_envelope": {
                "intent": "Task GLM",
                "dataset_id": "ds000001",
                "template_id": "glm/nilearn_glm",
                "analysis_id": "glm",
                "pipeline_id": "nilearn_glm",
            },
        },
    }
    await job_store.enqueue(
        JobRecord(
            job_id="job_analysis_list_001",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            project_id="proj_alpha",
        )
    )

    with TestClient(app) as client:
        resp = client.get("/api/analyses?project_id=proj_alpha")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"]
    item = data["items"][0]
    assert item["analysis_id"] == "job_analysis_list_001"
    assert item["project_id"] == "proj_alpha"
    assert item["thread_id"] == "thread_abc123"
    assert item["dataset_id"] == "ds000001"
    assert item["template_id"] == "glm/nilearn_glm"
    assert item["analysis_preset_id"] == "glm"
    assert item["pipeline_preset_id"] == "nilearn_glm"
    assert item["has_results"] is False


@pytest.mark.asyncio
async def test_list_analyses_honors_project_filter(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    for job_id, project_id in (
        ("job_proj_alpha", "proj_alpha"),
        ("job_proj_beta", "proj_beta"),
    ):
        await job_store.enqueue(
            JobRecord(
                job_id=job_id,
                kind="test",
                payload_json=json.dumps({"prompt": job_id, "metadata": {"project_id": project_id}}),
                state=JobState.QUEUED,
                project_id=project_id,
            )
        )

    with TestClient(app) as client:
        resp = client.get("/api/analyses?project_id=proj_beta")

    assert resp.status_code == 200
    data = resp.json()
    assert [item["analysis_id"] for item in data["items"]] == ["job_proj_beta"]


@pytest.mark.asyncio
async def test_list_analyses_include_id_adds_job_outside_current_page(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    await job_store.enqueue(
        JobRecord(
            job_id="job_old_known",
            kind="test",
            payload_json=json.dumps({"prompt": "old known job"}),
            state=JobState.FAILED,
            created_at=1_700_000_000,
        )
    )
    await job_store.enqueue(
        JobRecord(
            job_id="job_recent",
            kind="test",
            payload_json=json.dumps({"prompt": "recent job"}),
            state=JobState.QUEUED,
            created_at=1_700_000_100,
        )
    )

    with TestClient(app) as client:
        resp = client.get("/api/analyses?limit=1&include_id=job_old_known")

    assert resp.status_code == 200
    data = resp.json()
    assert [item["analysis_id"] for item in data["items"]] == ["job_recent", "job_old_known"]
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_list_analyses_include_id_respects_metadata_project_filter(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    await job_store.enqueue(
        JobRecord(
            job_id="job_project_alpha",
            kind="test",
            payload_json=json.dumps(
                {"prompt": "alpha", "metadata": {"project_id": "proj_alpha"}}
            ),
            state=JobState.FAILED,
            created_at=1_700_000_000,
        )
    )
    await job_store.enqueue(
        JobRecord(
            job_id="job_project_beta",
            kind="test",
            payload_json=json.dumps(
                {"prompt": "beta", "metadata": {"project_id": "proj_beta"}}
            ),
            state=JobState.QUEUED,
            project_id="proj_beta",
            created_at=1_700_000_100,
        )
    )

    with TestClient(app) as client:
        resp = client.get(
            "/api/analyses?project_id=proj_beta&limit=1&include_id=job_project_alpha"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert [item["analysis_id"] for item in data["items"]] == ["job_project_beta"]
