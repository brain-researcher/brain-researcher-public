"""Shared candidate-generation service for chat and contract planning surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent import preflight
from brain_researcher.services.agent.resolution_memory import export_resolution_state


@dataclass
class ToolCandidateBundle:
    """Normalized preflight output shared across routing entrypoints."""

    ctx: Dict[str, Any]
    query_understanding: Any | None
    tool_candidates: List[Dict[str, Any]]
    tool_candidate_diagnostics: Dict[str, Any]
    resolution_state: Dict[str, Any]


def generate_tool_candidates(
    query: str,
    *,
    ctx: Optional[Dict[str, Any]] = None,
    parser: Any | None = None,
    tool_retriever: Any | None = None,
    registry: Any | None = None,
    top_k: int = 12,
) -> ToolCandidateBundle:
    """Run shared preflight candidate generation and return a stable bundle."""

    working_ctx = ctx if isinstance(ctx, dict) else {}
    query_understanding = preflight.ensure_query_understanding(
        query,
        working_ctx,
        parser=parser,
    )
    tool_candidates = preflight.ensure_tool_candidates(
        query,
        working_ctx,
        tool_retriever=tool_retriever,
        registry=registry,
        top_k=top_k,
    )
    return ToolCandidateBundle(
        ctx=working_ctx,
        query_understanding=query_understanding,
        tool_candidates=list(tool_candidates or []),
        tool_candidate_diagnostics=dict(
            working_ctx.get("tool_candidate_diagnostics") or {}
        ),
        resolution_state=export_resolution_state(working_ctx),
    )


__all__ = ["ToolCandidateBundle", "generate_tool_candidates"]
