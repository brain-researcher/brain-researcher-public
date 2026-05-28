"""Planner module exports.

The package keeps these exports lazy so importing low-level catalog modules does
not pull optional ML dependencies from the legacy planner search index.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "choose_tool",
    "CandidateResult",
    "PlanResult",
    "select_tools",
    "SelectionCandidate",
    "explain_selection",
    "choose_tool_catalog",
    "choose_tool_intent_router",
]


def __getattr__(name: str) -> Any:
    if name in {"choose_tool", "CandidateResult", "PlanResult"}:
        from . import intent_mapper

        return getattr(intent_mapper, name)

    if name in {
        "select_tools",
        "SelectionCandidate",
        "explain_selection",
        "choose_tool_catalog",
        "choose_tool_intent_router",
    }:
        from . import selection

        if name == "choose_tool_catalog":
            return selection.choose_tool
        return getattr(selection, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
