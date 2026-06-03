"""
Intent-to-tool mapper with preflight validation.

This module implements the core planner logic:
1. Search for candidate tools matching the user intent
2. Run preflight checks on each candidate
3. Select the best viable tool
4. Return detailed trace for provenance
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from ..preflight import run_preflight
from ..tool_catalog_loader import get_tool_index, load_niwrap_containers

logger = logging.getLogger(__name__)


class CandidateResult(BaseModel):
    """
    Result for a single candidate tool during planning.

    Attributes:
        tool_id: Tool identifier
        tool_name: Human-readable tool name
        score: Search relevance score (0-1)
        image: Container image path (if available)
        preflight_ok: Whether preflight checks passed
        preflight_report: Full preflight report
        reason: Human-readable explanation (especially for failures)
    """

    tool_id: str
    tool_name: str
    score: float
    image: str | None = None
    preflight_ok: bool = False
    preflight_report: dict[str, Any] | None = None
    reason: str = ""


class PlanResult(BaseModel):
    """
    Overall result from the planner's choose_tool function.

    Attributes:
        intent: Original user intent
        candidates: All evaluated candidates with scores
        chosen: The selected tool (None if all failed)
        plan_id: Unique identifier for this plan
        constraints: Constraints provided by user
    """

    intent: str
    candidates: list[CandidateResult]
    chosen: CandidateResult | None = None
    plan_id: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)


def _resolve_image_path(tool_id: str, tool_name: str) -> str | None:
    """
    Resolve container image path for a tool.

    Args:
        tool_id: Tool identifier (e.g., "niwrap.fsl")
        tool_name: Tool name (e.g., "fsl")

    Returns:
        Path to container image, or None if not found
    """
    niwrap_containers = load_niwrap_containers()

    # Try exact match first
    if tool_name in niwrap_containers:
        container_info = niwrap_containers[tool_name]
        if isinstance(container_info, dict):
            return container_info.get("image")

    # Try stripping category prefix
    if "." in tool_id:
        _, base_name = tool_id.split(".", 1)
        if base_name in niwrap_containers:
            container_info = niwrap_containers[base_name]
            if isinstance(container_info, dict):
                return container_info.get("image")

    # Try matching by tool family (e.g., "fsl.bet" -> "fsl")
    parts = tool_name.split(".")
    for part in parts:
        if part in niwrap_containers:
            container_info = niwrap_containers[part]
            if isinstance(container_info, dict):
                return container_info.get("image")

    return None


def choose_tool(
    intent: str,
    constraints: dict[str, Any] | None = None,
    k: int = 8,
) -> PlanResult:
    """
    Choose the best tool for a given user intent.

    This function implements the core planner logic:
    1. Search the tool index for candidates matching the intent
    2. Resolve container image paths from niwrap_containers.yaml
    3. Run preflight checks on each candidate
    4. Return the first candidate that passes preflight
    5. If none pass, return the best scoring candidate with failure reason

    Args:
        intent: User's natural language intent (e.g., "skull strip")
        constraints: Optional constraints/parameters for the task
        k: Number of top candidates to evaluate (default: 8)

    Returns:
        PlanResult with candidates and chosen tool
    """
    constraints = constraints or {}

    # Step 1: Search for candidate tools
    tool_index = get_tool_index()
    search_results = tool_index.search(intent, k=k)

    if not search_results:
        logger.warning(f"No tools found for intent: {intent}")
        return PlanResult(
            intent=intent,
            candidates=[],
            chosen=None,
            constraints=constraints,
        )

    logger.info(f"Found {len(search_results)} candidates for intent: {intent}")

    # Step 2: Evaluate each candidate with preflight
    candidates: list[CandidateResult] = []

    for tool_entry, score in search_results:
        # Resolve container image path
        image_path = _resolve_image_path(tool_entry.id, tool_entry.name)

        if not image_path:
            # Image not found - record as failed candidate
            candidate = CandidateResult(
                tool_id=tool_entry.id,
                tool_name=tool_entry.name,
                score=score,
                image=None,
                preflight_ok=False,
                reason="Container image not configured",
            )
            candidates.append(candidate)
            logger.debug(f"Candidate {tool_entry.id}: no image configured")
            continue

        # Run preflight checks
        try:
            preflight_report = run_preflight(
                tool_name=tool_entry.name,
                params=constraints,
                image_path=image_path,
            )

            candidate = CandidateResult(
                tool_id=tool_entry.id,
                tool_name=tool_entry.name,
                score=score,
                image=image_path,
                preflight_ok=preflight_report.ok,
                preflight_report=preflight_report.model_dump(),
                reason=(
                    "Preflight passed"
                    if preflight_report.ok
                    else f"Preflight failed: {len(preflight_report.blockers)} blockers"
                ),
            )
            candidates.append(candidate)

            logger.debug(
                f"Candidate {tool_entry.id}: "
                f"score={score:.3f}, "
                f"preflight_ok={preflight_report.ok}"
            )

        except Exception as e:
            # Preflight raised an exception
            logger.warning(
                f"Preflight check failed for {tool_entry.id}: {e}",
                exc_info=True,
            )
            candidate = CandidateResult(
                tool_id=tool_entry.id,
                tool_name=tool_entry.name,
                score=score,
                image=image_path,
                preflight_ok=False,
                reason=f"Preflight error: {str(e)}",
            )
            candidates.append(candidate)

    # Step 3: Select the best viable tool
    chosen: CandidateResult | None = None

    # First, try to find a candidate that passed preflight
    for candidate in candidates:
        if candidate.preflight_ok:
            chosen = candidate
            logger.info(
                f"Chosen tool: {candidate.tool_id} " f"(score={candidate.score:.3f})"
            )
            break

    # If no candidate passed, select the best scoring one
    if chosen is None and candidates:
        chosen = candidates[0]
        logger.warning(
            f"No candidates passed preflight. "
            f"Best candidate: {chosen.tool_id} "
            f"(score={chosen.score:.3f}, reason={chosen.reason})"
        )

    return PlanResult(
        intent=intent,
        candidates=candidates,
        chosen=chosen,
        constraints=constraints,
    )


__all__ = ["choose_tool", "CandidateResult", "PlanResult"]
