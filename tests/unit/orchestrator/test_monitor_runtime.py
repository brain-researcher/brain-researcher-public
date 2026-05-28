from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator import state_store as state_store_module
from brain_researcher.services.orchestrator.monitor_runtime import (
    CreateDiscordBridgeRequest,
    CreateMonitorRequest,
    CreateSlackBridgeRequest,
    MonitorActionRequest,
    MonitorRuntime,
    MonitorSourceType,
    MonitorStatus,
)


@pytest.fixture
def isolated_state_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "true")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    state_store_module._STATE_STORE = None
    yield
    state_store_module._STATE_STORE = None


@pytest.mark.asyncio
async def test_local_process_monitor_refresh_and_logs(
    isolated_state_store, tmp_path: Path
) -> None:
    log_path = tmp_path / "local.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")

    runtime = MonitorRuntime()
    monitor = await runtime.create_monitor(
        "user_demo",
        CreateMonitorRequest(
            source_type=MonitorSourceType.LOCAL_PROCESS,
            source_ref=str(os.getpid()),
            display_name="current process",
            log_paths=[str(log_path)],
        ),
    )

    assert monitor.status == MonitorStatus.RUNNING
    assert monitor.thread_id is not None

    result = await runtime.perform_action(
        monitor.id,
        "tail_logs",
        MonitorActionRequest(tail=2),
    )
    assert result["logs"]["stdout"] == "line2\nline3"


@pytest.mark.asyncio
async def test_slurm_monitor_uses_sherlock_adapter(
    isolated_state_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    import brain_researcher.services.orchestrator.monitor_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "sherlock_job_inspect",
        lambda job_id: {
            "ok": True,
            "squeue": {"state": "RUNNING", "reason": "None"},
            "sacct": [{"State": "RUNNING"}],
            "log_paths": {"stdout": "/tmp/slurm.out", "stderr": "/tmp/slurm.err"},
        },
    )
    monkeypatch.setattr(
        runtime_module,
        "sherlock_job_logs",
        lambda **kwargs: {
            "ok": True,
            "stdout_text": "running\nstill running",
            "stderr_text": "",
            "log_paths": {"stdout": "/tmp/slurm.out", "stderr": "/tmp/slurm.err"},
        },
    )

    runtime = MonitorRuntime()
    monitor = await runtime.create_monitor(
        "user_demo",
        CreateMonitorRequest(
            source_type=MonitorSourceType.SLURM_JOB,
            source_ref="123456",
            display_name="slurm job",
        ),
    )
    assert monitor.status == MonitorStatus.RUNNING

    logs = await runtime.perform_action(
        monitor.id,
        "tail_logs",
        MonitorActionRequest(tail=10),
    )
    assert "running" in (logs["logs"]["stdout"] or "")


@pytest.mark.asyncio
async def test_chat_bridges_and_discord_command_formatting(
    isolated_state_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = MonitorRuntime()
    monitor = await runtime.create_monitor(
        "user_demo",
        CreateMonitorRequest(
            source_type=MonitorSourceType.LOCAL_PROCESS,
            source_ref=str(os.getpid()),
            display_name="bridge target",
        ),
    )

    sent_messages: list[tuple[str, str, str | None]] = []

    async def _fake_post_slack_message(*, channel_id, text, thread_ts):
        sent_messages.append((channel_id, text, thread_ts))
        return "1710000000.000100"

    async def _fake_post_discord_webhook(*, webhook_url, text, username):
        sent_messages.append((webhook_url, text, username))

    monkeypatch.setattr(runtime, "_post_slack_message", _fake_post_slack_message)
    monkeypatch.setattr(runtime, "_post_discord_webhook", _fake_post_discord_webhook)

    slack_bridge = await runtime.create_slack_bridge(
        monitor.id,
        CreateSlackBridgeRequest(channel_id="C123", thread_ts="1710000000.000100"),
    )
    discord_bridge = await runtime.create_discord_bridge(
        monitor.id,
        CreateDiscordBridgeRequest(
            webhook_url="https://discord.example/webhook",
            channel_id="999",
        ),
    )

    assert slack_bridge.platform == "slack"
    assert discord_bridge.platform == "discord"

    response = await runtime.handle_discord_interaction(
        json.dumps(
            {
                "type": 2,
                "data": {
                    "name": "monitor-status",
                    "options": [{"name": "monitor_id", "value": monitor.id}],
                },
            }
        ).encode("utf-8"),
        {},
    )
    assert response["type"] == 4
    assert "bridge target" in response["data"]["content"]

    handled = await runtime.handle_slack_events(
        json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "app_mention",
                    "channel": "C123",
                    "thread_ts": "1710000000.000100",
                    "text": "<@U1> status",
                },
            }
        ).encode("utf-8"),
        {},
    )
    assert handled["ok"] is True
    assert any("bridge target" in payload[1] for payload in sent_messages)
