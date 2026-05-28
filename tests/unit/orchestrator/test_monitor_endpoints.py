from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import state_store as state_store_module
from brain_researcher.services.orchestrator.monitor_endpoints import (
    integration_router,
    router,
)
from brain_researcher.services.orchestrator.monitor_runtime import (
    CreateMonitorRequest,
    CreateSlackBridgeRequest,
    MonitorRuntime,
    MonitorSourceType,
)


@pytest.fixture
def monitor_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "true")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    state_store_module._STATE_STORE = None

    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.monitor_endpoints._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(router)
    app.include_router(integration_router)
    app.state.monitor_runtime = MonitorRuntime()
    with TestClient(app) as client:
        yield client
    state_store_module._STATE_STORE = None


def test_monitor_crud_and_actions(monitor_client: TestClient) -> None:
    create_resp = monitor_client.post(
        "/api/monitors",
        json={
            "source_type": "local_process",
            "source_ref": str(os.getpid()),
            "display_name": "endpoint process",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    monitor = create_resp.json()["monitor"]

    list_resp = monitor_client.get(
        "/api/monitors",
        headers={"Authorization": "Bearer test"},
    )
    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()["items"]] == [monitor["id"]]

    get_resp = monitor_client.get(
        f"/api/monitors/{monitor['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["monitor"]["display_name"] == "endpoint process"

    status_resp = monitor_client.post(
        f"/api/monitors/{monitor['id']}/actions/status",
        json={},
        headers={"Authorization": "Bearer test"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["monitor"]["status"] == "running"


def test_slack_and_discord_integration_endpoints(
    monitor_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = monitor_client.app.state.monitor_runtime
    monitor = asyncio.run(
        runtime.create_monitor(
            "user_demo",
            CreateMonitorRequest(
                source_type=MonitorSourceType.LOCAL_PROCESS,
                source_ref=str(os.getpid()),
                display_name="phone monitor",
            ),
        )
    )

    async def _fake_post_slack_message(*, channel_id, text, thread_ts):
        return "1710000000.000100"

    monkeypatch.setattr(runtime, "_post_slack_message", _fake_post_slack_message)
    bridge = asyncio.run(
        runtime.create_slack_bridge(
            monitor.id,
            CreateSlackBridgeRequest(
                channel_id="C123",
                thread_ts="1710000000.000100",
            ),
        )
    )
    assert bridge.platform == "slack"

    slack_resp = monitor_client.post(
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

    discord_resp = monitor_client.post(
        "/api/integrations/discord/interactions",
        json={
            "type": 2,
            "data": {
                "name": "monitor-status",
                "options": [{"name": "monitor_id", "value": monitor.id}],
            },
        },
    )
    assert discord_resp.status_code == 200
    assert discord_resp.json()["type"] == 4
    assert "phone monitor" in discord_resp.json()["data"]["content"]
