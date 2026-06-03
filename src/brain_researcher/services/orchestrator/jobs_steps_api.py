"""
Step summary API.

Exposes GET /api/jobs/{job_id}/steps which loads the parent job's
provenance.json file and returns any recorded child step summaries.
Also exposes /api/jobs/{job_id}/steps/stream for real-time SSE updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from brain_researcher.core.contracts import Violation
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["job-steps"])


class StepSummary(BaseModel):
    """Shape of an individual step summary returned to clients.

    PR-4: Extended with timestamps, retry tracking, and cache metadata.
    """

    step_id: str
    name: str | None = None
    state: str

    # Timestamps (PR-4)
    created_at: int | None = None  # Unix timestamp in seconds
    started_at: int | None = None  # Unix timestamp in seconds
    finished_at: int | None = None  # Unix timestamp in seconds

    # Retry tracking (PR-4)
    attempt: int = 1
    max_attempts: int = 3
    retry_reason: str | None = None

    # Cache tracking (PR-4)
    cache_marker: str | None = None  # 'hit', 'miss', 'skip', 'disabled'
    cache_key: str | None = None

    # Existing fields
    execution_time_ms: int | None = None
    run_dir: str | None = None
    error: str | None = None

    # Provenance (PR-4)
    provenance_path: str | None = None

    # QC/Violation data
    violations: list[Violation] | None = None

    # Phase results (preflight/execute/postcheck)
    preflight_result: dict | None = None
    exec_result: dict | None = None
    postcheck_result: dict | None = None


class JobStepsResponse(BaseModel):
    """Envelope returned by GET /api/jobs/{job_id}/steps."""

    job_id: str
    state: str
    steps: list[StepSummary]
    cache_key: str | None = None
    cache_hit: bool | None = None


@router.get("/{job_id}/steps", response_model=JobStepsResponse)
async def get_job_steps(job_id: str, request: Request) -> JobStepsResponse:
    """
    Return child step summaries for the specified job.

    A 404 is raised when the job does not exist.  If provenance data is not yet
    available (e.g. while the job is still running), an empty list is returned.
    """

    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        logger.error("Job store not configured on application state")
        raise HTTPException(status_code=503, detail="Job store not available")

    job: JobRecord | None = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    cache_key, cache_hit = _extract_cache_metadata(job)
    provenance_path = _resolve_provenance_path(job)
    if provenance_path is None:
        logger.debug(
            "Job %s does not have a provenance path yet (state=%s)",
            job_id,
            job.state,
        )
        return JobStepsResponse(
            job_id=job.job_id,
            state=job.state,
            steps=_extract_payload_step_summaries(job),
            cache_key=cache_key,
            cache_hit=cache_hit,
        )

    if not provenance_path.exists():
        # When the job is still running it is expected that the provenance
        # document is not written yet.  In that case, prefer returning an empty
        # list instead of an error so the UI can poll until data arrives.
        if job.state not in _TERMINAL_STATES:
            logger.debug(
                "Provenance for job %s not found yet at %s (state=%s)",
                job_id,
                provenance_path,
                job.state,
            )
            return JobStepsResponse(
                job_id=job.job_id,
                state=job.state,
                steps=_extract_payload_step_summaries(job),
                cache_key=cache_key,
                cache_hit=cache_hit,
            )

        logger.warning(
            "Expected provenance for terminal job %s but file missing at %s",
            job_id,
            provenance_path,
        )
        return JobStepsResponse(
            job_id=job.job_id,
            state=job.state,
            steps=_extract_payload_step_summaries(job),
            cache_key=cache_key,
            cache_hit=cache_hit,
        )

    try:
        with provenance_path.open("r", encoding="utf-8") as fh:
            provenance = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse provenance JSON for job %s at %s: %s",
            job_id,
            provenance_path,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Malformed provenance document for job",
        ) from exc
    except OSError as exc:
        logger.error(
            "Error reading provenance for job %s at %s: %s",
            job_id,
            provenance_path,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to read job provenance",
        ) from exc

    steps_payload = provenance.get("child_runs")
    if not isinstance(steps_payload, Iterable):
        steps_payload = provenance.get("steps", [])

    summaries = [
        _build_step_summary(raw, index) for index, raw in enumerate(steps_payload or [])
    ]
    summaries = _coerce_terminal_failure_summaries(job, summaries)

    return JobStepsResponse(
        job_id=job.job_id,
        state=job.state,
        steps=summaries,
        cache_key=cache_key,
        cache_hit=cache_hit,
    )


def _resolve_provenance_path(job: JobRecord) -> Path | None:
    """
    Determine the absolute path to provenance.json for a job.

    Supports three cases:
    1. provenance_path is absolute.
    2. provenance_path is relative to run_dir.
    3. provenance_path is missing → default to run_dir / 'provenance.json'.
    """

    run_dir = Path(job.run_dir) if job.run_dir else None
    if job.provenance_path:
        candidate = Path(job.provenance_path)
        if candidate.is_absolute():
            return candidate
        if run_dir is not None:
            return run_dir / candidate

    if run_dir is not None:
        return run_dir / "provenance.json"

    return None


def _extract_cache_metadata(job: JobRecord) -> tuple[str | None, bool | None]:
    """Retrieve cache metadata stored on the job payload."""
    try:
        payload = json.loads(job.payload_json or "{}")
    except json.JSONDecodeError:
        return None, None

    metadata = payload.get("metadata", {}) or {}
    cache_meta = metadata.get("cache", {}) or {}
    cache_key = metadata.get("cache_key") or cache_meta.get("key")
    cache_hit = cache_meta.get("hit")
    return cache_key, cache_hit


def _safe_payload(job: JobRecord) -> dict[str, Any]:
    try:
        payload = json.loads(job.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _job_state_text(job: JobRecord) -> str:
    state = getattr(job, "state", "")
    return str(getattr(state, "value", state) or "").strip().lower()


def _string_error(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("message", "detail", "error", "reason"):
            nested = _string_error(value.get(key))
            if nested:
                return nested
        return ""
    return str(value).strip()


def _job_failure_message(job: JobRecord, payload: dict[str, Any]) -> str:
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    for value in (
        getattr(job, "error_message", None),
        payload.get("error_message"),
        payload.get("error"),
        payload.get("detail"),
        metadata.get("error_message"),
        metadata.get("error"),
    ):
        message = _string_error(value)
        if message:
            return message
    state = _job_state_text(job)
    if state == JobState.TIMEOUT.value:
        return "Job timed out before step logs were captured."
    return "Job failed before step logs were captured."


def _is_pending_like_step(step: StepSummary) -> bool:
    return (
        str(step.state or "").strip().lower()
        in {"", "pending", "queued", "claimed", "unknown"}
        and not step.started_at
        and not step.run_dir
        and not step.error
    )


def _job_level_failure_step(job: JobRecord, payload: dict[str, Any]) -> StepSummary:
    state = _job_state_text(job)
    step_state = (
        state
        if state in {JobState.FAILED.value, JobState.TIMEOUT.value}
        else JobState.FAILED.value
    )
    return StepSummary(
        step_id="job_failed",
        name="Job timed out" if step_state == JobState.TIMEOUT.value else "Job failed",
        state=step_state,
        error=_job_failure_message(job, payload),
    )


def _coerce_terminal_failure_summaries(
    job: JobRecord,
    summaries: list[StepSummary],
    payload: dict[str, Any] | None = None,
) -> list[StepSummary]:
    state = _job_state_text(job)
    if state not in {JobState.FAILED.value, JobState.TIMEOUT.value}:
        return summaries

    payload = payload if payload is not None else _safe_payload(job)
    if not summaries:
        return [_job_level_failure_step(job, payload)]

    if not all(_is_pending_like_step(step) for step in summaries):
        return summaries

    failure_message = _job_failure_message(job, payload)
    coerced: list[StepSummary] = []
    for index, step in enumerate(summaries):
        if index == 0:
            coerced.append(
                step.model_copy(update={"state": state, "error": failure_message})
            )
        else:
            coerced.append(step.model_copy(update={"state": JobState.SKIPPED.value}))
    return coerced


def _extract_payload_step_summaries(job: JobRecord) -> list[StepSummary]:
    """Return step summaries persisted in JobStore payload_json.

    Plan-execution jobs can fail before a provenance.json file is written. In
    that case the orchestrator still persists the live step trace into the
    JobStore payload, so expose that trace instead of returning an empty list.
    """

    payload = _safe_payload(job)

    steps_payload = payload.get("steps")
    if not isinstance(steps_payload, list):
        return _coerce_terminal_failure_summaries(job, [], payload)

    summaries = [
        _build_step_summary(raw, index)
        for index, raw in enumerate(steps_payload)
        if isinstance(raw, dict)
    ]
    return _coerce_terminal_failure_summaries(job, summaries, payload)


def _build_step_summary(raw_step: dict, index: int) -> StepSummary:
    """Normalise a single raw step dictionary into StepSummary.

    PR-4: Extended to parse timestamps, retry info, and cache metadata.
    """

    if not isinstance(raw_step, dict):
        logger.debug("Ignoring non-dict step payload at index %s: %r", index, raw_step)
        return StepSummary(step_id=f"step-{index}", state="unknown")

    step_id = str(raw_step.get("step_id") or raw_step.get("id") or f"step-{index}")
    state = str(raw_step.get("state") or raw_step.get("status") or "unknown")

    # Parse timestamps (PR-4)
    timestamps = raw_step.get("timestamps", {}) or {}
    created_at = (
        timestamps.get("created")
        or raw_step.get("created_at")
        or raw_step.get("created")
    )
    started_at = (
        timestamps.get("started")
        or timestamps.get("start")
        or raw_step.get("started_at")
        or raw_step.get("start_time")
    )
    finished_at = (
        timestamps.get("finished")
        or timestamps.get("end")
        or raw_step.get("finished_at")
        or raw_step.get("end_time")
    )

    # Parse retry info (PR-4)
    attempt = int(raw_step.get("attempt", 1))
    max_attempts = int(raw_step.get("max_attempts", 3))
    retry_reason = raw_step.get("retry_reason")

    # Parse cache info (PR-4)
    cache_data = raw_step.get("cache", {}) or {}
    cache_key = cache_data.get("cache_key") or raw_step.get("cache_key")
    cache_marker = None

    if cache_data.get("cache_hit") or raw_step.get("from_cache"):
        cache_marker = "hit"
    elif cache_key:
        cache_marker = "miss"
    elif cache_data.get("disabled"):
        cache_marker = "disabled"
    elif raw_step.get("cache_skip") or cache_data.get("skip"):
        cache_marker = "skip"

    # Execution time (existing)
    execution_time_ms = (
        raw_step.get("execution_time_ms")
        or raw_step.get("duration_ms")
        or raw_step.get("duration")
    )

    # Error message (existing)
    error_message = (
        raw_step.get("error")
        or raw_step.get("error_message")
        or raw_step.get("last_error")
    )
    if not error_message and state.lower() in {"failed", "error"}:
        error_message = raw_step.get("preview") or raw_step.get("message")

    # Run directory (existing)
    run_dir_value = raw_step.get("run_dir") or raw_step.get("run_dir_path")
    if run_dir_value is not None:
        run_dir_value = str(run_dir_value)

    # Provenance path (PR-4)
    provenance_path = raw_step.get("provenance_path")
    if provenance_path is not None:
        provenance_path = str(provenance_path)

    raw_violations = raw_step.get("violations") or []
    violations: list[Violation] | None = None
    if isinstance(raw_violations, list):
        try:
            violations = [Violation.model_validate(v) for v in raw_violations]
        except Exception:
            # best-effort; leave None
            violations = None

    preflight_result = raw_step.get("preflight_result")
    exec_result = raw_step.get("exec_result")
    postcheck_result = raw_step.get("postcheck_result")

    return StepSummary(
        step_id=step_id,
        name=raw_step.get("name"),
        state=state,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        attempt=attempt,
        max_attempts=max_attempts,
        retry_reason=retry_reason,
        cache_marker=cache_marker,
        cache_key=cache_key,
        execution_time_ms=execution_time_ms,
        run_dir=run_dir_value,
        error=error_message,
        provenance_path=provenance_path,
        violations=violations,
        preflight_result=(
            preflight_result if isinstance(preflight_result, dict) else None
        ),
        exec_result=exec_result if isinstance(exec_result, dict) else None,
        postcheck_result=(
            postcheck_result if isinstance(postcheck_result, dict) else None
        ),
    )


_TERMINAL_STATES = {
    JobState.SUCCEEDED.value,
    JobState.FAILED.value,
    JobState.CANCELLED.value,
    JobState.TIMEOUT.value,
    JobState.SKIPPED.value,
}


@router.get("/{job_id}/steps/stream")
async def stream_job_steps(job_id: str, request: Request) -> EventSourceResponse:
    """
    Stream real-time step state changes via Server-Sent Events.

    Polls the job's provenance file every 2 seconds and sends updates when
    step states change. Automatically closes connection when job reaches
    terminal state.

    Events:
        - steps_update: Step states changed (full JobStepsResponse)
        - ping: Keepalive (every 30 seconds)
        - complete: Job finished (includes final_state)
        - error: Error occurred (includes error message)
    """

    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        logger.error("Job store not configured on application state")
        raise HTTPException(status_code=503, detail="Job store not available")

    async def event_generator():
        """Generate SSE events for step state changes."""
        last_hash = None
        last_ping = time.time()

        while True:
            try:
                # Get current job state
                job: JobRecord | None = await job_store.get(job_id)
                if job is None:
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": f"Job {job_id} not found"}),
                    }
                    break

                # Load current steps using existing logic
                response = await get_job_steps(job_id, request)

                # Only send if changed (hash comparison for efficiency)
                response_json = response.model_dump_json()
                current_hash = hash(response_json)
                if current_hash != last_hash:
                    yield {
                        "event": "steps_update",
                        "data": response_json,
                        "id": str(
                            int(time.time() * 1000)
                        ),  # Millisecond timestamp as event ID
                    }
                    last_hash = current_hash
                    logger.debug(
                        "Sent steps_update for job %s (state=%s, %d steps)",
                        job_id,
                        response.state,
                        len(response.steps),
                    )

                # Check if job is terminal
                if job.state in _TERMINAL_STATES:
                    yield {
                        "event": "complete",
                        "data": json.dumps(
                            {
                                "final_state": job.state,
                                "job_id": job_id,
                                "total_steps": len(response.steps),
                            }
                        ),
                    }
                    logger.info(
                        "Job %s reached terminal state %s, closing SSE stream",
                        job_id,
                        job.state,
                    )
                    break

                # Send keepalive ping every 30 seconds
                now = time.time()
                if now - last_ping > 30:
                    yield {
                        "event": "ping",
                        "data": json.dumps({"timestamp": int(now), "job_id": job_id}),
                    }
                    last_ping = now

                # Poll interval (2 seconds)
                await asyncio.sleep(2)

            except HTTPException as exc:
                # Re-raise HTTP exceptions (like 404)
                logger.warning(
                    "HTTP error in SSE stream for job %s: %s", job_id, exc.detail
                )
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error": exc.detail, "status_code": exc.status_code}
                    ),
                }
                break
            except Exception as exc:
                logger.exception("Unexpected error in SSE stream for job %s", job_id)
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Internal server error: {str(exc)}"}),
                }
                break

    return EventSourceResponse(event_generator())
