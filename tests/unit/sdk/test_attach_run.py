"""Tests for ``br.attach_run`` and ``RunHandle``."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from brain_researcher.sdk import job_registry
from brain_researcher.sdk.client import BRClient
from brain_researcher.sdk.models import RunHandle

_BUNDLE_RESPONSE = {
    "ok": True,
    "run_id": "run_abc",
    "bundle": {
        "artifacts": [
            {"path": "outputs/result.nii.gz", "size": 1024},
        ],
    },
    "record": {
        "status": "running",
        "workflow": {"id": "wf_glm_v1"},
        "dataset": {"id": "ds:openneuro:ds000001"},
    },
}

_BUNDLE_COMPLETED = {
    **_BUNDLE_RESPONSE,
    "record": {**_BUNDLE_RESPONSE["record"], "status": "completed"},
}

_LOGS_RESPONSE = {
    "ok": True,
    "items": [{"relpath": "logs/stdout.txt", "size_bytes": 42}],
}


class _FakeContentItem:
    def __init__(self, text: str):
        self.text = text


class _FakeCallResult:
    def __init__(self, data: dict):
        self.content = [_FakeContentItem(json.dumps(data))]


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._bundle_seq = [_BUNDLE_RESPONSE, _BUNDLE_COMPLETED]
        self._bundle_idx = 0

    async def initialize(self):
        pass

    async def call_tool(self, name: str, params: dict) -> Any:
        self.calls.append({"name": name, "params": params})
        if name == "run_bundle_get":
            payload = self._bundle_seq[min(self._bundle_idx, len(self._bundle_seq) - 1)]
            self._bundle_idx += 1
            return _FakeCallResult(payload)
        if name == "run_logs":
            return _FakeCallResult(_LOGS_RESPONSE)
        return _FakeCallResult({"ok": False, "error": "unknown_tool"})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass


class _FakeStdioCtx:
    async def __aenter__(self):
        return (MagicMock(), MagicMock())

    async def __aexit__(self, *exc):
        pass


@pytest.fixture(autouse=True)
def _clean_singleton():
    import brain_researcher.sdk.client as mod

    old = mod._singleton
    mod._singleton = None
    job_registry.clear()
    yield
    mod._singleton = old
    job_registry.clear()


@pytest.fixture
def mock_client():
    client = BRClient(server_command=["fake-mcp"])
    loop = client._loop_thread.ensure_running()

    async def _fake_connect() -> None:
        client._session = _FakeSession()
        client._transport_ctx = _FakeStdioCtx()
        client._session_ctx = _FakeSession()
        client._connected = True

    asyncio.run_coroutine_threadsafe(_fake_connect(), loop).result(timeout=5)
    return client


def test_attach_run_returns_run_handle(mock_client: BRClient) -> None:
    handle = mock_client.attach_run("run_abc")
    assert isinstance(handle, RunHandle)
    assert handle.run_id == "run_abc"
    assert handle.status == "running"
    assert handle.workflow == {"id": "wf_glm_v1"}
    assert handle.dataset == {"id": "ds:openneuro:ds000001"}
    assert handle.artifacts and handle.artifacts[0]["path"] == "outputs/result.nii.gz"


def test_attach_run_validates_run_id(mock_client: BRClient) -> None:
    with pytest.raises(ValueError):
        mock_client.attach_run("")
    with pytest.raises(ValueError):
        mock_client.attach_run("   ")


def test_run_handle_refresh_re_fetches_status(mock_client: BRClient) -> None:
    handle = mock_client.attach_run("run_abc")
    assert handle.status == "running"
    handle.refresh()
    assert handle.status == "completed"
    assert handle.logs and handle.logs[0]["relpath"] == "logs/stdout.txt"


def test_run_handle_wait_polls_until_terminal(
    mock_client: BRClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import brain_researcher.sdk.models as models

    sleeps: list[float] = []
    monkeypatch.setattr(models.time, "sleep", lambda secs: sleeps.append(secs))

    # Extend the bundle sequence so wait() iterates a couple of refresh cycles
    # before hitting the terminal status, ensuring the sleep path is exercised.
    session = mock_client._session
    session._bundle_seq = [
        _BUNDLE_RESPONSE,  # initial attach_run snapshot
        _BUNDLE_RESPONSE,  # first wait() refresh — still running
        _BUNDLE_COMPLETED,
    ]
    session._bundle_idx = 0

    handle = mock_client.attach_run("run_abc")
    assert handle.status == "running"
    result = handle.wait(timeout=10, poll_interval=0.25)
    assert result is handle
    assert handle.status == "completed"
    assert sleeps, "wait() should have slept at least once between polls"
