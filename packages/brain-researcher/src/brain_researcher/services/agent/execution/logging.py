"""
Helpers for streaming long-running command output back to the orchestrator.

The JobLogEmitter posts log lines to the orchestrator's job log endpoint so
that Server-Sent Events (SSE) and WebSocket subscribers receive updates while
commands execute.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class JobLogEmitter:
    """Send command output lines to the orchestrator job log endpoint."""

    def __init__(
        self,
        base_url: Optional[str],
        job_id: Optional[str],
        *,
        step_id: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 1.5,
    ) -> None:
        base_url = (base_url or "").strip()
        self._base_url = base_url.rstrip("/") if base_url else None
        self._job_id = job_id
        self._step_id = step_id
        self._timeout = timeout
        self._lock = threading.Lock()
        self._sequence = 0
        self._active = bool(self._base_url and self._job_id)
        self._client = client or (
            httpx.Client(timeout=self._timeout) if self._active else None
        )
        self._owns_client = client is None and self._client is not None

    @property
    def enabled(self) -> bool:
        return self._active

    @classmethod
    def from_env(
        cls, job_id: Optional[str], *, step_id: Optional[str] = None
    ) -> "JobLogEmitter":
        """Build an emitter using environment defaults."""
        orchestrator_url = os.environ.get("ORCHESTRATOR_URL")
        return cls(orchestrator_url, job_id, step_id=step_id)

    def emit(self, message: str, *, stream: str = "stdout") -> None:
        """Emit a single log line to the orchestrator."""
        if not self._active or self._client is None:
            return

        text = (message or "").rstrip()
        if not text:
            return
        if len(text) > 2000:
            text = text[-2000:]

        with self._lock:
            self._sequence += 1
            sequence = self._sequence

        payload = {
            "message": text,
            "stream": stream,
            "sequence": sequence,
            "step_id": self._step_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self._client.post(
                f"{self._base_url}/jobs/{self._job_id}/logs",
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:  # pragma: no cover - telemetry best-effort
            logger.debug("Failed to emit job log: %s", exc)

    def close(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception as exc:  # pragma: no cover - cleanup best-effort
                logger.debug("Failed to close log emitter client: %s", exc)

    def __enter__(self) -> "JobLogEmitter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


__all__ = ["JobLogEmitter"]
