"""So-what gate for predictive FC term discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_so_what(
    plan: Mapping[str, Any],
    defaults: Mapping[str, float],
) -> dict[str, Any]:
    leader_score = float(plan["leader_score"])
    comparator_score_raw = plan.get("comparator_score")
    comparator_score = (
        float(comparator_score_raw) if comparator_score_raw is not None else None
    )
    delta = leader_score - comparator_score if comparator_score is not None else leader_score
    passed = delta > float(defaults["so_what_delta_threshold_r2"])
    return {
        "leader_backbone": plan["leader_backbone"],
        "leader_term_index": plan["leader_term_index"],
        "leader_score": leader_score,
        "comparator_backbone": plan.get("comparator_backbone"),
        "comparator_term_index": plan.get("comparator_term_index"),
        "comparator_score": comparator_score,
        "delta_vs_comparator": delta,
        "minimum_interesting_r2": float(defaults["minimum_interesting_r2"]),
        "pass": passed,
    }


__all__ = ["evaluate_so_what"]
