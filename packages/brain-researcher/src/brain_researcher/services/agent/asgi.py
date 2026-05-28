"""
ASGI entrypoint for the Agent service with WebSocket support.

This wraps the existing Flask HTTP app with Starlette's WSGIMiddleware and
adds a `/ws` WebSocket endpoint that replays the existing SSE event stream
(`api/analyses/{id}/events`) to WS clients. This keeps the HTTP surface intact
while enabling real-time WS updates for the web UI.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from starlette.middleware.wsgi import WSGIMiddleware

from .web_service import app as flask_app


def _default_sse_base() -> str:
    """Best-effort local base URL for the SSE stream.

    When run via `br serve agent` the agent may not be on 8000, so prefer the
    env vars already used across launchers (AGENT_PORT/PORT + HOST).
    """

    port = os.getenv("AGENT_PORT") or os.getenv("PORT") or "8000"
    host = (os.getenv("HOST") or "127.0.0.1").strip()
    # 0.0.0.0 is a bind address, not a connectable one.
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    scheme = (os.getenv("AGENT_HTTP_SCHEME") or "http").strip()
    return f"{scheme}://{host}:{port}"


# Base URL the shim will use to pull the SSE stream. Override if the HTTP
# surface is fronted by a separate reverse proxy.
SSE_BASE = (os.getenv("AGENT_HTTP_BASE") or _default_sse_base()).rstrip("/")

asgi_app = FastAPI(title="Brain Researcher Agent (ASGI + WS)")


def _build_sse_url(execution_id: str) -> str:
    # Existing UI uses /api/analyses/{id}/events for live job events.
    return f"{SSE_BASE}/api/analyses/{execution_id}/events"


@asgi_app.websocket("/ws")
async def websocket_bridge(
    ws: WebSocket,
    job_id: Optional[str] = Query(default=None, alias="job_id"),
    analysis_id: Optional[str] = Query(default=None, alias="analysis_id"),
):
    """
    Bridge SSE -> WebSocket.

    Client connect examples:
      ws://host:8000/ws?analysis_id=123
      ws://host:8000/ws?job_id=123
    """
    target_id = analysis_id or job_id
    if not target_id:
        await ws.accept()
        await ws.send_json({"error": "missing job_id or analysis_id"})
        await ws.close(code=4400)
        return

    await ws.accept()

    # Forward auth/cookies from the WS handshake to the SSE request.
    forward_headers = {}
    auth = ws.headers.get("authorization")
    if auth:
        forward_headers["authorization"] = auth
    cookie = ws.headers.get("cookie")
    if cookie:
        forward_headers["cookie"] = cookie

    sse_url = _build_sse_url(target_id)

    try:
        async with httpx.AsyncClient(timeout=None, headers=forward_headers) as client:
            async with client.stream("GET", sse_url) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    # SSE format: lines starting with "data: ..."
                    if line.startswith("data: "):
                        payload = line[6:]
                        try:
                            await ws.send_json(json.loads(payload))
                        except Exception:
                            await ws.send_text(payload)
    except WebSocketDisconnect:
        # Normal client disconnect
        return
    except Exception as exc:  # pragma: no cover - network/runtime errors
        try:
            await ws.send_json({"error": str(exc)})
        finally:
            await ws.close(code=1011)


# Mount last so the WSGI catch-all does not swallow `/ws`.
asgi_app.mount("/", WSGIMiddleware(flask_app))


# Convenience export for uvicorn: `uvicorn brain_researcher.services.agent.asgi:asgi_app`
app = asgi_app
