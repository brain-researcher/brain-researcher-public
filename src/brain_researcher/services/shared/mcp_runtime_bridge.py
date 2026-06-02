"""Shared MCP runtime bridge contract.

Agent/tools code can request MCP tool execution through this module without
importing ``services.mcp.server``. The default provider uses the configured MCP
HTTP endpoint; tests and composition roots may register an in-process provider.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

DEFAULT_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_CLIENT_NAME = "brain-researcher-service-bridge"
DEFAULT_CLIENT_VERSION = "0.1.0"


class MCPRuntimeUnavailable(RuntimeError):
    """Raised when no MCP runtime provider can execute a bridge call."""


@runtime_checkable
class MCPRuntimeProvider(Protocol):
    """Minimal runtime contract consumed by agent/tools call sites."""

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any: ...


_registered_provider: MCPRuntimeProvider | None = None
_default_http_provider: MCPRuntimeProvider | None = None


def register_mcp_runtime_provider(provider: MCPRuntimeProvider) -> MCPRuntimeProvider:
    """Register an explicit MCP provider for the current process."""

    global _registered_provider
    _registered_provider = provider
    return provider


def clear_mcp_runtime_provider() -> None:
    """Clear the explicit provider. Intended for tests."""

    global _registered_provider
    _registered_provider = None


def peek_mcp_runtime_provider() -> MCPRuntimeProvider | None:
    """Return an explicitly registered provider, if one exists."""

    return _registered_provider


def get_mcp_runtime_provider() -> MCPRuntimeProvider:
    """Return the explicit provider or the HTTP MCP provider.

    This function intentionally does not import ``services.mcp.server``. If a
    caller wants in-process MCP behavior, a higher-level composition root must
    register a provider explicitly.
    """

    if _registered_provider is not None:
        return _registered_provider
    return get_default_http_mcp_runtime_provider()


def call_mcp_tool(tool_name: str, **arguments: Any) -> Any:
    """Call one MCP tool through the configured provider."""

    return get_mcp_runtime_provider().call_tool(tool_name, arguments)


def _default_mcp_url() -> str:
    if os.environ.get("BR_MCP_HTTP_URL"):
        return str(os.environ["BR_MCP_HTTP_URL"])
    host = os.environ.get("BR_MCP_HOST", "127.0.0.1")
    port = os.environ.get("BR_MCP_PORT", "7000")
    mount_path = os.environ.get("BR_MCP_MOUNT_PATH", "/mcp")
    return f"http://{host}:{port}{mount_path}"


def _default_token() -> str | None:
    token = (
        os.environ.get("BR_MCP_TOKEN")
        or os.environ.get("BR_MCP_AUTH_TOKEN")
        or os.environ.get("BR_MCP_BEARER_TOKEN")
        or ""
    )
    token = str(token).strip()
    return token or None


def get_default_http_mcp_runtime_provider() -> MCPRuntimeProvider:
    """Return the cached default HTTP MCP provider."""

    global _default_http_provider
    if _default_http_provider is None:
        _default_http_provider = HttpMCPRuntimeProvider(
            url=_default_mcp_url(),
            token=_default_token(),
            timeout_s=float(os.environ.get("BR_MCP_HTTP_TIMEOUT_S", "20")),
        )
    return _default_http_provider


def reset_default_http_mcp_runtime_provider() -> None:
    """Reset the cached HTTP provider. Intended for tests."""

    global _default_http_provider
    _default_http_provider = None


def _extract_first_sse_json(body_text: str) -> dict[str, Any] | None:
    for raw_line in body_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            decoded = json.loads(payload)
        except Exception:
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _open_url(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


class HttpMCPRuntimeProvider:
    """Small stdlib-only MCP streamable HTTP provider."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None,
        timeout_s: float,
        session_id: str | None = None,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        client_name: str = DEFAULT_CLIENT_NAME,
        client_version: str = DEFAULT_CLIENT_VERSION,
        opener: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout_s = timeout_s
        self.session_id = session_id
        self.protocol_version = protocol_version
        self.client_name = client_name
        self.client_version = client_version
        self._opener = opener or _open_url
        self._initialize_done = False
        self._rpc_counter = 0

    def _next_id(self) -> str:
        self._rpc_counter += 1
        return f"bridge-{self._rpc_counter}"

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": os.environ.get("BR_MCP_HTTP_USER_AGENT", DEFAULT_CLIENT_NAME),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    def _update_session_id(self, headers: Mapping[str, Any] | None) -> None:
        if not headers:
            return
        for key, value in headers.items():
            if str(key).lower() == "mcp-session-id" and value:
                self.session_id = str(value)
                return

    def _request(
        self,
        *,
        method: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], str]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=self._base_headers(),
            method=method,
        )
        try:
            with self._opener(request, self.timeout_s) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            status = int(exc.code)
            response_headers = dict((exc.headers or {}).items())
        except Exception as exc:
            raise MCPRuntimeUnavailable(
                f"MCP HTTP request failed at {self.url}: {exc}"
            ) from exc
        self._update_session_id(response_headers)
        return status, response_headers, raw

    @staticmethod
    def _parse_rpc_body(
        *,
        status_code: int,
        headers: Mapping[str, Any],
        body: str,
    ) -> dict[str, Any]:
        content_type = str(headers.get("Content-Type", ""))
        if "text/event-stream" in content_type or body.lstrip().startswith(
            ("data:", "event:")
        ):
            parsed = _extract_first_sse_json(body)
            if parsed is not None:
                return parsed
            return {
                "ok": False,
                "error": "invalid_sse_response",
                "http_status": status_code,
                "body": body[:2000],
            }
        try:
            loaded = json.loads(body)
        except Exception:
            return {
                "ok": False,
                "error": "invalid_json_response",
                "http_status": status_code,
                "body": body[:2000],
            }
        if isinstance(loaded, dict):
            return loaded
        return {
            "ok": False,
            "error": "unexpected_json_response_type",
            "http_status": status_code,
            "body": body[:2000],
        }

    @staticmethod
    def extract_tools_call_payload(result_obj: Any) -> dict[str, Any]:
        if isinstance(result_obj, dict):
            structured = result_obj.get("structuredContent")
            if isinstance(structured, dict):
                return structured
            content = result_obj.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if not isinstance(text, str):
                        continue
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
            return result_obj
        return {"ok": True, "result": result_obj}

    def _rpc(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": dict(params or {}),
        }
        status, headers, body = self._request(method="POST", payload=payload)
        envelope = self._parse_rpc_body(
            status_code=status,
            headers=headers,
            body=body,
        )
        ok = status == 200 and isinstance(envelope, dict) and "error" not in envelope
        return {
            "ok": ok,
            "method": method,
            "params": dict(params or {}),
            "http_status": status,
            "session_id": self.session_id,
            "envelope": envelope,
        }

    def _initialize_once(self) -> None:
        if self._initialize_done:
            return
        response = self._rpc(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
        )
        if not response.get("ok"):
            raise MCPRuntimeUnavailable(
                f"MCP initialize failed at {self.url}: {response.get('envelope')}"
            )
        self._initialize_done = True

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        self._initialize_once()
        normalized_name = (
            tool_name.split(".", 1)[1] if tool_name.startswith("mcp.") else tool_name
        )
        response = self._rpc(
            "tools/call",
            {"name": normalized_name, "arguments": dict(arguments or {})},
        )
        if not response.get("ok"):
            raise MCPRuntimeUnavailable(
                f"MCP tool call failed for {normalized_name}: "
                f"{response.get('envelope')}"
            )
        envelope = response.get("envelope")
        result_obj = envelope.get("result") if isinstance(envelope, dict) else None
        return self.extract_tools_call_payload(result_obj)


__all__ = [
    "MCPRuntimeProvider",
    "MCPRuntimeUnavailable",
    "HttpMCPRuntimeProvider",
    "register_mcp_runtime_provider",
    "clear_mcp_runtime_provider",
    "peek_mcp_runtime_provider",
    "get_mcp_runtime_provider",
    "get_default_http_mcp_runtime_provider",
    "reset_default_http_mcp_runtime_provider",
    "call_mcp_tool",
]
