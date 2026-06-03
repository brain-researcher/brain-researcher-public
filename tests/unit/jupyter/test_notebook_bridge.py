from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import httpx
import pytest

from brain_researcher.integrations.jupyter.bridge import (
    BridgeSessionState,
    NotebookAssistantBridgeSettings,
    build_bootstrap_payload,
    build_proxy_request_headers,
    get_bridge_session_store,
    issue_bridge_session,
    proxy_mcp_request,
)
from brain_researcher.integrations.jupyter.server_extension import register_handlers


def test_notebook_bridge_settings_from_env(monkeypatch):
    monkeypatch.setenv("BR_NOTEBOOK_ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("BR_PRODUCT_NAME", "Brain Researcher")
    monkeypatch.setenv("BR_WORKSPACE_MODE", "hosted")
    monkeypatch.setenv("BR_NOTEBOOK_ASSISTANT_MODE", "mcp")
    monkeypatch.setenv("BR_MCP_MODE", "hosted_notebook_v1")
    monkeypatch.setenv("BR_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv(
        "BR_MCP_HTTP_URL",
        "https://user:secret@hub.${PUBLIC_HOSTNAME}/mcp?token=secret",
    )
    monkeypatch.setenv("BR_NOTEBOOK_BRIDGE_BASE_PATH", "brain-researcher/api")
    monkeypatch.setenv("BR_PUBLIC_WORKSPACE_URL", "https://hub.${PUBLIC_HOSTNAME}")
    monkeypatch.setenv("BR_NOTEBOOK_BRIDGE_TIMEOUT_SECONDS", "45")

    settings = NotebookAssistantBridgeSettings.from_env()

    assert settings.enabled is True
    assert settings.api_base_path == "/brain-researcher/api"
    assert settings.proxy_enabled is True
    assert settings.request_timeout_seconds == 45.0
    assert settings.redacted_mcp_http_url == "https://hub.${PUBLIC_HOSTNAME}/mcp"
    assert settings.session_header_name == "X-Brain-Researcher-Bridge-Session"
    assert settings.session_query_param == "bridge_session"


def test_bootstrap_payload_and_proxy_headers():
    settings = NotebookAssistantBridgeSettings(
        enabled=True,
        product_name="Brain Researcher",
        workspace_mode="hosted",
        assistant_mode="mcp",
        mcp_mode="hosted_notebook_v1",
        mcp_transport="streamable-http",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token="secret-token",
        api_base_path="/brain-researcher/api",
        docs_path="/docs",
        public_workspace_url="https://hub.${PUBLIC_HOSTNAME}",
        request_timeout_seconds=30.0,
        session_ttl_seconds=3600.0,
        session_header_name="X-Brain-Researcher-Bridge-Session",
        session_query_param="bridge_session",
    )
    bridge_session = BridgeSessionState(
        bridge_session_id="brj_test",
        created_at_epoch=1.0,
        last_seen_at_epoch=2.0,
        upstream_session_id="upstream-123",
    )

    payload = build_bootstrap_payload(settings, bridge_session=bridge_session)
    headers = build_proxy_request_headers(
        {"Content-Type": "application/json", "Accept": "application/json"},
        settings,
        bridge_session=bridge_session,
    )

    assert payload["assistant"] == {
        "enabled": True,
        "mode": "mcp",
        "bridge": "jupyter-server-extension",
    }
    assert payload["mcp"] == {
        "mode": "hosted_notebook_v1",
        "transport": "streamable-http",
        "proxy_enabled": True,
        "upstream_url": "https://hub.${PUBLIC_HOSTNAME}/mcp",
    }
    assert payload["routes"] == {
        "health": "/brain-researcher/api/health",
        "bootstrap": "/brain-researcher/api/bootstrap",
        "mcp": "/brain-researcher/api/mcp",
    }
    assert payload["session"] == {
        "header_name": "X-Brain-Researcher-Bridge-Session",
        "query_param": "bridge_session",
        "bridge_session_id": "brj_test",
        "upstream_session_bound": True,
    }
    assert headers["content-type"] == "application/json"
    assert headers["accept"] == "application/json"
    assert headers["mcp-session-id"] == "upstream-123"
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["X-Brain-Researcher-MCP-Mode"] == "hosted_notebook_v1"


def test_register_handlers_uses_base_url():
    settings = NotebookAssistantBridgeSettings(
        enabled=True,
        product_name="Brain Researcher",
        workspace_mode="hosted",
        assistant_mode="mcp",
        mcp_mode="hosted_notebook_v1",
        mcp_transport="streamable-http",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token=None,
        api_base_path="/brain-researcher/api",
        docs_path="/docs",
        public_workspace_url=None,
        request_timeout_seconds=30.0,
        session_ttl_seconds=3600.0,
        session_header_name="X-Brain-Researcher-Bridge-Session",
        session_query_param="bridge_session",
    )
    added_handlers = []

    class FakeWebApp:
        settings = {"base_url": "/user/demo/"}

        def add_handlers(self, host_pattern, handlers):
            added_handlers.append((host_pattern, handlers))

    runtime = SimpleNamespace(
        APIHandler=type("FakeAPIHandler", (), {}),
        url_path_join=lambda *parts: "/" + "/".join(
            part.strip("/") for part in parts if part and part.strip("/")
        ),
        web=SimpleNamespace(authenticated=lambda func: func),
    )
    serverapp = SimpleNamespace(
        web_app=FakeWebApp(),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None),
    )

    handlers = register_handlers(serverapp, settings=settings, runtime=runtime)

    assert len(handlers) == 3
    assert added_handlers
    assert added_handlers[0][0] == ".*$"
    route_patterns = [route for route, _handler in handlers]
    assert route_patterns == [
        "/user/demo/brain-researcher/api/health",
        "/user/demo/brain-researcher/api/bootstrap",
        "/user/demo/brain-researcher/api/mcp",
    ]


