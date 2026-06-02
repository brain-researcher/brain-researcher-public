"""Helpers for pipeline graph snapshots (HTTP + WS)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import Job, StepStatus


def _map_step_status(status: Optional[StepStatus | str]) -> str:
    if status is None:
        return "pending"
    raw = status.value if isinstance(status, StepStatus) else str(status)
    normalized = raw.lower()
    if normalized in {"pending", "queued"}:
        return "pending"
    if normalized in {"running", "retrying"}:
        return "running"
    if normalized in {"completed", "succeeded"}:
        return "completed"
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"paused"}:
        return "paused"
    if normalized in {"skipped"}:
        return "skipped"
    return "pending"


def _get_job_timing(job: Any) -> Tuple[Optional[datetime], Optional[datetime]]:
    timing = getattr(job, "timing", None)
    started_at = getattr(timing, "start_time", None) if timing else None
    ended_at = getattr(timing, "end_time", None) if timing else None
    if started_at is None:
        started_at = getattr(job, "started_at", None) or getattr(
            job, "created_at", None
        )
    if ended_at is None:
        ended_at = getattr(job, "completed_at", None) or getattr(
            job, "finished_at", None
        )
    return started_at, ended_at


def _get_step_timing(
    step: Any,
) -> Tuple[Optional[datetime], Optional[datetime], Optional[int]]:
    timing = getattr(step, "timing", None)
    started_at = getattr(timing, "start_time", None) if timing else None
    ended_at = getattr(timing, "end_time", None) if timing else None
    duration_ms = getattr(timing, "duration_ms", None) if timing else None

    if started_at is None:
        started_at = getattr(step, "start_time", None)
    if ended_at is None:
        ended_at = getattr(step, "end_time", None)
    if duration_ms is None and started_at and ended_at:
        try:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        except Exception:
            duration_ms = None

    return started_at, ended_at, duration_ms


def _get_step_dependencies(step: Any) -> List[str]:
    depends_on = getattr(step, "depends_on", None)
    if isinstance(depends_on, (list, tuple)):
        return [str(dep) for dep in depends_on if dep]
    return []


def build_job_graph_snapshot(
    job: Optional[Job], *, job_id: Optional[str] = None
) -> Dict[str, Any]:
    resolved_job_id = job_id or (job.id if job else "unknown")
    generated_at = datetime.utcnow().isoformat()

    if not job:
        return {
            "schema_version": "1.0",
            "job_id": resolved_job_id,
            "stream_id": f"job:{resolved_job_id}",
            "plan": {"plan_id": None, "version": 1},
            "owner": {"user_id": None, "tenant_id": None},
            "generated_at": generated_at,
            "checkpoint_id": 0,
            "nodes": [],
            "edges": [],
        }

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    previous_id: Optional[str] = None
    dependency_edges: List[Tuple[str, str]] = []

    for step in job.steps:
        step_id = (
            getattr(step, "id", None) or getattr(step, "step_id", None) or "unknown"
        )
        node_id = f"step:{step_id}"
        started_at, ended_at, duration_ms = _get_step_timing(step)
        progress = getattr(step, "progress", None)
        error_message = getattr(step, "error", None)
        meta_tool = getattr(step, "tool", None)
        if meta_tool is None:
            meta_tool = getattr(step, "name", None)

        nodes.append(
            {
                "id": node_id,
                "kind": "step",
                "type": "process",
                "label": getattr(step, "name", None)
                or getattr(step, "tool", None)
                or str(step_id),
                "status": _map_step_status(step.status),
                "progress": progress if isinstance(progress, (int, float)) else None,
                "timing": {
                    "created_at": None,
                    "started_at": started_at.isoformat() if started_at else None,
                    "ended_at": ended_at.isoformat() if ended_at else None,
                    "duration_ms": duration_ms,
                },
                "resources": {},
                "error": (
                    {"code": None, "message": error_message}
                    if error_message
                    else {"code": None, "message": None}
                ),
                "meta": {"tool": meta_tool} if meta_tool else {},
            }
        )
        depends_on = _get_step_dependencies(step)
        if depends_on:
            for dep in depends_on:
                dependency_edges.append((f"step:{dep}", node_id))
        else:
            if previous_id:
                edges.append(
                    {
                        "id": f"{previous_id}->{node_id}",
                        "source": previous_id,
                        "target": node_id,
                        "kind": "depends_on",
                    }
                )
        previous_id = node_id

    # Add explicit dependency edges if provided.
    for source_id, target_id in dependency_edges:
        edges.append(
            {
                "id": f"{source_id}->{target_id}",
                "source": source_id,
                "target": target_id,
                "kind": "depends_on",
            }
        )

    stream_id = job.run_id or f"job:{resolved_job_id}"
    plan_of_record = job.plan_of_record or {}
    return {
        "schema_version": "1.0",
        "job_id": resolved_job_id,
        "stream_id": stream_id,
        "plan": {
            "plan_id": plan_of_record.get("plan_id"),
            "version": plan_of_record.get("version", 1),
        },
        "owner": {"user_id": job.user_id, "tenant_id": None},
        "generated_at": generated_at,
        "checkpoint_id": 0,
        "nodes": nodes,
        "edges": edges,
    }
