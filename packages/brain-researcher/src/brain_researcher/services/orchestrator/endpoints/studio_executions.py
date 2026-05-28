"""FastAPI endpoints for the hosted Studio execution gateway."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..studio_execution_runtime import (
    StudioExecutionActionRequest,
    StudioExecutionKind,
    StudioExecutionRequest,
    StudioExecutionRuntime,
    StudioExecutionStatus,
)

router = APIRouter(
    prefix="/api/studio/sessions/{session_id}/executions",
    tags=["studio-executions"],
)


def _runtime_from_request(request: Request) -> StudioExecutionRuntime:
    runtime = getattr(request.app.state, "studio_execution_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="Studio execution runtime is not available"
        )
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.post("")
async def create_studio_execution(
    request: Request,
    session_id: str,
    payload: StudioExecutionRequest,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        execution = await runtime.create_execution(user.id, session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"execution": execution.model_dump(mode="json")}


@router.get("")
async def list_studio_executions(
    request: Request,
    session_id: str,
    kind: StudioExecutionKind | None = None,
    status: StudioExecutionStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    items = await runtime.list_executions(
        owner_user_id=user.id,
        session_id=session_id,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/{execution_id}")
async def get_studio_execution(
    request: Request,
    session_id: str,
    execution_id: str,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    execution = await runtime.get_execution(user.id, session_id, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Studio execution not found")
    return {"execution": execution.model_dump(mode="json")}


@router.post("/{execution_id}/actions/{action}")
async def perform_studio_execution_action(
    request: Request,
    session_id: str,
    execution_id: str,
    action: str,
    payload: StudioExecutionActionRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        return await runtime.perform_action(
            user.id, session_id, execution_id, action, payload
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio execution not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}") from exc

