"""Session-scoped idempotent execution guard.

Marimo re-executes cells when upstream dependencies change.  Without a guard
the same ``(tool_id, params)`` pair would be submitted multiple times.  This
module keeps a process-level registry keyed by a deterministic content hash so
that duplicate calls return the cached result instead.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Union

from brain_researcher.sdk.models import JobHandle, ToolResult

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_SESSION_JOBS: Dict[str, Union[JobHandle, ToolResult]] = {}


def get(content_hash: str) -> Union[JobHandle, ToolResult, None]:
    """Return the cached result for *content_hash*, or ``None``."""
    with _lock:
        return _SESSION_JOBS.get(content_hash)


def put(content_hash: str, value: Union[JobHandle, ToolResult]) -> None:
    """Store a result under *content_hash*."""
    with _lock:
        _SESSION_JOBS[content_hash] = value
    logger.debug(
        "job_registry: cached %s → %s", content_hash[:12], type(value).__name__
    )


def clear() -> int:
    """Reset the registry.  Returns the number of entries removed."""
    with _lock:
        count = len(_SESSION_JOBS)
        _SESSION_JOBS.clear()
    logger.info("job_registry: cleared %d entries", count)
    return count


def entries() -> Dict[str, Union[JobHandle, ToolResult]]:
    """Return a shallow copy of the registry (mainly for debugging)."""
    with _lock:
        return dict(_SESSION_JOBS)
