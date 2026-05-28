"""Trace + trajectory writers.

- `trace.jsonl`: append-only, crash-tolerant event stream for debugging.
- `trajectory.json`: Harbor ATIF-v1.4 trajectory for interchange/training/eval.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.ids import IdsV1
from brain_researcher.core.contracts.trajectory_atif import (
    ATIFAgent,
    ATIFFinalMetrics,
    ATIFObservation,
    ATIFObservationResult,
    ATIFStep,
    ATIFToolCall,
    ATIFTrajectory,
)

_TRACE_WRITE_LOCK = threading.Lock()


def _isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_pkg_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("brain_researcher")
    except Exception:  # pragma: no cover
        return "unknown"


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _read_last_seq(trace_path: Path) -> int | None:
    if not trace_path.exists() or not trace_path.is_file():
        return None
    try:
        with trace_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = 64 * 1024
            fh.seek(max(0, size - chunk))
            tail = fh.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    lines = [ln for ln in tail.splitlines() if ln.strip()]
    for raw in reversed(lines[-50:]):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        seq = obj.get("seq")
        if isinstance(seq, int):
            return seq
        # Back-compat for legacy trace-event-v1 lines.
        event_id = obj.get("event_id")
        parsed = _parse_int(event_id)
        if parsed is not None:
            return parsed
    return None


def _derive_ids(*, run_id: str, payload: dict[str, Any]) -> IdsV1:
    job_id = (
        payload.get("job_id") or payload.get("analysis_id") or payload.get("analysisId")
    )
    if not isinstance(job_id, str) or not job_id.strip():
        job_id = None
    session_id = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = None
    user_id = payload.get("user_id") or payload.get("userId")
    if not isinstance(user_id, str) or not user_id.strip():
        user_id = None
    trace_id = payload.get("trace_id") or payload.get("traceId")
    if not isinstance(trace_id, str) or not trace_id.strip():
        trace_id = None
    request_id = payload.get("request_id") or payload.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = None

    return IdsV1(
        job_id=job_id,
        analysis_id=job_id,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        trace_id=trace_id,
        request_id=request_id,
    )


def _append_trace_event_locked(run_dir: Path, *, event: Any) -> Path | None:
    """Append a single event line. Caller must hold _TRACE_WRITE_LOCK."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "trace.jsonl"
    try:
        dump = event.model_dump(exclude_none=True)
        line = json.dumps(dump, ensure_ascii=False)
    except Exception:
        return None

    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return path
    except Exception:
        return None


def append_trace_event(run_dir: Path, event: Any) -> Path | None:
    """Append a single AnalysisStreamEventV1 line to `run_dir/trace.jsonl`."""
    with _TRACE_WRITE_LOCK:
        return _append_trace_event_locked(run_dir, event=event)


def log_trace_event(
    run_dir: Path,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    timestamp: str | None = None,
    event_id: str | None = None,
) -> Path | None:
    """Append a best-effort typed AnalysisStreamEventV1 to `trace.jsonl`."""
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_legacy_event,
    )

    ts = timestamp or _isoformat_z(datetime.now(timezone.utc))
    safe_payload = payload if isinstance(payload, dict) else {}
    if event_id is not None:
        safe_payload.setdefault("event_id", event_id)

    with _TRACE_WRITE_LOCK:
        last = _read_last_seq(run_dir / "trace.jsonl")
        seq = int(last + 1) if last is not None else 1
        ids = _derive_ids(run_id=run_id, payload=safe_payload)
        typed = adapt_legacy_event(
            ids=ids,
            seq=seq,
            timestamp=ts,
            event_type=str(event_type),
            payload=safe_payload,
        )
        return _append_trace_event_locked(run_dir, event=typed)


def build_atif_trajectory(
    *,
    session_id: str,
    workflow_steps: list[dict[str, Any]],
    plan_steps: list[dict[str, Any]] | None = None,
    user_message: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
    model_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ATIFTrajectory:
    """Convert orchestrator workflow output into Harbor ATIF-v1.4 trajectory."""
    plan_steps = plan_steps or []
    extra = extra or {}

    step_args: dict[str, dict[str, Any]] = {}
    for raw in plan_steps:
        if not isinstance(raw, dict):
            continue
        sid = raw.get("id") or raw.get("step_id")
        if not sid:
            continue
        params = raw.get("params") or raw.get("args") or raw.get("parameters")
        if isinstance(params, dict):
            step_args[str(sid)] = params

    now = datetime.now(timezone.utc)
    steps: list[ATIFStep] = []
    next_id = 1

    if user_message:
        steps.append(
            ATIFStep(
                step_id=next_id,
                timestamp=_isoformat_z(now),
                source="user",
                message=str(user_message),
            )
        )
        next_id += 1
        now = now + timedelta(seconds=1)

    model = (
        model_name
        or os.getenv("BR_MODEL_NAME")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("MODEL_NAME")
        or "unknown"
    )

    for idx, raw in enumerate(workflow_steps):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("step_id") or raw.get("id") or f"step-{idx}")
        tool = raw.get("tool") or raw.get("tool_name") or "tool"
        args = step_args.get(sid, {})

        call_id = f"toolcall-{next_id}-0"
        tool_call = ATIFToolCall(
            tool_call_id=call_id,
            function_name=str(tool),
            arguments=args,
        )

        # Keep observation content fairly stable and human-inspectable; avoid
        # dumping giant nested payloads wholesale.
        content: dict[str, Any] = {"step_id": sid, "tool": tool}
        for key in (
            "status",
            "error",
            "result",
            "violations",
            "preflight_result",
            "exec_result",
            "postcheck_result",
            "duration_ms",
            "branch_group_id",
            "branch_rank",
            "branch_step_id",
        ):
            value = raw.get(key)
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            if isinstance(value, dict) and not value:
                continue
            content[key] = value

        steps.append(
            ATIFStep(
                step_id=next_id,
                timestamp=_isoformat_z(now),
                source="agent",
                message=f"Execute {tool}",
                model_name=model,
                tool_calls=[tool_call],
                observation=ATIFObservation(
                    results=[
                        ATIFObservationResult(
                            source_call_id=call_id,
                            content=content,
                        )
                    ]
                ),
            )
        )
        next_id += 1
        now = now + timedelta(seconds=1)

    final_metrics = ATIFFinalMetrics(total_steps=len(steps))
    return ATIFTrajectory(
        session_id=session_id,
        agent=ATIFAgent(
            name=agent_name or os.getenv("BR_AGENT_NAME", "brain_researcher"),
            version=agent_version or _get_pkg_version(),
            model_name=model,
        ),
        steps=steps,
        final_metrics=final_metrics,
        extra=extra or None,
    )


def write_trajectory_json(run_dir: Path, trajectory: ATIFTrajectory) -> Path | None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "trajectory.json"
    try:
        path.write_text(
            json.dumps(trajectory.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


__all__ = [
    "append_trace_event",
    "log_trace_event",
    "build_atif_trajectory",
    "write_trajectory_json",
]
