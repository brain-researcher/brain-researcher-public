"""Deterministic numeric review for ASL quantification pipelines."""

from __future__ import annotations

import re
from typing import Any

from brain_researcher.core.contracts.code_review import (
    CodeReviewVerdict,
    ReviewFinding,
)

_SYNTHETIC_SUBJECT_RE = re.compile(r"^sub-0[1-3]$")
_FIT_FAILURE_RULE_IDS = {
    "ASL_MULTI_PLD_FIT_CORRELATION_LOW",
    "ASL_MULTI_PLD_FIT_NRMSE_HIGH",
    "ASL_MULTI_PLD_DELTA_M_CURVE_MISMATCH",
    "ASL_2D_EFFECTIVE_PLD_NOT_APPLIED",
    "ASL_2D_EFFECTIVE_PLD_SPAN_ZERO",
}
_SCALE_WARNING_RULE_IDS = {
    "ASL_SYNTHETIC_P99_TOO_HIGH",
    "ASL_SYNTHETIC_GM_MEAN_OUT_OF_RANGE",
    "ASL_SYNTHETIC_WM_MEAN_OUT_OF_RANGE",
    "ASL_SYNTHETIC_GM_WM_INVERSION",
    "ASL_REAL_GM_CV_OUT_OF_RANGE",
    "ASL_REAL_GM_MEAN_OUT_OF_RANGE",
    "ASL_REAL_GM_WM_RATIO_STD_HIGH",
}
_AMPLITUDE_ONLY_FORBIDDEN_CHANGES = [
    "pld_att_convention",
    "slice_timing_logic",
    "single_vs_multi_pld_branching",
    "joint_multi_pld_fit_structure",
    "post_review_cohort_harmonization",
]
_AMPLITUDE_ONLY_TARGETED_CHECKS = [
    "m0_scale_factor_application",
    "m0_volume_aggregation",
    "cbf_prefactor_units",
    "labeling_efficiency_alpha",
    "blood_brain_partition_coefficient_lambda",
    "amplitude_normalization_terms",
]
_RULE_TO_TARGETED_CHECKS = {
    "ASL_MULTI_PLD_REQUIRES_JOINT_FIT": ["joint_multi_pld_fit"],
    "ASL_MULTI_PLD_SINGLE_FORMULA_AVERAGING": ["joint_multi_pld_fit"],
    "ASL_BIDS_PLD_CONVENTION_REQUIRED": ["pld_att_convention"],
    "ASL_2D_SLICE_TIMING_MISSING": ["slice_timing_logic"],
    "ASL_M0_SCALE_FACTOR_IGNORED": ["m0_scale_factor_application"],
    "ASL_MULTI_PLD_FIT_CORRELATION_LOW": ["delta_m_curve_fit"],
    "ASL_MULTI_PLD_FIT_NRMSE_HIGH": ["delta_m_curve_fit"],
    "ASL_MULTI_PLD_DELTA_M_CURVE_MISMATCH": ["delta_m_curve_fit"],
    "ASL_2D_EFFECTIVE_PLD_NOT_APPLIED": ["slice_timing_logic"],
    "ASL_2D_EFFECTIVE_PLD_SPAN_ZERO": ["slice_timing_logic"],
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return False


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _as_float_list(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for item in value:
        parsed = _as_float(item)
        if parsed is None:
            return None
        out.append(parsed)
    return out or None


def _first_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _as_float(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _first_float_list(payload: dict[str, Any], *keys: str) -> list[float] | None:
    for key in keys:
        parsed = _as_float_list(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    x_centered = [x - mean_x for x in xs]
    y_centered = [y - mean_y for y in ys]
    num = sum(x * y for x, y in zip(x_centered, y_centered, strict=False))
    den_x = sum(x * x for x in x_centered) ** 0.5
    den_y = sum(y * y for y in y_centered) ** 0.5
    if den_x <= 1e-12 or den_y <= 1e-12:
        return None
    return num / (den_x * den_y)


def _infer_subject_type(summary: dict[str, Any]) -> str | None:
    explicit = _as_str(summary.get("subject_type"))
    if explicit:
        normalized = explicit.lower().replace("-", "_")
        if normalized in {"synthetic", "phantom", "simulated"}:
            return "synthetic"
        if normalized in {"real", "invivo", "in_vivo"}:
            return "real"
    sid = _as_str(summary.get("subject_id")) or ""
    if _SYNTHETIC_SUBJECT_RE.match(sid):
        return "synthetic"
    return None


def _subject_regime(summary: dict[str, Any]) -> str | None:
    regime = _as_str(summary.get("regime"))
    if regime:
        return regime.lower().replace("-", "_")
    n_unique_plds = _as_float(summary.get("n_unique_plds"))
    if n_unique_plds is not None:
        return "multi_pld" if n_unique_plds > 1 else "single_pld"
    return None


def _has_slice_timing(summary: dict[str, Any]) -> bool:
    return _as_bool(summary.get("has_slice_timing")) or _as_bool(
        summary.get("slice_timing_present")
    )


def _has_m0_scale_factor(summary: dict[str, Any]) -> bool:
    if _as_bool(summary.get("m0_scale_factor_present")):
        return True
    scale = _as_float(summary.get("m0_scale_factor"))
    return scale is not None and abs(scale - 1.0) > 1e-6


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
        return f"ASL quant review passed all checks. Decision: {decision}."
    head = [f"ASL quant review — Decision: {decision}. {len(findings)} finding(s):"]
    for finding in findings[:5]:
        head.append(
            f"[{finding.severity.upper()}] {finding.rule_id}: {finding.message}"
        )
    return " | ".join(head)


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
        reason_tags=["asl", "quantification"],
    )


def _curve_corr_from_summary(summary: dict[str, Any]) -> float | None:
    observed_curve = _first_float_list(
        summary,
        "delta_m_curve_means",
        "observed_delta_m_curve_means",
    )
    predicted_curve = _first_float_list(
        summary,
        "predicted_delta_m_curve_means",
        "fit_delta_m_curve_means",
    )
    if observed_curve is None or predicted_curve is None:
        return None
    return _pearson_r(observed_curve, predicted_curve)


def _strong_multi_pld_fit_observables(subject_summaries: list[dict[str, Any]]) -> bool:
    fit_subjects = [
        summary
        for summary in subject_summaries
        if _subject_regime(summary) == "multi_pld"
        and _infer_subject_type(summary) == "synthetic"
    ]
    if not fit_subjects:
        return False

    has_any_fit_metric = False
    for summary in fit_subjects:
        fit_corr = _first_float(
            summary,
            "fit_curve_corr_proxy",
            "multi_pld_fit_corr",
            "fit_corr_proxy",
        )
        fit_nrmse = _first_float(
            summary,
            "fit_curve_nrmse_proxy",
            "multi_pld_fit_nrmse",
            "fit_nrmse_proxy",
        )
        curve_corr = _curve_corr_from_summary(summary)

        if fit_corr is not None:
            has_any_fit_metric = True
            if fit_corr < 0.97:
                return False
        if fit_nrmse is not None:
            has_any_fit_metric = True
            if fit_nrmse > 0.05:
                return False
        if curve_corr is not None:
            has_any_fit_metric = True
            if curve_corr < 0.97:
                return False
    return has_any_fit_metric


def _extreme_scale_pattern(subject_summaries: list[dict[str, Any]]) -> bool:
    for summary in subject_summaries:
        if _infer_subject_type(summary) != "synthetic":
            continue
        p99 = _as_float(summary.get("brain_p99"))
        gm = _as_float(summary.get("gm_mean_proxy"))
        wm = _as_float(summary.get("wm_mean_proxy"))
        if p99 is not None and p99 > 200.0:
            return True
        if gm is not None and gm > 100.0:
            return True
        if wm is not None and wm > 45.0:
            return True
    return False


def build_asl_quant_control(
    *,
    verdict: CodeReviewVerdict,
    subject_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return machine-readable control signals for the outer agent."""

    finding_ids = {finding.rule_id for finding in verdict.findings}
    targeted_checks: list[str] = []
    for finding in verdict.findings:
        targeted_checks.extend(_RULE_TO_TARGETED_CHECKS.get(finding.rule_id, []))
    targeted_checks = list(dict.fromkeys(targeted_checks))

    has_fit_failures = bool(finding_ids & _FIT_FAILURE_RULE_IDS)
    scale_warning_count = sum(
        1 for finding in verdict.findings if finding.rule_id in _SCALE_WARNING_RULE_IDS
    )
    strong_fit = _strong_multi_pld_fit_observables(subject_summaries)
    extreme_scale = _extreme_scale_pattern(subject_summaries)
    amplitude_only_pattern = (
        verdict.decision == "approve_with_warnings"
        and not has_fit_failures
        and strong_fit
        and (scale_warning_count >= 3 or extreme_scale)
    )

    if verdict.decision == "block":
        return {
            "protocol": "br.asl_quant_review.control.v1",
            "should_revise": True,
            "rewrite_scope": "block",
            "dominant_issue_class": "blocked_specification",
            "forbidden_changes": ["post_review_cohort_harmonization"],
            "targeted_checks": targeted_checks,
            "rationale": (
                "Blocking methodological issues were found; revise the solver once "
                "to satisfy the blocking requirements before rerunning."
            ),
        }

    if verdict.decision == "revise":
        return {
            "protocol": "br.asl_quant_review.control.v1",
            "should_revise": True,
            "rewrite_scope": "fit_model",
            "dominant_issue_class": "fit_observable_failure",
            "forbidden_changes": ["post_review_cohort_harmonization"],
            "targeted_checks": targeted_checks,
            "rationale": (
                "Fit-observable failures were found; revise the forward model or "
                "2D effective-PLD logic once before rerunning."
            ),
        }

    if amplitude_only_pattern:
        return {
            "protocol": "br.asl_quant_review.control.v1",
            "should_revise": True,
            "rewrite_scope": "amplitude_only",
            "dominant_issue_class": "amplitude_calibration",
            "forbidden_changes": list(_AMPLITUDE_ONLY_FORBIDDEN_CHANGES),
            "targeted_checks": list(_AMPLITUDE_ONLY_TARGETED_CHECKS),
            "rationale": (
                "Fit-to-data observables are already strong, but scale warnings are "
                "extreme. If you revise, limit the rewrite to amplitude calibration "
                "terms only and keep the timing convention and slice-timing logic fixed."
            ),
        }

    return {
        "protocol": "br.asl_quant_review.control.v1",
        "should_revise": False,
        "rewrite_scope": "none",
        "dominant_issue_class": "advisory_only",
        "forbidden_changes": list(_AMPLITUDE_ONLY_FORBIDDEN_CHANGES),
        "targeted_checks": [],
        "rationale": (
            "No blocking or fit-observable failures were found. Do not modify the "
            "physics/math code after this review."
        ),
    }


def _build_checklist(
    task_profile: str,
    subject_summaries: list[dict[str, Any]],
) -> list[str]:
    regimes = sorted(
        {
            regime
            for summary in subject_summaries
            if (regime := _subject_regime(summary)) is not None
        }
    )
    synthetic = sum(
        1
        for summary in subject_summaries
        if _infer_subject_type(summary) == "synthetic"
    )
    real = sum(
        1 for summary in subject_summaries if _infer_subject_type(summary) == "real"
    )
    has_2d = any(
        (_as_str(summary.get("acquisition_type")) or "").lower() == "2d"
        or (_as_str(summary.get("dimensionality")) or "").lower() == "2d"
        for summary in subject_summaries
    )
    has_slice_timing = any(_has_slice_timing(summary) for summary in subject_summaries)
    has_m0_scale = any(_has_m0_scale_factor(summary) for summary in subject_summaries)
    return [
        f"Task profile: {task_profile}",
        f"Subject summaries provided: {len(subject_summaries)}",
        f"Regimes present: {', '.join(regimes) if regimes else 'unknown'}",
        f"Synthetic summaries: {synthetic}",
        f"Real summaries: {real}",
        f"2D acquisitions present: {has_2d}",
        f"SliceTiming present: {has_slice_timing}",
        f"M0ScaleFactor present: {has_m0_scale}",
    ]


def review_asl_quant(
    *,
    task_profile: str,
    method_contract: dict[str, Any],
    subject_summaries: list[dict[str, Any]],
    cohort_summary: dict[str, Any] | None = None,
) -> CodeReviewVerdict:
    """Review ASL quantification method claims against lightweight numeric summaries."""

    profile = _as_str(task_profile)
    if not profile:
        raise ValueError("task_profile is required")
    if not isinstance(method_contract, dict):
        raise ValueError("method_contract must be an object")
    if not isinstance(subject_summaries, list) or not subject_summaries:
        raise ValueError("subject_summaries must be a non-empty list")
    if not all(isinstance(item, dict) for item in subject_summaries):
        raise ValueError("every subject summary must be an object")
    if cohort_summary is not None and not isinstance(cohort_summary, dict):
        raise ValueError("cohort_summary must be an object when provided")

    summaries = [dict(item) for item in subject_summaries]
    cohort = dict(cohort_summary or {})
    findings: list[ReviewFinding] = []
    checklist = _build_checklist(profile, summaries)

    regimes = {regime for summary in summaries if (regime := _subject_regime(summary))}
    mixed_regimes = len(regimes) > 1
    has_multi_pld = "multi_pld" in regimes
    has_2d_slice_timing = any(
        _has_slice_timing(summary)
        and (
            (_as_str(summary.get("acquisition_type")) or "").lower() == "2d"
            or (_as_str(summary.get("dimensionality")) or "").lower() == "2d"
        )
        for summary in summaries
    )
    has_m0_scale = any(_has_m0_scale_factor(summary) for summary in summaries)

    if mixed_regimes and not _as_bool(
        method_contract.get("separate_single_and_multi_pld")
    ):
        findings.append(
            _make_finding(
                rule_id="ASL_SEPARATE_REGIMES_REQUIRED",
                severity="critical",
                action="block",
                message="Mixed single-PLD and multi-PLD cohorts require separate quantification branches.",
                suggested_fix="Branch by unique PLD count per subject before quantification.",
            )
        )

    if has_multi_pld and not _as_bool(method_contract.get("uses_joint_multi_pld_fit")):
        findings.append(
            _make_finding(
                rule_id="ASL_MULTI_PLD_REQUIRES_JOINT_FIT",
                severity="critical",
                action="block",
                message="Multi-PLD subjects require a joint kinetic fit over PLD, not a single-delay formula.",
                suggested_fix="Fit CBF and ATT jointly from the PLD-dependent signal.",
            )
        )

    if _as_bool(method_contract.get("averages_single_pld_cbf_across_plds")):
        findings.append(
            _make_finding(
                rule_id="ASL_MULTI_PLD_SINGLE_FORMULA_AVERAGING",
                severity="critical",
                action="block",
                message="Averaging per-PLD single-PLD CBF estimates is not valid for multi-PLD ASL.",
                suggested_fix="Replace per-PLD averaging with a joint multi-PLD kinetic model.",
            )
        )

    if has_multi_pld and not _as_bool(method_contract.get("uses_bids_pld_convention")):
        findings.append(
            _make_finding(
                rule_id="ASL_BIDS_PLD_CONVENTION_REQUIRED",
                severity="critical",
                action="block",
                message="The multi-PLD timing convention must be consistent with BIDS PostLabelingDelay.",
                suggested_fix="Interpret PLD as delay from end of labeling to image acquisition.",
            )
        )

    if has_2d_slice_timing and not _as_bool(
        method_contract.get("uses_slice_timing_for_2d")
    ):
        findings.append(
            _make_finding(
                rule_id="ASL_2D_SLICE_TIMING_MISSING",
                severity="error",
                action="warn",
                message="A 2D ASL subject reports SliceTiming but the method contract does not apply it.",
                suggested_fix="Use slice-specific effective PLD for 2D acquisitions with SliceTiming.",
            )
        )

    if has_m0_scale and not _as_bool(method_contract.get("applies_m0_scale_factor")):
        findings.append(
            _make_finding(
                rule_id="ASL_M0_SCALE_FACTOR_IGNORED",
                severity="critical",
                action="block",
                message="At least one subject exposes M0ScaleFactor but the method contract ignores it.",
                suggested_fix="Multiply M0 by M0ScaleFactor before CBF normalization when present.",
            )
        )

    for summary in summaries:
        sid = _as_str(summary.get("subject_id")) or "unknown_subject"
        subject_type = _infer_subject_type(summary)
        regime = _subject_regime(summary)
        acquisition_type = (
            (_as_str(summary.get("acquisition_type")) or "")
            or (_as_str(summary.get("dimensionality")) or "")
        ).lower()
        p99 = _as_float(summary.get("brain_p99"))
        gm = _as_float(summary.get("gm_mean_proxy"))
        wm = _as_float(summary.get("wm_mean_proxy"))
        ratio = _as_float(summary.get("gm_wm_ratio_proxy"))
        fit_corr = _first_float(
            summary,
            "fit_curve_corr_proxy",
            "multi_pld_fit_corr",
            "fit_corr_proxy",
        )
        fit_nrmse = _first_float(
            summary,
            "fit_curve_nrmse_proxy",
            "multi_pld_fit_nrmse",
            "fit_nrmse_proxy",
        )
        effective_pld_span = _first_float(
            summary,
            "effective_pld_span_s",
            "slice_timing_effective_pld_span_s",
        )
        slice_timing_applied = summary.get("slice_timing_applied")
        observed_curve = _first_float_list(
            summary,
            "delta_m_curve_means",
            "observed_delta_m_curve_means",
        )
        predicted_curve = _first_float_list(
            summary,
            "predicted_delta_m_curve_means",
            "fit_delta_m_curve_means",
        )

        if subject_type == "synthetic":
            if p99 is not None and p99 > 150.0:
                findings.append(
                    _make_finding(
                        rule_id="ASL_SYNTHETIC_P99_TOO_HIGH",
                        severity="warn",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} has synthetic brain p99 {p99:.1f} mL/100g/min, suggesting a possible scale mismatch.",
                        suggested_fix="Inspect scaling and fit diagnostics, but do not change the timing convention from this proxy alone.",
                    )
                )
            if gm is not None and not (25.0 <= gm <= 90.0):
                findings.append(
                    _make_finding(
                        rule_id="ASL_SYNTHETIC_GM_MEAN_OUT_OF_RANGE",
                        severity="warn",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} synthetic GM proxy mean {gm:.1f} is outside the expected 25-90 range.",
                        suggested_fix="Treat this as a soft scale warning; confirm with fit-to-data observables before changing the kinetic model.",
                    )
                )
            if wm is not None and not (10.0 <= wm <= 40.0):
                findings.append(
                    _make_finding(
                        rule_id="ASL_SYNTHETIC_WM_MEAN_OUT_OF_RANGE",
                        severity="warn",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} synthetic WM proxy mean {wm:.1f} is outside the expected 10-40 range.",
                        suggested_fix="Treat this as a soft warning; confirm against fit residuals or curve correlation before changing ATT timing.",
                    )
                )
            if ratio is not None and ratio <= 1.0:
                findings.append(
                    _make_finding(
                        rule_id="ASL_SYNTHETIC_GM_WM_INVERSION",
                        severity="warn",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} synthetic GM/WM proxy ratio {ratio:.2f} is not greater than 1.0.",
                        suggested_fix="Inspect tissue ordering and scale terms before accepting the fit.",
                    )
                )

        if regime == "multi_pld":
            if fit_corr is not None and fit_corr < 0.90:
                findings.append(
                    _make_finding(
                        rule_id="ASL_MULTI_PLD_FIT_CORRELATION_LOW",
                        severity="error",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} reports low multi-PLD fit correlation {fit_corr:.3f}.",
                        suggested_fix="Compare observed and model-predicted DeltaM curves before changing global timing conventions.",
                    )
                )
            if fit_nrmse is not None and fit_nrmse > 0.25:
                findings.append(
                    _make_finding(
                        rule_id="ASL_MULTI_PLD_FIT_NRMSE_HIGH",
                        severity="error",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} reports high multi-PLD fit NRMSE {fit_nrmse:.3f}.",
                        suggested_fix="Reduce residual mismatch in the forward model before revising scale heuristics.",
                    )
                )
            if observed_curve is not None and predicted_curve is not None:
                curve_r = _pearson_r(observed_curve, predicted_curve)
                if curve_r is not None and curve_r < 0.90:
                    findings.append(
                        _make_finding(
                            rule_id="ASL_MULTI_PLD_DELTA_M_CURVE_MISMATCH",
                            severity="error",
                            action="warn",
                            artifact_name=sid,
                            message=f"{sid} observed/predicted DeltaM-PLD curve correlation {curve_r:.3f} is too low.",
                            suggested_fix="Reconcile the forward model with the observed DeltaM-versus-PLD curve before changing calibration heuristics.",
                        )
                    )

        if _has_slice_timing(summary) and acquisition_type == "2d":
            if slice_timing_applied is False:
                findings.append(
                    _make_finding(
                        rule_id="ASL_2D_EFFECTIVE_PLD_NOT_APPLIED",
                        severity="error",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} reports SliceTiming but the subject summary says effective PLD was not applied.",
                        suggested_fix="Use slice-specific effective PLD in the 2D branch and re-evaluate the fit.",
                    )
                )
            if effective_pld_span is not None and effective_pld_span <= 0.0:
                findings.append(
                    _make_finding(
                        rule_id="ASL_2D_EFFECTIVE_PLD_SPAN_ZERO",
                        severity="error",
                        action="warn",
                        artifact_name=sid,
                        message=f"{sid} reports zero effective-PLD span despite SliceTiming.",
                        suggested_fix="Confirm SliceTiming modifies the per-slice acquisition delay rather than being ignored.",
                    )
                )

    real_gm_cv = _as_float(
        cohort.get("real_gm_cv") or cohort.get("gm_cv") or cohort.get("cohort_gm_cv")
    )
    if real_gm_cv is not None and not (0.12 <= real_gm_cv < 0.30):
        findings.append(
            _make_finding(
                rule_id="ASL_REAL_GM_CV_OUT_OF_RANGE",
                severity="warn",
                action="warn",
                message=f"Real-cohort GM CV {real_gm_cv:.3f} is outside the expected [0.12, 0.30) band.",
                suggested_fix="Check whether the real cohort has been over-harmonized or uniformly mis-scaled.",
            )
        )

    real_gm_mean = _as_float(
        cohort.get("real_gm_mean")
        or cohort.get("gm_mean")
        or cohort.get("cohort_real_gm_mean")
    )
    if real_gm_mean is not None and not (50.0 <= real_gm_mean <= 75.0):
        findings.append(
            _make_finding(
                rule_id="ASL_REAL_GM_MEAN_OUT_OF_RANGE",
                severity="warn",
                action="warn",
                message=f"Real-cohort GM mean {real_gm_mean:.1f} is outside the expected 50-75 range.",
                suggested_fix="Check absolute calibration on real subjects before finalizing outputs.",
            )
        )

    real_ratio_std = _as_float(
        cohort.get("real_gm_ratio_std")
        or cohort.get("gm_ratio_std")
        or cohort.get("ratio_std")
    )
    if real_ratio_std is not None and real_ratio_std >= 0.30:
        findings.append(
            _make_finding(
                rule_id="ASL_REAL_GM_WM_RATIO_STD_HIGH",
                severity="warn",
                action="warn",
                message=f"Real-cohort GM/WM ratio std {real_ratio_std:.3f} is too high.",
                suggested_fix="Investigate instability in the real-subject calibration branch.",
            )
        )

    decision, risk_level = _roll_up(findings)
    return CodeReviewVerdict(
        decision=decision,
        risk_level=risk_level,
        findings=findings,
        kg_rules_consulted=[],
        checklist_generated=checklist,
        reviewer_rationale=_rationale(findings, decision),
    )


__all__ = ["build_asl_quant_control", "review_asl_quant"]
