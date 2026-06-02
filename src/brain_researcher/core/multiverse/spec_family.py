"""Generate reproducible multiverse spec families from priors."""

from __future__ import annotations

import hashlib
import json
import random
from itertools import product
from typing import Any, Dict, Iterable, List, Optional, Tuple

from brain_researcher.core.multiverse.confounds import (
    CONF_FAMILY_AXES,
    enforce_motion_consistency,
)

AXIS_PRIORITY = ("hrf_basis", "confounds", "high_pass")
_DEFAULT_AXES: dict[str, list[str]] = {
    # Keep these aligned with FitLins multiverse transforms in fitlins_tool.py.
    "hrf_basis": ["canonical", "derivs", "glover", "fir"],
    "confounds": ["6mot", "24mot", "24mot_physio", "24mot_pupil", "24mot_physio_pupil"],
    "high_pass": ["128", "256"],
}


def _normalize_dist(
    dist: Optional[dict[str, Any]],
    *,
    options: Iterable[str],
    fallback_weight: float = 0.01,
) -> dict[str, float]:
    if not isinstance(dist, dict):
        dist = {}
    weights: dict[str, float] = {}
    for opt in options:
        if opt in dist:
            try:
                val = float(dist[opt])
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                weights[opt] = val
            continue
        if fallback_weight > 0:
            weights[opt] = fallback_weight
    if not weights:
        weights = {str(opt): 1.0 for opt in options}
    total = sum(weights.values())
    if total <= 0:
        return {str(opt): 1.0 / max(len(options), 1) for opt in options}
    return {k: v / total for k, v in weights.items()}


def _normalize_presence(dist: Optional[dict[str, Any]]) -> Optional[dict[str, float]]:
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


def _extract_family_priors(priors: dict[str, Any]) -> dict[str, dict[str, float]]:
    families: dict[str, dict[str, float]] = {}
    for axis in CONF_FAMILY_AXES:
        normalized = _normalize_presence(priors.get(axis))
        if normalized:
            families[axis] = normalized
    return families


def _axis_sort_key(axis: str) -> tuple[int, int | str]:
    if axis in AXIS_PRIORITY:
        return (0, AXIS_PRIORITY.index(axis))
    return (1, axis)


def _ordered_options(options: list[str], dist: dict[str, float]) -> list[str]:
    if not dist:
        return options
    ranked = sorted(
        ((opt, dist.get(opt, 0.0)) for opt in options),
        key=lambda kv: kv[1],
        reverse=True,
    )
    ordered = [opt for opt, weight in ranked if weight > 0]
    return ordered or options


def _top_choice(options: list[str], dist: dict[str, float]) -> str:
    ordered = _ordered_options(options, dist)
    return ordered[0]


def _sample_choice(
    rng: random.Random, options: list[str], dist: dict[str, float]
) -> str:
    if not options:
        return ""
    weights = [dist.get(opt, 0.0) for opt in options]
    if sum(weights) <= 0:
        return options[0]
    return rng.choices(options, weights=weights, k=1)[0]


def _coerce_numeric(value: str) -> str | int | float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num.is_integer():
        return int(num)
    return num


