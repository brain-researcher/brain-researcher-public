"""FastAPI endpoints for persistent execution monitors and chat bridges."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..monitor_runtime import (
    CreateDiscordBridgeRequest,
    CreateMonitorRequest,
    CreateSlackBridgeRequest,
    MonitorActionRequest,
    MonitorRuntime,
)

router = APIRouter(prefix="/api/monitors", tags=["monitors"])
integration_router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _runtime_from_request(request: Request) -> MonitorRuntime:
    runtime = getattr(request.app.state, "monitor_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Monitor runtime is not available")
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.post("")
async def create_monitor(request: Request, payload: CreateMonitorRequest) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.create_monitor(user.id, payload)
    return {"monitor": monitor.model_dump(mode="json")}


@router.get("")
async def list_monitors(
    request: Request,
    thread_id: str | None = None,
    source_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitors = await runtime.list_monitors(
        owner_user_id=user.id,
        thread_id=thread_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return {"items": [item.model_dump(mode="json") for item in monitors]}


@router.get("/{monitor_id}")
async def get_monitor(request: Request, monitor_id: str) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.get_monitor(monitor_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"monitor": monitor.model_dump(mode="json")}


@router.get("/{monitor_id}/events")
async def get_monitor_events(
    request: Request,
    monitor_id: str,
    after_event_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.get_monitor(monitor_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    events = await runtime.list_monitor_events(
        monitor_id, after_event_id=after_event_id, limit=limit
    )
    return {"items": [event.model_dump(mode="json") for event in events]}


@router.post("/{monitor_id}/actions/{action}")
async def perform_monitor_action(
    request: Request,
    monitor_id: str,
    action: str,
    payload: MonitorActionRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.get_monitor(monitor_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return await runtime.perform_action(monitor_id, action, payload)


@router.post("/{monitor_id}/bridges/slack")
async def create_slack_bridge(
    request: Request, monitor_id: str, payload: CreateSlackBridgeRequest
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.get_monitor(monitor_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    bridge = await runtime.create_slack_bridge(monitor_id, payload)
    return {"bridge": bridge.model_dump(mode="json")}


@router.post("/{monitor_id}/bridges/discord")
async def create_discord_bridge(
    request: Request, monitor_id: str, payload: CreateDiscordBridgeRequest
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    monitor = await runtime.get_monitor(monitor_id)
    if monitor is None or monitor.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    bridge = await runtime.create_discord_bridge(monitor_id, payload)
    return {"bridge": bridge.model_dump(mode="json")}


@integration_router.post("/slack/events")
async def slack_events(request: Request) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    body = await request.body()
    return await runtime.handle_slack_events(body, dict(request.headers))


@integration_router.post("/slack/interactions")
async def slack_interactions(request: Request) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Missing Slack interaction payload")
    return await runtime.handle_slack_interaction(body, dict(request.headers))


@integration_router.post("/discord/interactions")
async def discord_interactions(request: Request) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    body = await request.body()
    return await runtime.handle_discord_interaction(body, dict(request.headers))
