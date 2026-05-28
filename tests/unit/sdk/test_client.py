"""Tests for brain_researcher.sdk.client."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import brain_researcher.sdk as br
from brain_researcher.sdk import job_registry
from brain_researcher.sdk.client import BRClient, connect
from brain_researcher.sdk.models import ToolCard, ToolResult

_SEARCH_RESPONSE = {
    "ok": True,
    "cards": [
        {
            "name": "fsl.bet",
            "description": "Brain extraction tool",
            "backend": "niwrap",
            "modalities": ["smri"],
            "kind": "imaging",
            "cost_hint": "normal",
        },
        {
            "name": "fsl.flirt",
            "description": "Linear registration",
            "backend": "niwrap",
            "modalities": ["smri", "fmri"],
            "kind": "imaging",
            "cost_hint": "normal",
        },
    ],
}

_EXECUTE_RESPONSE = {
    "ok": True,
    "resolved_tool_id": "fsl.bet",
    "result": {"output_path": "/tmp/out_brain.nii.gz"},
    "run_id": "run_123",
    "warnings": [],
}

_RECIPE_RESPONSE = {
    "ok": True,
    "requested_tool_id": "fsl.bet",
    "command": "bet input.nii.gz output.nii.gz -f 0.5",
}

_SERVER_INFO_RESPONSE = {
    "ok": True,
    "server_name": "brain-researcher",
    "version": "0.1.0",
}

_CALL_RESPONSE = {
    "ok": True,
    "nodes": [{"id": "kg_1", "name": "working memory"}],
}


class _FakeContentItem:
    def __init__(self, text: str):
        self.text = text


class _FakeCallResult:
    def __init__(self, data: dict):
        self.content = [_FakeContentItem(json.dumps(data))]


class _FakeSession:
    """Mock MCP ClientSession."""

    def __init__(self, *args, **kwargs):
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[str, dict] = {
            "tool_search": _SEARCH_RESPONSE,
            "tool_execute": _EXECUTE_RESPONSE,
            "get_execution_recipe": _RECIPE_RESPONSE,
            "server_info": _SERVER_INFO_RESPONSE,
            "kg_search_nodes": _CALL_RESPONSE,
        }

    async def initialize(self):
        pass

    async def call_tool(self, name: str, params: dict) -> Any:
        self.calls.append({"name": name, "params": params})
        data = self._responses.get(name, {"ok": False, "error": "unknown_tool"})
        return _FakeCallResult(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass


class _FakeStdioCtx:
    async def __aenter__(self):
        return (MagicMock(), MagicMock())

    async def __aexit__(self, *exc):
        pass


class _FakeHttpCtx:
    async def __aenter__(self):
        return (MagicMock(name="reader"), MagicMock(name="writer"), lambda: "sess_http")

    async def __aexit__(self, *exc):
        pass


@pytest.fixture(autouse=True)
def _clean_state():
    import brain_researcher.sdk.client as mod

    old = mod._singleton
    mod._singleton = None
    job_registry.clear()
    yield
    mod._singleton = old
    job_registry.clear()


@pytest.fixture
def mock_client():
    """Return a ``BRClient`` whose MCP transport is fully mocked."""
    client = BRClient(server_command=["fake-mcp"])
    loop = client._loop_thread.ensure_running()

    async def _fake_connect():
        client._session = _FakeSession()
        client._transport_ctx = _FakeStdioCtx()
        client._session_ctx = _FakeSession()
        client._connected = True

    future = asyncio.run_coroutine_threadsafe(_fake_connect(), loop)
    future.result(timeout=5)
    return client


class TestBRClientSearch:
    def test_search_returns_tool_cards(self, mock_client: BRClient):
        results = mock_client.search("skull stripping")
        assert len(results) == 2
        assert all(isinstance(r, ToolCard) for r in results)
        assert results[0].name == "fsl.bet"

    def test_search_with_filters(self, mock_client: BRClient):
        results = mock_client.search("reg", modalities=["fmri"], kind="imaging")
        assert len(results) == 2


class TestBRClientExecute:
    def test_execute_returns_tool_result(self, mock_client: BRClient):
        result = mock_client.execute("fsl.bet", {"input": "t1.nii.gz"})
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert result.output_path == "/tmp/out_brain.nii.gz"

    def test_execute_caches_result(self, mock_client: BRClient):
        r1 = mock_client.execute("fsl.bet", {"input": "t1.nii.gz"})
        r2 = mock_client.execute("fsl.bet", {"input": "t1.nii.gz"})
        assert r1 is r2

    def test_execute_force_bypasses_cache(self, mock_client: BRClient):
        r1 = mock_client.execute("fsl.bet", {"input": "t1.nii.gz"})
        r2 = mock_client.execute("fsl.bet", {"input": "t1.nii.gz"}, force=True)
        assert r1 is not r2
        assert r2.ok is True


class TestBRClientRecipe:
    def test_recipe_returns_dict(self, mock_client: BRClient):
        recipe = mock_client.recipe("fsl.bet", {"input": "t1.nii.gz"})
        assert recipe["ok"] is True
        assert "command" in recipe

    def test_recipe_omits_target_runtime_by_default(self, mock_client: BRClient):
        mock_client.recipe("fsl_bet", {"input_file": "t1.nii.gz"})
        assert "target_runtime" not in mock_client._session.calls[-1]["params"]

    def test_recipe_forwards_explicit_target(self, mock_client: BRClient):
        mock_client.recipe("fsl_bet", {"input_file": "t1.nii.gz"}, target="container")
        assert mock_client._session.calls[-1]["params"]["target_runtime"] == "container"


class TestBRClientServerInfo:
    def test_server_info(self, mock_client: BRClient):
        info = mock_client.server_info()
        assert info["server_name"] == "brain-researcher"


class TestBRClientCall:
    def test_call_returns_raw_dict(self, mock_client: BRClient):
        payload = mock_client.call("kg_search_nodes", {"query": "working memory"})
        assert payload["ok"] is True
        assert payload["nodes"][0]["name"] == "working memory"


class TestHTTPTransport:
    def test_http_transport_is_selected_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BR_MCP_HTTP_URL", "https://brain-researcher.com/mcp")
        monkeypatch.setenv("BR_MCP_AUTH_HEADER", "Bearer explicit-token")
        monkeypatch.setenv("BR_MCP_TOKEN", "ignored-token")

        fake_http_client = MagicMock()
        fake_http_client.aclose = AsyncMock()

        with patch(
            "brain_researcher.sdk.client.httpx.AsyncClient",
            return_value=fake_http_client,
        ) as async_client_cls:
            with patch(
                "mcp.client.streamable_http.streamable_http_client",
                return_value=_FakeHttpCtx(),
            ) as stream_ctx:
                with patch("mcp.ClientSession", _FakeSession):
                    client = BRClient()
                    client._run_async(client._connect())
                    assert client._connected is True
                    assert client._transport_mode == "http"
                    async_client_cls.assert_called_once_with(
                        headers={"Authorization": "Bearer explicit-token"},
                        timeout=120.0,
                    )
                    stream_ctx.assert_called_once_with(
                        "https://brain-researcher.com/mcp",
                        http_client=fake_http_client,
                    )
                    client.close()

    def test_http_transport_uses_bearer_token_when_no_auth_header(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("BR_MCP_HTTP_URL", "https://brain-researcher.com/mcp")
        monkeypatch.delenv("BR_MCP_AUTH_HEADER", raising=False)
        monkeypatch.delenv("BR_MCP_BEARER_TOKEN", raising=False)
        monkeypatch.setenv("BR_MCP_TOKEN", "token-from-env")

        fake_http_client = MagicMock()
        fake_http_client.aclose = AsyncMock()

        with patch(
            "brain_researcher.sdk.client.httpx.AsyncClient",
            return_value=fake_http_client,
        ) as async_client_cls:
            with patch(
                "mcp.client.streamable_http.streamable_http_client",
                return_value=_FakeHttpCtx(),
            ):
                with patch("mcp.ClientSession", _FakeSession):
                    client = BRClient()
                    client._run_async(client._connect())
                    assert async_client_cls.call_args.kwargs["headers"] == {
                        "Authorization": "Bearer token-from-env"
                    }
                    client.close()


class TestConnect:
    def test_connect_returns_singleton(self):
        with patch(
            "brain_researcher.sdk.client._resolve_server_command", return_value=["fake"]
        ):
            with patch.object(BRClient, "_ensure_connected"):
                c1 = connect(server_command=["fake"])
                c2 = connect()
                assert c1 is c2


class TestModuleShortcuts:
    def test_call_shortcut(self):
        fake_client = MagicMock()
        fake_client.call.return_value = {"ok": True}
        with patch("brain_researcher.sdk.connect", return_value=fake_client):
            result = br.call("server_info", {})
        assert result == {"ok": True}
        fake_client.call.assert_called_once_with("server_info", {})
