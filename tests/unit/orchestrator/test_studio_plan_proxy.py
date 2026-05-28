"""Unit tests for the orchestrator /api/agent/studio/plan proxy."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    try:
        from brain_researcher.services.orchestrator.main_enhanced import (
            app,
            get_current_user,
        )
        from brain_researcher.services.orchestrator.models import User
    except Exception as exc:  # pragma: no cover - env guard
        pytest.skip(f"Could not create orchestrator test client: {exc}")

    async def _fake_current_user() -> User:
        return User(
            id="user_demo",
            username="demo_user",
            email="demo@example.com",
            preferences={"workspace_id": "ws_demo"},
        )

    app.dependency_overrides[get_current_user] = _fake_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_agent(monkeypatch: pytest.MonkeyPatch):
    def _setup_agent(response: httpx.Response | Exception) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(
                self,
                url: str,
                json: dict[str, Any] | None = None,
                timeout: float | None = None,
            ):
                requests.append({"url": url, "json": json or {}, "timeout": timeout})
                if isinstance(response, Exception):
                    raise response
                return response

        monkeypatch.setattr(
            "brain_researcher.services.orchestrator.main_enhanced.httpx.AsyncClient",
            MockAsyncClient,
        )
        return requests

    return _setup_agent


def _make_agent_response(payload: dict[str, Any]) -> httpx.Response:
    request = httpx.Request("POST", "http://agent-service/agent/studio/plan")
    return httpx.Response(status_code=200, json=payload, request=request)


def test_agent_studio_plan_proxy_injects_owner_user_id_and_workspace_id(
    client: TestClient,
    mock_agent,
) -> None:
    requests = mock_agent(
        _make_agent_response(
            {
                "assistant_message": "Planned.",
                "ops": [],
                "source": "agent_typed",
            }
        )
    )

    with patch.dict(os.environ, {"BR_AGENT_URL": "http://agent-service"}, clear=False):
        response = client.post(
            "/api/agent/studio/plan",
            json={
                "prompt": "Add notebook cells.",
                "notebook_context": {"cells": []},
                "metadata": {
                    "surface": "studio",
                    "scenario_id": "studio_notebook_assistant",
                },
            },
        )

    assert response.status_code == 200
    assert len(requests) == 1
    assert requests[0]["url"] == "http://agent-service/agent/studio/plan"
    metadata = requests[0]["json"]["metadata"]
    assert metadata["surface"] == "studio"
    assert metadata["scenario_id"] == "studio_notebook_assistant"
    assert metadata["owner_user_id"] == "user_demo"
    assert metadata["workspace_id"] == "ws_demo"


def test_agent_studio_plan_proxy_preserves_existing_metadata(
    client: TestClient,
    mock_agent,
) -> None:
    requests = mock_agent(
        _make_agent_response(
            {
                "assistant_message": "Planned.",
                "ops": [],
                "source": "agent_typed",
            }
        )
    )

    with patch.dict(os.environ, {"BR_AGENT_URL": "http://agent-service"}, clear=False):
        response = client.post(
            "/api/agent/studio/plan",
            json={
                "prompt": "Add notebook cells.",
                "notebook_context": {"cells": []},
                "metadata": {
                    "surface": "studio",
                    "owner_user_id": "user_existing",
                    "workspace_id": "ws_existing",
                    "custom_key": "keep_me",
                },
            },
        )

    assert response.status_code == 200
    metadata = requests[0]["json"]["metadata"]
    assert metadata["surface"] == "studio"
    assert metadata["owner_user_id"] == "user_existing"
    assert metadata["workspace_id"] == "ws_existing"
    assert metadata["custom_key"] == "keep_me"


def test_agent_studio_plan_proxy_surfaces_upstream_error_detail(
    client: TestClient,
    mock_agent,
) -> None:
    request = httpx.Request("POST", "http://agent-service/agent/studio/plan")
    response = httpx.Response(
        422,
        json={"error": "missing_prompt", "message": "prompt is required"},
        request=request,
    )
    error = httpx.HTTPStatusError("422 Unprocessable Entity", request=request, response=response)
    mock_agent(error)

    with patch.dict(os.environ, {"BR_AGENT_URL": "http://agent-service"}, clear=False):
        resp = client.post(
            "/api/agent/studio/plan",
            json={"prompt": "Add notebook cells.", "metadata": {}},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "error": "missing_prompt",
        "message": "prompt is required",
    }


pytestmark = pytest.mark.unit
