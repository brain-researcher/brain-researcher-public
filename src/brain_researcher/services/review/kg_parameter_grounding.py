"""KG-backed parameter grounding for plan-time review findings."""

from __future__ import annotations

from typing import Any

from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
    ReviewFinding,
    ReviewRule,
)
from brain_researcher.services.br_kg.query_service import (
    get_effect_size_priors,
    get_glm_priors,
    get_method_compatibility,
)

_HIGH_PASS_RULE_ID = "REVIEW_HIGH_PASS_TOO_AGGRESSIVE"
_HIGH_PASS_KEYS = ("high_pass", "highpass", "hp", "hp_filter", "high_pass_filter")


def _high_pass_period_seconds(raw_value: Any) -> float | None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value >= 1.0:
        return value
    return 1.0 / value


def _collect_high_pass_steps(bundle: CodeReviewBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in bundle.plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        raw_value = None
        for key in _HIGH_PASS_KEYS:
            if key in params and params.get(key) is not None:
                raw_value = params.get(key)
                break
        if raw_value is None:
            continue
        period_seconds = _high_pass_period_seconds(raw_value)
        if period_seconds is None:
            continue
        rows.append(
            {
                "step_id": step.get("step_id"),
                "tool": str(step.get("tool") or ""),
                "raw_value": raw_value,
                "period_seconds": period_seconds,
            }
        )
    return rows


def _coerce_prior_seconds(prior_map: dict[str, Any]) -> dict[float, float]:
    out: dict[float, float] = {}
    for key, weight in prior_map.items():
        try:
            seconds = float(key)
            probability = float(weight)
        except (TypeError, ValueError):
            continue
        if seconds > 0 and probability > 0:
            out[seconds] = probability
    return out


def _lookup_spec_by_rule(rules: list[ReviewRule] | None) -> dict[str, Any]:
    if not rules:
        return {}
    return {
        rule.rule_id: rule.kg_lookup for rule in rules if rule.kg_lookup is not None
    }


def build_discovery_kg_context(
    *,
    task: str | None = None,
    contrast: str | None = None,
    region: str | None = None,
    design: str | None = None,
    method: str | None = None,
    study_id: str | None = None,
    analysis_family: str | None = None,
    db: Any | None = None,
) -> dict[str, Any]:
    """Build reusable KG context for discovery branch decisions.

    The discovery gates consume this helper so branch decisions can consult
    the same KG-backed priors that review-time checks already surface.
    """

    context: dict[str, Any] = {}
    if task:
        context["task"] = task
    if contrast:
        context["contrast"] = contrast
    if region:
        context["region"] = region
    if design:
        context["design"] = design
    if method:
        context["method"] = method
    if study_id:
        context["study_id"] = study_id
    if analysis_family:
        context["analysis_family"] = analysis_family

    if task or contrast or region:
        effect_size_priors = get_effect_size_priors(
            task=task,
            contrast=contrast,
            region=region,
            db=db,
        )
        if effect_size_priors:
            context["effect_size_priors"] = effect_size_priors

    if design and method:
        method_compatibility = get_method_compatibility(
            design=design,
            method=method,
            db=db,
        )
        if method_compatibility:
            context["method_compatibility"] = method_compatibility

    return context


def ground_parameter_findings(
    bundle: CodeReviewBundle,
    findings: list[ReviewFinding],
    *,
    rules: list[ReviewRule] | None = None,
) -> tuple[list[ReviewFinding], list[str]]:
    """Apply narrow KG-backed regrading for parameter findings.

    Current B1 slice only grounds the high-pass rule via task/dataset-conditioned
    GLM priors already exposed by BR-KG.
    """

    lookup_by_rule = _lookup_spec_by_rule(rules)
    if _HIGH_PASS_RULE_ID not in lookup_by_rule:
        return findings, []

    high_pass_steps = _collect_high_pass_steps(bundle)
    if not high_pass_steps:
        return findings, []

    task = str(bundle.kg_context.get("task") or "").strip() or None
    study_id = str(bundle.kg_context.get("study_id") or "").strip() or None
    design = str(bundle.kg_context.get("design_type") or "").strip() or None
    method = str(bundle.kg_context.get("statistical_method") or "").strip() or None
    analysis_family = (
        str(bundle.kg_context.get("analysis_family") or "").strip() or None
    )

    discovery_context = build_discovery_kg_context(
        task=task,
        study_id=study_id,
        analysis_family=analysis_family,
        design=design,
        method=method,
    )
    consulted: list[str] = []
    if discovery_context.get("effect_size_priors"):
        consulted.append("KG_EFFECT_SIZE_PRIORS")
    if discovery_context.get("method_compatibility"):
        consulted.append("KG_METHOD_COMPATIBILITY")

    try:
        priors_payload = get_glm_priors(
            task=task,
            study_id=study_id,
            include_literature=False,
        )
    except Exception:
        return findings, []

    if not priors_payload:
        return findings, []

    high_pass_priors = _coerce_prior_seconds(
        (priors_payload.get("priors") or {}).get("high_pass") or {}
    )
    if not high_pass_priors:
        return findings, []

    coverage = float((priors_payload.get("coverage") or {}).get("high_pass") or 0.0)
    min_confidence = float(lookup_by_rule[_HIGH_PASS_RULE_ID].min_confidence)
    if coverage < min_confidence:
        return findings, []

    scope = str(priors_payload.get("scope") or "unknown")
    lower_bound = min(high_pass_priors)
    mode_seconds = max(high_pass_priors.items(), key=lambda item: item[1])[0]
    consulted = [_HIGH_PASS_RULE_ID] + consulted

    finding_by_step = {
        finding.step_id: finding
        for finding in findings
        if finding.rule_id == _HIGH_PASS_RULE_ID
    }

    out: list[ReviewFinding] = []
    removed_step_ids: set[str | None] = set()

    for finding in findings:
        if finding.rule_id != _HIGH_PASS_RULE_ID:
            out.append(finding)
            continue

        matching_step = next(
            (
                step
                for step in high_pass_steps
                if step.get("step_id") == finding.step_id
            ),
            None,
        )
        if matching_step is None:
            out.append(finding)
            continue

        period_seconds = float(matching_step["period_seconds"])
        if period_seconds >= lower_bound:
            removed_step_ids.add(finding.step_id)
            continue

        kg_evidence = [
            (
                f"KG GLM priors ({scope} scope, coverage={coverage:.2f}) "
                f"support high-pass periods >= {lower_bound:.0f}s; "
                f"mode={mode_seconds:.0f}s."
            ),
            (
                f"Observed {matching_step['raw_value']} on tool "
                f"'{matching_step['tool']}' interpreted as {period_seconds:.1f}s."
            ),
        ]
        if discovery_context.get("method_compatibility"):
            compatibility = discovery_context["method_compatibility"]
            kg_evidence.append(
                "Discovery KG method compatibility: "
                f"{compatibility.get('verdict', 'unknown')}."
            )
        if discovery_context.get("effect_size_priors"):
            priors = discovery_context["effect_size_priors"].get("priors") or {}
            summary = priors.get("cohens_d") if isinstance(priors, dict) else {}
            if isinstance(summary, dict):
                kg_evidence.append(
                    "Discovery KG effect-size priors: "
                    f"source={discovery_context['effect_size_priors'].get('source', 'unknown')}, "
                    f"n_mentions={summary.get('n_mentions', 0)}."
                )
        out.append(
            finding.model_copy(
                update={
                    "message": (
                        f"High-pass period {period_seconds:.1f}s is shorter than "
                        f"contextual KG prior support ({lower_bound:.0f}s+)."
                    ),
                    "suggested_fix": (
                        f"Use a cutoff period closer to the contextual prior "
                        f"mode ({mode_seconds:.0f}s) unless the design demands otherwise."
                    ),
                    "kg_evidence": kg_evidence,
                }
            )
        )

    for step in high_pass_steps:
        step_id = step.get("step_id")
        if step_id in finding_by_step or step_id in removed_step_ids:
            continue
        period_seconds = float(step["period_seconds"])
        if period_seconds >= lower_bound:
            continue
        out.append(
            ReviewFinding(
                rule_id=_HIGH_PASS_RULE_ID,
                severity="warn",
                action="warn",
                message=(
                    f"High-pass period {period_seconds:.1f}s is shorter than "
                    f"contextual KG prior support ({lower_bound:.0f}s+)."
                ),
                suggested_fix=(
                    f"Use a cutoff period closer to the contextual prior "
                    f"mode ({mode_seconds:.0f}s) unless the design demands otherwise."
                ),
                step_id=step_id,
                kg_evidence=[
                    (
                        f"KG GLM priors ({scope} scope, coverage={coverage:.2f}) "
                        f"support high-pass periods >= {lower_bound:.0f}s; "
                        f"mode={mode_seconds:.0f}s."
                    ),
                    (
                        f"Observed {step['raw_value']} on tool '{step['tool']}' "
                        f"interpreted as {period_seconds:.1f}s."
                    ),
                ],
            )
        )

    return out, consulted


__all__ = ["build_discovery_kg_context", "ground_parameter_findings"]
