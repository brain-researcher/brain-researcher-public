"""Discovery gates for TRIBE branch evidence and novelty decisions."""

from .evidence_gate import (
    best_support_contrasts,
    failure_modes_from_summary,
    generic_failure_modes,
    summary_next_step_decision,
    support_contrasts_from_summary,
)
from .novelty_gate import (
    decision_and_rationale,
    global_recommendation,
    status_for_decision,
)

__all__ = [
    "best_support_contrasts",
    "decision_and_rationale",
    "failure_modes_from_summary",
    "generic_failure_modes",
    "global_recommendation",
    "status_for_decision",
    "summary_next_step_decision",
    "support_contrasts_from_summary",
]
