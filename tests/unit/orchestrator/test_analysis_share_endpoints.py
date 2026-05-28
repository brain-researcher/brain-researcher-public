"""Unit tests for current analysis share endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.config.run_artifacts import RecorderConfig
from brain_researcher.services.orchestrator.analyses_endpoints import api_router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.share_endpoints import (
    router as share_router,
)


class _FakeShareStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}

    async def store_analysis_share(
        self,
        *,
        share_token: str,
        analysis_id: str,
        share_level: str,
        expires_at: datetime,
        created_by: str | None = None,
    ) -> None:
        self.records[share_token] = {
            'analysis_id': analysis_id,
            'share_level': share_level,
            'created_at': int(datetime.utcnow().timestamp()),
            'expires_at': int(expires_at.timestamp()),
            'created_by': created_by,
            'revoked_at': None,
        }

    async def resolve_analysis_share(self, *, share_token: str, now: datetime | None = None):
        record = self.records.get(share_token)
        if not record:
            return None
        if record.get('revoked_at') is not None:
            return None
        now_ts = int((now or datetime.utcnow()).timestamp())
        if int(record['expires_at']) <= now_ts:
            return None
        return record


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(share_router)
    app.state.job_store = MemoryJobStore(total_gpu_slots=0)
    return app


def _write_minimal_run_dir(base_dir: Path) -> Path:
    run_dir = base_dir / 'run-1'
    run_dir.mkdir()

    (run_dir / 'output.txt').write_text('ok', encoding='utf-8')
    (run_dir / 'trajectory.json').write_text(
        '{"schema_version":"ATIF-v1.4"}', encoding='utf-8'
    )
    (run_dir / 'provenance.json').write_text(
        json.dumps({'schema_version': 'provenance-v1'}), encoding='utf-8'
    )
    return run_dir


@pytest.mark.asyncio
async def test_share_token_resolves_via_orchestrator_share_store(
    tmp_path: Path,
    app_with_job_store,
    monkeypatch: pytest.MonkeyPatch,
):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store
    share_store = _FakeShareStore()

    async def _mock_owner(_: object) -> str:
        return 'user_demo'

    async def _mock_requester(_: object) -> str:
        return 'user_demo'

    async def _mock_get_state_store():
        return share_store

    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.analyses_endpoints._resolve_share_owner_user_id',
        _mock_owner,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints._resolve_share_requester_id',
        _mock_requester,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.state_store.get_state_store',
        _mock_get_state_store,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints.get_state_store',
        _mock_get_state_store,
    )

    run_dir = _write_minimal_run_dir(tmp_path)
    payload = {
        'artifacts': [
            {'name': 'output.txt', 'type': 'text', 'path': 'output.txt', 'size': 2}
        ],
        'metadata': {'name': 'Example analysis'},
    }
    await job_store.enqueue(
        JobRecord(
            job_id='job_analysis_share_001',
            kind='test',
            payload_json=json.dumps(payload),
            state=JobState.SUCCEEDED,
            run_id='run-1',
            run_dir=str(run_dir),
        )
    )

    mock_config = RecorderConfig()
    mock_config.root = tmp_path
    with patch(
        'brain_researcher.services.orchestrator.analyses_endpoints.get_recorder_config',
        return_value=mock_config,
    ):
        with TestClient(app) as client:
            share_resp = client.post(
                '/api/analyses/job_analysis_share_001/share',
                json={'share_level': 'summary', 'expires_in_hours': 24},
            )
            assert share_resp.status_code == 201
            share_payload = share_resp.json()

            assert share_payload['analysis_id'] == 'job_analysis_share_001'
            assert share_payload['share_level'] == 'summary'
            assert 'share_token' in share_payload
            assert 'expires_at' in share_payload

            stored = share_store.records[share_payload['share_token']]
            assert stored['created_by'] == 'user_demo'

            resolve_resp = client.get(f"/api/share/{share_payload['share_token']}")
            assert resolve_resp.status_code == 200
            resolved = resolve_resp.json()

    assert resolved['analysis_id'] == 'job_analysis_share_001'
    assert resolved['share_level'] == 'summary'


def test_invalid_share_token_is_rejected(app_with_job_store, monkeypatch: pytest.MonkeyPatch):
    async def _mock_get_state_store():
        return _FakeShareStore()

    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints.get_state_store',
        _mock_get_state_store,
    )

    app = app_with_job_store
    with TestClient(app) as client:
        resp = client.get('/api/share/not-a-real-token')
        assert resp.status_code == 404
