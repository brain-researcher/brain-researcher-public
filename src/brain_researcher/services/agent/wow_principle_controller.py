"""Backward-compatible re-export shim for wow principle scoring."""

from __future__ import annotations

from brain_researcher.services.shared.wow_principle_controller import (  # noqa: F401
    rank_wow_candidates,
    score_wow_candidate,
)

__all__ = [
    "rank_wow_candidates",
    "score_wow_candidate",
]
