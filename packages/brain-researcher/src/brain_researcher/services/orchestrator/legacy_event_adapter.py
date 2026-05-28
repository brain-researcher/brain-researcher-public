"""Legacy → typed analysis stream event adapter (T7).

This module provides a single place to map existing best-effort event logs
(`JobEvent` / `trace.jsonl`) into the canonical `AnalysisStreamEventV1` contract.

Non-scope: does not change emitters/replay endpoints directly (done in PR-2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from brain_researcher.core.contracts.analysis_stream import (
    AnalysisCompletedEventV1,
    AnalysisCompletedPayloadV1,
    AnalysisStreamEventV1,
    ArtifactWrittenEventV1,
    ArtifactWrittenPayloadV1,
    ErrorEventV1,
    ErrorPayloadV1,
    JobStartedEventV1,
    JobStartedPayloadV1,
    LogLineEventV1,
    LogLinePayloadV1,
    LogStreamV1,
    MetricEventV1,
    MetricPayloadV1,
    ObservationAppendedEventV1,
    ObservationAppendedPayloadV1,
    StageEventV1,
    StagePayloadV1,
    StageStatusV1,
    ToolCallFinishedEventV1,
    ToolCallFinishedPayloadV1,
    ToolCallStartedEventV1,
    ToolCallStartedPayloadV1,
    ToolCallStatusV1,
    UnknownEventPayloadV1,
    UnknownEventV1,
    WarningEventV1,
    WarningPayloadV1,
)
from brain_researcher.core.contracts.artifact import ArtifactKindV1, ArtifactV1
from brain_researcher.core.contracts.ids import IdsV1
from brain_researcher.core.contracts.job import JobStatusV1
from brain_researcher.core.contracts.trace_event import TraceEventV1

from .job_store import JobEvent, JobRecord


def _isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, int | float):
        try:
            return _isoformat_z(datetime.fromtimestamp(float(value), tz=timezone.utc))
        except Exception:
            return _isoformat_z(datetime.now(timezone.utc))
    return _isoformat_z(datetime.now(timezone.utc))


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


def _normalize_job_status(
    value: Any, *, default: JobStatusV1 = JobStatusV1.failed
) -> JobStatusV1:
    if value is None:
        return default
    if isinstance(value, JobStatusV1):
        return value
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        return default
    normalized = raw.strip().lower()
    if normalized in {
        "completed",
        "complete",
        "done",
        "success",
        "successful",
        "succeeded",
    }:
        return JobStatusV1.succeeded
    if normalized in {"canceled", "cancelled"}:
        return JobStatusV1.cancelled
    try:
        return JobStatusV1(normalized)
    except Exception:
        return default


def _normalize_tool_status(
    value: Any, *, default: ToolCallStatusV1 = ToolCallStatusV1.failed
) -> ToolCallStatusV1:
    if value is None:
        return default
    if isinstance(value, ToolCallStatusV1):
        return value
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        return default
    normalized = raw.strip().lower()
    if normalized in {"ok", "success", "successful", "succeeded"}:
        return ToolCallStatusV1.succeeded
    if normalized in {"cancelled", "canceled"}:
        return ToolCallStatusV1.cancelled
    try:
        return ToolCallStatusV1(normalized)
    except Exception:
        return default


def _normalize_state_changed_status(raw_event_type: str) -> JobStatusV1 | None:
    prefix = "state_changed:"
    if not raw_event_type.startswith(prefix):
        return None
    raw_status = raw_event_type[len(prefix) :].strip()
    if not raw_status:
        return JobStatusV1.pending
    if "." in raw_status:
        raw_status = raw_status.rsplit(".", 1)[-1]
    return _normalize_job_status(raw_status.lower(), default=JobStatusV1.pending)


def _stage_status_for_job_status(status: JobStatusV1) -> StageStatusV1:
    if status in {JobStatusV1.pending, JobStatusV1.queued}:
        return StageStatusV1.scheduled
    if status in {JobStatusV1.claimed, JobStatusV1.running}:
        return StageStatusV1.started
    if status == JobStatusV1.retrying:
        return StageStatusV1.retrying
    if status == JobStatusV1.succeeded:
        return StageStatusV1.completed
    if status == JobStatusV1.skipped:
        return StageStatusV1.skipped
    if status in {JobStatusV1.cancelled, JobStatusV1.timeout, JobStatusV1.failed}:
        return StageStatusV1.failed
    return StageStatusV1.warned


def _derive_tool_call_id(*, payload: dict[str, Any], seq: int) -> str:
    for key in ("tool_call_id", "toolCallId", "call_id", "callId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    step_id = payload.get("step_id") or payload.get("stepId")
    tool = payload.get("tool") or payload.get("tool_name") or payload.get("toolName")
    if isinstance(step_id, str) and step_id.strip():
        if isinstance(tool, str) and tool.strip():
            return f"{step_id}:{tool}"
        return str(step_id)
    return f"tc_{seq}"


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
    # Avoid leaking full host paths when possible.
    if "/" in raw:
        return raw.split("/")[-1]
    return raw


def _artifact_from_payload(
    *, job_id: str | None, payload: dict[str, Any], default_uri: str
) -> ArtifactV1:
    uri = (
        payload.get("uri")
        or payload.get("path")
        or payload.get("ref")
        or payload.get("provenance_path")
        or payload.get("provenancePath")
    )
    base_dir = payload.get("run_dir") or payload.get("runDir")
    coerced = _coerce_artifact_uri(uri, base_dir=base_dir) or default_uri

    kind_value = payload.get("kind")
    try:
        kind = ArtifactKindV1(str(kind_value)) if kind_value else ArtifactKindV1.json
    except Exception:
        kind = ArtifactKindV1.json

    media_type = (
        payload.get("media_type") or payload.get("mime_type") or payload.get("mime")
    )
    sha256 = payload.get("sha256") or payload.get("checksum")
    size = payload.get("bytes") or payload.get("size")
    try:
        size_int = int(size) if size is not None else None
    except Exception:
        size_int = None

    tags = payload.get("tags")
    if not isinstance(tags, list):
        tags = []
    safe_tags = [str(t) for t in tags if isinstance(t, str | int)]

    return ArtifactV1(
        job_id=job_id,
        kind=kind,
        media_type=str(media_type) if isinstance(media_type, str) else None,
        uri=str(coerced),
        sha256=str(sha256) if isinstance(sha256, str) else None,
        bytes=size_int,
        tags=safe_tags,
        metadata=(
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        ),
    )


def adapt_legacy_event(
    *,
    ids: IdsV1,
    seq: int,
    timestamp: Any,
    event_type: str,
    payload: dict[str, Any] | None,
) -> AnalysisStreamEventV1:
    """Map a legacy event_type/payload into a typed AnalysisStreamEventV1."""
    ts = _coerce_timestamp(timestamp)
    payload = payload if isinstance(payload, dict) else {}
    raw_event_type = str(event_type or "").strip()

    state_changed_status = _normalize_state_changed_status(raw_event_type)
    if state_changed_status is not None:
        if state_changed_status == JobStatusV1.running:
            return JobStartedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=JobStartedPayloadV1(
                    status=JobStatusV1.running,
                    message=(
                        payload.get("message")
                        if isinstance(payload.get("message"), str)
                        else None
                    ),
                ),
            )
        if state_changed_status in {
            JobStatusV1.succeeded,
            JobStatusV1.failed,
            JobStatusV1.cancelled,
            JobStatusV1.timeout,
            JobStatusV1.skipped,
        }:
            message = (
                payload.get("message")
                or payload.get("error")
                or payload.get("error_message")
            )
            return AnalysisCompletedEventV1(
                ids=ids,
                seq=seq,
                timestamp=ts,
                payload=AnalysisCompletedPayloadV1(
                    status=state_changed_status,
                    message=str(message) if message else None,
                ),
            )
        return StageEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=StagePayloadV1(
                stage="job",
                status=_stage_status_for_job_status(state_changed_status),
                stage_id=ids.job_id or ids.analysis_id,
                details={"job_status": state_changed_status.value, **payload},
            ),
        )

    if raw_event_type in {"job_started", "job.started"}:
        return JobStartedEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=JobStartedPayloadV1.model_validate(payload),
        )

    if raw_event_type in {"tool_started", "tool.started", "tool.call.started"}:
        try:
            started_payload = ToolCallStartedPayloadV1.model_validate(payload)
        except Exception:
            tool_id = (
                payload.get("tool_id")
                or payload.get("toolId")
                or payload.get("tool")
                or payload.get("tool_name")
                or payload.get("command")
                or "tool"
            )
            params = payload.get("params") or payload.get("parameters") or {}
            if not isinstance(params, dict):
                params = {}
            started_payload = ToolCallStartedPayloadV1(
                tool_call_id=_derive_tool_call_id(payload=payload, seq=seq),
                tool_id=str(tool_id),
                params=params,
            )
        return ToolCallStartedEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=started_payload,
        )

    if raw_event_type in {"tool_completed", "tool.finished", "tool.call.finished"}:
        try:
            finished_payload = ToolCallFinishedPayloadV1.model_validate(payload)
        except Exception:
            tool_status = _normalize_tool_status(
                payload.get("status") or payload.get("state")
            )
            error_message = payload.get("error") or payload.get("error_message")
            artifacts: list[ArtifactV1] = []
            provenance_path = payload.get("provenance_path") or payload.get(
                "provenancePath"
            )
            if isinstance(provenance_path, str) and provenance_path.strip():
                artifacts.append(
                    _artifact_from_payload(
                        job_id=ids.job_id or ids.analysis_id,
                        payload={
                            "provenance_path": provenance_path,
                            "run_dir": payload.get("run_dir") or payload.get("runDir"),
                            "kind": "json",
                            "media_type": "application/json",
                            "tags": ["provenance"],
                        },
                        default_uri="provenance.json",
                    )
                )
            finished_payload = ToolCallFinishedPayloadV1(
                tool_call_id=_derive_tool_call_id(payload=payload, seq=seq),
                status=tool_status,
                artifacts=artifacts,
                error_message=str(error_message) if error_message else None,
            )
        return ToolCallFinishedEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=finished_payload,
        )

    if raw_event_type in {"job_finalized", "analysis.completed"}:
        try:
            completed_payload = AnalysisCompletedPayloadV1.model_validate(payload)
        except Exception:
            status = _normalize_job_status(
                payload.get("state") or payload.get("status")
            )
            message = payload.get("message") or payload.get("error")
            completed_payload = AnalysisCompletedPayloadV1(
                status=status, message=str(message) if message else None
            )
        return AnalysisCompletedEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=completed_payload,
        )

    if raw_event_type == "metric":
        try:
            metric_payload = MetricPayloadV1.model_validate(payload)
        except Exception:
            metric_payload = MetricPayloadV1(
                name="metric.unknown",
                value=0.0,
                unit=None,
                tags={},
                details=payload,
            )
        return MetricEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=metric_payload,
        )

    if raw_event_type in {"retry_scheduled", "retry.scheduled"}:
        delay = payload.get("delay_seconds") or payload.get("delaySeconds") or 0
        try:
            value = float(delay)
        except Exception:
            value = 0.0
        category = payload.get("category")
        tags: dict[str, str] = {}
        if isinstance(category, str) and category:
            tags["category"] = category
        attempt = payload.get("attempt")
        if attempt is not None:
            tags["attempt"] = str(attempt)
        return MetricEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=MetricPayloadV1(
                name="retry.delay_seconds",
                value=value,
                unit="s",
                tags=tags,
                details={
                    "next_retry_at": payload.get("next_retry_at"),
                    "reason": payload.get("reason"),
                },
            ),
        )

    if raw_event_type == "stage":
        try:
            stage_payload = StagePayloadV1.model_validate(payload)
        except Exception:
            stage_payload = StagePayloadV1(
                stage="stage",
                status=StageStatusV1.started,
                details=payload,
            )
        return StageEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=stage_payload,
        )

    if raw_event_type in {
        "step_scheduled",
        "step_started",
        "step_retry",
        "step_completed",
        "plan_started",
        "plan_completed",
        "plan_failed",
        "step_preflight_completed",
        "step_postcheck_completed",
    }:
        stage = "stage"
        stage_id = (
            payload.get("step_id")
            or payload.get("stepId")
            or payload.get("plan_id")
            or payload.get("planId")
        )
        tool_id = payload.get("tool") or payload.get("tool_id") or payload.get("toolId")
        attempt = payload.get("attempt")
        duration_ms = payload.get("duration_ms")
        try:
            attempt_int = int(attempt) if attempt is not None else None
        except Exception:
            attempt_int = None
        try:
            duration_int = int(duration_ms) if duration_ms is not None else None
        except Exception:
            duration_int = None

        status = StageStatusV1.started
        message = None
        details = dict(payload)

        if raw_event_type.startswith("plan_"):
            stage = "plan"
            if raw_event_type == "plan_started":
                status = StageStatusV1.started
            elif raw_event_type == "plan_completed":
                status = StageStatusV1.completed
            else:
                status = StageStatusV1.failed
                message = payload.get("error")
        elif raw_event_type.startswith("step_preflight_"):
            stage = "preflight"
            preflight = payload.get("preflight_result")
            outcome = preflight.get("status") if isinstance(preflight, dict) else None
            if outcome == "ok":
                status = StageStatusV1.completed
            elif outcome == "warn":
                status = StageStatusV1.warned
            elif outcome == "blocked":
                status = StageStatusV1.blocked
            else:
                status = StageStatusV1.completed
        elif raw_event_type.startswith("step_postcheck_"):
            stage = "postcheck"
            postcheck = payload.get("postcheck_result")
            outcome = postcheck.get("status") if isinstance(postcheck, dict) else None
            if outcome == "ok":
                status = StageStatusV1.completed
            elif outcome == "warn":
                status = StageStatusV1.warned
            elif outcome == "blocked":
                status = StageStatusV1.blocked
            else:
                status = StageStatusV1.completed
        else:
            stage = "step"
            if raw_event_type == "step_scheduled":
                status = StageStatusV1.scheduled
            elif raw_event_type == "step_started":
                status = StageStatusV1.started
            elif raw_event_type == "step_retry":
                status = StageStatusV1.retrying
                message = payload.get("error")
            elif raw_event_type == "step_completed":
                step_status = payload.get("status")
                if isinstance(step_status, str) and step_status.lower() in {
                    "success",
                    "succeeded",
                }:
                    status = StageStatusV1.completed
                elif isinstance(step_status, str) and step_status.lower() == "skipped":
                    status = StageStatusV1.skipped
                else:
                    status = StageStatusV1.failed
                    message = payload.get("error")

        return StageEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=StagePayloadV1(
                stage=stage,
                status=status,
                stage_id=str(stage_id) if stage_id is not None else None,
                tool_id=str(tool_id) if tool_id is not None else None,
                attempt=attempt_int,
                duration_ms=duration_int,
                message=str(message) if message else None,
                details=details,
            ),
        )

    if raw_event_type == "warning":
        try:
            warning_payload = WarningPayloadV1.model_validate(payload)
        except Exception:
            warning_payload = WarningPayloadV1(
                message=str(payload.get("message") or "Warning"),
                code=payload.get("code"),
                details=payload,
            )
        return WarningEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=warning_payload,
        )

    if raw_event_type in {"tool.blocked", "plan_preflight_blocked"}:
        message = payload.get("error") or "Blocked"
        return WarningEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=WarningPayloadV1(
                message=str(message),
                code=raw_event_type,
                details=payload,
            ),
        )

    if raw_event_type in {"artifact.written", "artifact_written", "artifact_emitted"}:
        nested = payload.get("artifact")
        artifact_payload = nested if isinstance(nested, dict) else payload
        try:
            artifact = ArtifactV1.model_validate(artifact_payload)
        except Exception:
            artifact = _artifact_from_payload(
                job_id=ids.job_id or ids.analysis_id,
                payload=artifact_payload,
                default_uri="artifact",
            )
        return ArtifactWrittenEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=ArtifactWrittenPayloadV1(artifact=artifact),
        )

    if raw_event_type in {"observation.appended", "act.bundle_written"}:
        nested = payload.get("observation")
        if raw_event_type == "observation.appended" and isinstance(nested, dict):
            try:
                artifact = ArtifactV1.model_validate(nested)
            except Exception:
                artifact = _artifact_from_payload(
                    job_id=ids.job_id or ids.analysis_id,
                    payload=nested,
                    default_uri="observation.json",
                )
        else:
            artifact = _artifact_from_payload(
                job_id=ids.job_id or ids.analysis_id,
                payload={
                    "uri": "observation.json",
                    "kind": "json",
                    "media_type": "application/json",
                    "tags": ["observation"],
                },
                default_uri="observation.json",
            )
        return ObservationAppendedEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=ObservationAppendedPayloadV1(observation=artifact),
        )

    if raw_event_type in {"error", "job_error", "tool_error"}:
        return ErrorEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=ErrorPayloadV1(
                message=str(payload.get("message") or payload.get("error") or "error"),
                error_class=payload.get("error_class") or payload.get("errorClass"),
                details=(
                    payload.get("details")
                    if isinstance(payload.get("details"), dict)
                    else {}
                ),
            ),
        )

    if raw_event_type in {"log_line", "log.line"}:
        stream = payload.get("stream")
        try:
            stream_enum = LogStreamV1(str(stream))
        except Exception:
            stream_enum = LogStreamV1.stdout
        return LogLineEventV1(
            ids=ids,
            seq=seq,
            timestamp=ts,
            payload=LogLinePayloadV1(
                stream=stream_enum, line=str(payload.get("line") or "")
            ),
        )

    return UnknownEventV1(
        ids=ids,
        seq=seq,
        timestamp=ts,
        payload=UnknownEventPayloadV1(
            raw_event_type=raw_event_type or "unknown",
            raw_payload=payload,
        ),
    )


def adapt_job_event(
    evt: JobEvent,
    *,
    record: JobRecord | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AnalysisStreamEventV1:
    payload = evt.payload if isinstance(evt.payload, dict) else {}
    ids = IdsV1(
        job_id=evt.job_id,
        analysis_id=evt.job_id,
        run_id=run_id or getattr(record, "run_id", None),
        user_id=user_id or getattr(record, "user_id", None),
        session_id=session_id or getattr(record, "session_id", None),
    )
    return adapt_legacy_event(
        ids=ids,
        seq=int(evt.event_id),
        timestamp=evt.created_at,
        event_type=str(evt.event_type),
        payload=payload,
    )


def adapt_trace_event(
    event: TraceEventV1 | dict[str, Any],
    *,
    seq: int | None = None,
) -> AnalysisStreamEventV1:
    from pydantic import TypeAdapter

    # New-format trace.jsonl: already a typed AnalysisStreamEventV1 envelope.
    if (
        isinstance(event, dict)
        and event.get("schema_version") == "analysis-stream-event-v1"
    ):
        typed = TypeAdapter(AnalysisStreamEventV1).validate_python(event)
        if seq is not None and getattr(typed, "seq", None) != seq:
            try:
                return typed.model_copy(update={"seq": int(seq)})
            except Exception:
                pass
        return typed

    trace = (
        event if isinstance(event, TraceEventV1) else TraceEventV1.model_validate(event)
    )

    payload = trace.payload if isinstance(trace.payload, dict) else {}
    job_id = (
        trace.ids.job_id
        or (payload.get("job_id") if isinstance(payload.get("job_id"), str) else None)
        or (
            payload.get("analysis_id")
            if isinstance(payload.get("analysis_id"), str)
            else None
        )
    )
    if job_id is None:
        job_id = trace.run_id

    seq_value = seq
    if seq_value is None:
        seq_value = _parse_int(trace.event_id) or _parse_int(payload.get("event_id"))
    if seq_value is None:
        seq_value = 0

    ids = IdsV1(
        job_id=job_id,
        analysis_id=job_id,
        run_id=trace.run_id,
        user_id=trace.ids.user_id,
        session_id=trace.ids.session_id,
        request_id=trace.ids.request_id,
    )
    return adapt_legacy_event(
        ids=ids,
        seq=int(seq_value),
        timestamp=trace.timestamp,
        event_type=str(trace.event_type),
        payload=payload,
    )


__all__ = [
    "adapt_legacy_event",
    "adapt_job_event",
    "adapt_trace_event",
]
