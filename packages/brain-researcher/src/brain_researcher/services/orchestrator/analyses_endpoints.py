"""Analysis bundle endpoints.

P0/M1 intent:
- Treat "analysis" as a first-class resource backed by JobStore runs.
- Provide a single, canonical "find everything for this run" document:
  `analysis_bundle.json` / AnalysisBundleV1.

In P0, `analysis_id == job_id` (alias) to avoid splitting the resource model
before the contracts/UI/benchmarks converge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import tempfile
import zipfile
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from brain_researcher.config.run_artifacts import get_recorder_config
from brain_researcher.core.analysis_bundle import save_analysis_bundle
from brain_researcher.services.orchestrator.observation import (
    load_or_build_observation,
    persist_observation,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])
api_router = APIRouter(prefix="/api/analyses", tags=["analyses"])

logger = logging.getLogger(__name__)


async def _resolve_share_owner_user_id(request: Request) -> str:
    from .auth_endpoints import _resolve_authenticated_user

    user, _payload = await _resolve_authenticated_user(request)
    user_id = str(getattr(user, "id", "") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user_id


def _safe_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_line(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _normalize_text(value)
        if text:
            return text
    return None


def _state_value(record: Any) -> str:
    state = getattr(record, "state", None)
    return state.value if hasattr(state, "value") else str(state)


def _build_analysis_list_item(record: Any) -> dict[str, Any]:
    payload = _safe_json_object(getattr(record, "payload_json", None))
    metadata = _safe_record(payload.get("metadata"))
    parameters = _safe_record(payload.get("parameters"))
    client_plan = _safe_record(metadata.get("client_plan_envelope"))
    plan_payload = _safe_record(payload.get("plan_of_record")) or _safe_record(
        metadata.get("plan_of_record")
    )
    dag = _safe_record(plan_payload.get("dag"))
    dag_steps = dag.get("steps") if isinstance(dag.get("steps"), list) else []
    first_step = _safe_record(dag_steps[0]) if dag_steps else {}
    step_params = _safe_record(first_step.get("params"))
    step_meta = _safe_record(first_step.get("metadata"))

    template_id = _first_text(
        client_plan.get("template_id"),
        metadata.get("template_id"),
        step_meta.get("template_id"),
    )
    analysis_preset_id = _first_text(
        client_plan.get("analysis_id"),
        step_meta.get("analysis_id"),
        step_params.get("analysis_id"),
    )
    pipeline_preset_id = _first_text(
        client_plan.get("pipeline_id"),
        step_meta.get("pipeline_id"),
        step_params.get("pipeline_id"),
    )
    dataset_id = _first_text(
        client_plan.get("dataset_id"),
        metadata.get("dataset_id"),
        parameters.get("dataset_id"),
        step_meta.get("dataset_id"),
        step_params.get("dataset_id"),
    )
    project_id = (
        _first_text(
            getattr(record, "project_id", None),
            metadata.get("project_id"),
            client_plan.get("project_id"),
        )
        or "default"
    )
    thread_id = _first_text(
        metadata.get("thread_id"),
        client_plan.get("thread_id"),
        getattr(record, "session_id", None),
    )
    title = _first_text(
        client_plan.get("intent"),
        metadata.get("title"),
        getattr(record, "job_name", None),
        _first_line(client_plan.get("prompt")),
        _first_line(payload.get("prompt")),
    )
    if title is None:
        title = f"Analysis {str(getattr(record, 'job_id', 'job'))[:8]}"

    item: dict[str, Any] = {
        "analysis_id": record.job_id,
        "job_id": record.job_id,
        "run_id": record.run_id,
        "state": _state_value(record),
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "run_dir": record.run_dir,
        "project_id": project_id,
        "thread_id": thread_id,
        "title": title,
        "has_results": bool(getattr(record, "run_dir", None)),
    }
    if dataset_id:
        item["dataset_id"] = dataset_id
        item["dataset"] = {"dataset_id": dataset_id}
    if template_id or analysis_preset_id or pipeline_preset_id:
        item["template_id"] = template_id
        item["analysis_preset_id"] = analysis_preset_id
        item["pipeline_preset_id"] = pipeline_preset_id
        item["template"] = {
            "template_id": template_id,
            "analysis_id": analysis_preset_id,
            "pipeline_id": pipeline_preset_id,
        }
    return item


def _record_matches_project(record: Any, project_id: str | None) -> bool:
    if not project_id:
        return True
    record_project = _first_text(_build_analysis_list_item(record).get("project_id")) or "default"
    if project_id == "default":
        return record_project == "default"
    return record_project == project_id


def _validate_path_security(target_path: Path, base_path: Path) -> None:
    resolved_target = target_path.resolve()
    resolved_base = base_path.resolve()
    if resolved_base not in resolved_target.parents and resolved_target != resolved_base:
        raise PermissionError(f"Path traversal detected: {target_path}")


async def _get_analysis_bundle(job_id: str, request: Request) -> dict[str, Any]:
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        raise HTTPException(status_code=503, detail="Job store not available")

    record = await job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if not record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this analysis"
        )

    run_dir = Path(record.run_dir)
    config = get_recorder_config()
    run_store_root = config.root.resolve()
    _validate_path_security(run_dir, run_store_root)

    bundle_path = run_dir / "analysis_bundle.json"
    _validate_path_security(bundle_path, run_store_root)

    def _try_read_bundle() -> dict[str, Any] | None:
        if not bundle_path.exists() or not bundle_path.is_file():
            return None
        try:
            data = json.loads(bundle_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != "analysis-bundle-v1":
            return None
        return data

    existing = _try_read_bundle()
    if existing is not None:
        return existing

    # Ensure observation exists so the bundle can embed a consistent run_card,
    # artifacts list, provenance, and checksums.
    spec = load_or_build_observation(record)
    if spec is not None:
        persist_observation(record, spec)
        # Best-effort: persist checksum-updated payload back into JobStore.
        try:
            if record.payload_json:
                await job_store.update_state(
                    job_id,
                    record.state,
                    payload_json=record.payload_json,
                )
        except Exception:
            pass

    # Best-effort: backfill analysis_bundle.json and return it.
    try:
        await asyncio.to_thread(save_analysis_bundle, record, run_dir)
    except Exception as exc:
        logger.debug("Failed to build analysis bundle for %s: %s", job_id, exc)

    built = _try_read_bundle()
    if built is None:
        raise HTTPException(status_code=404, detail="Analysis bundle not available")

    return built


@router.get("")
@api_router.get("")
async def list_analyses(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project_id: str | None = Query(None),
    include_id: str | None = Query(
        None,
        description="Ensure a specific known analysis/job id is present even when outside the current page.",
    ),
) -> dict[str, Any]:
    """List analyses from JobStore using canonical orchestrator metadata."""
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        raise HTTPException(status_code=503, detail="Job store not available")

    records = await job_store.list_all(limit=limit, offset=offset, project_id=project_id)
    include_id = (include_id or "").strip()
    if include_id and all(str(getattr(record, "job_id", "")) != include_id for record in records):
        included = await job_store.get(include_id)
        if included is not None and _record_matches_project(included, project_id):
            records.append(included)

    analyses = [_build_analysis_list_item(record) for record in records]
    return {
        "items": analyses,
        "count": len(analyses),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{analysis_id}")
@api_router.get("/{analysis_id}")
async def get_analysis_bundle(analysis_id: str, request: Request) -> dict[str, Any]:
    """Return the canonical analysis bundle (AnalysisBundleV1)."""
    return await _get_analysis_bundle(analysis_id, request)


@router.get("/{analysis_id}/events")
@api_router.get("/{analysis_id}/events")
async def get_analysis_events(
    analysis_id: str,
    request: Request,
    since: int = Query(0, ge=0, description="Return events after this event_id"),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """Return replayable event log entries for the analysis."""
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        raise HTTPException(status_code=503, detail="Job store not available")
    record = await job_store.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    events = await job_store.list_events(analysis_id, after_event_id=since, limit=limit)
    return {
        "analysis_id": analysis_id,
        "events": [
            {
                "event_id": evt.event_id,
                "type": evt.event_type,
                "ts": evt.created_at,
                "payload": evt.payload or {},
            }
            for evt in events
        ],
    }


@router.get("/{analysis_id}/stream")
@api_router.get("/{analysis_id}/stream")
async def stream_analysis_progress(
    analysis_id: str,
    request: Request,
    since: int = Query(0, ge=0, description="Resume event stream after this event_id"),
    since_event_id: int | None = Query(
        None, ge=0, description="Alias for since (resume after event_id)"
    ),
    include_initial_state: bool = Query(
        True, description="Emit an initial_state snapshot before streaming events"
    ),
):
    """Replayable SSE stream for the analysis (alias for job stream).

    In P0, `analysis_id == job_id`, so this delegates to the canonical job
    event stream backed by the append-only JobStore event log.
    """

    from brain_researcher.services.orchestrator.job_management_endpoints import (
        stream_job_progress,
    )

    return await stream_job_progress(
        job_id=analysis_id,
        request=request,
        since=since,
        since_event_id=since_event_id,
        include_initial_state=include_initial_state,
    )


class AnalysisShareLevel(str, Enum):
    SUMMARY = "summary"
    FULL = "full"


class AnalysisShareRequest(BaseModel):
    expires_in_hours: int = Field(default=24, ge=1, le=168)
    share_level: AnalysisShareLevel = AnalysisShareLevel.SUMMARY


class AnalysisShareResponse(BaseModel):
    analysis_id: str
    share_token: str
    share_level: AnalysisShareLevel
    expires_at: datetime


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


@api_router.post("/{analysis_id}/share", response_model=AnalysisShareResponse, status_code=201)
async def share_analysis(analysis_id: str, request: Request, payload: AnalysisShareRequest):
    requester_id = await _resolve_share_owner_user_id(request)

    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        raise HTTPException(status_code=503, detail="Job store not available")

    record = await job_store.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if not record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this analysis"
        )

    run_dir = Path(record.run_dir)
    config = get_recorder_config()
    run_store_root = config.root.resolve()
    _validate_path_security(run_dir, run_store_root)

    try:
        from .state_store import get_state_store

        store = await get_state_store()
    except Exception:
        store = None

    if not store:
        raise HTTPException(status_code=503, detail="state_store_not_configured")

    share_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=payload.expires_in_hours)

    try:
        await store.store_analysis_share(
            share_token=share_token,
            analysis_id=analysis_id,
            share_level=payload.share_level.value,
            expires_at=expires_at,
            created_by=requester_id,
        )
    except Exception as exc:
        logger.warning("Failed to persist analysis share token: %s", exc)
        raise HTTPException(status_code=500, detail="share_token_persist_failed") from exc

    return AnalysisShareResponse(
        analysis_id=analysis_id,
        share_token=share_token,
        share_level=payload.share_level,
        expires_at=expires_at,
    )


@api_router.get("/{analysis_id}/export", response_class=FileResponse)
async def export_analysis_bundle_zip(analysis_id: str, request: Request) -> FileResponse:
    """Export a run zip with canonical bundle files plus `.bundle_support/` install assets."""
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        raise HTTPException(status_code=503, detail="Job store not available")

    record = await job_store.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this analysis"
        )

    run_dir = Path(record.run_dir)
    config = get_recorder_config()
    run_store_root = config.root.resolve()
    _validate_path_security(run_dir, run_store_root)

    try:
        await asyncio.to_thread(save_analysis_bundle, record, run_dir)
    except Exception:
        pass

    export_dir = run_store_root / "_exports"
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="export_tmpdir_unavailable") from exc

    tmp = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f"analysis_{analysis_id}_",
        suffix=".zip",
        delete=False,
        dir=str(export_dir),
    )
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, filenames in os.walk(run_dir):
                for filename in filenames:
                    file_path = Path(root) / filename
                    if not file_path.is_file():
                        continue
                    try:
                        rel_path = file_path.relative_to(run_dir).as_posix()
                    except Exception:
                        continue
                    zf.write(file_path, arcname=rel_path)
    except Exception as exc:
        _safe_unlink(tmp_path)
        raise HTTPException(status_code=500, detail="failed_to_build_export_zip") from exc

    return FileResponse(
        path=str(tmp_path),
        filename=f"analysis_{analysis_id}.zip",
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(_safe_unlink, tmp_path),
    )


__all__ = ["router", "api_router"]
