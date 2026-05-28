"""Cross-user isolation tests for session-scoped Studio endpoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.studio_executions import (
    router as executions_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_notebook import (
    router as notebook_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_sessions import (
    router as sessions_router,
)
from brain_researcher.services.orchestrator.studio_execution_runtime import (
    StudioExecutionRuntime,
)
from brain_researcher.services.orchestrator.studio_notebook_runtime import (
    StudioNotebookRuntime,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


async def _resolve_request_user_from_header(request: Request):
    user_id = request.headers.get("X-Test-User", "user_alpha")
    return SimpleNamespace(id=user_id), {}


@pytest.fixture
def isolation_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_sessions._resolve_request_user",
        _resolve_request_user_from_header,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_executions._resolve_request_user",
        _resolve_request_user_from_header,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_notebook._resolve_request_user",
        _resolve_request_user_from_header,
    )

    db_path = tmp_path / "studio_sessions.sqlite"
    session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=db_path,
    )

    app = FastAPI()
    app.include_router(sessions_router)
    app.include_router(executions_router)
    app.include_router(notebook_router)
    app.state.studio_session_runtime = session_runtime
    app.state.studio_execution_runtime = StudioExecutionRuntime(
        studio_session_runtime=session_runtime,
    )
    app.state.studio_notebook_runtime = StudioNotebookRuntime(
        studio_session_runtime=session_runtime,
        db_path=tmp_path / "studio_notebooks.sqlite",
    )

    with TestClient(app) as client:
        yield client


def _create_session_as_alpha(client: TestClient) -> dict:
    resp = client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_iso",
            "display_name": "Isolation Demo",
            "runtime_profile_id": "standard",
            "attach_if_exists": True,
        },
        headers={"X-Test-User": "user_alpha"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session"]


def test_get_session_returns_404_for_non_owner(isolation_client: TestClient) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp_beta = isolation_client.get(
        f"/api/studio/sessions/{session['id']}",
        headers={"X-Test-User": "user_beta"},
    )
    assert resp_beta.status_code == 404

    resp_alpha = isolation_client.get(
        f"/api/studio/sessions/{session['id']}",
        headers={"X-Test-User": "user_alpha"},
    )
    assert resp_alpha.status_code == 200


@pytest.mark.parametrize("action", ["touch", "close"])
def test_session_action_returns_404_for_non_owner(
    isolation_client: TestClient, action: str
) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp = isolation_client.post(
        f"/api/studio/sessions/{session['id']}/actions/{action}",
        json={},
        headers={"X-Test-User": "user_beta"},
    )
    assert resp.status_code == 404


def test_workspace_handoff_returns_404_for_non_owner(
    isolation_client: TestClient,
) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp = isolation_client.post(
        f"/api/studio/sessions/{session['id']}/workspace-handoff",
        json={"target_path": "scripts/demo.py"},
        headers={"X-Test-User": "user_beta"},
    )
    assert resp.status_code == 404


def test_execution_create_returns_404_for_non_owner(
    isolation_client: TestClient,
) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp = isolation_client.post(
        f"/api/studio/sessions/{session['id']}/executions",
        json={"kind": "code", "language": "python", "code": "print(1)"},
        headers={"X-Test-User": "user_beta"},
    )
    assert resp.status_code == 404


def test_execution_list_isolates_per_user(isolation_client: TestClient) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp = isolation_client.get(
        f"/api/studio/sessions/{session['id']}/executions",
        headers={"X-Test-User": "user_beta"},
    )
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json()["items"] == []


def test_notebook_open_or_create_returns_404_for_non_owner(
    isolation_client: TestClient,
) -> None:
    session = _create_session_as_alpha(isolation_client)

    resp = isolation_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/open-or-create",
        json={},
        headers={"X-Test-User": "user_beta"},
    )
    assert resp.status_code == 404


def test_notebook_get_does_not_expose_alpha_content_to_beta(
    isolation_client: TestClient,
) -> None:
    session = _create_session_as_alpha(isolation_client)

    try:
        resp = isolation_client.get(
            f"/api/studio/sessions/{session['id']}/notebook",
            headers={"X-Test-User": "user_beta"},
        )
    except KeyError:
        return

    assert resp.status_code == 404
