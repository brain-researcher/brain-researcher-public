"""Plan materializer for converting SelectionCandidate to structured Plan (PR-3).

This module provides functions to convert tool selection results into
the structured Plan/PlanDAG format used by the orchestrator.

Conversion flow:
    SelectionCandidate → Plan/PlanDAG (existing models)

For PR-3, this enables:
- Structured plan representation from catalog selection
- Backward compatibility with existing orchestrator interface
- Easy extension to multi-step plans in future
"""

from __future__ import annotations

import secrets
from typing import List, Optional

from brain_researcher.services.agent.planner.selection import SelectionCandidate
from brain_researcher.services.shared.planner.models import (
    Plan,
    PlanDAG,
    StepSpec,
    ArtifactSpec,
    Domain,
    Modality,
    ResourceType,
)
from brain_researcher.services.tools.catalog_loader import resolve_primary_runtime_tool_id


def _canonical_tool_id(raw_tool_id: str | None) -> str:
    normalized = str(raw_tool_id or "").strip()
    return resolve_primary_runtime_tool_id(normalized) or normalized


def materialize_simple_plan(
    candidate: SelectionCandidate,
    query: str,
    domain: Domain = "neuroimaging",
    modality: Optional[List[Modality]] = None,
) -> Plan:
    """Convert SelectionCandidate to single-step Plan.

    Args:
        candidate: Selected tool candidate
        query: Original user query
        domain: Domain (default: "neuroimaging")
        modality: List of modalities (optional)

    Returns:
        Plan object with single step

    Examples:
        >>> from brain_researcher.services.agent.planner import select_tools
        >>> candidates = select_tools("skull strip T1 image")
        >>> if candidates:
        ...     plan = materialize_simple_plan(candidates[0], "skull strip T1 image")
        ...     print(plan.dag.steps[0].tool)
    """
    tool = candidate.tool

    # Create single step
    step = StepSpec(
        id="step_001",
        tool=_canonical_tool_id(tool.id),
        consumes={},  # No explicit inputs for single-step plan
        produces={},  # No explicit outputs tracked yet
        params={},    # Parameters would come from user in full implementation
        runtime_kind=tool.runtime_kind,  # Propagate backend type from catalog
    )

    # Create DAG
    dag = PlanDAG(
        steps=[step],
        artifacts=[],  # No artifacts tracked for simple plans yet
    )

    # Create plan with metadata
    plan = Plan(
        plan_id=f"plan_{secrets.token_urlsafe(8)}",
        version=1,
        domain=domain,
        modality=modality or [],
        resolvable=candidate.preflight_passed,
        dag=dag,
        estimates={
            "confidence": candidate.final_score,
            "intent_match": candidate.intent_match_score,
            "description_relevance": candidate.description_score,
            "metadata_quality": candidate.metadata_score,
            "resource_fit": candidate.resource_fit_score,  # PR-3
        },
        warnings=[] if candidate.preflight_passed else [
            f"Preflight checks failed: {candidate.preflight_detail}"
        ],
    )

    return plan


def materialize_plan_with_alternatives(
    candidates: List[SelectionCandidate],
    query: str,
    domain: Domain = "neuroimaging",
    modality: Optional[List[Modality]] = None,
    include_top_n: int = 3,
) -> Plan:
    """Convert multiple candidates to Plan with alternatives.

    Uses the best candidate for the primary plan, and includes
    alternative tools in the estimates for reference.

    Args:
        candidates: List of candidates (sorted by score)
        query: Original user query
        domain: Domain
        modality: List of modalities (optional)
        include_top_n: Number of alternatives to include in metadata

    Returns:
        Plan with best tool and alternatives listed in estimates

    Examples:
        >>> candidates = select_tools("skull strip", max_results=5)
        >>> plan = materialize_plan_with_alternatives(candidates, "skull strip")
        >>> print(plan.estimates.get("alternatives"))
    """
    if not candidates:
        raise ValueError("Cannot materialize plan from empty candidate list")

    # Use best candidate for plan
    best = candidates[0]
    plan = materialize_simple_plan(best, query, domain, modality)

    # Add alternatives to estimates
    alternatives = []
    for i, candidate in enumerate(candidates[1:include_top_n], start=2):
        alternatives.append({
            "rank": i,
            "tool_id": _canonical_tool_id(candidate.tool.id),
            "tool_name": candidate.tool.name,
            "score": candidate.final_score,
            "explanation": candidate.explanation,
            "preflight_passed": candidate.preflight_passed,
        })

    if alternatives:
        plan.estimates["alternatives"] = alternatives
        plan.estimates["alternatives_count"] = len(alternatives)

    # Add explanation
    plan.estimates["explanation"] = best.explanation
    plan.estimates["selected_tool_name"] = best.tool.name

    return plan


