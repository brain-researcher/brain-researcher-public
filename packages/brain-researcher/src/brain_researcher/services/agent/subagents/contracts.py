"""Contracts for lightweight multi-agent orchestration decisions.

These contracts are intentionally small and local to the agent service.
They provide structured outputs for critic and recovery helpers without
changing public API schemas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Literal, Optional

Decision = Literal["approve", "revise", "block"]
RiskLevel = Literal["low", "medium", "high"]
RecoveryActionType = Literal["retry", "fallback_tool", "degrade_mode", "ask_user"]


@dataclass
class CriticIssue:
    """A single issue detected by the critic."""

    code: str
    message: str
    severity: RiskLevel = "medium"
    field: Optional[str] = None


@dataclass
class CriticVerdict:
    """Structured verdict for plan/tool-call review."""

    decision: Decision = "approve"
    risk_level: RiskLevel = "low"
    issues: list[CriticIssue] = field(default_factory=list)
    suggested_patch: Optional[Dict[str, Any]] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "risk_level": self.risk_level,
            "issues": [asdict(issue) for issue in self.issues],
            "suggested_patch": self.suggested_patch,
            "reason": self.reason,
        }


@dataclass
class RecoveryProposal:
    """Recovery recommendation from the recovery agent."""

    action_type: RecoveryActionType
    confidence: float
    reason: str
    fallback_tools: list[str] = field(default_factory=list)
    adjusted_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "confidence": float(self.confidence),
            "reason": self.reason,
            "fallback_tools": list(self.fallback_tools),
            "adjusted_params": dict(self.adjusted_params),
        }

