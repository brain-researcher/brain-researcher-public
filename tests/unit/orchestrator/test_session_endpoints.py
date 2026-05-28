from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import state_store as state_store_module
from brain_researcher.services.orchestrator.monitor_runtime import MonitorRuntime
from brain_researcher.services.orchestrator.session_endpoints import (
    integration_router,
    router,
)
from brain_researcher.services.orchestrator.session_runtime import SessionRuntime


@pytest.fixture
def session_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from brain_researcher.services.mcp import server as mcp_server

    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "true")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    state_store_module._STATE_STORE = None

    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.session_endpoints._resolve_request_user",
        _fake_user,
    )

    run_dir = tmp_path / "runs" / "run_demo"
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "stdout.log").write_text("line1\nline2\nline3\n", encoding="utf-8")

    def _run_get(run_id: str) -> dict[str, object]:
        return {
            "ok": True,
            "run": {
                "run_id": run_id,
                "status": "running",
                "steps": [
                    {"step_id": "prepare", "title": "Prepare", "status": "succeeded"},
                    {"step_id": "fit", "title": "Fit", "status": "running"},
                ],
            },
            "run_dir": str(run_dir),
        }

    def _run_metrics(_run_id: str) -> dict[str, object]:
        return {"ok": True, "metrics": {"totals": {"steps": 2}}}

    monkeypatch.setattr(mcp_server, "run_get", _run_get)
    monkeypatch.setattr(mcp_server, "run_metrics", _run_metrics)

    app = FastAPI()
    app.include_router(router)
    app.include_router(integration_router)
    app.state.monitor_runtime = MonitorRuntime()
    app.state.session_runtime = SessionRuntime(app, app.state.monitor_runtime)
    with TestClient(app) as client:
        yield client
    state_store_module._STATE_STORE = None


def test_session_attach_list_actions_and_slack_bridge(
    session_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_posts: list[tuple[str, str, str | None]] = []

    async def _fake_post_slack_message(*, channel_id, text, thread_ts):
        bridge_posts.append((channel_id, text, thread_ts))
        return "1710000000.000100"

    monkeypatch.setattr(
        session_client.app.state.monitor_runtime,
        "_post_slack_message",
        _fake_post_slack_message,
    )

    create_resp = session_client.post(
        "/api/sessions/attach",
        json={
            "kind": "mcp_run",
            "session_ref": "run_demo",
            "display_name": "Demo Session",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    session = create_resp.json()["session"]
    assert session["status"] == "running"

    list_resp = session_client.get(
        "/api/sessions",
        headers={"Authorization": "Bearer test"},
    )
    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()["items"]] == [session["id"]]

    status_resp = session_client.post(
        f"/api/sessions/{session['id']}/actions/status",
        json={},
        headers={"Authorization": "Bearer test"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["session"]["status"] == "running"

    logs_resp = session_client.post(
        f"/api/sessions/{session['id']}/actions/logs",
        json={"tail": 2},
        headers={"Authorization": "Bearer test"},
    )
    assert logs_resp.status_code == 200
    assert logs_resp.json()["logs"]["stdout"] == "line2\nline3"

    bridge_resp = session_client.post(
        f"/api/sessions/{session['id']}/bridges/slack",
        json={"channel_id": "C123", "thread_ts": "1710000000.000100"},
        headers={"Authorization": "Bearer test"},
    )
    assert bridge_resp.status_code == 200

    slack_resp = session_client.post(
        "/api/integrations/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "thread_ts": "1710000000.000100",
                "text": "<@U1> status",
            },
        },
    )
    assert slack_resp.status_code == 200
    assert slack_resp.json()["ok"] is True
    assert any("Demo Session" in text for _, text, _ in bridge_posts)
