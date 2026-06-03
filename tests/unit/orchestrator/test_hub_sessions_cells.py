"""Unit tests for the POST /api/hub/sessions/{id}/cells endpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.hub_sessions import (
    _resolve_marimo_internal_base_url,
    router,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


def test_internal_base_url_appends_marimo_base_path() -> None:
    """marimo serves under --base-url <path>; internal calls must include it."""
    target = SimpleNamespace(
        internal_url="http://br-marimo-rt-abc:2718",
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-rt-abc",
    )
    assert (
        _resolve_marimo_internal_base_url(target)
        == "http://br-marimo-rt-abc:2718/hub/br-marimo-rt-abc"
    )


def test_internal_base_url_no_double_prefix() -> None:
    target = SimpleNamespace(
        internal_url="http://br-marimo-rt-abc:2718/hub/br-marimo-rt-abc",
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-rt-abc",
    )
    assert (
        _resolve_marimo_internal_base_url(target)
        == "http://br-marimo-rt-abc:2718/hub/br-marimo-rt-abc"
    )


def test_internal_base_url_no_path_when_public_has_none() -> None:
    target = SimpleNamespace(
        internal_url="http://br-marimo-rt-abc:2718",
        public_url="https://${PUBLIC_HOSTNAME}",
    )
    assert _resolve_marimo_internal_base_url(target) == "http://br-marimo-rt-abc:2718"


@pytest.fixture
def cells_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "hub_cells.sqlite",
    )
    with TestClient(app) as client:
        yield client


def _create_session(client: TestClient) -> dict[str, Any]:
    resp = client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_cells_demo",
            "display_name": "Cells Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_runtime_envelope_strips_runtime_token(
    cells_client: TestClient,
) -> None:
    created = _create_session(cells_client)
    runtime = created["runtime"]
    assert "marimo_runtime_token" not in (runtime.get("metadata") or {})


def test_append_cell_forwards_create_cell_to_marimo(
    cells_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_session(cells_client)
    session_id = created["session"]["id"]

    captured: dict[str, Any] = {}

    async def _fake_get(self, url, *, headers=None):  # type: ignore[no-untyped-def]
        captured["get_url"] = url
        captured["get_headers"] = dict(headers or {})
        # marimo discovery endpoint: {marimo_session_id: {filename, path}}.
        return httpx.Response(
            200,
            json={
                "s_disco1": {
                    "filename": "br_quickstart.py",
                    "path": "/home/jovyan/notebooks/br_quickstart.py",
                }
            },
        )

    async def _fake_post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = dict(headers or {})
        return httpx.Response(200, text='{"success": true}')

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    response = cells_client.post(
        f"/api/hub/sessions/{session_id}/cells",
        json={"code": "br.attach_run('run_abc')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    cell_id = body["cell_id"]
    assert len(cell_id) == 40
    # Marimo's external-cell convention: UUID4 (36 chars) + 4 ASCII letters.
    uuid_obj = UUID(cell_id[:36], version=4)
    assert str(uuid_obj) == cell_id[:36]
    assert cell_id[36:].isalpha()
    assert captured["get_url"].endswith("/api/sessions")
    assert captured["url"].endswith("/api/document/transaction")
    payload = captured["json"]
    assert len(payload["changes"]) == 1
    change = payload["changes"][0]
    assert change["type"] == "create-cell"
    assert change["cellId"] == cell_id
    assert change["code"] == "br.attach_run('run_abc')"
    # marimo OWNS its session id now: the orchestrator discovers the live id via
    # GET /api/sessions and uses THAT, not the studio session_id (studio_...) and
    # not the internal runtime id (rt_...).
    assert captured["headers"]["Marimo-Session-Id"] == "s_disco1"
    assert captured["headers"]["Marimo-Session-Id"] != created["session"]["id"]
    assert captured["headers"]["Marimo-Session-Id"] != created["runtime"]["id"]
    # marimo gates the transaction on two distinct checks: the skew token goes in
    # Marimo-Server-Token, and the auth token authenticates via Authorization.
    skew_header = captured["headers"].get("Marimo-Server-Token")
    auth_header = captured["headers"].get("Authorization", "")
    assert skew_header  # pinned skew-protection token
    assert auth_header.startswith("Bearer ") and auth_header != "Bearer "
    # The auth bearer must NOT be the skew token (auth token != skew token).
    assert auth_header != f"Bearer {skew_header}"


def test_append_cell_maps_marimo_401_to_auth_failed_503(
    cells_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_session(cells_client)
    session_id = created["session"]["id"]

    async def _fake_get(self, url, *, headers=None):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"s_disco1": {"path": "x", "filename": "x"}})

    async def _fake_post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        return httpx.Response(401, text="bad token")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    response = cells_client.post(
        f"/api/hub/sessions/{session_id}/cells",
        json={"code": "br.attach_run('x')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "marimo-auth-failed"


def test_append_cell_returns_503_when_no_live_marimo_session(
    cells_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No discoverable marimo session => clear 503, never a stale studio id."""
    created = _create_session(cells_client)
    session_id = created["session"]["id"]

    posted = {"called": False}

    async def _fake_get(self, url, *, headers=None):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={})

    async def _fake_post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        posted["called"] = True
        return httpx.Response(200, text='{"success": true}')

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    response = cells_client.post(
        f"/api/hub/sessions/{session_id}/cells",
        json={"code": "br.attach_run('x')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "marimo-session-not-found"
    assert detail["reason"] == "no_active_session"
    # Must NOT have attempted the transaction with a bogus session id.
    assert posted["called"] is False


def test_append_cell_returns_503_when_runtime_unknown(
    cells_client: TestClient,
) -> None:
    response = cells_client.post(
        "/api/hub/sessions/studio_does_not_exist/cells",
        json={"code": "br.attach_run('x')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 404
