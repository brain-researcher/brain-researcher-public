"""Append-only job event log helpers.

This module provides a single entry point for emitting replayable job events.

Design goals:
- Persist every event into the JobStore-backed event log (JobStore.append_event)
- Optionally mirror the same event into the on-disk debug trace (trace.jsonl)
  when a run_dir is available, using a shared event_id for correlation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .job_store import JobStore
from .trace import log_trace_event

logger = logging.getLogger(__name__)


async def emit_job_event(
    job_store: JobStore,
    *,
    job_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    run_dir: str | Path | None = None,
) -> int:
    """Append a job event to the durable event log and (optionally) trace.jsonl.

    Returns:
        The assigned event_id (monotonic within the JobStore backend).
    """
    safe_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        safe_payload.update(payload)

    event_id = await job_store.append_event(job_id, event_type, payload=safe_payload)

    # Attach stable identifiers for downstream consumers.
    safe_payload.setdefault("event_id", event_id)
    safe_payload.setdefault("job_id", job_id)
    if run_id:
        safe_payload.setdefault("run_id", run_id)

    if run_dir is not None:
        try:
            run_path = Path(run_dir)
            log_trace_event(
                run_path,
                run_id=str(run_id or job_id),
                event_type=str(event_type),
                payload=safe_payload,
                event_id=str(event_id),
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Failed to mirror job event to trace.jsonl: %s", exc)

    return int(event_id or 0)


__all__ = ["emit_job_event"]
