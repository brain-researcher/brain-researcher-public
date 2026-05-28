"""
Unit tests for observation API endpoint.

Tests the following endpoint:
- GET /api/jobs/{job_id}/observation

Verifies:
- Serving persisted observation.json from run_dir
- Synthesizing observation.json from provenance.json + JobStore payload when missing
"""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from brain_researcher.config.run_artifacts import RecorderConfig
from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.job_store import (
    JobRecord,
    JobState,
    JobStore,
)


class DummyJobStore(JobStore):
    """Simple test job store without asyncio locks for cross-event-loop testing."""

    def __init__(self):
        self._jobs = {}

    async def enqueue(self, job: JobRecord) -> bool:
        self._jobs[job.job_id] = job
        return True

    async def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def claim_next(self, worker_id: str, lease_ttl: int) -> JobRecord | None:
        return None

    async def update_state(self, job_id: str, state: JobState, **kwargs) -> bool:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.state = state
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            return True
        return False

    async def cancel(self, job_id: str, reason: str) -> bool:
        if job_id in self._jobs:
            self._jobs[job_id].cancel_reason = reason
            self._jobs[job_id].state = JobState.CANCELLED
            return True
        return False

    async def heartbeat(
        self, worker_id: str, job_id: str, lease_ttl: int
    ) -> int | None:
        return 1


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(router)
    job_store = DummyJobStore()
    app.state.job_store = job_store
    yield app, job_store


@pytest.fixture
def test_run_directory(tmp_path: Path):
    base_dir = tmp_path
    run_dir = base_dir / "test_run_001"
    run_dir.mkdir()

    provenance_data = {
        "run_id": "test_run_001",
        "child_runs": [
            {"step_id": "step-0", "state": "succeeded", "execution_time_ms": 12}
        ],
    }
    provenance_path = run_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance_data), encoding="utf-8")

    (run_dir / "output.txt").write_text("ok", encoding="utf-8")

    yield base_dir, run_dir, provenance_path


