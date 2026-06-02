"""Persistent MCP client for the Brain Researcher SDK.

Supports both local stdio transport and hosted streamable HTTP transport.
Provides a sync-safe public API backed by an ``asyncio`` event loop running
in a background daemon thread. The MCP connection stays alive for the
lifetime of the client.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import shutil
import threading
from concurrent.futures import Future
from typing import Any

import httpx

from brain_researcher.sdk import job_registry
from brain_researcher.sdk.models import JobHandle, RunHandle, ToolCard, ToolResult

logger = logging.getLogger(__name__)

_singleton_lock = threading.Lock()
_singleton: BRClient | None = None

_DEFAULT_SERVER_COMMAND = ["brain-researcher-mcp"]
_DEFAULT_HTTP_TIMEOUT_SECONDS = 120.0


def _normalize_optional_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def _resolve_server_command() -> list[str]:
    """Resolve the MCP server command from env or PATH."""
    env_cmd = os.environ.get("BR_MCP_SERVER_COMMAND")
    if env_cmd:
        return env_cmd.split()
    if shutil.which("brain-researcher-mcp"):
        return list(_DEFAULT_SERVER_COMMAND)
    return ["python", "-m", "brain_researcher.services.mcp.server"]


def _resolve_http_url() -> str | None:
    return _normalize_optional_text(os.environ.get("BR_MCP_HTTP_URL"))


def _resolve_http_headers() -> dict[str, str]:
    auth_header = _normalize_optional_text(os.environ.get("BR_MCP_AUTH_HEADER"))
    if auth_header:
        return {"Authorization": auth_header}

    bearer_token = _normalize_optional_text(
        os.environ.get("BR_MCP_BEARER_TOKEN") or os.environ.get("BR_MCP_TOKEN")
    )
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}

    return {}


class _LoopThread:
    """Daemon thread that owns a single ``asyncio`` event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def ensure_running(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None and self._loop.is_running():
            return self._loop
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait(timeout=10)
        assert self._loop is not None
        return self._loop

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)