def _normalize_axis_overrides(
    axis_overrides: Optional[dict[str, list[Any]]],
) -> dict[str, list[str]]:
    if not isinstance(axis_overrides, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for axis, raw_options in axis_overrides.items():
        if raw_options is None:
            continue
        if isinstance(raw_options, (str, int, float)):
            option_iterable = [raw_options]
        else:
            option_iterable = list(raw_options)
        options: list[str] = []
        seen: set[str] = set()
        for option in option_iterable:
            value = str(option).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            options.append(value)
        if options:
            normalized[str(axis)] = options
    return normalized


def _variant_id(decision_points: dict[str, Any]) -> str:
    payload = json.dumps(decision_points, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _axis_source(axis: str, axis_sources: Optional[dict[str, str]]) -> str:
    if not axis_sources:
        return "unknown"
    return axis_sources.get(axis, "unknown")


def _implied_confounds_families(confounds_mode: Any) -> dict[str, bool]:
    mode = str(confounds_mode or "").strip().lower()
    if not mode:
        return {}
    families: dict[str, bool] = {}
    if "24mot" in mode:
        families["confounds_motion_24"] = True
    if "acompcor" in mode:
        families["confounds_acompcor"] = True
    if "physio" in mode:
        families["confounds_physio"] = True
    if "pupil" in mode:
        families["confounds_pupil"] = True
    return enforce_motion_consistency(families) if families else {}


def _merge_confounds_mode_families(
    confounds_mode: Any,
    families: Optional[dict[str, bool]],
) -> dict[str, bool]:
    merged = dict(families or {})
    implied = _implied_confounds_families(confounds_mode)
    if implied:
        merged.update(implied)
    return enforce_motion_consistency(merged) if merged else {}


def generate_spec_family(
    priors: dict[str, Any],
    *,
    k: int,
    seed: int | None = None,
    axis_sources: Optional[dict[str, str]] = None,
    axis_overrides: Optional[dict[str, list[Any]]] = None,
) -> list[dict[str, Any]]:
    """Generate a reproducible spec family with coverage guarantees."""
    if k <= 0:
        return []
    rng = random.Random(seed)

    axes: dict[str, tuple[list[str], dict[str, float]]] = {}
    for axis, dist in (priors or {}).items():
        if axis in CONF_FAMILY_AXES:
            continue
        if not isinstance(dist, dict) or not dist:
            continue
        options = sorted({str(opt) for opt in dist.keys()})
        if not options:
            continue
        norm = _normalize_dist(dist, options=options, fallback_weight=0.0)
        axes[axis] = (options, norm)

    # Ensure core axes exist even when priors are empty or incomplete.
    for axis, options in _DEFAULT_AXES.items():
        if axis in axes:
            continue
        weights = {opt: 1.0 / len(options) for opt in options}
        axes[axis] = (list(options), weights)

    # Explicit axis overrides take precedence over priors/defaults.
    normalized_overrides = _normalize_axis_overrides(axis_overrides)
    for axis, options in normalized_overrides.items():
        weights = {opt: 1.0 / len(options) for opt in options}
        axes[axis] = (list(options), weights)

    family_priors = _extract_family_priors(priors or {})
    family_axes = list(family_priors.keys())

    # Base decision points
    base = {
        axis: _coerce_numeric(_top_choice(options, dist))
        for axis, (options, dist) in axes.items()
    }
    base_families = {
        axis: dist.get("present", 0.0) >= dist.get("absent", 0.0)
        for axis, dist in family_priors.items()
    }
    base_families = enforce_motion_consistency(base_families)

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(decision_points: dict[str, Any], reason: str) -> None:
        key = json.dumps(decision_points, sort_keys=True, separators=(",", ":"))
        if key in seen:
            return
        seen.add(key)
        specs.append(
            {
                "variant_id": _variant_id(decision_points),
                "decision_points": decision_points,
                "selection_reason": reason,
            }
        )

    def _with_base(**updates: Any) -> dict[str, Any]:
        dp = dict(base)
        dp.update(updates)
        merged_families = _merge_confounds_mode_families(
            dp.get("confounds"),
            dp.get("confounds_families") or base_families or None,
        )
        if merged_families:
            dp["confounds_families"] = merged_families
        else:
            dp.pop("confounds_families", None)
        return dp

    # Seed variant
    _add(_with_base(), "base")

    # Coverage requirements for key axes
    coverage_axes = []
    for axis in ("hrf_basis", "confounds", "high_pass"):
        if axis not in axes:
            continue
        options, dist = axes[axis]
        if len(options) < 2:
            continue
        coverage_axes.append(axis)

    for axis in coverage_axes:
        options, dist = axes[axis]
        ordered = _ordered_options(options, dist)
        if len(ordered) < 2:
            continue
        for idx in range(1, len(ordered)):
            alt = _coerce_numeric(ordered[idx])
            _add(
                _with_base(**{axis: alt, "confounds_families": dict(base_families)}),
                "coverage_required",
            )

    # Ensure canonical + derivs appear if available
    if "hrf_basis" in axes and "hrf_basis" in base:
        hrf_opts = {opt for opt in axes["hrf_basis"][0]}
        for hrf in ("canonical", "derivs"):
            if hrf in hrf_opts and base["hrf_basis"] != hrf:
                _add(
                    _with_base(hrf_basis=hrf, confounds_families=dict(base_families)),
                    "coverage_required",
                )

    # Ensure both 6mot and 24mot appear if available
    if "confounds" in axes and "confounds" in base:
        conf_opts = {opt for opt in axes["confounds"][0]}
        for conf in ("6mot", "24mot"):
            if conf in conf_opts and base["confounds"] != conf:
                _add(
                    _with_base(confounds=conf, confounds_families=dict(base_families)),
                    "coverage_required",
                )

    family_variations = [dict(base_families)]
    if family_axes:
        uncertainty = sorted(
            (
                (abs(dist.get("present", 0.0) - dist.get("absent", 0.0)), axis)
                for axis, dist in family_priors.items()
            ),
            key=lambda kv: kv[0],
        )
        for _, axis in uncertainty[:2]:
            alt = dict(base_families)
            alt[axis] = not alt.get(axis, False)
            alt = enforce_motion_consistency(alt)
            family_variations.append(alt)
            dp = _with_base(confounds_families=alt)
            _add(dp, "coverage_required")

        # Ensure we flip each eligible family axis at least once when budget allows.
        for axis in family_axes:
            if len(specs) >= k:
                break
            alt = dict(base_families)
            alt[axis] = not alt.get(axis, False)
            alt = enforce_motion_consistency(alt)
            if alt not in family_variations:
                family_variations.append(alt)
            dp = _with_base(confounds_families=alt)
            _add(dp, "coverage_required")

    # Deterministic grid fill to reach k
    ordered_axes = []
    for axis in sorted(axes.keys(), key=_axis_sort_key):
        options, dist = axes[axis]
        ordered_axes.append((axis, _ordered_options(options, dist)))
    combos = product(*[opts for _, opts in ordered_axes])
    for combo in combos:
        if len(specs) >= k:
            break
        decision_points = {
            axis: _coerce_numeric(val) for (axis, _), val in zip(ordered_axes, combo)
        }
        for fam in family_variations:
            if len(specs) >= k:
                break
            dp = dict(decision_points)
            merged_families = _merge_confounds_mode_families(
                dp.get("confounds"),
                dict(fam) if fam else None,
            )
            if merged_families:
                dp["confounds_families"] = merged_families
            _add(dp, "grid_fill")

    # Fill remaining with weighted sampling
    max_attempts = max(k * 10, 50)
    attempts = 0
    while len(specs) < k and attempts < max_attempts:
        decision_points: dict[str, Any] = {}
        for axis, (options, dist) in axes.items():
            if _axis_source(axis, axis_sources) == "default":
                decision_points[axis] = base[axis]
            else:
                choice = _sample_choice(rng, options, dist)
                decision_points[axis] = _coerce_numeric(choice)

        families: dict[str, bool] = {}
        for axis, dist in family_priors.items():
            if _axis_source(axis, axis_sources) == "default":
                continue
            val = rng.choices(
                ["present", "absent"],
                weights=[dist.get("present", 0.0), dist.get("absent", 0.0)],
                k=1,
            )[0]
            families[axis] = val == "present"
        merged_families = _merge_confounds_mode_families(
            decision_points.get("confounds"),
            families or None,
        )
        if merged_families:
            decision_points["confounds_families"] = merged_families

        _add(decision_points, "priors_weighted")
        attempts += 1

    return specs[:k]


__all__ = ["generate_spec_family"]
