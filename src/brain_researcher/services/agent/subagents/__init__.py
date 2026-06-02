"""Subagent helpers used by the agent service."""

from .contracts import CriticIssue, CriticVerdict, RecoveryProposal
from .critic_agent import CriticAgent
from .recovery_agent import RecoveryAgent
from .router import MultiAgentRouter

# Legacy symbols (older subagent prototype); keep optional for compatibility.
BaseSubagent = None
SubagentState = None
SubagentMessage = None
CommunicationLayer = None
MessageBroker = None
PlannerSubagent = None
ExecutorSubagent = None
ReviewerSubagent = None
IntegratorSubagent = None
SubagentController = None

try:
    from .base import BaseSubagent, SubagentMessage, SubagentState
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .communication import CommunicationLayer, MessageBroker
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .planner import PlannerSubagent
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .executor import ExecutorSubagent
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .reviewer import ReviewerSubagent
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .integrator import IntegratorSubagent
except Exception:  # pragma: no cover - optional legacy module
    pass
try:
    from .controller import SubagentController
except Exception:  # pragma: no cover - optional legacy module
    pass

try:  # Backward-compatible export for existing provenance consumers.
    from .provenance_tracker import ProvenanceTracker
except Exception:  # pragma: no cover - optional during partial installs
    ProvenanceTracker = None  # type: ignore

__all__ = [
    "CriticIssue",
    "CriticVerdict",
    "RecoveryProposal",
    "CriticAgent",
    "RecoveryAgent",
    "MultiAgentRouter",
    "ProvenanceTracker",
    "BaseSubagent",
    "SubagentState",
    "SubagentMessage",
    "CommunicationLayer",
    "MessageBroker",
    "PlannerSubagent",
    "ExecutorSubagent",
    "ReviewerSubagent",
    "IntegratorSubagent",
    "SubagentController",
]
