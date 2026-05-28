"""Shared verdict and stop vocab for line-specific autoresearch controllers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # Python 3.10 compatibility.

    class StrEnum(str, Enum):
        pass


class LineId(StrEnum):
    PREDICTIVE = "predictive"
    DISCOVERY = "discovery"


class AutoresearchStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class StopReason(StrEnum):
    COMPLETED = "completed"
    BOUNDED_LIMIT_REACHED = "bounded_limit_reached"
    STALLED = "stalled"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    INFRA_RECOVERY_FAILED = "infra_recovery_failed"


class GateVerdict(StrEnum):
    PROCEED = "proceed"
    NEEDS_DIAGNOSIS = "needs_diagnosis"
    NEEDS_EXPLORATION = "needs_exploration"
    STOP_HUMAN_REVIEW = "stop_human_review"


@dataclass(frozen=True)
class RecoveryEvent:
    line_id: str
    status: str
    stop_reason: str
    code: str
    detail: str
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "code": self.code,
            "detail": self.detail,
            "metadata": self.metadata or {},
        }


__all__ = [
    "AutoresearchStatus",
    "GateVerdict",
    "LineId",
    "RecoveryEvent",
    "StopReason",
]
