from __future__ import annotations

import os
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.main_enhanced import app


def test_auto_classifies_code_track(monkeypatch):
    # Ensure auto is on and force is off
    monkeypatch.setenv("CODING_AGENT_AUTO", "1")
    monkeypatch.setenv("CODING_AGENT_FORCE", "0")
    if os.environ.get("CODING_AGENT_MODE"):
        monkeypatch.delenv("CODING_AGENT_MODE", raising=False)

    client = TestClient(app)
    resp = client.post(
        "/run",
        json={
            "prompt": "please apply patch to update README and run pytest",
            "pipeline": "chat",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Coding plan should be returned inline when entering coding track
    assert "plan" in body


def test_auto_avoids_code_for_domain_prompt(monkeypatch):
    # Ensure auto is on and force is off
    monkeypatch.setenv("CODING_AGENT_AUTO", "1")
    monkeypatch.setenv("CODING_AGENT_FORCE", "0")
    if os.environ.get("CODING_AGENT_MODE"):
        monkeypatch.delenv("CODING_AGENT_MODE", raising=False)

    client = TestClient(app)
    resp = client.post(
        "/run",
        json={
            "prompt": "Run a GLM on ds000114 motor task",
            "pipeline": "chat",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Non-coding path returns just a job_id without plan
    assert "job_id" in body
    assert "plan" not in body