def create_plan_preview(
    candidate: SelectionCandidate,
    query: str,
) -> dict:
    """Create a lightweight plan preview for UI display.

    Returns a simplified dict representation suitable for
    quick preview without full Plan object overhead.

    Args:
        candidate: Selected tool candidate
        query: Original user query

    Returns:
        Dict with preview information

    Examples:
        >>> candidate = select_tools("skull strip")[0]
        >>> preview = create_plan_preview(candidate, "skull strip")
        >>> print(preview["tool_name"])
    """
    return {
        "query": query,
        "tool_id": _canonical_tool_id(candidate.tool.id),
        "tool_name": candidate.tool.name,
        "tool_description": candidate.tool.description,
        "confidence": candidate.final_score,
        "explanation": candidate.explanation,
        "ready_to_execute": candidate.preflight_passed,
        "preflight_details": candidate.preflight_detail,
        "scores": {
            "intent_match": candidate.intent_match_score,
            "preflight": 1.0 if candidate.preflight_passed else 0.0,
            "description": candidate.description_score,
            "metadata": candidate.metadata_score,
            "resource_fit": candidate.resource_fit_score,
        },
        "runtime_kind": candidate.tool.runtime_kind,
        "capabilities": list(candidate.tool.capabilities),
    }


def materialize_multi_step_plan(
    candidates: List[SelectionCandidate],
    query: str,
    domain: Domain = "neuroimaging",
    modality: Optional[List[Modality]] = None,
) -> Plan:
    """Create multi-step plan from multiple candidates (PR-3 stub).

    NOTE: This is a stub for future multi-step planning. Currently
    creates a sequential pipeline from the candidate list.

    Args:
        candidates: List of tool candidates in execution order
        query: Original user query
        domain: Domain
        modality: List of modalities

    Returns:
        Plan with multiple steps

    Examples:
        >>> # Future: multi-step skull strip + registration pipeline
        >>> candidates = [skull_strip_tool, registration_tool]
        >>> plan = materialize_multi_step_plan(candidates, "skull strip and register")
    """
    if not candidates:
        raise ValueError("Cannot materialize plan from empty candidate list")

    # Create steps from candidates
    steps = []
    for i, candidate in enumerate(candidates, start=1):
        step = StepSpec(
            id=f"step_{i:03d}",
                tool=_canonical_tool_id(candidate.tool.id),
            consumes={},  # TODO: infer from tool metadata
            produces={},  # TODO: infer from tool metadata
            params={},
            runtime_kind=candidate.tool.runtime_kind,  # Propagate backend type from catalog
        )
        steps.append(step)

    # Create DAG
    dag = PlanDAG(
        steps=steps,
        artifacts=[],  # TODO: infer from steps
    )

    # Aggregate estimates
    avg_score = sum(c.final_score for c in candidates) / len(candidates)
    all_passed = all(c.preflight_passed for c in candidates)

    # Create plan
    plan = Plan(
        plan_id=f"plan_{secrets.token_urlsafe(8)}",
        version=1,
        domain=domain,
        modality=modality or [],
        resolvable=all_passed,
        dag=dag,
        estimates={
            "confidence": avg_score,
            "step_count": len(steps),
            "avg_intent_match": sum(c.intent_match_score for c in candidates) / len(candidates),
            "all_preflight_passed": all_passed,
        },
        warnings=[] if all_passed else [
            f"Some steps failed preflight: {[c.tool.id for c in candidates if not c.preflight_passed]}"
        ],
    )

    # Add step-level estimates
    for i, candidate in enumerate(candidates):
        plan.estimates[f"step_{i+1}_confidence"] = candidate.final_score
        plan.estimates[f"step_{i+1}_explanation"] = candidate.explanation

    return plan


# Backward compatibility: alias for existing code
def convert_candidate_to_plan(
    candidate: SelectionCandidate,
    query: str,
    domain: Domain = "neuroimaging",
) -> Plan:
    """Legacy alias for materialize_simple_plan.

    Maintained for backward compatibility with existing code.
    """
    return materialize_simple_plan(candidate, query, domain=domain)
