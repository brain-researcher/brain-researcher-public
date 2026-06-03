"""Core settings and proxy helpers for the hosted notebook assistant bridge."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from brain_researcher.core.utils.env_loader import ensure_env_loaded

DEFAULT_API_BASE_PATH = "/brain-researcher/api"
DEFAULT_DOCS_PATH = "/docs"
DEFAULT_PROXY_TIMEOUT_SECONDS = 30.0
DEFAULT_SESSION_TTL_SECONDS = 3600.0
DEFAULT_SESSION_HEADER_NAME = "X-Brain-Researcher-Bridge-Session"
DEFAULT_SESSION_QUERY_PARAM = "bridge_session"
FORWARDED_REQUEST_HEADERS = (
    "accept",
    "content-type",
    "last-event-id",
)
FORWARDED_RESPONSE_HEADERS = (
    "cache-control",
    "content-type",
    "location",
    "x-request-id",
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _normalize_path(raw: str | None, default: str) -> str:
    value = (raw or default).strip()
    if not value.startswith("/"):
        value = f"/{value}"
    value = value.rstrip("/")
    return value or default


def _normalize_optional_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def _redact_url(raw: str | None) -> str | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


@dataclass(frozen=True)
class NotebookAssistantBridgeSettings:
    enabled: bool
    product_name: str
    workspace_mode: str
    assistant_mode: str
    mcp_mode: str
    mcp_transport: str
    mcp_http_url: str | None
    mcp_bearer_token: str | None
    api_base_path: str
    docs_path: str
    public_workspace_url: str | None
    request_timeout_seconds: float
    session_ttl_seconds: float
    session_header_name: str
    session_query_param: str

    @classmethod
    def from_env(cls) -> NotebookAssistantBridgeSettings:
        ensure_env_loaded()
        return cls(
            enabled=_bool_env("BR_NOTEBOOK_ASSISTANT_ENABLED", True),
            product_name=os.getenv("BR_PRODUCT_NAME", "Brain Researcher").strip()
            or "Brain Researcher",
            workspace_mode=os.getenv("BR_WORKSPACE_MODE", "hosted").strip() or "hosted",
            assistant_mode=os.getenv("BR_NOTEBOOK_ASSISTANT_MODE", "mcp").strip()
            or "mcp",
            mcp_mode=os.getenv("BR_MCP_MODE", "hosted_notebook_v1").strip()
            or "hosted_notebook_v1",
            mcp_transport=os.getenv("BR_MCP_TRANSPORT", "streamable-http").strip()
            or "streamable-http",
            mcp_http_url=_normalize_optional_text(os.getenv("BR_MCP_HTTP_URL")),
            mcp_bearer_token=_normalize_optional_text(os.getenv("BR_MCP_BEARER_TOKEN")),
            api_base_path=_normalize_path(
                os.getenv("BR_NOTEBOOK_BRIDGE_BASE_PATH"), DEFAULT_API_BASE_PATH
            ),
            docs_path=_normalize_path(
                os.getenv("BR_NOTEBOOK_BRIDGE_DOCS_PATH"), DEFAULT_DOCS_PATH
            ),
            public_workspace_url=_normalize_optional_text(
                os.getenv("BR_PUBLIC_WORKSPACE_URL")
                or os.getenv("NEXT_PUBLIC_WORKSPACE_URL")
            ),
            request_timeout_seconds=_float_env(
                "BR_NOTEBOOK_BRIDGE_TIMEOUT_SECONDS",
                DEFAULT_PROXY_TIMEOUT_SECONDS,
            ),
            session_ttl_seconds=_float_env(
                "BR_NOTEBOOK_BRIDGE_SESSION_TTL_SECONDS",
                DEFAULT_SESSION_TTL_SECONDS,
            ),
            session_header_name=(
                os.getenv("BR_NOTEBOOK_BRIDGE_SESSION_HEADER")
                or DEFAULT_SESSION_HEADER_NAME
            ).strip()
            or DEFAULT_SESSION_HEADER_NAME,
            session_query_param=(
                os.getenv("BR_NOTEBOOK_BRIDGE_SESSION_QUERY_PARAM")
                or DEFAULT_SESSION_QUERY_PARAM
            ).strip()
            or DEFAULT_SESSION_QUERY_PARAM,
        )

    @property
    def proxy_enabled(self) -> bool:
        return bool(
            self.enabled
            and self.mcp_http_url
            and self.mcp_transport.lower() in {"http", "streamable-http"}
        )

    @property
    def redacted_mcp_http_url(self) -> str | None:
        return _redact_url(self.mcp_http_url)


@dataclass(frozen=True)
class ProxyHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class BridgeSessionState:
    bridge_session_id: str
    created_at_epoch: float
    last_seen_at_epoch: float
    upstream_session_id: str | None = None


class BridgeSessionStore:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = max(60.0, ttl_seconds)
        self._lock = threading.Lock()
        self._sessions: dict[str, BridgeSessionState] = {}

    def _prune_locked(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_seen_at_epoch > self.ttl_seconds
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def issue(self, session_id: str | None = None) -> BridgeSessionState:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            existing = self._sessions.get(session_id or "")
            if existing is not None:
                refreshed = BridgeSessionState(
                    bridge_session_id=existing.bridge_session_id,
                    created_at_epoch=existing.created_at_epoch,
                    last_seen_at_epoch=now,
                    upstream_session_id=existing.upstream_session_id,
                )
                self._sessions[existing.bridge_session_id] = refreshed
                return refreshed

            created = BridgeSessionState(
                bridge_session_id=session_id or f"brj_{secrets.token_urlsafe(18)}",
                created_at_epoch=now,
                last_seen_at_epoch=now,
                upstream_session_id=None,
            )
            self._sessions[created.bridge_session_id] = created
            return created

    def get(self, session_id: str | None) -> BridgeSessionState | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            session = self._sessions.get(session_id)
            if session is None:
                return None
            refreshed = BridgeSessionState(
                bridge_session_id=session.bridge_session_id,
                created_at_epoch=session.created_at_epoch,
                last_seen_at_epoch=now,
                upstream_session_id=session.upstream_session_id,
            )
            self._sessions[session_id] = refreshed
            return refreshed

    def bind_upstream(
        self,
        session_id: str,
        *,
        upstream_session_id: str | None,
    ) -> BridgeSessionState | None:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            session = self._sessions.get(session_id)
            if session is None:
                return None
            bound = BridgeSessionState(
                bridge_session_id=session.bridge_session_id,
                created_at_epoch=session.created_at_epoch,
                last_seen_at_epoch=now,
                upstream_session_id=upstream_session_id or session.upstream_session_id,
            )
            self._sessions[session_id] = bound
            return bound


_SESSION_STORES: dict[tuple[float, str, str], BridgeSessionStore] = {}
_SESSION_STORES_LOCK = threading.Lock()


def get_bridge_session_store(
    settings: NotebookAssistantBridgeSettings,
) -> BridgeSessionStore:
    key = (
        settings.session_ttl_seconds,
        settings.session_header_name,
        settings.session_query_param,
    )
    with _SESSION_STORES_LOCK:
        store = _SESSION_STORES.get(key)
        if store is None:
            store = BridgeSessionStore(ttl_seconds=settings.session_ttl_seconds)
            _SESSION_STORES[key] = store
        return store


def issue_bridge_session(
    settings: NotebookAssistantBridgeSettings,
    *,
    requested_session_id: str | None = None,
) -> BridgeSessionState:
    return get_bridge_session_store(settings).issue(session_id=requested_session_id)


def build_bootstrap_payload(
    settings: NotebookAssistantBridgeSettings,
    *,
    bridge_session: BridgeSessionState | None = None,
) -> dict[str, object]:
    return {
        "product": {
            "name": settings.product_name,
            "workspace_mode": settings.workspace_mode,
        },
        "assistant": {
            "enabled": settings.enabled,
            "mode": settings.assistant_mode,
            "bridge": "jupyter-server-extension",
        },
        "mcp": {
            "mode": settings.mcp_mode,
            "transport": settings.mcp_transport,
            "proxy_enabled": settings.proxy_enabled,
            "upstream_url": settings.redacted_mcp_http_url,
        },
        "routes": {
            "health": f"{settings.api_base_path}/health",
            "bootstrap": f"{settings.api_base_path}/bootstrap",
            "mcp": f"{settings.api_base_path}/mcp",
        },
        "session": {
            "header_name": settings.session_header_name,
            "query_param": settings.session_query_param,
            "bridge_session_id": (
                bridge_session.bridge_session_id if bridge_session else None
            ),
            "upstream_session_bound": bool(
                bridge_session and bridge_session.upstream_session_id
            ),
        },
        "docs_path": settings.docs_path,
        "public_workspace_url": settings.public_workspace_url,
    }


def build_proxy_request_headers(
    request_headers: Mapping[str, str],
    settings: NotebookAssistantBridgeSettings,
    *,
    bridge_session: BridgeSessionState | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "X-Brain-Researcher-MCP-Mode": settings.mcp_mode,
        "X-Brain-Researcher-Workspace-Mode": settings.workspace_mode,
    }
    lowered = {key.lower(): value for key, value in request_headers.items()}
    for name in FORWARDED_REQUEST_HEADERS:
        value = lowered.get(name)
        if value:
            headers[name] = value
    if bridge_session and bridge_session.upstream_session_id:
        headers["mcp-session-id"] = bridge_session.upstream_session_id
    if settings.mcp_bearer_token:
        headers["Authorization"] = f"Bearer {settings.mcp_bearer_token}"
    return headers


def _json_error_response(status_code: int, message: str) -> ProxyHttpResponse:
    return ProxyHttpResponse(
        status_code=status_code,
        headers={"content-type": "application/json"},
        body=json.dumps({"ok": False, "error": message}).encode("utf-8"),
    )


async def proxy_mcp_request(
    *,
    method: str,
    request_headers: Mapping[str, str],
    body: bytes,
    settings: NotebookAssistantBridgeSettings,
    bridge_session: BridgeSessionState | None = None,
) -> ProxyHttpResponse:
    if not settings.enabled:
        return _json_error_response(503, "Notebook assistant bridge is disabled.")
    if not settings.mcp_http_url:
        return _json_error_response(503, "BR_MCP_HTTP_URL is not configured.")
    if settings.mcp_transport.lower() not in {"http", "streamable-http"}:
        return _json_error_response(
            501,
            f"Transport '{settings.mcp_transport}' is not supported by the hosted notebook bridge skeleton.",
        )

    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.request(
                method=method.upper(),
                url=settings.mcp_http_url,
                headers=build_proxy_request_headers(
                    request_headers,
                    settings,
                    bridge_session=bridge_session,
                ),
                content=body,
            )
    except httpx.HTTPError as exc:
        return _json_error_response(502, f"Upstream MCP request failed: {exc}")

    response_headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in FORWARDED_RESPONSE_HEADERS
    }
    upstream_session_id = response.headers.get("mcp-session-id")
    if bridge_session and bridge_session.bridge_session_id:
        response_headers[settings.session_header_name] = (
            bridge_session.bridge_session_id
        )
        if upstream_session_id:
            bound = get_bridge_session_store(settings).bind_upstream(
                bridge_session.bridge_session_id,
                upstream_session_id=upstream_session_id,
            )
            if bound is not None:
                bridge_session = bound
    response_headers["x-brain-researcher-upstream-session-bound"] = (
        "true" if bridge_session and bridge_session.upstream_session_id else "false"
    )
    return ProxyHttpResponse(
        status_code=response.status_code,
        headers=response_headers,
        body=response.content,
    )