def test_issue_bridge_session_reuses_existing_state():
    settings = NotebookAssistantBridgeSettings(
        enabled=True,
        product_name="Brain Researcher",
        workspace_mode="hosted",
        assistant_mode="mcp",
        mcp_mode="hosted_notebook_v1",
        mcp_transport="streamable-http",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token=None,
        api_base_path="/brain-researcher/api",
        docs_path="/docs",
        public_workspace_url=None,
        request_timeout_seconds=30.0,
        session_ttl_seconds=3600.0,
        session_header_name="X-Brain-Researcher-Bridge-Session",
        session_query_param="bridge_session",
    )

    first = issue_bridge_session(settings)
    second = issue_bridge_session(settings, requested_session_id=first.bridge_session_id)

    assert second.bridge_session_id == first.bridge_session_id
    assert second.created_at_epoch == first.created_at_epoch
    assert second.last_seen_at_epoch >= first.last_seen_at_epoch


@pytest.mark.asyncio
async def test_proxy_mcp_request_binds_upstream_session(monkeypatch):
    settings = NotebookAssistantBridgeSettings(
        enabled=True,
        product_name="Brain Researcher",
        workspace_mode="hosted",
        assistant_mode="mcp",
        mcp_mode="hosted_notebook_v1",
        mcp_transport="streamable-http",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token=None,
        api_base_path="/brain-researcher/api",
        docs_path="/docs",
        public_workspace_url=None,
        request_timeout_seconds=30.0,
        session_ttl_seconds=3600.0,
        session_header_name="X-Brain-Researcher-Bridge-Session",
        session_query_param="bridge_session",
    )
    bridge_session = issue_bridge_session(settings)
    captured_headers = deque()

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        session_header = request.headers.get("mcp-session-id")
        if session_header:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"ok": True, "seen_session": session_header},
            )
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": "upstream-abc",
            },
            json={"ok": True, "initialized": True},
        )

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)

    first = await proxy_mcp_request(
        method="POST",
        request_headers={"content-type": "application/json"},
        body=b'{"jsonrpc":"2.0","id":"1","method":"initialize"}',
        settings=settings,
        bridge_session=bridge_session,
    )
    bound_session = get_bridge_session_store(settings).get(
        bridge_session.bridge_session_id
    )
    second = await proxy_mcp_request(
        method="POST",
        request_headers={"content-type": "application/json"},
        body=b'{"jsonrpc":"2.0","id":"2","method":"tools/list"}',
        settings=settings,
        bridge_session=bound_session,
    )

    assert first.headers["X-Brain-Researcher-Bridge-Session"] == bridge_session.bridge_session_id
    assert first.headers["x-brain-researcher-upstream-session-bound"] == "true"
    assert second.headers["x-brain-researcher-upstream-session-bound"] == "true"
    assert bound_session is not None
    assert bound_session.upstream_session_id == "upstream-abc"
    assert "mcp-session-id" not in captured_headers[0]
    assert captured_headers[1]["mcp-session-id"] == "upstream-abc"
