"""FastAPI endpoints for the hosted Studio session gateway.

Every session-scoped endpoint in this router must return 404, not 403,
when the caller is not the session owner. That prevents leaking whether a
given opaque session id exists for another user.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..studio_session_runtime import (
    CreateStudioSessionRequest,
    StudioRuntimeProfile,
    StudioSessionActionRequest,
    StudioSessionRuntime,
    StudioSessionStatus,
    WorkspaceHandoffRequest,
)

router = APIRouter(prefix="/api/studio/sessions", tags=["studio-sessions"])


def _runtime_from_request(request: Request) -> StudioSessionRuntime:
    runtime = getattr(request.app.state, "studio_session_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="Studio session runtime is not available"
        )
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.post("")
async def create_or_attach_studio_session(
    request: Request, payload: CreateStudioSessionRequest
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.create_or_attach_session(user.id, payload)
    return {"session": session.model_dump(mode="json")}


@router.get("")
async def list_studio_sessions(
    request: Request,
    project_id: str | None = None,
    runtime_profile_id: StudioRuntimeProfile | None = None,
    status: StudioSessionStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    items = await runtime.list_sessions(
        owner_user_id=user.id,
        project_id=project_id,
        runtime_profile_id=runtime_profile_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/{session_id}")
async def get_studio_session(request: Request, session_id: str) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Studio session not found")
    return {"session": session.model_dump(mode="json")}


@router.post("/{session_id}/actions/{action}")
async def perform_studio_session_action(
    request: Request,
    session_id: str,
    action: str,
    payload: StudioSessionActionRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        return await runtime.perform_action(user.id, session_id, action, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}") from exc


@router.post("/{session_id}/workspace-handoff")
async def create_workspace_handoff(
    request: Request,
    session_id: str,
    payload: WorkspaceHandoffRequest,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        handoff = await runtime.build_workspace_handoff(user.id, session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    return {"handoff": handoff.model_dump(mode="json")}
