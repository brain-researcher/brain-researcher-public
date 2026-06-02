from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from brain_researcher.services.shared.mcp_runtime_bridge import (
    HttpMCPRuntimeProvider,
    MCPRuntimeUnavailable,
    clear_mcp_runtime_provider,
    get_mcp_runtime_provider,
    register_mcp_runtime_provider,
)


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_registered_mcp_runtime_provider_round_trips(monkeypatch):
    class FakeProvider:
        def call_tool(self, tool_name, arguments=None):
            return {"tool_name": tool_name, "arguments": dict(arguments or {})}

    monkeypatch.setattr(
        "brain_researcher.services.shared.mcp_runtime_bridge._registered_provider",
        None,
    )
    provider = register_mcp_runtime_provider(FakeProvider())

    assert get_mcp_runtime_provider() is provider
    assert provider.call_tool("server_info", {"x": 1}) == {
        "tool_name": "server_info",
        "arguments": {"x": 1},
    }

    clear_mcp_runtime_provider()


def test_http_mcp_runtime_provider_calls_tool_without_importing_server():
    sys.modules.pop("brain_researcher.services.mcp.server", None)
    seen: list[dict[str, Any]] = []

    def opener(request, timeout):
        assert timeout == 3.0
        payload = json.loads(request.data.decode("utf-8"))
        seen.append(payload)
        if payload["method"] == "initialize":
            return _FakeResponse(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {"ok": True}},
                headers={
                    "Content-Type": "application/json",
                    "mcp-session-id": "session-1",
                },
            )
        assert payload == {
            "jsonrpc": "2.0",
            "id": "bridge-2",
            "method": "tools/call",
            "params": {
                "name": "server_info",
                "arguments": {"detail": True},
            },
        }
        assert request.headers["Mcp-session-id"] == "session-1"
        return _FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "structuredContent": {
                        "ok": True,
                        "name": "brain-researcher",
                    }
                },
            }
        )

    provider = HttpMCPRuntimeProvider(
        url="http://127.0.0.1:7000/mcp",
        token=None,
        timeout_s=3.0,
        opener=opener,
    )

    payload = provider.call_tool("mcp.server_info", {"detail": True})

    assert payload == {"ok": True, "name": "brain-researcher"}
    assert [item["method"] for item in seen] == ["initialize", "tools/call"]
    assert "brain_researcher.services.mcp.server" not in sys.modules


def test_http_mcp_runtime_provider_surfaces_unavailable():
    def opener(_request, _timeout):
        raise OSError("connection refused")

    provider = HttpMCPRuntimeProvider(
        url="http://127.0.0.1:7000/mcp",
        token=None,
        timeout_s=1.0,
        opener=opener,
    )

    with pytest.raises(MCPRuntimeUnavailable, match="connection refused"):
        provider.call_tool("server_info")
