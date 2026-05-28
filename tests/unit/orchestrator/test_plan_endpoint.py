"""Unit tests for the orchestrator /api/agent/plan endpoint."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client():
    try:
        from brain_researcher.services.orchestrator.main_enhanced import app

        return TestClient(app)
    except Exception as exc:  # pragma: no cover - env guard
        pytest.skip(f"Could not create orchestrator test client: {exc}")


@pytest.fixture
def sample_plan() -> Dict[str, Any]:
    return {
        "plan_id": "plan-123",
        "version": "1.0",
        "resolvable": True,
        "timestamp": 1_700_000_000,
        "intent": ["skull_strip"],
        "chosen_tool": "fsl.bet.run",
        "selection_reason": "BET handles skull stripping best",
        "candidates": [
            {
                "tool_id": "fsl.bet.run",
                "final_score": 0.95,
                "intent_match_score": 0.9,
                "description_score": 0.8,
                "metadata_score": 0.75,
                "resource_fit_score": 1.0,
                "preflight_passed": True,
                "preflight_detail": {"container_image": "cvmfs://bet"},
                "explanation": "Excellent match for skull stripping",
            }
        ],
        "dag": {
            "steps": [
                {
                    "id": "001-main",
                    "tool": "fsl.bet.run",
                    "params": {"input": "brain.nii.gz"},
                }
            ],
            "artifacts": [],
        },
    }


@pytest.fixture
def mock_agent(monkeypatch):
    """Patch httpx.AsyncClient used by orchestrator to speak with the agent service."""

    def _setup_agent(response: httpx.Response | Exception) -> List[Dict[str, Any]]:
        requests: List[Dict[str, Any]] = []

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):  # noqa: D401 - FastAPI signature parity
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: Dict[str, Any] | None = None, timeout: float | None = None):
                requests.append({"url": url, "json": json or {}})
                if isinstance(response, Exception):
                    raise response
                return response

        monkeypatch.setattr(
            "brain_researcher.services.orchestrator.main_enhanced.httpx.AsyncClient",
            MockAsyncClient,
        )

        return requests

    return _setup_agent


def _make_agent_response(payload: Dict[str, Any]) -> httpx.Response:
    request = httpx.Request("POST", "http://agent-service/agent/plan")
    return httpx.Response(status_code=200, json=payload, request=request)


def test_plan_endpoint_basic_success(client, mock_agent, sample_plan):
    requests = mock_agent(_make_agent_response(sample_plan))
    with patch.dict(os.environ, {"BR_PLANNER_MODE": "advisor", "BR_AGENT_URL": "http://agent-service"}, clear=False):
        response = client.post(
            "/api/agent/plan",
            json={
                "pipeline": "skull_strip",
                "domain": "neuroimaging",
                "modality": ["smri"],
                "inputs": {"image": "brain.nii.gz"},
            },
        )

    assert response.status_code == 200
    assert response.json() == sample_plan
    assert requests == [
        {
            "url": "http://agent-service/agent/plan",
            "json": {
                "pipeline": "skull_strip",
                "domain": "neuroimaging",
                "modality": ["smri"],
                "inputs": {"image": "brain.nii.gz"},
                "constraints": None,
                "mode": "catalog",
            },
        }
    ]


def test_plan_endpoint_disabled_returns_501(client, mock_agent, sample_plan):
    requests = mock_agent(_make_agent_response(sample_plan))
    with patch.dict(os.environ, {"BR_PLANNER_MODE": "disabled"}, clear=False):
        response = client.post(
            "/api/agent/plan",
            json={"pipeline": "skull_strip"},
        )

    assert response.status_code == 501
    assert response.json()["detail"]["error"] == "planner_disabled"
    assert requests == []


def test_plan_endpoint_missing_pipeline_returns_422(client):
    response = client.post("/api/agent/plan", json={})
    assert response.status_code == 422


def test_plan_endpoint_with_constraints_forwards_payload(client, mock_agent, sample_plan):
    requests = mock_agent(_make_agent_response(sample_plan))
    payload = {
        "pipeline": "skull_strip",
        "constraints": {"tool_allowlist": ["fsl.bet.run"], "max_steps": 2},
    }

    response = client.post("/api/agent/plan", json=payload)

    assert response.status_code == 200
    sent_constraints = requests[0]["json"]["constraints"]
    assert sent_constraints["tool_allowlist"] == payload["constraints"]["tool_allowlist"]
    assert sent_constraints["max_steps"] == payload["constraints"]["max_steps"]


def test_plan_endpoint_default_mode_is_catalog_when_env_absent(client, mock_agent, sample_plan):
    """Ensure orchestrator aligns with agent catalog-first default when env unset."""
    requests = mock_agent(_make_agent_response(sample_plan))
    # Clear BR_PLANNER_SOURCE to exercise default
    with patch.dict(os.environ, {"BR_AGENT_URL": "http://agent-service"}, clear=True):
        response = client.post(
            "/api/agent/plan",
            json={"pipeline": "skull_strip", "domain": "neuroimaging"},
        )

    assert response.status_code == 200
    assert requests[0]["json"]["mode"] == "catalog"


def test_plan_endpoint_ignores_legacy_env_override(client, mock_agent, sample_plan):
    """Ensure active runtime ignores legacy env overrides and stays catalog-only."""
    requests = mock_agent(_make_agent_response(sample_plan))
    with patch.dict(
        os.environ,
        {"BR_AGENT_URL": "http://agent-service", "BR_PLANNER_SOURCE": "legacy"},
        clear=True,
    ):
        response = client.post(
            "/api/agent/plan",
            json={"pipeline": "skull_strip", "domain": "neuroimaging"},
        )

    assert response.status_code == 200
    assert requests[0]["json"]["mode"] == "catalog"


def test_plan_endpoint_response_structure(client, mock_agent, sample_plan):
    requests = mock_agent(_make_agent_response(sample_plan))
    response = client.post(
        "/api/agent/plan",
        json={"pipeline": "skull_strip"},
    )

    data = response.json()
    assert data["plan_id"] == sample_plan["plan_id"]
    assert data["chosen_tool"] == "fsl.bet.run"
    assert isinstance(data["candidates"], list)
    assert data["selection_reason"]
    assert data["timestamp"]
    assert requests


def test_plan_endpoint_surfaces_agent_http_error(client, mock_agent):
    request = httpx.Request("POST", "http://agent-service/agent/plan")
    response = httpx.Response(422, json={"error": "missing_inputs"}, request=request)
    error = httpx.HTTPStatusError("422 Unprocessable Entity", request=request, response=response)
    mock_agent(error)

    resp = client.post("/api/agent/plan", json={"pipeline": "skull_strip"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "missing_inputs"


def test_plan_endpoint_handles_agent_request_error(client, mock_agent):
    request_error = httpx.RequestError("Connection refused", request=httpx.Request("POST", "http://agent-service/agent/plan"))
    mock_agent(request_error)

    resp = client.post("/api/agent/plan", json={"pipeline": "skull_strip"})
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["error"] == "agent_unavailable"


pytestmark = pytest.mark.unit
