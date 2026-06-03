"""Helpers for producing a closed-loop run bundle (P0).

Writes (best-effort) run-level files into a single `run_dir`:
  - trace.jsonl (append-only AnalysisStreamEventV1 events)
  - trajectory.json (ATIF-v1.4)
  - observation.json (ObservationSpecV1)
  - analysis_bundle.json (AnalysisBundleV1)

The bundle is designed for replay/benchmark/export consumers.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts import (
    AnalysisCompletedEventV1,
    AnalysisCompletedPayloadV1,
    AnalysisStreamEventV1,
    ArtifactKindV1,
    ArtifactV1,
    ATIFAgent,
    ATIFObservation,
    ATIFObservationResult,
    ATIFStep,
    ATIFToolCall,
    ATIFTrajectory,
    IdsV1,
    JobStartedEventV1,
    JobStartedPayloadV1,
    ObservationAppendedEventV1,
    ObservationAppendedPayloadV1,
    ToolCallFinishedEventV1,
    ToolCallFinishedPayloadV1,
    ToolCallStartedEventV1,
    ToolCallStartedPayloadV1,
    ToolCallStatusV1,
)
from brain_researcher.core.contracts.analysis_stream import (
    UnknownEventPayloadV1,
    UnknownEventV1,
    WarningEventV1,
    WarningPayloadV1,
)
from brain_researcher.core.contracts.job import JobStatusV1
from brain_researcher.core.run_bundle_persistence import (
    persist_agent_analysis_bundle,
    persist_agent_observation,
)
from brain_researcher.services.agent.telemetry import utc_now

_TRACE_WRITE_LOCK = threading.Lock()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


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
        # Back-compat for any historical trace-event-v1.
        event_id = obj.get("event_id")
        parsed = _parse_int(event_id)
        if parsed is not None:
            return parsed
    return None


def _coerce_artifact_uri(uri: Any, *, base_dir: Any = None) -> str | None:
    if not isinstance(uri, str) or not uri.strip():
        return None
    raw = uri.strip()
    if base_dir:
        try:
            base = str(base_dir)
            if base and raw.startswith(base.rstrip("/") + "/"):
                return raw[len(base.rstrip("/") + "/") :]
        except Exception:
            pass
    if "/" in raw:
        return raw.split("/")[-1]
    return raw


def _normalize_tool_status(value: Any) -> ToolCallStatusV1:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        return ToolCallStatusV1.failed
    normalized = raw.strip().lower()
    if normalized in {"ok", "success", "successful", "succeeded"}:
        return ToolCallStatusV1.succeeded
    if normalized in {"cancelled", "canceled"}:
        return ToolCallStatusV1.cancelled
    if normalized == "timeout":
        return ToolCallStatusV1.timeout
    if normalized in {"partial"}:
        return ToolCallStatusV1.partial
    return ToolCallStatusV1.failed


def _normalize_job_status(value: Any) -> JobStatusV1:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        return JobStatusV1.failed
    normalized = raw.strip().lower()
    if normalized in {"ok", "success", "successful", "succeeded", "done", "completed"}:
        return JobStatusV1.succeeded
    if normalized in {"cancelled", "canceled"}:
        return JobStatusV1.cancelled
    if normalized == "timeout":
        return JobStatusV1.timeout
    try:
        return JobStatusV1(normalized)
    except Exception:
        return JobStatusV1.failed


def _derive_ids(*, run_id: str, payload: dict[str, Any]) -> IdsV1:
    job_id = (
        payload.get("job_id") or payload.get("analysis_id") or payload.get("analysisId")
    )
    if not isinstance(job_id, str) or not job_id.strip():
        job_id = None
    session_id = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = None
    trace_id = payload.get("trace_id") or payload.get("traceId")
    if not isinstance(trace_id, str) or not trace_id.strip():
        trace_id = None

    return IdsV1(
        job_id=job_id,
        analysis_id=job_id,
        run_id=(
            payload.get("run_id") if isinstance(payload.get("run_id"), str) else run_id
        ),
        session_id=session_id,
        trace_id=trace_id,
    )


def _append_event_locked(run_dir: Path, *, event: Any) -> Path:
    path = run_dir / "trace.jsonl"
    try:
        line = json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False)
    except Exception:
        line = json.dumps(
            UnknownEventV1(
                ids=IdsV1(run_id=str(run_dir)),
                seq=0,
                timestamp=utc_now(),
                payload=UnknownEventPayloadV1(
                    raw_event_type="serialize_error", raw_payload={}
                ),
            ).model_dump(exclude_none=True),
            ensure_ascii=False,
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")
    return path


def log_trace_event(
    run_dir: Path,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> Path:
    """Append a best-effort typed AnalysisStreamEventV1 line to trace.jsonl."""

    run_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_now()
    safe_payload = payload if isinstance(payload, dict) else {}

    with _TRACE_WRITE_LOCK:
        last = _read_last_seq(run_dir / "trace.jsonl")
        seq = int(last + 1) if last is not None else 1

        ids = _derive_ids(run_id=run_id, payload=safe_payload)
        raw_type = str(event_type or "").strip()

        typed: AnalysisStreamEventV1
        if raw_type in {"agent.run.started", "tool.started", "tool_started"}:
            if raw_type == "agent.run.started":
                typed = JobStartedEventV1(
                    ids=ids,
                    seq=seq,
                    timestamp=ts,
                    payload=JobStartedPayloadV1(
                        status=JobStatusV1.running,
                        message="Agent async run started",
                    ),
                )
                return _append_event_locked(run_dir, event=typed)

        if raw_type in {"agent.step.started", "tool.started", "tool_started"}:
            tool_call_id = safe_payload.get("tool_call_id") or safe_payload.get(
                "toolCallId"
            )
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                tool_call_id = f"tc_{seq}"
            tool_id = (
                safe_payload.get("tool_id")
                or safe_payload.get("toolId")
                or safe_payload.get("tool")
                or "tool"
            )
            typed = ToolCallStartedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=ToolCallStartedPayloadV1(
                    tool_call_id=str(tool_call_id),
                    tool_id=str(tool_id),
                    params={},
                ),
            )
        elif raw_type in {"agent.step.finished", "tool.finished", "tool_completed"}:
            tool_call_id = safe_payload.get("tool_call_id") or safe_payload.get(
                "toolCallId"
            )
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                tool_call_id = f"tc_{seq}"
            tool_id = (
                safe_payload.get("tool_id")
                or safe_payload.get("toolId")
                or safe_payload.get("tool")
                or "tool"
            )
            status = _normalize_tool_status(
                safe_payload.get("status") or safe_payload.get("state")
            )

            artifacts: list[ArtifactV1] = []
            provenance_path = safe_payload.get("provenance_path") or safe_payload.get(
                "provenancePath"
            )
            if isinstance(provenance_path, str) and provenance_path.strip():
                uri = _coerce_artifact_uri(
                    provenance_path,
                    base_dir=safe_payload.get("run_dir") or safe_payload.get("runDir"),
                )
                artifacts.append(
                    ArtifactV1(
                        job_id=ids.job_id,
                        kind=ArtifactKindV1.json,
                        media_type="application/json",
                        uri=uri or "provenance.json",
                        tags=["provenance"],
                    )
                )

            typed = ToolCallFinishedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=ToolCallFinishedPayloadV1(
                    tool_call_id=str(tool_call_id),
                    status=status,
                    artifacts=artifacts,
                    error_message=(
                        None if status == ToolCallStatusV1.succeeded else "tool_failed"
                    ),
                ),
            )
        elif raw_type in {"agent.run.finished"}:
            status = _normalize_job_status(
                safe_payload.get("status") or safe_payload.get("state")
            )
            message = safe_payload.get("error") or safe_payload.get("message")
            typed = AnalysisCompletedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=AnalysisCompletedPayloadV1(
                    status=status,
                    message=str(message) if message else None,
                ),
            )
        elif raw_type in {"tool.blocked"}:
            typed = WarningEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=WarningPayloadV1(
                    message="Blocked",
                    code=raw_type,
                    details=safe_payload,
                ),
            )
        elif raw_type in {"act.bundle_written", "observation.appended"}:
            typed = ObservationAppendedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=ObservationAppendedPayloadV1(
                    observation=ArtifactV1(
                        job_id=ids.job_id,
                        kind=ArtifactKindV1.json,
                        media_type="application/json",
                        uri="observation.json",
                        tags=["observation"],
                    )
                ),
            )
        else:
            typed = UnknownEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=UnknownEventPayloadV1(
                    raw_event_type=raw_type or "unknown",
                    raw_payload=safe_payload,
                ),
            )

        return _append_event_locked(run_dir, event=typed)


def persist_agent_trajectory(
    run_dir: Path,
    *,
    session_id: str,
    model_name: str,
    user_message: str,
    agent_message: str,
    tool_calls: list[dict[str, Any]],
    started_at_iso: str | None = None,
    finished_at_iso: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ATIF-v1.4 trajectory.json (best-effort)."""

    ts = finished_at_iso or utc_now()
    user_ts = started_at_iso or ts

    steps: list[ATIFStep] = [
        ATIFStep(step_id=1, timestamp=user_ts, source="user", message=user_message),
    ]

    atif_tool_calls: list[ATIFToolCall] = []
    obs_results: list[ATIFObservationResult] = []
    for call in tool_calls:
        tool_call_id = str(call.get("tool_call_id") or call.get("id") or "")
        function_name = str(call.get("name") or call.get("tool") or "")
        atif_tool_calls.append(
            ATIFToolCall(
                tool_call_id=tool_call_id,
                function_name=function_name,
                arguments=call.get("arguments") or {},
                extra={
                    "status": call.get("status"),
                    "run_dir": call.get("run_dir"),
                    "provenance_path": call.get("provenance_path"),
                },
            )
        )
        obs_results.append(
            ATIFObservationResult(
                source_call_id=tool_call_id,
                content={
                    "status": call.get("status"),
                    "result": call.get("result"),
                    "error": call.get("error"),
                    "error_category": call.get("error_category"),
                    "recovery_suggestions": call.get("recovery_suggestions") or [],
                },
                extra={
                    "run_dir": call.get("run_dir"),
                },
            )
        )

    steps.append(
        ATIFStep(
            step_id=2,
            timestamp=ts,
            source="agent",
            message=agent_message,
            model_name=model_name,
            tool_calls=atif_tool_calls or None,
            observation=ATIFObservation(results=obs_results) if obs_results else None,
            extra=extra,
        )
    )

    trajectory = ATIFTrajectory(
        session_id=session_id,
        agent=ATIFAgent(
            name="brain-researcher-agent",
            version="0",
            model_name=model_name,
        ),
        steps=steps,
        extra=extra,
    )

    path = run_dir / "trajectory.json"
    _atomic_write_json(path, trajectory.to_json_dict())
    return path



__all__ = [
    "log_trace_event",
    "persist_agent_analysis_bundle",
    "persist_agent_observation",
    "persist_agent_trajectory",
]
