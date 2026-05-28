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

from brain_researcher.services.orchestrator.endpoints.hub_sessions import router
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


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

    async def _fake_post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = dict(headers or {})
        return httpx.Response(200, text='{"success": true}')

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
    assert captured["url"].endswith("/api/document/transaction")
    payload = captured["json"]
    assert len(payload["changes"]) == 1
    change = payload["changes"][0]
    assert change["type"] == "create-cell"
    assert change["cellId"] == cell_id
    assert change["code"] == "br.attach_run('run_abc')"
    assert captured["headers"]["Marimo-Session-Id"] == created["runtime"]["id"]
    # Token must be sent when the runtime row has one provisioned.
    assert "Marimo-Server-Token" in captured["headers"]


def test_append_cell_maps_marimo_401_to_auth_failed_503(
    cells_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_session(cells_client)
    session_id = created["session"]["id"]

    async def _fake_post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        return httpx.Response(401, text="bad token")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    response = cells_client.post(
        f"/api/hub/sessions/{session_id}/cells",
        json={"code": "br.attach_run('x')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "marimo-auth-failed"


def test_append_cell_returns_503_when_runtime_unknown(
    cells_client: TestClient,
) -> None:
    response = cells_client.post(
        "/api/hub/sessions/studio_does_not_exist/cells",
        json={"code": "br.attach_run('x')"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 404
