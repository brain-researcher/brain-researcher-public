"""Operation Router: map PlanRequest to high-level Operations (intent-level).

Phase 1 implementation: single-operation routing using intent synonyms.
Multi-step DAGs can be added later without changing callers.
"""

from __future__ import annotations

from typing import List, Optional

from brain_researcher.services.shared.planner.models import PlanRequest

from .catalog_loader import load_intents
from .intents import Intent, Operation
from .synonyms_loader import match_intents_from_text


def _pick_best_intent_for_request(
    plan_request: PlanRequest, intents_by_id: dict[str, Intent]
) -> Optional[Intent]:
    """Select the first matching intent based on simple synonym matching."""
    text = plan_request.pipeline or ""
    matched_intents = match_intents_from_text(text)

    for intent in matched_intents:
        # Domain filter (if provided)
        if plan_request.domain and intent.domains and plan_request.domain not in intent.domains:
            continue
        # Modality filter (if provided)
        if plan_request.modality:
            if intent.modalities and not any(m in intent.modalities for m in plan_request.modality):
                continue
        return intent

    return None


def plan_operations(plan_request: PlanRequest) -> List[Operation]:
    """Map a PlanRequest to one or more Operations.

    Phase 1: return at most one Operation; fall back to empty list if we
    cannot map the request (caller can then use legacy selection).
    """
    intents_by_id = load_intents()
    intent = _pick_best_intent_for_request(plan_request, intents_by_id)
    if intent is None:
        return []

    op = Operation(
        op_id=intent.id,
        intent=intent,
        inputs={},
        outputs={},
        preferences={},
    )
    return [op]
