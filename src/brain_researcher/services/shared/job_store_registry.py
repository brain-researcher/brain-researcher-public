"""Process-wide job-store registry (dependency-inversion seam).

The orchestrator constructs the ``JobStore`` and registers it here at startup
(``set_initialized_job_store``), plus an auto-initializer callback
(``register_autoinit``) used as a fallback. Lower layers (agent, mcp) read the
instance through this module instead of importing the orchestrator — which
removes a set of ``*-> orchestrator`` back-edges.

The store is typed as ``Any`` so this low layer stays free of the orchestrator
``JobStore`` protocol; ``orchestrator.job_store_factory`` re-exports these
functions for backward compatibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_job_store_instance: Any | None = None
_autoinit: Callable[[], Any] | None = None


def register_autoinit(factory: Callable[[], Any]) -> None:
    """Register an auto-initializer (the orchestrator's job-store factory).

    Used by :func:`get_initialized_job_store` as a fallback when no store has
    been explicitly set, preserving the prior auto-initialize behaviour without
    a lower-layer -> orchestrator import.
    """

    global _autoinit
    _autoinit = factory


def set_initialized_job_store(job_store: Any) -> Any:
    """Set the process-wide JobStore instance (called by the orchestrator)."""

    global _job_store_instance
    _job_store_instance = job_store
    logger.info("JobStore instance set: %s", type(job_store).__name__)
    return _job_store_instance


def peek_initialized_job_store() -> Any | None:
    """Return the registered JobStore if set (no auto-initialize)."""

    return _job_store_instance


def get_initialized_job_store() -> Any:
    """Return the registered JobStore, auto-initializing via the registered
    orchestrator factory if necessary.
    """

    global _job_store_instance
    if _job_store_instance is None:
        if _autoinit is None:
            raise RuntimeError(
                "JobStore not initialized and no auto-initializer registered. "
                "Ensure the orchestrator job_store_factory has been imported."
            )
        logger.warning(
            "JobStore not explicitly initialized. Auto-initializing with defaults."
        )
        _job_store_instance = _autoinit()
    return _job_store_instance
