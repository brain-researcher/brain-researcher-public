"""Canonical reason codes for Studio session / runtime cleanup fanout."""

from __future__ import annotations

from enum import Enum


class CleanupReason(str, Enum):
    POD_GONE = "runtime_backing_pod_missing"
    POD_TERMINATING = "pod_terminating"
    POD_UNREADY = "pod_unready"
    KUBERNETES_UNAVAILABLE = "kubernetes_unavailable"
    RUNTIME_RECORD_MISSING = "runtime_record_missing"
    USER_CLOSE = "user_close"
    IDLE_CULL = "idle_cull"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


__all__ = ["CleanupReason"]
