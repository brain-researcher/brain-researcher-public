"""Deterministic canonical-method review for rapidtide sLFO time-lag pipelines.

rapidtide maps systemic low-frequency oscillation (sLFO) blood-arrival delays by
cross-correlating each voxel's timecourse against an iteratively refined probe
regressor over a lag-search window. The most damaging errors are not numeric but
*methodological*: doing a static zero-lag regression, skipping refinement, or
clipping the lag-search range so true delays rail at the boundary. This critic
checks a declared ``method_contract`` (and optional numeric ``subject_summaries``)
against those canonical-method requirements.

Mirrors ``asl_quant_critic.review_asl_quant``: returns a ``CodeReviewVerdict``.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.core.contracts.code_review import (
    CodeReviewVerdict,
    ReviewFinding,
)

# Canonical sLFO band (Hz): low-frequency oscillation, below respiratory/cardiac.
_LFO_BAND_LOW_HZ = 0.009
_LFO_BAND_HIGH_HZ = 0.15
# A lag-search window narrower than this (seconds, total span) clips real sLFO
# transit delays, which span roughly -10..+10 s across the brain.
_MIN_LAG_SEARCH_SPAN_S = 8.0
# Canonical refinement uses multiple passes to purify the probe regressor.
_MIN_REFINEMENT_PASSES = 2
# Long TR needs oversampling for sub-TR lag resolution.
_OVERSAMPLE_TR_THRESHOLD_S = 1.5
# Fraction of voxels whose peak lag sits at the search boundary that indicates a
# genuinely too-narrow window (observable confirmation, not just a declaration).
_LAG_BOUNDARY_RAIL_FRACTION = 0.10

_REASON_TAGS = ["rapidtide", "slfo_lag", "method_appropriateness"]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    low, high = _as_float(value[0]), _as_float(value[1])
    if low is None or high is None:
        return None
    return (min(low, high), max(low, high))


def _make_finding(
    *,
    rule_id: str,
    severity: str,
    action: str,
    message: str,
    suggested_fix: str,
    artifact_name: str | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        rule_id=rule_id,
        severity=severity,
        action=action,
        message=message,
        suggested_fix=suggested_fix,
        artifact_name=artifact_name,
        reason_tags=list(_REASON_TAGS),
    )


def _roll_up(findings: list[ReviewFinding]) -> tuple[str, str]:
    if not findings:
        return "approve", "low"
    if any(f.action == "block" or f.severity == "critical" for f in findings):
        return "block", "critical"
    if any(f.severity == "error" for f in findings):
        return "revise", "high"
    return "approve_with_warnings", "medium"


def _rationale(findings: list[ReviewFinding], decision: str) -> str:
    if not findings:
        return f"rapidtide method review passed all canonical checks. Decision: {decision}."
    head = [
        f"rapidtide method review — Decision: {decision}. {len(findings)} finding(s):"
    ]
    for finding in findings[:5]:
        head.append(
            f"[{finding.severity.upper()}] {finding.rule_id}: {finding.message}"
        )
    return " | ".join(head)


def _checklist(method_contract: dict[str, Any]) -> list[str]:
    return [
        "cross_correlation_lag_search",
        "lag_search_range_s",
        "refinement_passes",
        "temporal_filter_band_hz",
        "regressor_source",
    ]


def review_rapidtide_implementation(
    *,
    task_profile: str,
    method_contract: dict[str, Any],
    subject_summaries: list[dict[str, Any]] | None = None,
) -> CodeReviewVerdict:
    """Review a rapidtide-style sLFO lag analysis against the canonical method.

    ``method_contract`` declares how the analysis was configured. Recognized
    keys (all optional; missing ones skip their check, except the lag-search
    contract whose absence blocks): ``cross_correlation_lag_search`` (bool),
    ``lag_search_range_s`` ([low, high] s), ``refinement_passes`` (int),
    ``regressor_source`` ("refined_sLFO" | "global_mean" | ...),
    ``temporal_filter_band_hz`` ([low, high] Hz), ``oversample_factor`` (number),
    ``tr_s`` (number), ``lag_map_despeckle`` (bool).
    """

    profile = _as_str(task_profile)
    if not profile:
        raise ValueError("task_profile is required")
    if not isinstance(method_contract, dict):
        raise ValueError("method_contract must be an object")
    if subject_summaries is not None and not isinstance(subject_summaries, list):
        raise ValueError("subject_summaries must be a list when provided")

    findings: list[ReviewFinding] = []

    # 1. The defining canonical step: cross-correlation lag search. A static
    #    zero-lag regression is a different (wrong) method for sLFO delay mapping.
    if "cross_correlation_lag_search" in method_contract and not _as_bool(
        method_contract.get("cross_correlation_lag_search")
    ):
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_STATIC_ZERO_LAG_CORRELATION",
                severity="critical",
                action="block",
                message=(
                    "Analysis uses a static (zero-lag) regression instead of a "
                    "time-lagged cross-correlation search. This is not the "
                    "canonical rapidtide sLFO delay-mapping method."
                ),
                suggested_fix=(
                    "Search peak cross-correlation over a lag window per voxel; "
                    "do not fit a single fixed-lag GLM."
                ),
            )
        )

    # 2. Lag-search window: required, and must be wide enough not to clip delays.
    lag_range = _pair(method_contract.get("lag_search_range_s"))
    if lag_range is None:
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_LAG_SEARCH_RANGE_MISSING",
                severity="error",
                action="block",
                message="No lag-search range declared; cannot verify sLFO delays are not clipped.",
                suggested_fix="Declare lag_search_range_s, e.g. [-10, 10] s, covering plausible transit delays.",
            )
        )
    else:
        span = lag_range[1] - lag_range[0]
        if span < _MIN_LAG_SEARCH_SPAN_S:
            findings.append(
                _make_finding(
                    rule_id="RAPIDTIDE_LAG_SEARCH_RANGE_TOO_NARROW",
                    severity="error",
                    action="block",
                    message=(
                        f"Lag-search span {span:.1f}s is narrower than the "
                        f"~{_MIN_LAG_SEARCH_SPAN_S:.0f}s needed for whole-brain sLFO "
                        "transit delays; true peaks will rail at the boundary."
                    ),
                    suggested_fix="Widen lag_search_range_s (e.g. [-10, 10] s) and re-run.",
                )
            )

    # 3. Probe-regressor refinement (canonical iterative purification).
    passes = method_contract.get("refinement_passes")
    passes_num = _as_float(passes)
    if passes_num is not None and passes_num < _MIN_REFINEMENT_PASSES:
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_NO_REGRESSOR_REFINEMENT",
                severity="error",
                action="warn",
                message=(
                    f"Only {int(passes_num)} refinement pass(es); the canonical "
                    "method iteratively refines the probe regressor (>= "
                    f"{_MIN_REFINEMENT_PASSES})."
                ),
                suggested_fix="Run >=2 refinement passes so the regressor reflects the sLFO, not the raw global mean.",
            )
        )

    # 4. Naive global-mean regressor without refinement.
    regressor_source = (_as_str(method_contract.get("regressor_source")) or "").lower()
    if regressor_source in {"global_mean", "global_signal", "mean"} and (
        passes_num is None or passes_num < _MIN_REFINEMENT_PASSES
    ):
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_NAIVE_GLOBAL_REGRESSOR",
                severity="warn",
                action="warn",
                message=(
                    "Probe regressor is the raw global mean without refinement; "
                    "this conflates sLFO with non-sLFO global signal."
                ),
                suggested_fix="Derive and iteratively refine the sLFO probe regressor instead of using the raw global mean.",
            )
        )

    # 5. Temporal filter band must isolate the LFO band.
    band = _pair(method_contract.get("temporal_filter_band_hz"))
    if band is not None and (
        band[0] < _LFO_BAND_LOW_HZ - 1e-6 or band[1] > _LFO_BAND_HIGH_HZ + 1e-6
    ):
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_FILTER_BAND_OUTSIDE_LFO",
                severity="warn",
                action="warn",
                message=(
                    f"Temporal filter band [{band[0]:.3g}, {band[1]:.3g}] Hz extends "
                    f"outside the sLFO band [{_LFO_BAND_LOW_HZ}, {_LFO_BAND_HIGH_HZ}] Hz; "
                    "respiratory/cardiac signal can contaminate the regressor."
                ),
                suggested_fix="Restrict the bandpass to the LFO band (~0.009-0.15 Hz).",
            )
        )

    # 6. Oversampling for sub-TR lag resolution when TR is long.
    tr_s = _as_float(method_contract.get("tr_s"))
    oversample = _as_float(method_contract.get("oversample_factor"))
    if (
        tr_s is not None
        and tr_s >= _OVERSAMPLE_TR_THRESHOLD_S
        and oversample is not None
        and oversample < 2.0
    ):
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_INSUFFICIENT_OVERSAMPLING",
                severity="warn",
                action="warn",
                message=(
                    f"TR={tr_s:.2g}s with oversample_factor={oversample:.2g}; lag "
                    "resolution is limited to the TR without oversampling."
                ),
                suggested_fix="Increase oversample_factor (>=2) for sub-TR lag resolution at long TR.",
            )
        )

    # 7. Lag-map despeckling.
    if "lag_map_despeckle" in method_contract and not _as_bool(
        method_contract.get("lag_map_despeckle")
    ):
        findings.append(
            _make_finding(
                rule_id="RAPIDTIDE_LAG_MAP_NO_DESPECKLE",
                severity="warn",
                action="warn",
                message="Lag-map despeckling disabled; isolated voxels can hold spurious extreme lags.",
                suggested_fix="Enable despeckling so neighbours correct isolated lag outliers.",
            )
        )

    # 8. Observable confirmation: peak lags railing at the search boundary.
    for summary in subject_summaries or []:
        if not isinstance(summary, dict):
            continue
        sid = _as_str(summary.get("subject")) or _as_str(summary.get("id"))
        rail = _as_float(summary.get("lag_boundary_fraction"))
        if rail is not None and rail > _LAG_BOUNDARY_RAIL_FRACTION:
            findings.append(
                _make_finding(
                    rule_id="RAPIDTIDE_LAG_RAILING_AT_BOUNDARY",
                    severity="error",
                    action="block",
                    artifact_name=sid,
                    message=(
                        f"{rail:.0%} of voxels peak at the lag-search boundary"
                        + (f" in {sid}" if sid else "")
                        + "; the search window truncates real delays."
                    ),
                    suggested_fix="Widen the lag-search range until boundary railing is negligible, then re-run.",
                )
            )

    decision, risk_level = _roll_up(findings)
    return CodeReviewVerdict(
        decision=decision,
        risk_level=risk_level,
        findings=findings,
        kg_rules_consulted=[],
        checklist_generated=_checklist(method_contract),
        reviewer_rationale=_rationale(findings, decision),
    )


__all__ = ["review_rapidtide_implementation"]
