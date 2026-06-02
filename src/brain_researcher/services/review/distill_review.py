"""Post-execution artifact review: build bundle, produce verdict, persist result."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
    CodeReviewVerdict,
)

logger = logging.getLogger(__name__)


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump_json"):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        return

    def _default(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True)
        raise TypeError(
            f"Object of type {value.__class__.__name__} is not JSON serializable"
        )

    path.write_text(json.dumps(payload, indent=2, default=_default), encoding="utf-8")


@dataclass
class DistilledReviewMemory:
    """Result of distill_review_records()."""

    verdict: CodeReviewVerdict | None
    bundle: CodeReviewBundle | None
    warnings: list[str]


def _coalesce_claim_verdict(claims: list[Any]) -> Any | None:
    from brain_researcher.core.contracts import ClaimVerdictV1

    verdicts = [
        claim.verdict for claim in claims if getattr(claim, "verdict", None) is not None
    ]
    unique = {verdict for verdict in verdicts if verdict is not None}
    if not unique:
        return None
    if len(unique) == 1:
        return next(iter(unique))
    return ClaimVerdictV1.mixed


def _claim_family_summary(run_id: str, run_dir: Path) -> dict[str, Any] | None:
    try:
        from brain_researcher.services.memory.canonical import summarize_claim_families
        from brain_researcher.services.memory.distill import distill_run_records

        distilled = distill_run_records(run_id, run_dir=run_dir)
        if not distilled.claim_cards:
            return None
        return summarize_claim_families(
            [card.model_dump(exclude_none=True) for card in distilled.claim_cards]
        )
    except Exception:
        return None


def _build_evidence_gate_verdict(
    *,
    bundle: CodeReviewBundle,
    verdict: Any,
    evidence_items: list[Any],
) -> Any:
    from brain_researcher.core.contracts import EvidenceGateVerdictV1

    blockers: list[str] = []
    severity_counts = {"error": 0, "warn": 0}
    for finding in verdict.correctness.findings:
        severity = getattr(finding, "severity", "warn")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if severity == "error":
            blockers.append(f"{finding.rule_id}: {finding.message}")

    if (
        verdict.overall_decision == "stop_with_rationale"
        or verdict.judgment.decision == "unsound"
    ):
        decision = "stop"
    elif (
        verdict.correctness.decision == "flag"
        or verdict.judgment.decision == "questionable"
        or verdict.completeness.decision == "incomplete"
        or verdict.overall_decision in {"diagnose", "explore_more"}
    ):
        decision = "collect_more"
    else:
        decision = "go"

    missing_keys = [key for key, ok in verdict.completeness.checklist.items() if not ok]
    confidence = None
    if decision == "go":
        confidence = 0.9
    elif decision == "collect_more":
        confidence = 0.55
    elif blockers:
        confidence = 0.2

    return EvidenceGateVerdictV1(
        decision=decision,
        summary=(
            f"Scientific review {verdict.overall_decision}; "
            f"{len(evidence_items)} evidence items observed."
        ),
        required_evidence_ids=sorted(
            {
                evidence_id
                for claim in bundle.observed_artifacts.get("quote_grounded_claims", [])
                or []
                if isinstance(claim, dict)
                for evidence_id in claim.get("evidence_ids", []) or []
                if isinstance(evidence_id, str) and evidence_id.strip()
            }
        ),
        supporting_evidence_ids=[
            evidence.evidence_id
            for evidence in evidence_items
            if getattr(evidence, "evidence_id", None)
        ],
        missing_evidence_ids=[f"check:{key}" for key in missing_keys],
        blockers=blockers
        or list(verdict.judgment.issues[:3])
        or list(verdict.completeness.missing_caveats[:3]),
        confidence=confidence,
        extra={
            "scientific_review": verdict.model_dump(exclude_none=True),
            "severity_counts": severity_counts,
        },
    )


def _build_claim_report(
    *,
    run_id: str,
    run_dir: Path,
    bundle: CodeReviewBundle,
    verdict: Any,
    claims: list[Any],
    evidence_items: list[Any],
    claim_source: str,
) -> Any:
    from brain_researcher.core.contracts import ClaimReportV1
    from brain_researcher.core.epistemic_policy import calibrate_claim_epistemics
    from brain_researcher.services.review.checks.epistemic_integrity import (
        find_directional_claim_conflicts,
    )

    calibrated_claims = [
        calibrate_claim_epistemics(claim, evidence_items) for claim in claims
    ]

    # Best-effort traceability PRODUCER: bind each claim's evidence references to
    # the artifacts this run actually produced (file_manifest) + the plan step
    # that produced them, attaching artifact_path + artifact_sha256 + code_ref to
    # claim.extra['artifact_provenance']. Attaches only on a real manifest match;
    # claims with no resolvable artifact are recorded unprovenanced (no fabrication).
    from brain_researcher.services.review.claim_provenance_producer import (
        attach_claim_artifact_provenance,
    )

    _analysis_bundle = (
        bundle.observed_artifacts.get("analysis_bundle")
        if isinstance(bundle.observed_artifacts, dict)
        else None
    )
    _file_manifest = (
        _analysis_bundle.get("file_manifest")
        if isinstance(_analysis_bundle, dict)
        else None
    )
    try:
        _provenance_summary = attach_claim_artifact_provenance(
            calibrated_claims,
            evidence_items,
            file_manifest=_file_manifest,
            plan_steps=bundle.plan_steps,
        )
    except Exception:
        _provenance_summary = None

    evidence_ids = sorted(
        {
            evidence_id
            for claim in calibrated_claims
            for evidence_id in getattr(claim, "evidence_ids", []) or []
            if isinstance(evidence_id, str) and evidence_id.strip()
        }
        | {
            evidence.evidence_id
            for evidence in evidence_items
            if getattr(evidence, "evidence_id", None)
        }
    )
    directional_conflicts = find_directional_claim_conflicts(
        calibrated_claims,
        evidence_items,
    )
    cross_study_claim_present = any(
        (
            getattr(claim, "evidence_provenance", None) is not None
            and claim.evidence_provenance.value == "cross_study_inference"
            and getattr(claim, "direct_statistical_test", None) is not True
        )
        for claim in calibrated_claims
    )
    caveats = list(
        dict.fromkeys(
            [
                *list(verdict.completeness.missing_caveats),
                *list(verdict.judgment.issues),
                *[finding.message for finding in verdict.correctness.findings[:3]],
            ]
        )
    )
    if cross_study_claim_present:
        caveats.append(
            "At least one claim is cross-study inference without a direct statistical test; "
            "treat it as indirect consistency evidence, not a confirmed group difference."
        )
    if directional_conflicts:
        for conflict in directional_conflicts[:3]:
            directions = ", ".join(sorted(conflict["directions"].keys()))
            caveats.append(
                f"Directional tension remains unresolved for {conflict['family_key']}: "
                f"{directions}."
            )
    claim_family_summary = _claim_family_summary(run_id, run_dir)
    scientific_review_extra = {
        "overall_decision": verdict.overall_decision,
        "rationale": verdict.rationale,
        "correctness_decision": verdict.correctness.decision,
        "correctness_rule_ids": [
            finding.rule_id for finding in verdict.correctness.findings
        ],
        "judgment_decision": verdict.judgment.decision,
        "completeness_decision": verdict.completeness.decision,
        "missing_caveats": verdict.completeness.missing_caveats,
    }
    extra: dict[str, Any] = {
        "run_id": run_id,
        "claim_source": claim_source,
        "evidence_items_file": "quote_grounded_evidence_items.json",
        "evidence_count": len(evidence_items),
        "scientific_review": scientific_review_extra,
        "epistemic_claims_calibrated": True,
        "directional_conflicts": directional_conflicts,
    }
    if claim_family_summary:
        extra["claim_family_summary"] = claim_family_summary
    if _provenance_summary is not None:
        extra["claim_artifact_provenance_summary"] = _provenance_summary.model_dump()
    return ClaimReportV1(
        report_id=f"claim_report:{run_id}",
        episode_id=(
            (bundle.observed_artifacts.get("research_episode") or {}).get("episode_id")
            if isinstance(bundle.observed_artifacts.get("research_episode"), dict)
            else None
        ),
        claims=calibrated_claims,
        evidence_ids=evidence_ids,
        summary=(
            f"{len(calibrated_claims)} claims, {len(evidence_items)} evidence items. "
            f"Scientific review: {verdict.overall_decision}."
        ),
        overall_verdict=_coalesce_claim_verdict(calibrated_claims),
        caveats=caveats,
        unresolved_questions=list(
            dict.fromkeys(
                [
                    *list(verdict.judgment.reviewer_questions),
                    *[
                        "Which direction is supported once the conflicting literature "
                        f"for {conflict['family_key']} is adjudicated by a direct comparison?"
                        for conflict in directional_conflicts[:3]
                    ],
                ]
            )
        ),
        scientific_review_overall_decision=verdict.overall_decision,
        extra=extra,
    )


def _build_claim_updates(
    *,
    run_id: str,
    claim_report: Any,
    verdict: Any,
    claims: list[Any],
    evidence_items: list[Any],
) -> list[Any]:
    from brain_researcher.core.contracts import ClaimUpdateV1
    from brain_researcher.core.epistemic_policy import (
        assess_claim_epistemics,
        calibrate_claim_epistemics,
        validate_claim_epistemics,
    )

    updates: list[Any] = []
    for claim in claims:
        issues = validate_claim_epistemics(claim, evidence_items)
        assessment = assess_claim_epistemics(claim, evidence_items)
        calibrated_claim = calibrate_claim_epistemics(claim, evidence_items)
        if getattr(claim, "extra", None) and isinstance(claim.extra, dict):
            canonical_claim_id = claim.extra.get("canonical_claim_id")
            supersedes_claim_id = claim.extra.get("supersedes_claim_id")
        else:
            canonical_claim_id = None
            supersedes_claim_id = None

        if supersedes_claim_id:
            action = "supersede"
        elif verdict.overall_decision == "stop_with_rationale":
            action = "refute"
        elif issues or verdict.overall_decision in {"diagnose", "explore_more"}:
            action = "weaken"
        else:
            action = "support"

        note = verdict.rationale or "Scientific review completed."
        if issues:
            note = "REVIEW_EPISTEMIC_CLAIM_POLICY: " + issues[0]

        updates.append(
            ClaimUpdateV1(
                claim_id=claim.claim_id,
                canonical_claim_id=(
                    canonical_claim_id if isinstance(canonical_claim_id, str) else None
                ),
                action=action,
                claim_text=calibrated_claim.claim_text,
                verdict=calibrated_claim.verdict,
                confidence=claim.confidence,
                evidence_ids=list(claim.evidence_ids or []),
                supersedes_claim_id=(
                    supersedes_claim_id
                    if isinstance(supersedes_claim_id, str)
                    else None
                ),
                rationale=verdict.rationale or None,
                note=note,
                updated_at=None,
                extra={
                    "run_id": run_id,
                    "claim_report_id": claim_report.report_id,
                    "scientific_review_overall_decision": verdict.overall_decision,
                    "scientific_review_rationale": verdict.rationale,
                    "epistemic_issues": issues,
                    "allowed_verdicts": [
                        verdict_label.value
                        for verdict_label in assessment.allowed_verdicts
                    ],
                    "recommended_confidence_tier": assessment.recommended_confidence_tier.value,
                    "evidence_provenance": assessment.evidence_provenance.value,
                    "claim_scope": assessment.claim_scope.value,
                    "raw_data_available": assessment.raw_data_available,
                    "direct_statistical_test": assessment.direct_statistical_test,
                    "calibrated_claim": calibrated_claim.model_dump(exclude_none=True),
                },
            )
        )
    return updates


def _write_scientific_episode_sidecars(
    *,
    run_id: str,
    run_dir: Path,
    bundle: CodeReviewBundle,
    verdict: Any,
    force: bool = False,
) -> None:
    from brain_researcher.services.review.checks.epistemic_integrity import (
        load_review_claims_and_evidence,
    )
    from brain_researcher.services.review.research_episode_artifacts import (
        sync_research_episode_artifact,
    )

    claims, evidence_items, claim_source = load_review_claims_and_evidence(bundle)
    evidence_gate = _build_evidence_gate_verdict(
        bundle=bundle, verdict=verdict, evidence_items=evidence_items
    )
    claim_report = _build_claim_report(
        run_id=run_id,
        run_dir=run_dir,
        bundle=bundle,
        verdict=verdict,
        claims=claims,
        evidence_items=evidence_items,
        claim_source=claim_source,
    )
    claim_updates = _build_claim_updates(
        run_id=run_id,
        claim_report=claim_report,
        verdict=verdict,
        claims=claims,
        evidence_items=evidence_items,
    )

    targets = {
        run_dir / "evidence_gate.json": evidence_gate,
        run_dir / "claim_report.json": claim_report,
        run_dir / "claim_update.json": claim_updates,
    }
    for path, payload in targets.items():
        if force or not path.exists():
            _write_json(path, payload)

    sync_research_episode_artifact(
        run_dir,
        evidence_gate=evidence_gate,
        claim_report=claim_report,
        claim_updates=claim_updates,
    )


def distill_review_records(
    run_id: str,
    *,
    run_dir: Path | None = None,
    workflow_id: str | None = None,
    force_recompute: bool = False,
) -> DistilledReviewMemory:
    """Build an artifact-time CodeReviewBundle, produce a verdict, and cache it.

    Reads ``code_review_verdict.json`` from the run directory if it already exists
    (unless ``force_recompute=True``). On success, writes the verdict back to
    ``code_review_verdict.json``.

    Args:
        run_id: The run identifier.
        run_dir: Explicit path to the run directory. Resolved automatically if None.
        workflow_id: Optional workflow identifier for context.
        force_recompute: Re-evaluate even if a cached verdict file exists.

    Returns:
        DistilledReviewMemory with verdict and bundle (or None on failure).
    """
    from brain_researcher.services.memory.distill import _find_run_dir
    from brain_researcher.services.review.bundle_builder import (
        build_artifact_review_bundle,
    )
    from brain_researcher.services.review.rule_engine import get_engine
    from brain_researcher.services.review.verdict_builder import produce_verdict

    warnings: list[str] = []

    try:
        resolved_run_dir = _find_run_dir(run_id, run_dir=run_dir)
    except FileNotFoundError as exc:
        return DistilledReviewMemory(verdict=None, bundle=None, warnings=[str(exc)])

    verdict_path = resolved_run_dir / "code_review_verdict.json"

    # Return cached verdict unless forced
    if not force_recompute and verdict_path.exists():
        try:
            data = json.loads(verdict_path.read_text(encoding="utf-8"))
            cached = CodeReviewVerdict.model_validate(data)
            return DistilledReviewMemory(
                verdict=cached, bundle=None, warnings=["cached"]
            )
        except Exception as exc:
            warnings.append(f"could not load cached verdict: {exc}")

    try:
        bundle = build_artifact_review_bundle(
            run_id, run_dir=resolved_run_dir, workflow_id=workflow_id
        )
    except Exception as exc:
        return DistilledReviewMemory(
            verdict=None, bundle=None, warnings=[f"build_artifact_review_bundle: {exc}"]
        )

    try:
        engine = get_engine()
        verdict = produce_verdict(bundle, engine=engine, use_kg=False)
    except Exception as exc:
        return DistilledReviewMemory(
            verdict=None, bundle=bundle, warnings=[f"produce_verdict: {exc}"]
        )

    # Persist
    try:
        verdict_path.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        warnings.append(f"could not write verdict cache: {exc}")

    return DistilledReviewMemory(verdict=verdict, bundle=bundle, warnings=warnings)


def _enrich_bundle_with_effect_priors(bundle: CodeReviewBundle) -> CodeReviewBundle:
    """Add effect-size prior context to a bundle copy for the judgment critic."""
    task = bundle.kg_context.get("task")
    contrast = bundle.kg_context.get("contrast")
    if not task and not contrast:
        return bundle
    try:
        from brain_researcher.services.br_kg.query_service import (
            get_effect_size_priors,
        )

        priors = get_effect_size_priors(task=task, contrast=contrast)
        if priors and priors.get("status") == "ok":
            enriched = bundle.model_copy(deep=True)
            enriched.kg_context["effect_size_priors"] = {
                "source": priors.get("source"),
                "confidence_tier": priors.get("confidence_tier"),
                "cohens_d": (priors.get("priors") or {}).get("cohens_d", {}),
            }
            return enriched
    except Exception as exc:
        logger.info("KG review-rule registry evaluation skipped: %s", exc)
    return bundle


def distill_scientific_review_records(
    run_id: str,
    *,
    run_dir: Path | None = None,
    workflow_id: str | None = None,
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
) -> Any:
    """Run all three verdict layers and return a ScientificReviewVerdict.

    Caches result to scientific_review_verdict.json in the run directory.
    """
    from brain_researcher.core.contracts.scientific_review import (
        CompletenessVerdict,
        CorrectnessVerdict,
        JudgmentVerdict,
        ScientificReviewVerdict,
        derive_verdict_metadata,
        roll_up_scientific_decision,
    )
    from brain_researcher.services.memory.distill import _find_run_dir
    from brain_researcher.services.review.checks.artifact_structure import (
        cluster_peak_cardinality_check,
        cluster_table_count_consistency_check,
        cluster_table_semantics_check,
        condition_number_check,
        contrast_estimability_check,
        contrast_table_semantics_check,
        contrast_vector_dim_check,
        correction_summary_numeric_consistency_check,
        cross_file_n_subjects_check,
        design_matrix_confound_column_consistency_check,
        design_matrix_rank_check,
        design_model_metadata_consistency_check,
        effect_tstat_shape_check,
        multiple_comparison_metadata_consistency_check,
        peak_cluster_membership_consistency_check,
        peak_table_semantics_check,
    )
    from brain_researcher.services.review.checks.circularity_confound import (
        demographic_confound_uncontrolled_check,
        double_dipping_check,
    )
    from brain_researcher.services.review.checks.claim_validity import (
        claim_inflation_check,
        construct_validity_confound_check,
        controversial_choice_sensitivity_check,
        model_fit_mechanism_overreach_check,
        reverse_inference_risk_check,
    )
    from brain_researcher.services.review.checks.completeness import (
        build_completeness_checklist,
    )
    from brain_researcher.services.review.checks.correlation_validity import (
        corr_diag_check,
        corr_has_nan_check,
        corr_positive_semidefinite_check,
        corr_range_check,
        corr_region_count_check,
        corr_symmetric_check,
        partial_correlation_estimator_hazard_check,
        partial_correlation_required_diagnostics_check,
    )
    from brain_researcher.services.review.checks.cross_step_compat import (
        atlas_registration_space_mismatch,
        bandpass_before_confound_regression,
        bandpass_glm_drift_overlap,
        preprocessing_stats_space_mismatch,
    )
    from brain_researcher.services.review.checks.effect_plausibility import (
        effect_size_plausibility_check,
        meta_analytic_spatial_plausibility_check,
    )
    from brain_researcher.services.review.checks.epistemic_integrity import (
        cross_study_coordinate_comparison_check,
        directional_claim_contradiction_check,
        epistemic_claim_policy_check,
    )
    from brain_researcher.services.review.checks.leakage_extra import (
        brainmap_correlation_spatial_null_check,
        leakage_preprocessing_fit_scope_check,
        leakage_pseudoreplication_check,
    )
    from brain_researcher.services.review.checks.method_appropriateness import (
        method_appropriateness_check,
    )
    from brain_researcher.services.review.checks.neuroai_validity import (
        neuroai_declared_subject_set_missing_subject_column_check,
        neuroai_nested_cv_inner_partition_gap_check,
        neuroai_nested_cv_outer_holdout_conflict_check,
        neuroai_nested_cv_outer_missing_inner_resampling_check,
        neuroai_nested_cv_outer_partition_gap_check,
        neuroai_nested_cv_schema_missing_fold_keys_check,
        neuroai_selection_multiplicity_accounting_check,
        neuroai_selection_on_test_check,
        neuroai_selection_validation_gap_check,
        neuroai_split_grouping_mismatch_check,
        neuroai_split_manifest_missing_group_keys_check,
        neuroai_split_manifest_partition_conflict_check,
        neuroai_subject_intersection_coverage_check,
        neuroai_subject_intersection_selection_source_subset_conflict_check,
        neuroai_subject_intersection_subset_conflict_check,
        neuroai_subject_manifest_coverage_check,
        neuroai_subject_manifest_selection_source_subset_conflict_check,
        neuroai_subject_selection_source_coverage_check,
        neuroai_winner_without_candidate_set_check,
    )
    from brain_researcher.services.review.checks.null_model_validity import (
        permutation_exchangeability_check,
        spatial_null_validity_check,
        surface_volume_correction_domain_mismatch_check,
    )
    from brain_researcher.services.review.checks.predictive_integrity import (
        predictive_cv_leakage_check,
        predictive_fisher_z_input_domain_check,
        predictive_split_integrity_check,
    )
    from brain_researcher.services.review.checks.review_context_validity import (
        external_evidence_path_integrity_check,
        predictive_required_diagnostics_check,
        predictive_review_context_metadata_check,
        review_context_leakage_circularity_flag_check,
        review_context_mirror_conflict_check,
    )
    from brain_researcher.services.review.checks.sensitivity_packages import (
        dynamic_fc_sensitivity_package_check,
        graph_atlas_hrf_sensitivity_package_check,
        gsr_sensitivity_package_check,
    )
    from brain_researcher.services.review.checks.task_construct_validity import (
        behavioral_imbalance_not_modeled_check,
        stimulus_fixed_effect_risk_check,
        task_fc_ppi_evoked_response_control_check,
    )
    from brain_researcher.services.review.checks.value_domain import (
        value_domain_contract_violation_check,
    )
    from brain_researcher.services.review.kg_rule_registry import (
        evaluate_kg_review_registry,
        merge_kg_registry_findings,
    )
    from brain_researcher.services.review.rule_engine import get_engine

    resolved_run_dir = _find_run_dir(run_id, run_dir=run_dir)

    # Check cache.
    cache_path = resolved_run_dir / "scientific_review_verdict.json"
    if not force_recompute and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_verdict = ScientificReviewVerdict.model_validate(data)
            sidecar_paths = (
                resolved_run_dir / "evidence_gate.json",
                resolved_run_dir / "claim_report.json",
                resolved_run_dir / "claim_update.json",
            )
            if not all(path.exists() for path in sidecar_paths):
                from brain_researcher.services.review.bundle_builder import (
                    build_artifact_review_bundle,
                )

                bundle = build_artifact_review_bundle(
                    run_id,
                    run_dir=resolved_run_dir,
                    workflow_id=workflow_id,
                )
                _write_scientific_episode_sidecars(
                    run_id=run_id,
                    run_dir=resolved_run_dir,
                    bundle=bundle,
                    verdict=cached_verdict,
                    force=False,
                )
            return cached_verdict
        except Exception:
            pass

    from brain_researcher.services.review.bundle_builder import (
        build_artifact_review_bundle,
    )

    bundle = build_artifact_review_bundle(
        run_id,
        run_dir=resolved_run_dir,
        workflow_id=workflow_id,
    )

    # 1. Correctness verdict (deterministic).
    correctness_findings = []
    _correctness_checks = (
        # Existing structural checks
        design_matrix_rank_check,
        contrast_vector_dim_check,
        cross_file_n_subjects_check,
        effect_tstat_shape_check,
        # Design matrix numerical diagnostics
        condition_number_check,
        contrast_estimability_check,
        design_matrix_confound_column_consistency_check,
        multiple_comparison_metadata_consistency_check,
        correction_summary_numeric_consistency_check,
        contrast_table_semantics_check,
        cluster_table_count_consistency_check,
        cluster_table_semantics_check,
        peak_table_semantics_check,
        peak_cluster_membership_consistency_check,
        cluster_peak_cardinality_check,
        design_model_metadata_consistency_check,
        # Cross-step assumption consistency
        bandpass_glm_drift_overlap,
        preprocessing_stats_space_mismatch,
        bandpass_before_confound_regression,
        atlas_registration_space_mismatch,
        # Correlation matrix validity
        corr_has_nan_check,
        corr_symmetric_check,
        corr_diag_check,
        corr_range_check,
        corr_positive_semidefinite_check,
        corr_region_count_check,
        partial_correlation_required_diagnostics_check,
        partial_correlation_estimator_hazard_check,
        # Task-conditioned literature plausibility
        effect_size_plausibility_check,
        meta_analytic_spatial_plausibility_check,
        # review_context validity
        predictive_review_context_metadata_check,
        predictive_required_diagnostics_check,
        review_context_leakage_circularity_flag_check,
        review_context_mirror_conflict_check,
        external_evidence_path_integrity_check,
        # Predictive integrity
        predictive_fisher_z_input_domain_check,
        predictive_cv_leakage_check,
        predictive_split_integrity_check,
        # Additional leakage / non-independence (registry-backed)
        leakage_preprocessing_fit_scope_check,
        leakage_pseudoreplication_check,
        brainmap_correlation_spatial_null_check,
        # Circularity / confound (explicit-provenance only)
        double_dipping_check,
        demographic_confound_uncontrolled_check,
        # General value-domain contract violations
        value_domain_contract_violation_check,
        # neuroAI / selection validity
        neuroai_selection_on_test_check,
        neuroai_split_grouping_mismatch_check,
        neuroai_declared_subject_set_missing_subject_column_check,
        neuroai_subject_manifest_coverage_check,
        neuroai_subject_manifest_selection_source_subset_conflict_check,
        neuroai_subject_intersection_coverage_check,
        neuroai_subject_intersection_selection_source_subset_conflict_check,
        neuroai_subject_intersection_subset_conflict_check,
        neuroai_subject_selection_source_coverage_check,
        neuroai_split_manifest_missing_group_keys_check,
        neuroai_split_manifest_partition_conflict_check,
        neuroai_nested_cv_schema_missing_fold_keys_check,
        neuroai_nested_cv_outer_partition_gap_check,
        neuroai_nested_cv_outer_missing_inner_resampling_check,
        neuroai_nested_cv_inner_partition_gap_check,
        neuroai_nested_cv_outer_holdout_conflict_check,
        neuroai_selection_multiplicity_accounting_check,
        neuroai_winner_without_candidate_set_check,
        neuroai_selection_validation_gap_check,
        # Null-model validity
        permutation_exchangeability_check,
        spatial_null_validity_check,
        surface_volume_correction_domain_mismatch_check,
        # Claim / sensitivity / construct validity
        claim_inflation_check,
        reverse_inference_risk_check,
        model_fit_mechanism_overreach_check,
        controversial_choice_sensitivity_check,
        construct_validity_confound_check,
        stimulus_fixed_effect_risk_check,
        behavioral_imbalance_not_modeled_check,
        task_fc_ppi_evoked_response_control_check,
        gsr_sensitivity_package_check,
        dynamic_fc_sensitivity_package_check,
        graph_atlas_hrf_sensitivity_package_check,
        # Claim/evidence label integrity
        epistemic_claim_policy_check,
        cross_study_coordinate_comparison_check,
        directional_claim_contradiction_check,
        # Design-method compatibility
        method_appropriateness_check,
    )

    # Optional, default-OFF routing: when BR_REVIEW_CHECK_ROUTING is enabled we
    # subset the correctness checks via check_routing.select_checks, which
    # preserves an always-on safety floor and keeps any check it cannot prove
    # irrelevant (false-negative-averse). When the flag is off, behaviour is
    # unchanged: every check runs.
    _active_checks = _correctness_checks
    import os as _os

    if _os.getenv("BR_REVIEW_CHECK_ROUTING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from brain_researcher.services.review.check_routing import select_checks

            _routing_decision = select_checks(
                bundle, [fn.__name__ for fn in _correctness_checks]
            )
            _active_checks = tuple(
                _routing_decision.select_callables(_correctness_checks)
            )
        except Exception:
            # On any routing failure, degrade to running every check.
            _active_checks = _correctness_checks

    for check_fn in _active_checks:
        finding = check_fn(bundle)
        if finding is not None:
            correctness_findings.append(finding)

    try:
        kg_registry_findings, _kg_rules_consulted = evaluate_kg_review_registry(
            bundle,
            engine=get_engine(),
            catalog_rule_ids_filter={
                finding.rule_id for finding in correctness_findings
            },
        )
        correctness_findings = merge_kg_registry_findings(
            correctness_findings,
            kg_registry_findings,
        )
    except Exception:
        pass

    # ASL quantification critic (retired from the public tool surface) runs
    # inside the gate when an ASL method contract is present in review_context.
    try:
        from brain_researcher.services.review.checks.asl_quant_gate import (
            asl_quantification_findings,
        )

        correctness_findings.extend(asl_quantification_findings(bundle))
    except Exception:
        pass

    if any(f.severity == "error" for f in correctness_findings):
        correctness_decision = "block"
    elif correctness_findings:
        correctness_decision = "flag"
    else:
        correctness_decision = "pass"

    correctness = CorrectnessVerdict(
        decision=correctness_decision,  # type: ignore[arg-type]
        findings=correctness_findings,
    )

    # 2. Judgment verdict (LLM, optional).
    if use_judgment_critic:
        from brain_researcher.services.review.judgment_critic import run_judgment_critic

        # B3.5: Enrich bundle with effect-size priors for the judgment critic.
        enriched_bundle = _enrich_bundle_with_effect_priors(bundle)
        judgment = run_judgment_critic(enriched_bundle)
    else:
        judgment = JudgmentVerdict(decision="sound")

    # 3. Completeness verdict (deterministic checklist).
    checklist = build_completeness_checklist(bundle)
    missing_keys = [k for k, v in checklist.items() if not v]
    completeness = CompletenessVerdict(
        decision="incomplete" if missing_keys else "complete",  # type: ignore[arg-type]
        checklist=checklist,
        missing_caveats=[f"{k} not specified" for k in missing_keys],
    )

    overall_decision, rationale = roll_up_scientific_decision(
        correctness, judgment, completeness
    )

    (
        claim_strength,
        report_action,
        required_next_actions,
        validation_status,
    ) = derive_verdict_metadata(
        correctness,
        judgment,
        completeness,
        overall_decision,
        scope="pipeline_run",
        validation_evidence_present=False,
        replication_evidence_present=False,
    )

    verdict = ScientificReviewVerdict(
        correctness=correctness,
        judgment=judgment,
        completeness=completeness,
        review_scope="pipeline_run",
        overall_decision=overall_decision,  # type: ignore[arg-type]
        claim_strength=claim_strength,
        report_action=report_action,
        required_next_actions=required_next_actions,
        validation_status=validation_status,
        rationale=rationale,
    )

    # Cache result.
    try:
        cache_path.write_text(
            json.dumps(verdict.model_dump(), indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    _write_scientific_episode_sidecars(
        run_id=run_id,
        run_dir=resolved_run_dir,
        bundle=bundle,
        verdict=verdict,
        force=True,
    )

    return verdict
