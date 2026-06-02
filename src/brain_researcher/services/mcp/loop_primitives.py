"""Compatibility shim for loop primitives now hosted in ``services.shared``."""

from __future__ import annotations

from brain_researcher.services.shared.loop_primitives import (
    DEFAULT_LOOP_PROFILE_ID,
    SUPPORTED_LOOP_PROFILE_IDS,
    build_artifact_index,
    build_run_bundle_payload,
    build_run_scorecard,
    compare_run_scorecards,
    get_loop_profile,
    normalize_completion_state,
)

__all__ = [
    "DEFAULT_LOOP_PROFILE_ID",
    "SUPPORTED_LOOP_PROFILE_IDS",
    "build_artifact_index",
    "build_run_bundle_payload",
    "build_run_scorecard",
    "compare_run_scorecards",
    "get_loop_profile",
    "normalize_completion_state",
]
