"""FastAPI endpoints for BR-owned TaskBeacon operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain_researcher.services.orchestrator.taskbeacon_handoff import (
    default_taskbeacon_target_path,
    normalize_taskbeacon_ref,
    normalize_taskbeacon_repo,
)
from brain_researcher.services.orchestrator.taskbeacon_mcp_adapter import (
    TaskBeaconMCPError,
    async_download_taskbeacon_task,
    async_list_taskbeacon_tasks,
    async_localize_taskbeacon_task,
    async_run_taskbeacon_qa_sim,
)

router = APIRouter(prefix="/api/taskbeacon", tags=["taskbeacon"])


class TaskBeaconListEnvelope(BaseModel):
    tasks: list[dict[str, Any]]
    count: int
    source: str


class TaskBeaconDownloadRequest(BaseModel):
    repo: str = Field(..., min_length=1, max_length=500)
    project_id: str = Field(default="proj_workspace", min_length=1, max_length=200)
    target_path: str | None = Field(default=None, max_length=2000)
    ref: str | None = Field(default=None, max_length=200)
    prefer_mcp: bool = True


class TaskBeaconDownloadEnvelope(BaseModel):
    result: dict[str, Any]


class TaskBeaconLocalizeRequest(BaseModel):
    task_path: str = Field(..., min_length=1, max_length=2000)
    target_language: str = Field(..., min_length=1, max_length=100)
    voice: str | None = Field(default=None, max_length=200)


class TaskBeaconLocalizeEnvelope(BaseModel):
    result: dict[str, Any]


class TaskBeaconRunRequest(BaseModel):
    task_path: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="qa", pattern="^(qa|sim)$")
    config_path: str | None = Field(default=None, max_length=2000)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


class TaskBeaconRunEnvelope(BaseModel):
    result: dict[str, Any]


async def _require_user(request: Request) -> None:
    from ..auth_endpoints import _resolve_authenticated_user

    await _resolve_authenticated_user(request)


def _workspace_root() -> Path:
    raw = os.getenv("BR_TASKBEACON_WORKSPACE_ROOT") or os.getenv("BR_DATA_ROOT")
    if not raw:
        raise ValueError("BR_TASKBEACON_WORKSPACE_ROOT or BR_DATA_ROOT is required")
    return Path(raw).expanduser().resolve()


def _orchestrator_run_enabled() -> bool:
    raw = os.getenv("BR_TASKBEACON_ENABLE_ORCHESTRATOR_RUN", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError | TypeError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, TaskBeaconMCPError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _download_failure_detail(result: dict[str, Any]) -> str | None:
    if result.get("status") != "error":
        return None
    return str(
        result.get("stderr")
        or result.get("error")
        or result.get("mcp_error")
        or result.get("error_file")
        or "TaskBeacon download failed"
    )


@router.get("/tasks")
async def list_taskbeacon_catalog(
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=1000),
) -> TaskBeaconListEnvelope:
    await _require_user(request)
    try:
        result = await async_list_taskbeacon_tasks(query=query, limit=limit)
    except Exception as exc:
        raise _http_error(exc) from exc
    return TaskBeaconListEnvelope(
        tasks=result.get("tasks") or [],
        count=int(result.get("count") or 0),
        source=str(result.get("source") or "taskbeacon_mcp"),
    )


@router.post("/download")
async def download_taskbeacon_catalog_task(
    request: Request,
    payload: TaskBeaconDownloadRequest,
) -> TaskBeaconDownloadEnvelope:
    await _require_user(request)
    try:
        normalized_repo = normalize_taskbeacon_repo(payload.repo)
        if normalized_repo is None:
            raise ValueError("repo is required")
        normalized_ref = normalize_taskbeacon_ref(payload.ref)
        target_path = payload.target_path or default_taskbeacon_target_path(
            payload.project_id,
            normalized_repo,
        )
        result = await async_download_taskbeacon_task(
            workspace_root=_workspace_root(),
            repo=normalized_repo,
            target_path=target_path,
            ref=normalized_ref,
            prefer_mcp=payload.prefer_mcp,
        )
        failure_detail = _download_failure_detail(result)
        if failure_detail:
            raise HTTPException(status_code=502, detail=failure_detail)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise _http_error(exc) from exc
    return TaskBeaconDownloadEnvelope(result=result)


@router.post("/localize")
async def localize_taskbeacon_catalog_task(
    request: Request,
    payload: TaskBeaconLocalizeRequest,
) -> TaskBeaconLocalizeEnvelope:
    await _require_user(request)
    try:
        result = await async_localize_taskbeacon_task(
            workspace_root=_workspace_root(),
            task_path=payload.task_path,
            target_language=payload.target_language,
            voice=payload.voice,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return TaskBeaconLocalizeEnvelope(result=result)


@router.post("/run")
async def run_taskbeacon_catalog_task(
    request: Request,
    payload: TaskBeaconRunRequest,
) -> TaskBeaconRunEnvelope:
    await _require_user(request)
    if not _orchestrator_run_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "TaskBeacon QA/sim execution is disabled in the central "
                "orchestrator. Run inside the hosted marimo/runtime workspace, "
                "or set BR_TASKBEACON_ENABLE_ORCHESTRATOR_RUN=1 only on an "
                "image that includes the PsychoPy/psyflow runtime stack."
            ),
        )
    try:
        result = await async_run_taskbeacon_qa_sim(
            workspace_root=_workspace_root(),
            task_path=payload.task_path,
            mode=payload.mode,
            config_path=payload.config_path,
            timeout_seconds=payload.timeout_seconds,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return TaskBeaconRunEnvelope(result=result)
