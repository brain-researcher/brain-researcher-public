"""FastAPI endpoints for the remote session wrapper surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..monitor_runtime import CreateSlackBridgeRequest
from ..session_runtime import (
    CreateSessionRequest,
    SessionActionRequest,
    SessionKind,
    SessionRuntime,
)
from .monitor import integration_router as monitor_integration_router

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
integration_router = monitor_integration_router


def _runtime_from_request(request: Request) -> SessionRuntime:
    runtime = getattr(request.app.state, "session_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Session runtime is not available")
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.post("")
@router.post("/attach")
async def create_session(
    request: Request, payload: CreateSessionRequest
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.create_session(user.id, payload)
    return {"session": session.model_dump(mode="json")}


@router.get("")
async def list_sessions(
    request: Request,
    kind: SessionKind | None = None,
    thread_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    sessions = await runtime.list_sessions(
        owner_user_id=user.id,
        kind=kind,
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )
    return {"items": [item.model_dump(mode="json") for item in sessions]}


@router.get("/{session_id}")
async def get_session(request: Request, session_id: str) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    monitor = await runtime._monitor_runtime.get_monitor(session_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.model_dump(mode="json")}


@router.get("/{session_id}/events")
async def get_session_events(
    request: Request,
    session_id: str,
    after_event_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime._monitor_runtime.get_monitor(session_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    events = await runtime.list_session_events(
        session_id, after_event_id=after_event_id, limit=limit
    )
    return {"items": [event.model_dump(mode="json") for event in events]}


@router.post("/{session_id}/actions/{action}")
async def perform_session_action(
    request: Request,
    session_id: str,
    action: str,
    payload: SessionActionRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime._monitor_runtime.get_monitor(session_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return await runtime.perform_action(session_id, action, payload)


@router.post("/{session_id}/bridges/slack")
async def create_slack_bridge(
    request: Request, session_id: str, payload: CreateSlackBridgeRequest
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime._monitor_runtime.get_monitor(session_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    bridge = await runtime.create_slack_bridge(session_id, payload)
    return {"bridge": bridge.model_dump(mode="json")}
