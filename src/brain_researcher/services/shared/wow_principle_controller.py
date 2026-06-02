"""Scoring helpers for wow-style research ideas.

This controller is intentionally separate from the legacy novelty controller.
It scores candidates on counterintuitiveness, testability, and impact radius,
while vetoing obvious bridge-only or prior-art-obvious ideas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_CONTROLLER_MODE = "wow_principle_v1"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed:
        return default
    return parsed


def _clip01(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _safe_float(value, default)))


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _non_empty_list(value: Any) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if item not in (None, "", [], {})]


def _count_cross_layer_types(value: Any) -> int:
    types = set()
    for item in _non_empty_list(value):
        if isinstance(item, Mapping):
            raw = str(item.get("node_type") or item.get("type") or "").strip()
        else:
            raw = str(item or "").strip()
        if raw:
            types.add(raw)
    return len(types)


def _derive_counterintuitiveness(candidate: Mapping[str, Any]) -> float:
    contradiction = _clip01(
        candidate.get("contradiction_score")
        or candidate.get("contradiction_density")
        or candidate.get("frontier_score"),
        0.0,
    )
    assumption = _clip01(
        candidate.get("assumption_crack_score")
        or candidate.get("challengeability_score")
        or candidate.get("defaultness_score"),
        0.0,
    )
    transfer = _clip01(
        candidate.get("transfer_score")
        or candidate.get("analogy_score")
        or candidate.get("method_gap_score"),
        0.0,
    )
    bridge = _clip01(candidate.get("bridge_score"), 0.0)
    result = (0.45 * contradiction) + (0.35 * assumption) + (0.25 * transfer)
    if bridge > 0.75 and max(contradiction, assumption, transfer) < 0.25:
        result *= 0.55
    return round(_clip01(result), 6)


def _derive_testability(candidate: Mapping[str, Any]) -> float:
    minimal_test = 1.0 if _has_text(candidate.get("minimal_test")) else 0.0
    falsifier = 1.0 if _has_text(candidate.get("falsifier")) else 0.0
    evidence_count = min(
        1.0,
        _safe_float(
            candidate.get("evidence_count")
            or candidate.get("publication_count")
            or candidate.get("support_count")
            or 0.0,
            0.0,
        )
        / 4.0,
    )
    seed_count = min(
        1.0,
        len(_non_empty_list(candidate.get("seed_kg_ids") or candidate.get("seeds")))
        / 3.0,
    )
    return round(
        _clip01(
            (0.40 * minimal_test)
            + (0.25 * falsifier)
            + (0.20 * evidence_count)
            + (0.15 * seed_count)
        ),
        6,
    )


def _derive_impact_radius(candidate: Mapping[str, Any]) -> float:
    cross_layer = min(
        1.0,
        _count_cross_layer_types(candidate.get("supporting_nodes")) / 3.0,
    )
    touched_domains = min(
        1.0,
        len(
            _non_empty_list(
                candidate.get("touched_domains") or candidate.get("domains")
            )
        )
        / 3.0,
    )
    publication_count = min(
        1.0,
        _safe_float(candidate.get("publication_count") or 0.0, 0.0) / 5.0,
    )
    dataset_count = min(
        1.0,
        _safe_float(candidate.get("dataset_count") or 0.0, 0.0) / 3.0,
    )
    return round(
        _clip01(
            (0.35 * cross_layer)
            + (0.25 * touched_domains)
            + (0.25 * publication_count)
            + (0.15 * dataset_count)
        ),
        6,
    )


def _derive_prior_art_obviousness(candidate: Mapping[str, Any]) -> float:
    explicit = _clip01(candidate.get("prior_art_obviousness"), 0.0)
    if explicit > 0:
        return explicit
    bridge = _clip01(candidate.get("bridge_score"), 0.0)
    transfer = _clip01(
        candidate.get("transfer_score")
        or candidate.get("analogy_score")
        or candidate.get("method_gap_score"),
        0.0,
    )
    contradiction = _clip01(
        candidate.get("contradiction_score")
        or candidate.get("contradiction_density")
        or candidate.get("frontier_score"),
        0.0,
    )
    assumption = _clip01(
        candidate.get("assumption_crack_score")
        or candidate.get("challengeability_score")
        or candidate.get("defaultness_score"),
        0.0,
    )
    result = max(
        0.0,
        (0.60 * bridge)
        - (0.20 * contradiction)
        - (0.15 * assumption)
        - (0.15 * transfer),
    )
    if _has_text(candidate.get("why_this_is_not_just_a_bridge")):
        result *= 0.7
    return round(_clip01(result), 6)


def _derive_execution_gap_only(candidate: Mapping[str, Any]) -> bool:
    if bool(candidate.get("execution_gap_only")):
        return True
    bridge = _clip01(candidate.get("bridge_score"), 0.0)
    contradiction = _clip01(
        candidate.get("contradiction_score")
        or candidate.get("contradiction_density")
        or candidate.get("frontier_score"),
        0.0,
    )
    assumption = _clip01(
        candidate.get("assumption_crack_score")
        or candidate.get("challengeability_score")
        or candidate.get("defaultness_score"),
        0.0,
    )
    transfer = _clip01(
        candidate.get("transfer_score")
        or candidate.get("analogy_score")
        or candidate.get("method_gap_score"),
        0.0,
    )
    return bridge >= 0.65 and max(contradiction, assumption, transfer) < 0.20


def score_wow_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return a scored wow-candidate payload with veto explanations."""

    contradiction_signature = (
        str(candidate.get("contradiction_signature") or "").strip() or None
    )
    transfer_signature = str(candidate.get("transfer_signature") or "").strip() or None
    broken_default_assumption = (
        str(
            candidate.get("broken_default_assumption")
            or candidate.get("main_assumption_text")
            or candidate.get("challenged_assumption")
            or ""
        ).strip()
        or None
    )

    counterintuitiveness = _derive_counterintuitiveness(candidate)
    testability = _derive_testability(candidate)
    impact_radius = _derive_impact_radius(candidate)
    prior_art_obviousness = _derive_prior_art_obviousness(candidate)
    execution_gap_only = _derive_execution_gap_only(candidate)
    vetoed = prior_art_obviousness >= 0.80 or execution_gap_only
    wow_score = (
        0.0 if vetoed else round(counterintuitiveness * testability * impact_radius, 6)
    )

    why_not_bridge = str(candidate.get("why_this_is_not_just_a_bridge") or "").strip()
    if not why_not_bridge:
        if broken_default_assumption:
            why_not_bridge = f"This challenges the field default assumption: {broken_default_assumption}."
        elif contradiction_signature:
            why_not_bridge = f"This is driven by a contradiction pattern, not a missing bridge: {contradiction_signature}."
        elif transfer_signature:
            why_not_bridge = f"This proposes a method-family transfer beyond local bridge search: {transfer_signature}."
        else:
            why_not_bridge = "This lacks a non-bridge justification."

    scored = dict(candidate)
    scored.update(
        {
            "controller_mode": _CONTROLLER_MODE,
            "counterintuitiveness": counterintuitiveness,
            "testability": testability,
            "impact_radius": impact_radius,
            "prior_art_obviousness": prior_art_obviousness,
            "execution_gap_only": execution_gap_only,
            "vetoed": vetoed,
            "wow_score": wow_score,
            "broken_default_assumption": broken_default_assumption,
            "contradiction_signature": contradiction_signature,
            "transfer_signature": transfer_signature,
            "why_this_is_not_just_a_bridge": why_not_bridge,
        }
    )
    return scored


def rank_wow_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Score and rank wow candidates."""

    scored = [score_wow_candidate(candidate) for candidate in candidates]
    scored.sort(
        key=lambda item: (
            bool(item.get("vetoed")),
            -_safe_float(item.get("wow_score"), 0.0),
            -_safe_float(item.get("counterintuitiveness"), 0.0),
            -_safe_float(item.get("impact_radius"), 0.0),
            str(
                item.get("title") or item.get("candidate_label") or item.get("id") or ""
            ),
        )
    )
    for idx, item in enumerate(scored, start=1):
        item["rank"] = idx
    return scored


__all__ = [
    "rank_wow_candidates",
    "score_wow_candidate",
]
