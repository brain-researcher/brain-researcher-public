"""Scientific review adapter for autoresearch loop artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchLineDirective,
    AutoresearchReviewBundle,
    ValidationEvidenceItem,
)
from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.core.contracts.scientific_review import (
    CompletenessVerdict,
    CorrectnessVerdict,
    JudgmentVerdict,
    ScientificReviewVerdict,
    derive_verdict_metadata,
    roll_up_scientific_decision,
)
from brain_researcher.services.review.autoresearch_bundle_builder import (
    build_autoresearch_review_bundle,
)
from brain_researcher.services.review.autoresearch_judgment_critic import (
    run_autoresearch_judgment_critic,
)

_VALIDATION_ACTIONS = {
    "permutation_baseline": "run_permutation_baseline",
    "alternate_folds": "run_repeated_cv_or_alternate_folds",
    "deterministic_audit": "run_deterministic_audit_rerun",
    "alternate_parcellation_or_gsr": "run_alternate_parcellation_or_gsr_sensitivity",
    "external_cohort_replication": "run_external_cohort_replication",
}

_CORE_VALIDATION_NAMES = {
    "permutation_baseline",
    "alternate_folds",
    "deterministic_audit",
    "alternate_parcellation_or_gsr",
}
_REPLICATION_VALIDATION_NAMES = {"external_cohort_replication"}

_CLAIM_STRENGTH_RANK: dict[str | None, int] = {
    None: 0,
    "contract_satisfied": 1,
    "internally_supported": 2,
    "scientifically_convincing": 3,
}
_CLAIM_STRENGTH_BY_RANK: dict[int, str | None] = {
    rank: name for name, rank in _CLAIM_STRENGTH_RANK.items()
}
_LINE_DIRECTIVE_PRESETS: dict[str, dict[str, Any]] = {
    "exploration": {
        "loaded_modules": ["base", "representation_scaling"],
        "forbidden_modules": [
            "robustness",
            "confound",
            "generalization",
            "foundation_transfer",
        ],
        "training_backend": "cpu_local",
        "success_criterion": "discover_component_specific_regimes",
    },
    "validation": {
        "loaded_modules": ["base", "robustness", "confound"],
        "forbidden_modules": [
            "model_scaling",
            "generalization",
            "foundation_transfer",
        ],
        "training_backend": "cpu_local",
        "success_criterion": "establish_internal_support_for_top_components",
    },
    "sensitivity": {
        "loaded_modules": ["base", "robustness", "representation_scaling", "confound"],
        "forbidden_modules": [
            "model_scaling",
            "generalization",
            "foundation_transfer",
        ],
        "training_backend": "cpu_local",
        "success_criterion": "stress_test_whether_the_claim_survives_sensitive_design_choices",
    },
    "closeout": {
        "loaded_modules": ["base"],
        "forbidden_modules": [
            "data_scaling",
            "representation_scaling",
            "model_scaling",
            "robustness",
            "confound",
            "generalization",
            "foundation_transfer",
        ],
        "training_backend": "cpu_local",
        "success_criterion": "write_an_honest_claim_matched_report",
    },
}


def _derive_evidence_flags(
    bundle: AutoresearchReviewBundle,
) -> tuple[bool, bool]:
    """Return ``(validation_evidence_present, replication_evidence_present)``.

    - ``validation_evidence_present``: at least 2 core validation categories
      have status ``"present"``.
    - ``replication_evidence_present``: ``external_cohort_replication`` is
      ``"present"``.
    """

    present_core = 0
    replication_present = False
    for item in bundle.validation_evidence:
        if item.status != "present":
            continue
        if item.name in _CORE_VALIDATION_NAMES:
            present_core += 1
        if item.name in _REPLICATION_VALIDATION_NAMES:
            replication_present = True
    return present_core >= 2, replication_present


def _earned_claim_strength_ceiling(
    *,
    correctness_decision: str,
    judgment_decision: str,
    completeness_decision: str,
    validation_present: bool,
    replication_present: bool,
) -> str | None:
    """Return the highest claim_strength the evidence actually supports."""

    if (
        correctness_decision == "block"
        or judgment_decision == "unsound"
        or completeness_decision == "incomplete"
    ):
        return None
    if replication_present and validation_present:
        return "scientifically_convincing"
    if validation_present:
        return "internally_supported"
    return "contract_satisfied"


def _missing_categories_for_target(
    bundle: AutoresearchReviewBundle, declared: str
) -> list[str]:
    """Return validation category names whose absence blocks ``declared``."""

    missing: list[str] = []
    statuses = {item.name: item.status for item in bundle.validation_evidence}
    declared_rank = _CLAIM_STRENGTH_RANK.get(declared, 0)

    if declared_rank >= _CLAIM_STRENGTH_RANK["internally_supported"]:
        present_core = sum(
            1
            for name in _CORE_VALIDATION_NAMES
            if statuses.get(name) == "present"
        )
        if present_core < 2:
            for name in sorted(_CORE_VALIDATION_NAMES):
                if statuses.get(name) != "present":
                    missing.append(name)

    if declared_rank >= _CLAIM_STRENGTH_RANK["scientifically_convincing"]:
        for name in sorted(_REPLICATION_VALIDATION_NAMES):
            if statuses.get(name) != "present":
                if name not in missing:
                    missing.append(name)

    return missing


def _claim_strength_overreach_finding(
    bundle: AutoresearchReviewBundle,
    *,
    earned_ceiling: str | None,
) -> ReviewFinding | None:
    """Emit a blocking finding if declared claim_strength exceeds earned."""

    declared = bundle.claim_strength_declared
    if declared is None:
        return None
    declared_rank = _CLAIM_STRENGTH_RANK.get(declared)
    if declared_rank is None:
        return None
    earned_rank = _CLAIM_STRENGTH_RANK.get(earned_ceiling, 0)
    if declared_rank <= earned_rank:
        return None

    missing_categories = _missing_categories_for_target(bundle, declared)
    missing_str = ", ".join(missing_categories) if missing_categories else "none"
    earned_label = earned_ceiling or "no_contract"
    return ReviewFinding(
        rule_id="AUTORESEARCH_CLAIM_STRENGTH_OVERREACH",
        severity="error",
        action="block",
        message=(
            f"Report self-declares claim_strength='{declared}' but evidence only "
            f"supports '{earned_label}'. Missing: {missing_str}."
        ),
        suggested_fix=(
            "Either lower the declared claim_strength in final_report.md "
            "to match actual validation evidence, or run the missing "
            "validation steps before claiming a stronger level."
        ),
        reason_tags=["claim_inflation"],
    )


def _min_claim_strength(
    declared: str | None, derived: str | None
) -> str | None:
    """Return the minimum-rank claim_strength of ``declared`` and ``derived``."""

    if derived is None:
        return None
    if declared is None:
        return derived
    declared_rank = _CLAIM_STRENGTH_RANK.get(declared)
    derived_rank = _CLAIM_STRENGTH_RANK.get(derived)
    if declared_rank is None:
        return derived
    if derived_rank is None:
        return declared
    chosen_rank = min(declared_rank, derived_rank)
    chosen = _CLAIM_STRENGTH_BY_RANK.get(chosen_rank)
    if chosen is None:
        return None
    return chosen  # type: ignore[return-value]


def _cache_paths(autoresearch_dir: Path) -> tuple[Path, Path, Path]:
    outputs_dir = autoresearch_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return (
        outputs_dir / "autoresearch_scientific_review_bundle.json",
        outputs_dir / "autoresearch_scientific_review_verdict.json",
        outputs_dir / "autoresearch_scientific_review_meta.json",
    )


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _line_directive_preset(line_type: str) -> dict[str, Any]:
    return dict(_LINE_DIRECTIVE_PRESETS.get(line_type, {}))


def _derive_line_directive(
    bundle: AutoresearchReviewBundle,
    *,
    overall_decision: str,
    report_action: str | None,
    validation_status: dict[str, str],
) -> AutoresearchLineDirective:
    current_line_type = str(bundle.review_context.get("line_type") or "exploration")
    current_loaded_modules = _normalize_str_list(
        bundle.review_context.get("loaded_modules")
    )
    current_forbidden_modules = _normalize_str_list(
        bundle.review_context.get("forbidden_modules")
    )
    current_training_backend = str(bundle.review_context.get("training_backend") or "")
    current_success_criterion = str(bundle.review_context.get("success_criterion") or "")

    directive_line_type = current_line_type
    next_line_type: str | None = None

    if overall_decision == "proceed" and report_action == "write_report":
        directive_line_type = "closeout"
    elif current_line_type == "exploration":
        if bundle.final_report_present:
            directive_line_type = "validation"
            next_line_type = "validation"
    elif current_line_type in {"validation", "sensitivity"}:
        needs_alt_parcellation = (
            validation_status.get("validation:alternate_parcellation_or_gsr") != "present"
        )
        if overall_decision in {"diagnose", "explore_more", "stop_with_rationale"}:
            if needs_alt_parcellation:
                directive_line_type = "sensitivity"
                next_line_type = "sensitivity"
            else:
                directive_line_type = "validation"
                next_line_type = "validation"

    preset = _line_directive_preset(directive_line_type)
    loaded_modules = (
        current_loaded_modules
        if directive_line_type == current_line_type and current_loaded_modules
        else _normalize_str_list(preset.get("loaded_modules"))
    )
    forbidden_modules = (
        current_forbidden_modules
        if directive_line_type == current_line_type and current_forbidden_modules
        else _normalize_str_list(preset.get("forbidden_modules"))
    )
    training_backend = (
        current_training_backend
        if directive_line_type == current_line_type and current_training_backend
        else str(preset.get("training_backend") or "")
    )
    success_criterion = (
        current_success_criterion
        if directive_line_type == current_line_type and current_success_criterion
        else str(preset.get("success_criterion") or "")
    )

    return AutoresearchLineDirective(
        line_type=directive_line_type or None,
        next_line_type=next_line_type,
        loaded_modules=loaded_modules,
        forbidden_modules=forbidden_modules,
        training_backend=training_backend or None,
        success_criterion=success_criterion or None,
    )


def _load_cached_verdict(
    verdict_path: Path, meta_path: Path, fingerprint: str
) -> ScientificReviewVerdict | None:
    if not verdict_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("fingerprint") != fingerprint:
            return None
        data = json.loads(verdict_path.read_text(encoding="utf-8"))
        return ScientificReviewVerdict.model_validate(data)
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump_json"):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _component_mentions(report_text: str | None) -> list[str]:
    text = report_text or ""
    return [
        component
        for component in (
            "ICA_Cognition",
            "ICA_TobaccoUse",
            "ICA_PersonalityEmotion",
            "ICA_IllicitDrugUse",
            "ICA_MentalHealth",
        )
        if component in text
    ]


def _validation_present_count(items: list[ValidationEvidenceItem]) -> int:
    return sum(1 for item in items if item.status == "present")


def _shared_correctness_findings(
    bundle: AutoresearchReviewBundle,
) -> list[ReviewFinding]:
    """Run the cross-profile predictive / connectivity checks against the
    autoresearch bundle's review_context. Wraps the context into a minimal
    CodeReviewBundle so the existing deterministic checks apply unchanged."""

    review_context = dict(bundle.review_context or {})
    if not review_context:
        return []

    try:
        from brain_researcher.services.review.checks.correlation_validity import (
            partial_correlation_estimator_hazard_check,
        )
        from brain_researcher.services.review.checks.review_context_validity import (
            predictive_required_diagnostics_check,
        )
    except Exception:  # pragma: no cover - check imports must not crash review
        return []

    try:
        code_bundle = CodeReviewBundle(
            plan_steps=[],
            review_context=review_context,
        )
    except Exception:  # pragma: no cover - context shape is best-effort
        return []

    findings: list[ReviewFinding] = []
    for check in (
        predictive_required_diagnostics_check,
        partial_correlation_estimator_hazard_check,
    ):
        try:
            finding = check(code_bundle)
        except Exception:  # pragma: no cover - one bad check must not block all
            continue
        if finding is not None:
            findings.append(finding)
    return findings


def _correctness_verdict(bundle: AutoresearchReviewBundle) -> CorrectnessVerdict:
    findings: list[ReviewFinding] = []

    if bundle.ledger_row_count <= 0:
        findings.append(
            ReviewFinding(
                rule_id="AUTORESEARCH_LEDGER_MISSING",
                severity="error",
                action="block",
                message="experiments.jsonl is missing or empty.",
            )
        )

    if bundle.final_report_present and not bundle.final_report_text:
        findings.append(
            ReviewFinding(
                rule_id="AUTORESEARCH_REPORT_UNREADABLE",
                severity="error",
                action="block",
                message="final_report.md exists but could not be read.",
            )
        )

    if bundle.final_report_present and bundle.latest_summary is not None:
        if bundle.latest_summary.action_type not in {"final_report", "synthesize"}:
            findings.append(
                ReviewFinding(
                    rule_id="AUTORESEARCH_REPORT_WITHOUT_TERMINAL_ROW",
                    severity="warn",
                    action="warn",
                    message=(
                        "final_report.md exists, but the latest ledger row is not "
                        "a final_report or synthesize action."
                    ),
                )
            )

    findings.extend(_shared_correctness_findings(bundle))

    if any(f.action == "block" or f.severity in {"error", "critical"} for f in findings):
        decision = "block"
    elif findings:
        decision = "flag"
    else:
        decision = "pass"

    return CorrectnessVerdict(decision=decision, findings=findings)


def _completeness_checklist(bundle: AutoresearchReviewBundle) -> dict[str, bool]:
    report_text = bundle.final_report_text or ""
    mentioned_components = _component_mentions(report_text)
    checklist = {
        "ledger_present": bundle.ledger_row_count > 0,
        "final_report_present": bundle.final_report_present,
        "five_components_addressed": len(mentioned_components) == 5,
        "self_critique_checkpoint_present": len(bundle.self_critique_sections) == 4,
        "claim_strength_declared": bundle.claim_strength_declared is not None,
        "stop_condition_declared": "final_stopping_condition" in report_text
        or "stopping condition" in report_text.lower(),
        "primary_vs_sensitivity_declared": (
            "primary analysis" in report_text.lower()
            and "sensitivity analysis" in report_text.lower()
        ),
        "validation_disclosure_declared": bool(bundle.validation_missing_declared)
        or any(item.status != "missing" for item in bundle.validation_evidence),
    }

    if bundle.claim_strength_declared == "scientifically_convincing":
        checklist["claim_strength_supported_by_validation"] = (
            _validation_present_count(bundle.validation_evidence) >= 2
        )
    else:
        checklist["claim_strength_supported_by_validation"] = True

    return checklist


def _completeness_verdict(bundle: AutoresearchReviewBundle) -> CompletenessVerdict:
    checklist = _completeness_checklist(bundle)
    missing = [key for key, ok in checklist.items() if not ok]
    return CompletenessVerdict(
        decision="incomplete" if missing else "complete",
        checklist=checklist,
        missing_caveats=[f"{key} not satisfied" for key in missing],
    )


def _autoresearch_validation_actions(
    bundle: AutoresearchReviewBundle,
    overall_decision: str,
) -> list[str]:
    """Return autoresearch-specific validation actions (no judgment hooks)."""

    actions: list[str] = []
    if overall_decision in {"diagnose", "explore_more", "stop_with_rationale"}:
        for item in bundle.validation_evidence:
            if item.status != "present":
                action = _VALIDATION_ACTIONS.get(item.name)
                if action and action not in actions:
                    actions.append(action)
    return actions


def _roll_up_autoresearch_decision(
    correctness: CorrectnessVerdict,
    judgment: JudgmentVerdict,
    completeness: CompletenessVerdict,
) -> tuple[str, str]:
    """Autoresearch-specific roll-up with tolerance for judge transport failure.

    A transient LLM transport failure in the judgment critic should not block an
    otherwise complete and structurally sound final report. We therefore allow
    ``proceed`` when correctness passes, completeness is complete, and the only
    reason judgment is not ``sound`` is transport failure.
    """

    overall_decision, rationale = roll_up_scientific_decision(
        correctness, judgment, completeness
    )
    if (
        overall_decision == "explore_more"
        and correctness.decision == "pass"
        and completeness.decision == "complete"
        and judgment.decision == "questionable"
        and judgment.judgment_status in {"parse_failed", "provider_failed"}
    ):
        transport_note = (
            judgment.judge_transport_error or "judgment critic transport unavailable"
        )
        return (
            "proceed",
            "Judgment critic transport failed; accepting based on correctness and "
            f"completeness cards. Transport note: {transport_note}",
        )
    return overall_decision, rationale


def render_autoresearch_review_feedback(verdict: ScientificReviewVerdict) -> str:
    """Render reviewer feedback for the loop workspace."""

    lines = [
        "# Autoresearch Scientific Review Feedback",
        "",
        f"- overall_decision: `{verdict.overall_decision}`",
        f"- report_action: `{verdict.report_action or 'continue_loop'}`",
    ]
    if verdict.claim_strength:
        lines.append(f"- claim_strength: `{verdict.claim_strength}`")
    if verdict.line_directive is not None:
        lines.append(
            f"- line_directive.line_type: `{verdict.line_directive.line_type or 'none'}`"
        )
        lines.append(
            f"- line_directive.next_line_type: `{verdict.line_directive.next_line_type or 'none'}`"
        )
    if verdict.judgment.judgment_status != "ok":
        lines.append(f"- judgment_status: `{verdict.judgment.judgment_status}`")
    if verdict.judgment.judge_transport_error:
        lines.append(
            f"- judge_transport_error: `{verdict.judgment.judge_transport_error}`"
        )
    if verdict.rationale:
        lines.extend(["", "## Rationale", "", verdict.rationale])
    issues = list(verdict.judgment.issues or [])
    questions = list(verdict.judgment.reviewer_questions or [])
    if issues:
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- {issue}" for issue in issues)
    if questions:
        lines.extend(["", "## Reviewer Questions", ""])
        lines.extend(f"- {question}" for question in questions)
    if verdict.required_next_actions:
        lines.extend(["", "## Required Next Actions", ""])
        lines.extend(f"- {action}" for action in verdict.required_next_actions)
    return "\n".join(lines).strip() + "\n"


def distill_autoresearch_scientific_review(
    autoresearch_dir: str | Path,
    *,
    logs_dir: str | Path | None = None,
    task_id: str = "default",
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
) -> ScientificReviewVerdict:
    """Run scientific review over an autoresearch loop workspace."""

    resolved_autoresearch_dir = Path(autoresearch_dir).resolve()
    bundle = build_autoresearch_review_bundle(
        resolved_autoresearch_dir,
        logs_dir=logs_dir,
        task_id=task_id,
    )
    bundle_path, verdict_path, meta_path = _cache_paths(resolved_autoresearch_dir)

    if not force_recompute:
        cached = _load_cached_verdict(verdict_path, meta_path, bundle.fingerprint)
        if cached is not None:
            return cached

    correctness = _correctness_verdict(bundle)
    completeness = _completeness_verdict(bundle)
    if use_judgment_critic:
        judgment = run_autoresearch_judgment_critic(bundle)
    else:
        judgment = JudgmentVerdict(decision="sound")

    # Compute the earned ceiling using the *current* (pre-overreach) verdicts
    # so the overreach check sees the structural baseline that the evidence
    # actually justifies before we collapse correctness to "block".
    validation_present, replication_present = _derive_evidence_flags(bundle)
    earned_ceiling = _earned_claim_strength_ceiling(
        correctness_decision=correctness.decision,
        judgment_decision=judgment.decision,
        completeness_decision=completeness.decision,
        validation_present=validation_present,
        replication_present=replication_present,
    )
    overreach = _claim_strength_overreach_finding(
        bundle, earned_ceiling=earned_ceiling
    )
    if overreach is not None:
        new_findings = list(correctness.findings) + [overreach]
        new_decision: str = correctness.decision
        if overreach.action == "block":
            new_decision = "block"
        elif new_decision == "pass":
            new_decision = "flag"
        correctness = CorrectnessVerdict(
            decision=new_decision,  # type: ignore[arg-type]
            findings=new_findings,
        )
        # Re-derive evidence-based ceiling now that correctness may be a block.
        earned_ceiling = _earned_claim_strength_ceiling(
            correctness_decision=correctness.decision,
            judgment_decision=judgment.decision,
            completeness_decision=completeness.decision,
            validation_present=validation_present,
            replication_present=replication_present,
        )

    overall_decision, rationale = _roll_up_autoresearch_decision(
        correctness, judgment, completeness
    )

    derived_claim_strength, report_action, required_next_actions, validation_status = (
        derive_verdict_metadata(
            correctness,
            judgment,
            completeness,
            overall_decision,
            scope="autoresearch_loop",
            validation_evidence_present=validation_present,
            replication_evidence_present=replication_present,
        )
    )

    # Merge autoresearch-specific actions into the helper's list (preserve order).
    autoresearch_actions = _autoresearch_validation_actions(bundle, overall_decision)
    for extra in autoresearch_actions:
        if extra not in required_next_actions:
            required_next_actions.append(extra)

    # Merge per-item validation evidence statuses into validation_status without
    # overwriting helper-derived keys (helper uses unprefixed keys).
    for item in bundle.validation_evidence:
        validation_status.setdefault(f"validation:{item.name}", item.status)

    final_claim_strength = _min_claim_strength(
        bundle.claim_strength_declared, derived_claim_strength
    )
    line_directive = _derive_line_directive(
        bundle,
        overall_decision=overall_decision,
        report_action=report_action,
        validation_status=validation_status,
    )

    verdict = ScientificReviewVerdict(
        correctness=correctness,
        judgment=judgment,
        completeness=completeness,
        review_scope="autoresearch_loop",
        overall_decision=overall_decision,  # type: ignore[arg-type]
        claim_strength=final_claim_strength,  # type: ignore[arg-type]
        report_action=report_action,
        required_next_actions=required_next_actions,
        validation_status=validation_status,
        line_directive=line_directive,
        rationale=rationale,
    )

    _write_json(bundle_path, bundle)
    _write_json(verdict_path, verdict)
    _write_json(
        meta_path,
        {
            "task_id": task_id,
            "autoresearch_dir": str(resolved_autoresearch_dir),
            "logs_dir": None if logs_dir is None else str(Path(logs_dir).resolve()),
            "fingerprint": bundle.fingerprint,
        },
    )
    return verdict


__all__ = [
    "distill_autoresearch_scientific_review",
    "render_autoresearch_review_feedback",
]
