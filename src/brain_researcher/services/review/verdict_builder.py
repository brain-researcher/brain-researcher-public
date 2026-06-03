"""Build CodeReviewVerdict from a CodeReviewBundle and a ReviewRuleEngine."""

from __future__ import annotations

from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
    CodeReviewVerdict,
    ReviewFinding,
)
from brain_researcher.services.review.rule_engine import ReviewRuleEngine

# Decision roll-up priority (highest → lowest)
_BLOCK_SEVERITIES = frozenset({"critical"})
_REVISE_SEVERITIES = frozenset({"error"})
_WARN_SEVERITIES = frozenset({"warn"})


def _generate_checklist_from_spec(bundle: CodeReviewBundle) -> list[str]:
    """Generate expected checklist items from the bundle spec, before evaluating rules.

    This is called first so the checklist is independent of which rules fire.
    """
    checklist: list[str] = []
    tools = [str(s.get("tool") or "") for s in bundle.plan_steps]
    tools_lower = [t.lower() for t in tools]

    checklist.append(f"Plan has {len(bundle.plan_steps)} step(s)")

    if bundle.declared_modalities:
        checklist.append(
            f"Declared modalities: {', '.join(bundle.declared_modalities)}"
        )
    if bundle.declared_spaces:
        checklist.append(f"Declared spaces: {', '.join(bundle.declared_spaces)}")
    if bundle.workflow_id:
        checklist.append(f"Workflow: {bundle.workflow_id}")

    # Check expected structural properties
    has_registration = any(
        t
        in {
            "coreg_register",
            "coreg_apply_xfm",
            "fsl_flirt",
            "fsl_fnirt",
            "ants_registration",
            "antsregistration",
            "mri_robust_register",
        }
        for t in tools_lower
    )
    has_glm = any(
        t
        in {
            "glm_fit",
            "glm_first_level",
            "spm_glm",
            "nilearn_first_level_model",
            "first_level_model",
            "fsl_feat",
            "fsl_film_gls",
        }
        for t in tools_lower
    )
    has_confound = any(
        t
        in {
            "confound_regression",
            "regress_confounds",
            "nilearn_clean_img",
            "fsl_regfilt",
            "aroma_denoise",
            "fmriprep_confounds",
            "extract_confounds",
        }
        for t in tools_lower
    )

    checklist.append(f"Registration step present: {has_registration}")
    if has_glm:
        checklist.append(f"GLM step present: {has_glm}")
        checklist.append(f"Confound regression before GLM: {has_confound}")

    # TR / FWHM checks
    tr_values = [
        step.get("params", {}).get("tr")
        for step in bundle.plan_steps
        if step.get("params", {}).get("tr") is not None
    ]
    if tr_values:
        checklist.append(f"TR values in plan: {tr_values}")

    fwhm_values = [
        step.get("params", {}).get("fwhm")
        for step in bundle.plan_steps
        if step.get("params", {}).get("fwhm") is not None
    ]
    if fwhm_values:
        checklist.append(f"FWHM values in plan: {fwhm_values}")

    return checklist


def _roll_up_decision(
    findings: list[ReviewFinding],
) -> tuple[str, str]:
    """Return (decision, risk_level) from the list of findings.

    Priority (highest → lowest):
      - any finding with action=block → "block" / critical
      - any finding with severity=error → "revise" / high
      - any finding with severity=warn → "approve_with_warnings" / medium
      - no findings → "approve" / low
    """
    if not findings:
        return "approve", "low"

    severities = {f.severity for f in findings}
    has_block_action = any(getattr(f, "action", "warn") == "block" for f in findings)
    has_error = bool(severities & _REVISE_SEVERITIES)
    has_warn = bool(severities & _WARN_SEVERITIES)

    if has_block_action or bool(severities & _BLOCK_SEVERITIES):
        return "block", "critical"
    if has_error:
        return "revise", "high"
    if has_warn:
        return "approve_with_warnings", "medium"
    return "approve", "low"


def _build_rationale(
    checklist: list[str],
    findings: list[ReviewFinding],
    decision: str,
    mode: str = "plan",
) -> str:
    label = "Artifact review" if mode == "artifact" else "Plan review"
    if not findings:
        return f"{label} passed all checks. Decision: {decision}."
    lines = [f"{label} — Decision: {decision}. {len(findings)} finding(s):"]
    for f in findings:
        lines.append(f"  [{f.severity.upper()}] {f.rule_id}: {f.message}")
    return " | ".join(lines)


def _is_artifact_mode(bundle: CodeReviewBundle) -> bool:
    """Determine review mode from bundle content."""
    return bool(bundle.stats_metrics or bundle.scorecard_snapshot)


def produce_verdict(
    bundle: CodeReviewBundle,
    *,
    engine: ReviewRuleEngine,
    use_kg: bool = False,
) -> CodeReviewVerdict:
    """Produce a CodeReviewVerdict for a bundle.

    Steps:
    1. Generate checklist from spec (before rule evaluation — reviewer independence).
    2. Evaluate rules (dispatch by mode: plan or artifact).
    3. Roll-up decision.
    4. Build rationale.

    ``use_kg`` enables narrow KG-backed grounding for selected plan-time
    parameter findings.
    """
    # Step 1: checklist independent of rule evaluation
    checklist = _generate_checklist_from_spec(bundle)

    # Step 2: evaluate rules — dispatch by mode
    artifact_mode = _is_artifact_mode(bundle)
    if artifact_mode:
        findings = engine.evaluate_artifacts(bundle)
        mode_label = "artifact"
    else:
        findings = engine.evaluate_plan(bundle)
        mode_label = "plan"

    kg_rules_consulted: list[str] = []
    if use_kg and not artifact_mode:
        from brain_researcher.services.review.kg_parameter_grounding import (
            ground_parameter_findings,
        )

        findings, kg_rules_consulted = ground_parameter_findings(
            bundle,
            findings,
            rules=engine.rules,
        )

    # Step 3: roll-up
    decision, risk_level = _roll_up_decision(findings)

    # Step 4: rationale
    rationale = _build_rationale(checklist, findings, decision, mode=mode_label)

    return CodeReviewVerdict(
        decision=decision,
        risk_level=risk_level,
        findings=findings,
        kg_rules_consulted=kg_rules_consulted,
        checklist_generated=checklist,
        reviewer_rationale=rationale,
    )
