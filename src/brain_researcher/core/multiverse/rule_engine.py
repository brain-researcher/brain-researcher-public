"""
Deterministic, branch-aware variant generation for GLM multiverse.

This initial implementation keeps the legacy grid (HRF, confounds, high-pass)
but wraps it in a decision-point abstraction and attaches rationales, making
it easier to extend with constraints/priors later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from brain_researcher.core.multiverse.confounds import (
    CONF_FAMILY_AXES,
    enforce_motion_consistency,
)
from brain_researcher.core.multiverse.spec_family import generate_spec_family


@dataclass
class DecisionPoint:
    name: str
    options: List[str]
    rationale: str
    weights: Optional[Dict[str, float]] = None


def _ordered_options(options: List[str], weights: Optional[Dict[str, float]]) -> List[str]:
    if not weights:
        return options
    ordered = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in ordered if k in options]


def _normalize_presence(dist: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(dist, dict):
        return None
    try:
        present = float(dist.get("present", 0.0))
    except (TypeError, ValueError):
        present = 0.0
    try:
        absent = float(dist.get("absent", 0.0))
    except (TypeError, ValueError):
        absent = 0.0
    total = present + absent
    if total <= 0:
        return None
    return {"present": present / total, "absent": absent / total}


def _extract_confounds_family_priors(pri: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    family_priors: Dict[str, Dict[str, float]] = {}
    for axis in CONF_FAMILY_AXES:
        normalized = _normalize_presence(pri.get(axis))
        if normalized:
            family_priors[axis] = normalized
    for key, val in pri.items():
        if key.startswith("confounds_") and key not in family_priors:
            normalized = _normalize_presence(val if isinstance(val, dict) else None)
            if normalized:
                family_priors[key] = normalized
    return family_priors


def _build_family_selections(
    family_priors: Dict[str, Dict[str, float]],
    *,
    max_variants: int,
) -> List[Dict[str, bool]]:
    if not family_priors:
        return []

    base = {
        axis: dist.get("present", 0.0) >= dist.get("absent", 0.0)
        for axis, dist in family_priors.items()
    }
    base = enforce_motion_consistency(base)

    selections: List[Dict[str, bool]] = []
    seen: set[tuple[tuple[str, bool], ...]] = set()

    def _add(selection: Dict[str, bool]) -> None:
        key = tuple(sorted(selection.items()))
        if key in seen:
            return
        seen.add(key)
        selections.append(selection)

    _add(dict(base))
    if max_variants <= 1:
        return selections

    candidates: List[tuple[float, str]] = []
    for axis, dist in family_priors.items():
        present = dist.get("present", 0.0)
        absent = dist.get("absent", 0.0)
        if present <= 0 or absent <= 0:
            continue
        candidates.append((abs(present - absent), axis))

    for _, axis in sorted(candidates):
        alt = dict(base)
        alt[axis] = not alt.get(axis, False)
        enforce_motion_consistency(alt)
        _add(alt)
        if len(selections) >= max_variants:
            break

    return selections


def _confound_family_label(families: Dict[str, bool]) -> str:
    present = [axis.replace("confounds_", "") for axis, val in families.items() if val]
    if not present:
        return "Confound families: none"
    return f"Confound families: {', '.join(sorted(present))}"


def generate_variants(
    priors: Optional[Dict[str, Any]],
    max_models: int,
    use_priors: bool = True,
    seed: int = 0,
    axis_overrides: Optional[Dict[str, List[Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Return a list of variant dicts with rationale.
    """
    pri = priors if use_priors else {}
    family_priors = _extract_confounds_family_priors(pri) if pri else {}

    spec_family = generate_spec_family(
        pri,
        k=max_models,
        seed=seed,
        axis_overrides=axis_overrides,
    )
    variants: List[Dict[str, Any]] = []
    for spec in spec_family:
        decision_points = spec.get("decision_points", {})
        families = decision_points.get("confounds_families")
        if families:
            families = enforce_motion_consistency(dict(families))
        rationale = []
        hrf = decision_points.get("hrf_basis")
        conf = decision_points.get("confounds")
        hp = decision_points.get("high_pass")
        if hrf:
            rationale.append(f"HRF basis choices commonly varied across GLM analyses: {hrf}")
        if conf:
            rationale.append(f"Motion + aCompCor strategies: {conf}")
        if hp is not None:
            rationale.append(f"High-pass cutoff (s): {hp}")
        if families:
            rationale.append(_confound_family_label(families))
        hp_value = decision_points.get("high_pass")
        if isinstance(hp_value, str):
            try:
                hp_value = int(float(hp_value))
            except ValueError:
                pass

        variants.append(
            {
                "hrf": hrf,
                "confounds": conf,
                "high_pass": hp_value,
                "confounds_families": families,
                "variant_id": spec.get("variant_id"),
                "rationale": rationale,
                "priors_used": {
                    "hrf_basis": pri.get("hrf_basis") if pri else None,
                    "confounds": pri.get("confounds") if pri else None,
                    "high_pass": pri.get("high_pass") if pri else None,
                    "confounds_families": family_priors or None,
                },
                "selection_reason": spec.get("selection_reason")
                or ("priors_weighted" if priors and use_priors else "uniform"),
            }
        )

    return variants[:max_models]