class TestObservationEndpoint:
    @pytest.mark.asyncio
    async def test_observation_serves_existing_file(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        observation_data = {
            "schema_version": "observation-v1",
            "job_id": "job_obs_001",
            "run_id": "test_run_001",
            "state": JobState.SUCCEEDED.value,
            "run_dir": str(run_dir),
            "files": {
                "observation_json": "observation.json",
                "provenance_json": "provenance.json",
            },
            "diagnostics_summary": {
                "schema_version": "diagnostics-v1",
                "counts": {"warning": 0, "error": 0, "blocking": 0},
                "top_codes": [],
                "recommended_next_actions": [],
                "sample_errors": [],
                "sample_warnings": [],
            },
            "artifacts": [],
            "steps": [],
        }
        (run_dir / "observation.json").write_text(
            json.dumps(observation_data),
            encoding="utf-8",
        )

        job = JobRecord(
            job_id="job_obs_001",
            kind="test",
            payload_json=json.dumps({"artifacts": []}),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_001/observation")
                assert resp.status_code == 200
                data = resp.json()
                assert data["schema_version"] == "observation-v1"
                assert data["job_id"] == "job_obs_001"

    @pytest.mark.asyncio
    async def test_observation_serves_existing_file_with_deduped_artifacts(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        artifact_path = (
            "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy"
        )
        (run_dir / artifact_path).parent.mkdir(parents=True)
        (run_dir / artifact_path).write_bytes(b"matrix")
        observation_data = {
            "schema_version": "observation-v1",
            "job_id": "job_obs_dedupe_001",
            "run_id": "test_run_001",
            "state": JobState.SUCCEEDED.value,
            "run_dir": str(run_dir),
            "files": {
                "observation_json": "observation.json",
                "provenance_json": "provenance.json",
            },
            "diagnostics_summary": {
                "schema_version": "diagnostics-v1",
                "counts": {"warning": 0, "error": 0, "blocking": 0},
                "top_codes": [],
                "recommended_next_actions": [],
                "sample_errors": [],
                "sample_warnings": [],
            },
            "run_card": {
                "outputs": [
                    {
                        "id": "payload-random-output-id",
                        "name": "connectivity_matrix.npy",
                        "path": artifact_path,
                        "download_url": "https://stale.example/output.npy",
                    },
                    {
                        "id": "artifact_workflow_outputs_connectivity_matrix.npy",
                        "name": "connectivity_matrix.npy",
                        "path": artifact_path,
                        "download_url": (
                            "/api/jobs/job_obs_dedupe_001/artifacts/files/"
                            f"{artifact_path}"
                        ),
                    },
                ],
                "artifacts": [
                    {
                        "id": "payload-random-run-card-id",
                        "name": "connectivity_matrix.npy",
                        "metadata": {"path": artifact_path},
                        "download_url": "https://stale.example/run-card.npy",
                    },
                    {
                        "id": "artifact_workflow_outputs_connectivity_matrix.npy",
                        "name": "connectivity_matrix.npy",
                        "path": artifact_path,
                        "download_url": (
                            "/api/jobs/job_obs_dedupe_001/artifacts/files/"
                            f"{artifact_path}"
                        ),
                    },
                ],
            },
            "artifacts": [
                {
                    "id": "payload-random-id",
                    "name": "connectivity_matrix.npy",
                    "metadata": {"path": artifact_path},
                    "download_url": "https://stale.example/connectivity_matrix.npy",
                    "checksum_status": "ok",
                },
                {
                    "id": "artifact_workflow_outputs_connectivity_matrix.npy",
                    "name": "connectivity_matrix.npy",
                    "path": artifact_path,
                    "download_url": (
                        "/api/jobs/job_obs_dedupe_001/artifacts/files/"
                        f"{artifact_path}"
                    ),
                    "checksum_status": "ok",
                },
            ],
            "steps": [],
        }
        (run_dir / "observation.json").write_text(
            json.dumps(observation_data),
            encoding="utf-8",
        )

        job = JobRecord(
            job_id="job_obs_dedupe_001",
            kind="test",
            payload_json=json.dumps({"artifacts": []}),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_dedupe_001/observation")
                assert resp.status_code == 200
                artifacts = resp.json()["artifacts"]
                matching_artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact.get("path") == artifact_path
                ]
                assert len(matching_artifacts) == 1
                assert "stale.example" not in matching_artifacts[0]["download_url"]
                assert matching_artifacts[0]["download_url"].endswith(artifact_path)
                run_card = resp.json()["run_card"]
                matching_run_card_artifacts = [
                    artifact
                    for artifact in run_card["artifacts"]
                    if artifact.get("path") == artifact_path
                ]
                assert len(matching_run_card_artifacts) == 1
                assert (
                    "stale.example"
                    not in matching_run_card_artifacts[0]["download_url"]
                )
                matching_outputs = [
                    artifact
                    for artifact in run_card["outputs"]
                    if artifact.get("path") == artifact_path
                ]
                assert len(matching_outputs) == 1

    @pytest.mark.asyncio
    async def test_observation_backfills_new_run_dir_outputs_from_stale_existing_file(
        self, app_with_job_store, tmp_path: Path
    ):
        app, job_store = app_with_job_store
        base_dir = tmp_path
        run_dir = base_dir / "job_obs_backfill_001"
        run_dir.mkdir()
        provenance_path = run_dir / "provenance.json"
        provenance_path.write_text(
            json.dumps({"run_id": "job_obs_backfill_001"}), encoding="utf-8"
        )

        (run_dir / "atlas").mkdir()
        (run_dir / "atlas" / "atlas.nii.gz").write_bytes(b"atlas")
        (run_dir / "timeseries").mkdir()
        (run_dir / "timeseries" / "timeseries.npy").write_bytes(b"npy")
        (run_dir / "timeseries" / "timeseries.csv").write_text(
            "region,value\n", encoding="utf-8"
        )
        (run_dir / "connectivity_matrix.npy").write_bytes(b"matrix")

        observation_data = {
            "schema_version": "observation-v1",
            "job_id": "job_obs_backfill_001",
            "run_id": "job_obs_backfill_001",
            "state": JobState.SUCCEEDED.value,
            "run_dir": str(run_dir),
            "files": {
                "observation_json": "observation.json",
                "provenance_json": "provenance.json",
            },
            "diagnostics_summary": {
                "schema_version": "diagnostics-v1",
                "counts": {"warning": 0, "error": 0, "blocking": 0},
                "top_codes": [],
                "recommended_next_actions": [],
                "sample_errors": [],
                "sample_warnings": [],
            },
            "run_card": {
                "outputs": [{"name": "atlas.nii.gz", "path": "atlas/atlas.nii.gz"}],
                "artifacts": [{"name": "atlas.nii.gz", "path": "atlas/atlas.nii.gz"}],
            },
            "artifacts": [{"name": "atlas.nii.gz", "path": "atlas/atlas.nii.gz"}],
            "steps": [],
        }
        (run_dir / "observation.json").write_text(
            json.dumps(observation_data),
            encoding="utf-8",
        )

        job = JobRecord(
            job_id="job_obs_backfill_001",
            kind="test",
            payload_json=json.dumps({"artifacts": []}),
            state=JobState.SUCCEEDED,
            run_id="job_obs_backfill_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_backfill_001/observation")
                assert resp.status_code == 200
                data = resp.json()
                artifact_paths = {
                    artifact.get("path")
                    for artifact in data.get("artifacts", [])
                    if isinstance(artifact, dict)
                }
                assert "atlas/atlas.nii.gz" in artifact_paths
                assert "timeseries/timeseries.npy" in artifact_paths
                assert "timeseries/timeseries.csv" in artifact_paths
                assert "connectivity_matrix.npy" in artifact_paths

                output_paths = {
                    artifact.get("path")
                    for artifact in data.get("run_card", {}).get("outputs", [])
                    if isinstance(artifact, dict)
                }
                assert "timeseries/timeseries.npy" in output_paths
                assert "timeseries/timeseries.csv" in output_paths
                assert "connectivity_matrix.npy" in output_paths

    @pytest.mark.asyncio
    async def test_observation_supports_legacy_run_root_alias_paths(
        self,
        app_with_job_store,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        app, job_store = app_with_job_store
        canonical_root = tmp_path / "shared" / "runs"
        legacy_root = tmp_path / "data" / "runs"
        run_dir = canonical_root / "20260223" / "job_obs_legacy_001"
        run_dir.mkdir(parents=True)

        provenance_path = run_dir / "provenance.json"
        provenance_path.write_text(
            json.dumps({"run_id": "job_obs_legacy_001"}),
            encoding="utf-8",
        )
        observation_path = run_dir / "observation.json"
        observation_path.write_text(
            json.dumps(
                {
                    "schema_version": "observation-v1",
                    "job_id": "job_obs_legacy_001",
                    "run_id": "job_obs_legacy_001",
                    "state": JobState.SUCCEEDED.value,
                    "run_dir": str(run_dir),
                    "files": {
                        "observation_json": "observation.json",
                        "provenance_json": "provenance.json",
                    },
                    "diagnostics_summary": {
                        "schema_version": "diagnostics-v1",
                        "counts": {"warning": 0, "error": 0, "blocking": 0},
                        "top_codes": [],
                        "recommended_next_actions": [],
                        "sample_errors": [],
                        "sample_warnings": [],
                    },
                    "artifacts": [],
                    "steps": [],
                }
            ),
            encoding="utf-8",
        )

        job = JobRecord(
            job_id="job_obs_legacy_001",
            kind="test",
            payload_json=json.dumps({"artifacts": []}),
            state=JobState.SUCCEEDED,
            run_id="job_obs_legacy_001",
            run_dir=str(legacy_root / "20260223" / "job_obs_legacy_001"),
            provenance_path=str(
                legacy_root / "20260223" / "job_obs_legacy_001" / "provenance.json"
            ),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = canonical_root
        monkeypatch.setenv("BR_RUN_STORE_ROOT_ALIASES", str(legacy_root))

        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_legacy_001/observation")
                assert resp.status_code == 200
                data = resp.json()
                assert data["job_id"] == "job_obs_legacy_001"
                assert data["run_id"] == "job_obs_legacy_001"

    @pytest.mark.asyncio
    async def test_observation_backfills_existing_file_missing_diagnostics_and_checksums(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        observation_data = {
            "schema_version": "observation-v1",
            "job_id": "job_obs_004",
            "run_id": "test_run_001",
            "state": JobState.SUCCEEDED.value,
            "run_dir": str(run_dir),
            "files": {
                "observation_json": "observation.json",
                "provenance_json": "provenance.json",
            },
            "artifacts": [
                {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
            ],
            "steps": [],
        }
        obs_path = run_dir / "observation.json"
        obs_path.write_text(json.dumps(observation_data), encoding="utf-8")

        payload = {
            "metadata": {"name": "Example analysis"},
            "artifacts": [
                {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
            ],
        }
        job = JobRecord(
            job_id="job_obs_004",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_004/observation")
                assert resp.status_code == 200
                data = resp.json()
                assert isinstance(data.get("diagnostics_summary"), dict)
                artifact = next(
                    a
                    for a in data.get("artifacts", [])
                    if a.get("name") == "output.txt"
                )
                assert isinstance(artifact.get("checksum"), str)
                assert artifact["checksum"].startswith("sha256:")
                assert artifact.get("checksum_status") == "ok"

        persisted = json.loads(obs_path.read_text(encoding="utf-8"))
        assert isinstance(persisted.get("diagnostics_summary"), dict)
        persisted_artifact = next(
            a
            for a in persisted.get("artifacts", [])
            if isinstance(a, dict) and a.get("name") == "output.txt"
        )
        assert persisted_artifact.get("checksum_status") == "ok"

    @pytest.mark.asyncio
    async def test_observation_backfills_empty_artifacts_when_run_dir_has_outputs(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        observation_data = {
            "schema_version": "observation-v1",
            "job_id": "job_obs_006",
            "run_id": "test_run_001",
            "state": JobState.SUCCEEDED.value,
            "run_dir": str(run_dir),
            "files": {
                "observation_json": "observation.json",
                "provenance_json": "provenance.json",
            },
            "diagnostics_summary": {
                "schema_version": "diagnostics-v1",
                "counts": {"warning": 0, "error": 0, "blocking": 0},
                "top_codes": [],
                "recommended_next_actions": [],
                "sample_errors": [],
                "sample_warnings": [],
            },
            "run_card": {"outputs": []},
            "artifacts": [],
            "steps": [],
        }
        obs_path = run_dir / "observation.json"
        obs_path.write_text(json.dumps(observation_data), encoding="utf-8")

        payload = {
            "metadata": {"name": "Example analysis"},
            "artifacts": [],
        }
        job = JobRecord(
            job_id="job_obs_006",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_006/observation")
                assert resp.status_code == 200
                data = resp.json()
                assert any(
                    a.get("name") == "output.txt" for a in data.get("artifacts", [])
                )
                run_card = data.get("run_card") or {}
                assert any(
                    o.get("name") == "output.txt" for o in run_card.get("outputs", [])
                )
                assert any(
                    a.get("name") == "output.txt" for a in run_card.get("artifacts", [])
                )

        persisted = json.loads(obs_path.read_text(encoding="utf-8"))
        assert any(
            a.get("name") == "output.txt"
            for a in persisted.get("artifacts", [])
            if isinstance(a, dict)
        )

    @pytest.mark.asyncio
    async def test_observation_synthesizes_when_missing(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        obs_path = run_dir / "observation.json"
        assert not obs_path.exists()
        (run_dir / "reward_breakdown.json").write_text(
            json.dumps({"schema_version": "reward-v1", "total": 1.0}),
            encoding="utf-8",
        )

        payload = {
            "metadata": {"name": "Example analysis"},
            "artifacts": [
                {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
            ],
        }
        job = JobRecord(
            job_id="job_obs_002",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_002/observation")
                assert resp.status_code == 200
                data = resp.json()
                assert data["schema_version"] == "observation-v1"
                assert data["job_id"] == "job_obs_002"
                assert isinstance(data.get("run_card"), dict)
                assert isinstance(data.get("diagnostics_summary"), dict)
                assert data["diagnostics_summary"]["schema_version"] == "diagnostics-v1"
                assert data["diagnostics_summary"]["counts"]["error"] == 0
                assert any(
                    a.get("name") == "output.txt" for a in data.get("artifacts", [])
                )
                assert (
                    data.get("files", {}).get("reward_breakdown_json")
                    == "reward_breakdown.json"
                )
                artifact = next(
                    a
                    for a in data.get("artifacts", [])
                    if a.get("name") == "output.txt"
                )
                assert isinstance(artifact.get("checksum"), str)
                assert artifact["checksum"].startswith("sha256:")
                assert obs_path.exists()

    @pytest.mark.asyncio
    async def test_observation_synthesis_deduplicates_payload_and_scanned_artifacts(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        obs_path = run_dir / "observation.json"
        assert not obs_path.exists()

        payload = {
            "metadata": {"name": "Example analysis"},
            "artifacts": [
                {
                    "id": "payload-random-id",
                    "artifact_id": "payload-random-id",
                    "name": "output.txt",
                    "type": "text",
                    "path": "output.txt",
                    "download_url": "https://stale.example/output.txt",
                }
            ],
        }
        job = JobRecord(
            job_id="job_obs_dedupe_002",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_dedupe_002/observation")
                assert resp.status_code == 200
                artifacts = [
                    artifact
                    for artifact in resp.json()["artifacts"]
                    if artifact.get("path") == "output.txt"
                ]
                assert len(artifacts) == 1
                assert "stale.example" not in artifacts[0]["download_url"]
                assert artifacts[0]["download_url"].endswith(
                    "/api/jobs/job_obs_dedupe_002/artifacts/files/output.txt"
                )

    @pytest.mark.asyncio
    async def test_observation_includes_quote_grounded_refs(
        self, app_with_job_store, test_run_directory
    ):
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        # Quote-grounded artifacts (written directly in run_dir).
        (run_dir / "quote_grounded_evidence_items.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "evidence-item-v1",
                        "evidence_id": "gfs_test_001",
                        "type": "file",
                        "ref": "doc_001",
                        "payload_ref": "quote_grounded_evidence_gfs_test_001.txt",
                        "quote_span": {"start_char": 0, "end_char": 2},
                        "extra": {"source": "gfs"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        (run_dir / "quote_grounded_claims.json").write_text(
            json.dumps(
                [
                    {
                        "schema_version": "claim-v1",
                        "claim_id": "claim_1",
                        "claim_text": "ok",
                        "confidence": 0.5,
                        "evidence_ids": ["gfs_test_001"],
                        "extra": {},
                    }
                ]
            ),
            encoding="utf-8",
        )
        (run_dir / "quote_grounded_evidence_gfs_test_001.txt").write_text(
            "ok", encoding="utf-8"
        )

        payload = {"metadata": {"name": "Example analysis"}, "artifacts": []}
        job = JobRecord(
            job_id="job_obs_005",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_005/observation")
                assert resp.status_code == 200
                data = resp.json()
                run_card = data.get("run_card") or {}
                prov = run_card.get("provenance") or {}
                qg = prov.get("quote_grounded") or {}
                assert qg.get("claims_file") == "quote_grounded_claims.json"
                assert (
                    qg.get("evidence_items_file")
                    == "quote_grounded_evidence_items.json"
                )

    @pytest.mark.asyncio
    async def test_observation_diagnostics_summary_includes_step_taxonomy(
        self, app_with_job_store, tmp_path: Path
    ):
        app, job_store = app_with_job_store

        base_dir = tmp_path
        run_dir = base_dir / "test_run_002"
        run_dir.mkdir()

        provenance_data = {
            "run_id": "test_run_002",
            "child_runs": [
                {
                    "step_id": "step-0",
                    "state": "failed",
                    "error": "boom",
                    "error_taxonomy": {
                        "category": "infra",
                        "is_retryable": True,
                        "recovery_action": "retry_backoff",
                        "recovery_suggestions": ["Retry with backoff"],
                        "debug": {"rule": "timeout_pattern"},
                    },
                }
            ],
        }
        provenance_path = run_dir / "provenance.json"
        provenance_path.write_text(json.dumps(provenance_data), encoding="utf-8")

        (run_dir / "output.txt").write_text("ok", encoding="utf-8")

        payload = {
            "metadata": {"name": "Example analysis"},
            "artifacts": [
                {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
            ],
        }
        job = JobRecord(
            job_id="job_obs_003",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_002",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_003/observation")
                assert resp.status_code == 200
                data = resp.json()
                diag = data.get("diagnostics_summary") or {}
                assert diag.get("schema_version") == "diagnostics-v1"
                assert diag.get("counts", {}).get("error") == 1
                actions = [
                    a.get("action") for a in diag.get("recommended_next_actions", [])
                ]
                assert "Retry with backoff" in actions

    @pytest.mark.asyncio
    async def test_observation_includes_payload_violations(
        self, app_with_job_store, test_run_directory
    ):
        """Violations stored in payload.metadata should be surfaced by default."""
        app, job_store = app_with_job_store
        base_dir, run_dir, provenance_path = test_run_directory

        payload = {
            "metadata": {
                "name": "Example analysis",
                "violations": [
                    {
                        "schema_version": "violation-v1",
                        "code": "DEPENDENCY_MISSING",
                        "message": "Preflight failed",
                        "severity": "warn",
                        "blocking": True,
                    }
                ],
            },
            "artifacts": [
                {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
            ],
        }
        job = JobRecord(
            job_id="job_obs_violations_001",
            kind="test",
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id="test_run_001",
            run_dir=str(run_dir),
            provenance_path=str(provenance_path),
        )
        await job_store.enqueue(job)

        mock_config = RecorderConfig()
        mock_config.root = base_dir
        with patch(
            "brain_researcher.services.orchestrator.job_management_endpoints.get_recorder_config",
            return_value=mock_config,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/jobs/job_obs_violations_001/observation")
                assert resp.status_code == 200
                data = resp.json()
                violations = data.get("violations") or []
                assert any(v.get("code") == "DEPENDENCY_MISSING" for v in violations)
