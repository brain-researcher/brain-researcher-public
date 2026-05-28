"""Smoke tests for /agent/plan covering LLM and coding domains.

These tests are skipped if the agent service is not reachable. They are
lightweight and only assert that the endpoint accepts the extended domains and
returns a successful response structure.
"""

from __future__ import annotations

import os
import requests
import pytest
import warnings


BASE_URL = os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:8000")

# Silence harmless fakeredis ResourceWarnings emitted when the agent
# instantiates async fake Redis connections during startup.
warnings.filterwarnings(
    "ignore",
    message=r"unclosed Connection .*fakeredis\.aioredis\.FakeConnection.*",
    category=ResourceWarning,
)


def _post_plan(payload: dict):
    try:
        resp = requests.post(f"{BASE_URL}/agent/plan", json=payload, timeout=5)
        return resp
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Agent not reachable at {BASE_URL}")
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"Agent request failed: {exc}")


def _assert_ok(resp: requests.Response):
    if resp.status_code in {404, 405}:
        pytest.skip(f"/agent/plan not available (status {resp.status_code})")
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "error" not in data, f"Planner returned error: {data}"
    assert "plan_id" in data or "candidates" in data, f"Unexpected response body: {data}"
    return data


def test_plan_coding_agent_smoke():
    payload = {
        "pipeline": "coding agent",
        "domain": "code_assistant",
        "modality": ["general"],
        "inputs": {"instruction": "fix this bug"},
        "mode": "catalog",
    }
    resp = _post_plan(payload)
    _assert_ok(resp)


def test_plan_llm_service_smoke():
    payload = {
        "pipeline": "summarize text",
        "domain": "llm_service",
        "modality": ["general"],
        "inputs": {"prompt": "Summarize: The quick brown fox jumps over the lazy dog."},
        "mode": "catalog",
    }
    resp = _post_plan(payload)
    _assert_ok(resp)
