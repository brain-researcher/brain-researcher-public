"""FastAPI endpoints for the hosted Studio assistant gateway."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..studio_assistant_runtime import (
    StudioAssistantRuntime,
    StudioAssistantTurnRequest,
)

router = APIRouter(
    prefix="/api/studio/sessions/{session_id}/assistant",
    tags=["studio-assistant"],
)


def _runtime_from_request(request: Request) -> StudioAssistantRuntime:
    runtime = getattr(request.app.state, "studio_assistant_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="Studio assistant runtime is not available"
        )
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.get("")
async def get_studio_assistant_state(
    request: Request,
    session_id: str,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        state = await runtime.get_thread_state(user.id, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    return state.model_dump(mode="json", by_alias=True)


@router.post("/turns")
async def submit_studio_assistant_turn(
    request: Request,
    session_id: str,
    payload: StudioAssistantTurnRequest,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        result = await runtime.submit_turn(user.id, session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result.model_dump(mode="json", by_alias=True)
