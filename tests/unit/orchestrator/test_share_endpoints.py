from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.share_endpoints import router


class _FakeStateStore:
    def __init__(self, record: dict[str, object] | None):
        self.record = record
        self.revoked = False

    async def resolve_analysis_share(self, *, share_token: str, now: datetime | None = None):
        assert share_token == 'share_tok'
        return self.record

    async def revoke_analysis_share(self, *, share_token: str) -> bool:
        assert share_token == 'share_tok'
        self.revoked = True
        return self.record is not None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_share_revoke_requires_owner_match(monkeypatch) -> None:
    record = {
        'analysis_id': 'job_1',
        'share_level': 'summary',
        'created_at': int(datetime.utcnow().timestamp()),
        'expires_at': int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        'created_by': 'user_owner',
    }
    store = _FakeStateStore(record)

    async def _mock_get_state_store():
        return store

    async def _mock_requester(_request):
        return 'user_other'

    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints.get_state_store',
        _mock_get_state_store,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints._resolve_share_requester_id',
        _mock_requester,
    )

    with TestClient(_build_app()) as client:
        resp = client.delete('/api/share/share_tok')

    assert resp.status_code == 403
    assert resp.json()['detail'] == 'Only the share link owner can revoke it.'
    assert store.revoked is False


def test_share_revoke_allows_owner_when_authenticated(monkeypatch) -> None:
    record = {
        'analysis_id': 'job_1',
        'share_level': 'summary',
        'created_at': int(datetime.utcnow().timestamp()),
        'expires_at': int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        'created_by': 'user_owner',
    }
    store = _FakeStateStore(record)

    async def _mock_get_state_store():
        return store

    async def _mock_requester(_request):
        return 'user_owner'

    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints.get_state_store',
        _mock_get_state_store,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints._resolve_share_requester_id',
        _mock_requester,
    )

    with TestClient(_build_app()) as client:
        resp = client.delete('/api/share/share_tok')

    assert resp.status_code == 200
    assert resp.json() == {'revoked': True}
    assert store.revoked is True


def test_share_revoke_allows_legacy_ownerless_records(monkeypatch) -> None:
    record = {
        'analysis_id': 'job_1',
        'share_level': 'summary',
        'created_at': int(datetime.utcnow().timestamp()),
        'expires_at': int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        'created_by': None,
    }
    store = _FakeStateStore(record)

    async def _mock_get_state_store():
        return store

    async def _mock_requester(_request):
        return 'user_any'

    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints.get_state_store',
        _mock_get_state_store,
    )
    monkeypatch.setattr(
        'brain_researcher.services.orchestrator.share_endpoints._resolve_share_requester_id',
        _mock_requester,
    )

    with TestClient(_build_app()) as client:
        resp = client.delete('/api/share/share_tok')

    assert resp.status_code == 200
    assert resp.json() == {'revoked': True}
    assert store.revoked is True