class BRClient:
    """Thin sync wrapper around the Brain Researcher MCP server."""

    def __init__(
        self,
        server_command: list[str] | None = None,
        *,
        mcp_http_url: str | None = None,
        mcp_http_headers: dict[str, str] | None = None,
    ) -> None:
        self._server_command = server_command or _resolve_server_command()
        self._mcp_http_url = (
            _normalize_optional_text(mcp_http_url) or _resolve_http_url()
        )
        self._mcp_http_headers = (
            dict(mcp_http_headers)
            if mcp_http_headers is not None
            else _resolve_http_headers()
        )
        self._transport_mode = "http" if self._mcp_http_url else "stdio"
        self._loop_thread = _LoopThread()
        self._session: Any = None
        self._transport_ctx: Any = None
        self._session_ctx: Any = None
        self._http_client: httpx.AsyncClient | None = None
        self._connected = False

    def _run_async(self, coro: Any) -> Any:
        """Submit *coro* to the background loop and block until done."""
        loop = self._loop_thread.ensure_running()
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=120)

    async def _connect(self) -> None:
        from mcp import ClientSession

        if self._mcp_http_url:
            from mcp.client.streamable_http import streamable_http_client

            self._http_client = httpx.AsyncClient(
                headers=self._mcp_http_headers or None,
                timeout=_DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
            self._transport_ctx = streamable_http_client(
                self._mcp_http_url,
                http_client=self._http_client,
            )
            reader, writer, _get_session_id = await self._transport_ctx.__aenter__()
            self._session_ctx = ClientSession(reader, writer)
            self._session = await self._session_ctx.__aenter__()
            await self._session.initialize()
            self._connected = True
            logger.info("BRClient connected via HTTP %s", self._mcp_http_url)
            return

        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = os.environ.copy()
        server_params = StdioServerParameters(
            command=self._server_command[0],
            args=self._server_command[1:],
            env=env,
        )
        self._transport_ctx = stdio_client(server_params)
        reader, writer = await self._transport_ctx.__aenter__()
        self._session_ctx = ClientSession(reader, writer)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()
        self._connected = True
        logger.info("BRClient connected via %s", self._server_command)

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._run_async(self._connect())

    async def _call_tool(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Low-level MCP tool call → parsed JSON dict."""
        result = await self._session.call_tool(name, params)
        text = result.content[0].text if result.content else "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse MCP response for %s: %s", name, text[:200])
            return {"ok": False, "error": "json_decode_error", "raw": text[:500]}

    def call(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call any MCP tool exposed by the configured Brain Researcher server."""
        self._ensure_connected()
        return self._run_async(self._call_tool(name, params or {}))

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        modalities: list[str] | None = None,
        kind: str | None = None,
        phases: list[str] | None = None,
    ) -> list[ToolCard]:
        """Search for tools matching *query*. Returns a list of ``ToolCard``."""
        params: dict[str, Any] = {"query": query, "limit": limit}
        if modalities:
            params["modalities"] = modalities
        if kind:
            params["kind"] = kind
        if phases:
            params["phases"] = phases
        raw = self.call("tool_search", params)
        cards = raw.get("cards") or raw.get("tools") or []
        if isinstance(cards, list):
            return [ToolCard.from_mcp_card(c) for c in cards]
        return []

    def execute(
        self,
        tool_id: str,
        params: dict[str, Any] | None = None,
        *,
        work_dir: str | None = None,
        output_dir: str | None = None,
        force: bool = False,
    ) -> ToolResult | JobHandle:
        """Execute a tool. Returns cached result on duplicate ``(tool_id, params)``.

        Pass ``force=True`` to bypass the job registry and re-execute.
        """
        params = params or {}
        content_hash = JobHandle.compute_content_hash(tool_id, params)

        if not force:
            cached = job_registry.get(content_hash)
            if cached is not None:
                logger.debug(
                    "execute: returning cached result for %s", content_hash[:12]
                )
                return cached

        call_params: dict[str, Any] = {"tool_id": tool_id, "params": params}
        if work_dir:
            call_params["work_dir"] = work_dir
        if output_dir:
            call_params["output_dir"] = output_dir

        raw = self.call("tool_execute", call_params)
        result = ToolResult.from_mcp_response(raw)
        job_registry.put(content_hash, result)
        return result

    def recipe(
        self,
        tool_id: str,
        params: dict[str, Any] | None = None,
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Return an execution recipe without running the tool."""
        call_params: dict[str, Any] = {
            "tool_id": tool_id,
            "params": params or {},
        }
        if target:
            call_params["target_runtime"] = target
        return self.call("get_execution_recipe", call_params)

    def server_info(self) -> dict[str, Any]:
        """Return MCP server metadata."""
        return self.call("server_info", {})

    def attach_run(self, run_id: str) -> RunHandle:
        """Attach to a run created elsewhere (Studio, external agent, …).

        Calls ``run_bundle_get`` under the hood and wraps the result in a
        :class:`RunHandle`. Use ``handle.refresh()`` / ``handle.wait()`` to
        track status from inside a notebook.
        """
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        normalized = run_id.strip()
        payload = self.call("run_bundle_get", {"run_id": normalized})
        return RunHandle.from_mcp_response(normalized, payload, client=self)

    def close(self) -> None:
        """Shut down the MCP transport and background loop."""
        if not self._connected:
            return

        async def _teardown() -> None:
            try:
                if self._session_ctx:
                    await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                if self._transport_ctx:
                    await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                if self._http_client is not None:
                    await self._http_client.aclose()
            except Exception:
                pass

        try:
            self._run_async(_teardown())
        except Exception:
            pass
        self._loop_thread.stop()
        self._connected = False
        logger.info("BRClient closed")

    def __enter__(self) -> BRClient:
        self._ensure_connected()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def connect(
    server_command: list[str] | None = None,
    *,
    mcp_http_url: str | None = None,
    mcp_http_headers: dict[str, str] | None = None,
) -> BRClient:
    """Return (and lazily create) the module-level ``BRClient`` singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = BRClient(
                server_command=server_command,
                mcp_http_url=mcp_http_url,
                mcp_http_headers=mcp_http_headers,
            )
            atexit.register(_singleton.close)
        return _singleton
