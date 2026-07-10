"""Methodological evidence-quality scorer for the named uncertainty vector.

``society/uncertainty.py`` reserves an ``evidence_quality`` axis: a study-quality /
method-rigor weight kept *separate* from the scientific association probability. Until
now that axis was a slot — the compiler passed ``evidence_quality=None``, so it always
surfaced as an unresolved 'sorry'. This module fills it with a **transparent,
deterministic, documented** scorer (NOT a learned model): it maps the methodological
metadata a backend already exposes (study count, evidence balance, significance/
inference tier, sensitivity-flip fragility, and — when available — multiverse
robustness) onto a single ``[0, 1]`` quality weight.

The HARD invariant (status-doc §5, "no laundering"): this scorer reads ONLY
methodological / robustness signals. It MUST NOT read the association probability or
the extraction confidence. Method rigor is *orthogonal* to how strong the association
looks and to how sure we are we transcribed the paper right — a confidently-extracted,
strongly-associated finding from a single underpowered study is still low-quality
evidence. :func:`score_evidence_quality` therefore never accepts an ``association_p``
or ``extraction_confidence`` argument, and the unit tests assert the laundering
contract directly.

Design principles:

* **Deterministic + transparent.** Every contributing factor is a small, named,
  bounded term; the returned :class:`EvidenceQuality` carries the per-factor
  breakdown and a human-readable rationale, so the number is always auditable.
* **Conservative under missing metadata.** With no usable signals the score degrades
  to a low floor (never crashes, never silently scores high). Absence of evidence of
  quality is treated as low quality, not as neutral.
* **Multiverse robustness is asymmetric — it can only CAP DOWN or CONFIRM, never
  raise.** A pipeline-fragile or sign-flipping result caps quality regardless of the
  other factors (this mirrors the multiverse claim-strength ceiling, applied to the
  *evidence-quality* axis). A *non-fragile* multiverse is treated purely as
  confirmation: it never lifts the methodological base above what the methodological
  factors alone support, and never penalises a strong base just because the multiverse
  is merely modest-but-non-fragile. Robustness alone — with no usable methodological
  factor — therefore cannot produce a score above :data:`NO_SIGNAL_QUALITY`. (Letting a
  50/50 base⊕robustness blend raise a weak base, or drop a strong one, would launder
  robustness into the orthogonal methodological axis in BOTH directions; it does not.)
* **Study count is monotonically non-decreasing.** Adding a study can never lower the
  methodological base: the anecdotal (n < ``_MIN_STUDIES``) and linear branches of the
  study-count factor meet continuously at ``_STUDY_BASE_ANCHOR``.

Nothing here imports the service tier, so the module is safe inside ``autoresearch``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

#: Conservative floor when no usable methodological signal is present. Low, not zero:
#: "we could not assess rigor", not "we assessed it and it is null".
NO_SIGNAL_QUALITY: float = 0.2

#: Study-count saturation points. Below ``_MIN_STUDIES`` the count is treated as noise;
#: at/above ``_AMPLE_STUDIES`` the count contributes its full weight. (Neurosynth-era
#: convention: a handful of studies is anecdotal, dozens is a meta-analytic base.)
_MIN_STUDIES: int = 3
_AMPLE_STUDIES: int = 25

#: Per-factor weights (sum to 1.0) for the methodological base score. Each factor is
#: computed in ``[0, 1]`` and the base is their weighted mean over the factors that
#: have a usable signal (missing factors are dropped, then re-normalised).
_WEIGHTS: dict[str, float] = {
    "study_base": 0.35,  # how many studies underpin the association
    "evidence_balance": 0.25,  # supporting vs conflicting balance
    "inference_tier": 0.25,  # forward-convergence < reverse/specificity rigor
    "sensitivity": 0.15,  # survives a stricter evidence bar?
}

#: Inference-mode rigor tiers. Reverse inference / specificity directly answers the
#: cognitive-engagement question; forward convergence is weaker evidence for it.
_INFERENCE_TIER: dict[str, float] = {
    "reverse_specificity": 1.0,
    "reverse": 1.0,
    "compositional_forward": 0.85,
    "network_coactivation": 0.8,
    "forward_inference": 0.6,
    "forward_convergence": 0.5,
}
#: Default tier when the inference mode is unknown/blank (e.g. the KG backend) — neutral.
_DEFAULT_INFERENCE_TIER: float = 0.55

#: Multiverse-robustness floors that CAP evidence quality regardless of the base score.
#: A sign-flipping or pipeline-fragile result is low-quality evidence by construction.
_MULTIVERSE_SIGN_FLOOR: float = 0.9  # below this sign_consistency -> hard cap
_MULTIVERSE_ACTIVE_FLOOR: float = 0.5  # below this active_frac -> hard cap
_MULTIVERSE_FRAGILE_CAP: float = 0.3  # quality ceiling for a fragile multiverse result


def _clamp01(x: float) -> float:
    """Clamp ``x`` into ``[0, 1]``, mapping NaN/inf to the CONSERVATIVE end.

    ``min(1.0, nan)`` returns ``1.0`` in Python, so a naive clamp would turn a
    non-finite (uncomputed) input into the maximum quality and silently bypass the
    fragile cap. A non-finite input is "no usable measurement", which is the
    conservative ``0.0`` end — never ``1.0``.
    """
    xf = float(x)
    if not math.isfinite(xf):
        return 0.0
    return max(0.0, min(1.0, xf))


class EvidenceQuality(BaseModel):
    """A transparent methodological-quality score with its per-factor breakdown."""

    value: float = Field(..., ge=0.0, le=1.0)
    factors: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""
    used_signals: list[str] = Field(default_factory=list)


#: Value of ``study_base`` exactly at the anecdotal→linear boundary (n == _MIN_STUDIES).
#: The anecdotal branch climbs *up to* this value and the linear branch starts *from*
#: it, so the factor is monotonically non-decreasing across the boundary (H13 fix: a
#: linear branch starting at 0.0 used to drop below the anecdotal n==2 value, so adding
#: a study lowered the methodological base — a non-monotonic cliff at n=2 -> n=3).
_STUDY_BASE_ANCHOR: float = 0.15


def _study_base_factor(n_supporting: int, n_conflicting: int) -> float | None:
    """Saturating, MONOTONICALLY NON-DECREASING function of the study count.

    Below ``_MIN_STUDIES`` total this is anecdotal (low) and climbs linearly to
    ``_STUDY_BASE_ANCHOR`` at the boundary; at/above ``_MIN_STUDIES`` it continues from
    that same anchor up to full weight at ``_AMPLE_STUDIES``. The two branches meet at
    ``_STUDY_BASE_ANCHOR`` so adding a study can never LOWER the base (H13). Conflicting
    studies still count as *evidence that was examined*, so they add to the base (their
    direction is handled by the balance factor, not here).
    """
    n = int(n_supporting or 0) + int(n_conflicting or 0)
    if n <= 0:
        return None
    if n < _MIN_STUDIES:
        # Anecdotal: a fraction of the way to the boundary anchor, hard-capped low.
        return _clamp01(_STUDY_BASE_ANCHOR * (n / _MIN_STUDIES))
    span = max(1, _AMPLE_STUDIES - _MIN_STUDIES)
    # Resume from the anchor (not 0.0) so the linear branch is continuous with the
    # anecdotal branch and never dips below the n == _MIN_STUDIES - 1 value.
    progress = min(1.0, (n - _MIN_STUDIES) / span)
    return _clamp01(_STUDY_BASE_ANCHOR + (1.0 - _STUDY_BASE_ANCHOR) * progress)


def _evidence_balance_factor(n_supporting: int, n_conflicting: int) -> float | None:
    """Supporting share of the examined evidence (1.0 = unanimous, 0.5 = split)."""
    s = int(n_supporting or 0)
    c = int(n_conflicting or 0)
    total = s + c
    if total <= 0:
        return None
    return _clamp01(s / total)


def _inference_tier_factor(inference: str) -> float | None:
    if not inference:
        return None
    return _INFERENCE_TIER.get(inference.strip().lower(), _DEFAULT_INFERENCE_TIER)


def _sensitivity_factor(verdict_survives: bool | None) -> float | None:
    """1.0 when the verdict survives the strict bar, low when it is threshold-fragile."""
    if verdict_survives is None:
        return None
    return 1.0 if verdict_survives else 0.25


def score_evidence_quality(
    *,
    n_supporting: int = 0,
    n_conflicting: int = 0,
    inference: str = "",
    verdict_survives: bool | None = None,
    multiverse: dict[str, Any] | Any | None = None,
) -> EvidenceQuality:
    """Score the *methodological* quality of the evidence in ``[0, 1]``.

    Deliberately accepts ONLY method/robustness signals — never the association
    probability or extraction confidence — so it cannot launder either into the
    quality axis (see module docstring; the unit tests assert this).

    Args:
        n_supporting / n_conflicting: study counts behind the verdict (sample-size /
            corpus-coverage proxy + evidence balance).
        inference: the backend's inference mode (forward vs reverse/specificity) — a
            rigor tier for the *kind* of evidence.
        verdict_survives: whether the verdict survived the conservative sensitivity
            sweep (``None`` when the sweep did not run).
        multiverse: an optional multiverse-robustness profile (a mapping or an object
            with ``active_frac`` / ``sign_consistency`` / ``effect_size_stability``).
            When present and fragile it CAPS the score regardless of the base factors.

    Returns:
        An :class:`EvidenceQuality` with the value, per-factor breakdown, the list of
        signals that were actually usable, and a human-readable rationale. With no
        usable signal the value degrades to :data:`NO_SIGNAL_QUALITY` (conservative),
        never raising.
    """
    factors: dict[str, float] = {}
    candidates = {
        "study_base": _study_base_factor(n_supporting, n_conflicting),
        "evidence_balance": _evidence_balance_factor(n_supporting, n_conflicting),
        "inference_tier": _inference_tier_factor(inference),
        "sensitivity": _sensitivity_factor(verdict_survives),
    }
    used: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for name, val in candidates.items():
        if val is None:
            continue
        factors[name] = round(val, 4)
        used.append(name)
        w = _WEIGHTS[name]
        weighted_sum += w * val
        weight_total += w

    if weight_total <= 0.0:
        base = NO_SIGNAL_QUALITY
        rationale = (
            f"no usable methodological signal — conservative floor {NO_SIGNAL_QUALITY:.2f}"
        )
    else:
        base = _clamp01(weighted_sum / weight_total)
        rationale = (
            "weighted methodological factors "
            + ", ".join(f"{k}={factors[k]:.2f}" for k in used)
            + f" -> base {base:.2f}"
        )

    value = base
    has_method_signal = weight_total > 0.0
    mv = _multiverse_factor(multiverse)
    if mv is not None:
        mv_value, mv_capped, mv_note = mv
        used.append("multiverse")
        factors["multiverse"] = round(mv_value, 4)
        if mv_capped:
            value = min(base, _MULTIVERSE_FRAGILE_CAP)
            rationale += f"; {mv_note} -> capped at {_MULTIVERSE_FRAGILE_CAP:.2f}"
        else:
            # H8: multiverse robustness is ASYMMETRIC. It may only cap DOWN when fragile
            # (the branch above) or act as a NON-RAISING confirmation otherwise. A
            # non-fragile multiverse must NOT lift the methodological base above what the
            # methodological factors alone support (so a single anecdotal study is not
            # laundered up just because a robustness profile exists), and must NOT drop a
            # strong base merely because the multiverse is modest-but-non-fragile. So we
            # leave ``value = base`` untouched. When there is NO usable methodological
            # factor, robustness alone cannot manufacture quality above the no-signal
            # floor, so we additionally cap at NO_SIGNAL_QUALITY.
            if not has_method_signal:
                value = min(base, NO_SIGNAL_QUALITY)
            rationale += (
                f"; {mv_note} -> non-raising confirmation, base held at {value:.2f}"
            )

    return EvidenceQuality(
        value=round(_clamp01(value), 4),
        factors=factors,
        rationale=rationale,
        used_signals=used,
    )


def _multiverse_factor(
    multiverse: dict[str, Any] | Any | None,
) -> tuple[float, bool, str] | None:
    """Reduce a multiverse-robustness profile to ``(quality_factor, capped, note)``.

    ``capped`` is True when the profile is fragile (sign-flipping or low survival),
    which forces a hard quality ceiling upstream. Returns ``None`` when no profile is
    supplied (graceful degradation: the multiverse factor is simply absent).
    """
    if multiverse is None:
        return None

    def _get(key: str) -> Any:
        if isinstance(multiverse, dict):
            return multiverse.get(key)
        return getattr(multiverse, key, None)

    active = _get("active_frac")
    sign = _get("sign_consistency")
    esz = _get("effect_size_stability")
    if active is None and sign is None:
        return None

    def _is_nonfinite(v: Any) -> bool:
        try:
            return not math.isfinite(float(v))
        except (TypeError, ValueError):
            # Unparseable cell -> treat as a missing/uncomputed (i.e. fragile) signal.
            return True

    # A non-finite (uncomputed/NaN/inf) survival or sign cell is the FRAGILE direction:
    # never let it classify a profile as robust. ``_clamp01`` already maps such a value
    # to ``0.0``, but we also flag fragility explicitly so the cap fires independently of
    # the floor thresholds.
    nonfinite_active = active is not None and _is_nonfinite(active)
    nonfinite_sign = sign is not None and _is_nonfinite(sign)

    a = _clamp01(active if active is not None else 0.0)
    s = _clamp01(sign if sign is not None else 0.0)
    components = [a, s]
    if esz is not None:
        components.append(_clamp01(esz))
    factor = sum(components) / len(components)

    fragile = (
        nonfinite_active
        or nonfinite_sign
        or s < _MULTIVERSE_SIGN_FLOOR
        or a < _MULTIVERSE_ACTIVE_FLOOR
    )
    if fragile:
        note = (
            f"multiverse fragile (active_frac {a:.2f}, sign_consistency {s:.2f})"
        )
        return factor, True, note
    note = f"multiverse robust (active_frac {a:.2f}, sign_consistency {s:.2f})"
    return factor, False, note
