from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.config.run_artifacts import RecorderConfig
from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def _build_client(job_store: MemoryJobStore) -> TestClient:
    app = FastAPI()
    app.state.job_store = job_store
    app.include_router(router)
    return TestClient(app)


def test_job_artifacts_include_workflow_output_dir_files(tmp_path: Path) -> None:
    run_store_root = tmp_path / "runs"
    run_dir = run_store_root / "20260521" / "job-connectome"
    output_dir = run_store_root / "ds000114" / "workflow_rest_connectome_e2e"
    run_dir.mkdir(parents=True)
    (run_dir / "commitment.json").write_text("{}", encoding="utf-8")
    (run_dir / "option_set.json").write_text("{}", encoding="utf-8")
    (run_dir / "research_episode.json").write_text("{}", encoding="utf-8")
    (output_dir / "timeseries").mkdir(parents=True)
    (output_dir / "timeseries" / "timeseries.npy").write_bytes(b"npy")
    (output_dir / "timeseries" / "timeseries.csv").write_text(
        "roi,value\n", encoding="utf-8"
    )
    (output_dir / "connectivity_matrix.npy").write_bytes(b"matrix")
    (output_dir / "feature_contract.json").write_text(
        '{"matrix_kind":"correlation"}',
        encoding="utf-8",
    )
    (output_dir / "review_probes").mkdir()
    (output_dir / "review_probes" / "label_permutation_null.json").write_text(
        '{"pipeline_scope":"full_pipeline"}',
        encoding="utf-8",
    )

    payload = {
        "parameters": {"output_dir": str(output_dir)},
        "steps": [
            {
                "id": "step_001",
                "tool": "workflow_rest_connectome_e2e",
                "args": {"output_dir": str(output_dir)},
            }
        ],
    }
    job = JobRecord(
        job_id="job-connectome",
        kind="dag",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED,
        run_id="job-connectome",
        run_dir=str(run_dir),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    config = RecorderConfig()
    config.root = run_store_root
    with patch(
        "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
        return_value=config,
    ):
        response = client.get(f"/api/jobs/{job.job_id}/artifacts")

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    paths = {artifact["path"] for artifact in artifacts}

    assert (
        "workflow_outputs/workflow_rest_connectome_e2e/timeseries/timeseries.npy"
        in paths
    )
    assert (
        "workflow_outputs/workflow_rest_connectome_e2e/timeseries/timeseries.csv"
        in paths
    )
    assert (
        "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy" in paths
    )
    assert (
        "workflow_outputs/workflow_rest_connectome_e2e/feature_contract.json" in paths
    )
    assert (
        "workflow_outputs/workflow_rest_connectome_e2e/review_probes/"
        "label_permutation_null.json"
    ) in paths
    assert "commitment.json" not in paths
    assert "option_set.json" not in paths
    assert "research_episode.json" not in paths

    matrix = next(
        artifact
        for artifact in artifacts
        if artifact["path"].endswith("connectivity_matrix.npy")
    )
    assert matrix["download_url"].endswith(
        "/api/jobs/job-connectome/artifacts/files/"
        "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
    )


def test_job_artifacts_skip_output_dir_in_prefix_sibling_root(tmp_path: Path) -> None:
    run_store_root = tmp_path / "runs"
    run_dir = run_store_root / "20260521" / "job-safe"
    output_dir = tmp_path / "runs_evil" / "workflow_rest_connectome_e2e"
    run_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (output_dir / "secret.txt").write_text("outside-root", encoding="utf-8")

    job = JobRecord(
        job_id="job-safe",
        kind="dag",
        payload_json=json.dumps({"parameters": {"output_dir": str(output_dir)}}),
        state=JobState.SUCCEEDED,
        run_id="job-safe",
        run_dir=str(run_dir),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    config = RecorderConfig()
    config.root = run_store_root
    with (
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=config,
        ),
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_job_observation",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = client.get(f"/api/jobs/{job.job_id}/artifacts")

    assert response.status_code == 200
    paths = {artifact["path"] for artifact in response.json()["artifacts"]}
    assert "workflow_outputs/workflow_rest_connectome_e2e/secret.txt" not in paths
    assert not (run_dir / "workflow_outputs").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink support required")
def test_job_artifacts_skip_symlinked_output_files(tmp_path: Path) -> None:
    run_store_root = tmp_path / "runs"
    run_dir = run_store_root / "20260521" / "job-safe"
    output_dir = run_store_root / "external" / "workflow_rest_connectome_e2e"
    outside_file = tmp_path / "outside.txt"
    run_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    outside_file.write_text("outside-root", encoding="utf-8")
    (output_dir / "leak.txt").symlink_to(outside_file)

    job = JobRecord(
        job_id="job-safe",
        kind="dag",
        payload_json=json.dumps({"parameters": {"output_dir": str(output_dir)}}),
        state=JobState.SUCCEEDED,
        run_id="job-safe",
        run_dir=str(run_dir),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    config = RecorderConfig()
    config.root = run_store_root
    with (
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=config,
        ),
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_job_observation",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = client.get(f"/api/jobs/{job.job_id}/artifacts")

    assert response.status_code == 200
    paths = {artifact["path"] for artifact in response.json()["artifacts"]}
    assert "workflow_outputs/workflow_rest_connectome_e2e/leak.txt" not in paths
    assert not (run_dir / "workflow_outputs").exists()


def test_job_artifacts_deduplicate_observation_and_scanned_paths(
    tmp_path: Path,
) -> None:
    run_store_root = tmp_path / "runs"
    run_dir = run_store_root / "20260521" / "job-connectome"
    artifact_path = (
        run_dir
        / "workflow_outputs"
        / "workflow_rest_connectome_e2e"
        / "connectivity_matrix.npy"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"matrix")

    job = JobRecord(
        job_id="job-connectome",
        kind="dag",
        payload_json=json.dumps({"parameters": {}}),
        state=JobState.SUCCEEDED,
        run_id="job-connectome",
        run_dir=str(run_dir),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    config = RecorderConfig()
    config.root = run_store_root
    observation = {
        "artifacts": [
            {
                "id": "observation-artifact",
                "name": "connectivity_matrix.npy",
                "path": "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy",
                "download_url": (
                    "/api/jobs/job-connectome/artifacts/files/"
                    "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
                ),
            }
        ]
    }
    with (
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=config,
        ),
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_job_observation",
            new=AsyncMock(return_value=observation),
        ),
    ):
        response = client.get(f"/api/jobs/{job.job_id}/artifacts")

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    paths = [artifact["path"] for artifact in artifacts]
    assert paths == [
        "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
    ]


def test_job_artifacts_deduplicate_nested_observation_paths(tmp_path: Path) -> None:
    run_store_root = tmp_path / "runs"
    run_dir = run_store_root / "20260521" / "job-connectome"
    artifact_path = (
        run_dir
        / "workflow_outputs"
        / "workflow_rest_connectome_e2e"
        / "connectivity_matrix.npy"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"matrix")

    job = JobRecord(
        job_id="job-connectome",
        kind="dag",
        payload_json=json.dumps({"parameters": {}}),
        state=JobState.SUCCEEDED,
        run_id="job-connectome",
        run_dir=str(run_dir),
    )
    client = _build_client(MemoryJobStore(jobs_dict={job.job_id: job}))

    config = RecorderConfig()
    config.root = run_store_root
    observation = {
        "artifacts": [
            {
                "id": "random-payload-id",
                "name": "connectivity_matrix.npy",
                "download_url": "https://stale.example/artifacts/connectivity_matrix.npy",
                "metadata": {
                    "path": (
                        "workflow_outputs/workflow_rest_connectome_e2e/"
                        "connectivity_matrix.npy"
                    )
                },
            }
        ]
    }
    with (
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=config,
        ),
        patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_job_observation",
            new=AsyncMock(return_value=observation),
        ),
    ):
        response = client.get(f"/api/jobs/{job.job_id}/artifacts")

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["path"] == (
        "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
    )
    assert "stale.example" not in artifact["download_url"]
    assert artifact["download_url"].endswith(
        "/api/jobs/job-connectome/artifacts/files/"
        "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
    )
