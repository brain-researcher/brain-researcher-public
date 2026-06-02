"""Safety-regression battery for ``check_routing.select_checks``.

Why this exists
---------------
``BR_REVIEW_CHECK_ROUTING`` (see ``distill_review.distill_scientific_review_records``)
gates an *optional, default-OFF* routing layer that subsets the correctness
``check_fn`` tuple before running it. The routing layer is documented as
"false-negative-averse": it must only *skip* a check when it has positive
evidence the check is irrelevant for a bundle. The flag stays OFF until that
property is demonstrated, not asserted.

This battery builds **confidence to eventually flip the flag** without flipping
it. It assembles a battery of representative, *coherent* bundles -- one per
analysis family (functional connectivity, predictive / neuroAI, GLM,
GLM-design, null-model, task) -- where each bundle carries the
``review_context`` / ``kg_context`` / ``stats_metrics`` that actually make
specific correctness checks FIRE. For every bundle it asserts two safety
invariants of ``select_checks``:

1. **Finding-preserving.** Run the *entire* canonical correctness tuple against
   the bundle and collect the set of checks that return a ``ReviewFinding``.
   Routing must keep every one of those checks in ``selected`` -- i.e. enabling
   routing on this bundle would not drop a single check that would have produced
   a finding. This is the core regression guard: a routing-map edit that gates a
   firing check fails here.

2. **Safety floor preserved.** The always-on groups
   (structural_integrity / value_domain / leakage / null_model /
   review_context_integrity) are never dropped, and every present check that
   classifies into them survives, regardless of routing signals.

Honesty contract
----------------
- The canonical check tuple is reconstructed by importing the SAME check
  functions, in the SAME order, that ``distill_scientific_review_records`` wires
  into its local ``_correctness_checks`` tuple. ``test_canonical_tuple_matches_router_universe``
  guards against drift between this list and the router's classification map.
- We never assert that a particular check *must* fire on a bundle (that would
  duplicate the calibration harness and couple to check internals). We assert
  the weaker, routing-relevant property: *whatever* fires must be preserved.
  Bundles are constructed so that at least several conditional-group checks DO
  fire (``test_battery_actually_exercises_conditional_groups``), otherwise the
  finding-preservation assertion would be vacuous.
- ``test_routing_can_drop_on_mislabeled_bundle`` documents a KNOWN residual gap:
  routing is finding-preserving for *coherent* bundles, but a *mislabeled*
  bundle (e.g. a correlation matrix carrying GLM family signals and no FC
  ``review_context`` key) can still have a firing FC check dropped. This is
  surfaced, not hidden, and is the central caveat in the deploy ceiling below.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.services.review.check_routing import (
    ALWAYS_ON_GROUPS,
    classify_check,
    routing_shadow_report,
    select_checks,
)
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

# --------------------------------------------------------------------------- #
# Canonical correctness tuple.
#
# Reconstructed from the SAME imports distill_review.distill_scientific_review_records
# uses to build its local `_correctness_checks` tuple (see distill_review.py
# import block ~L521-L635 and the tuple ~L689-L786). Kept in the same order.
# `test_canonical_tuple_matches_router_universe` guards against drift.
# --------------------------------------------------------------------------- #


CheckFn = Callable[[CodeReviewBundle], "ReviewFinding | None"]

# Order mirrors distill_review's `_correctness_checks`.
CANONICAL_CHECKS: tuple[CheckFn, ...] = (
    design_matrix_rank_check,
    contrast_vector_dim_check,
    cross_file_n_subjects_check,
    effect_tstat_shape_check,
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
    bandpass_glm_drift_overlap,
    preprocessing_stats_space_mismatch,
    bandpass_before_confound_regression,
    atlas_registration_space_mismatch,
    corr_has_nan_check,
    corr_symmetric_check,
    corr_diag_check,
    corr_range_check,
    corr_positive_semidefinite_check,
    corr_region_count_check,
    partial_correlation_required_diagnostics_check,
    partial_correlation_estimator_hazard_check,
    effect_size_plausibility_check,
    meta_analytic_spatial_plausibility_check,
    predictive_review_context_metadata_check,
    predictive_required_diagnostics_check,
    review_context_leakage_circularity_flag_check,
    review_context_mirror_conflict_check,
    external_evidence_path_integrity_check,
    predictive_fisher_z_input_domain_check,
    predictive_cv_leakage_check,
    predictive_split_integrity_check,
    leakage_preprocessing_fit_scope_check,
    leakage_pseudoreplication_check,
    brainmap_correlation_spatial_null_check,
    double_dipping_check,
    demographic_confound_uncontrolled_check,
    value_domain_contract_violation_check,
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
    permutation_exchangeability_check,
    spatial_null_validity_check,
    surface_volume_correction_domain_mismatch_check,
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
    epistemic_claim_policy_check,
    cross_study_coordinate_comparison_check,
    directional_claim_contradiction_check,
    method_appropriateness_check,
)

ALL_CHECK_NAMES: list[str] = [fn.__name__ for fn in CANONICAL_CHECKS]


def _fire(name_to_fn: dict[str, CheckFn], bundle: CodeReviewBundle) -> set[str]:
    """Names of canonical checks that return a finding on ``bundle``.

    Defensive: a check that raises on a partial bundle is treated as
    non-firing for the purposes of this battery (the routing layer's job is to
    preserve *findings*, and a raising check produces none). This keeps the
    battery from coupling to incidental check fragility.
    """
    fired: set[str] = set()
    for name, fn in name_to_fn.items():
        try:
            finding = fn(bundle)
        except Exception:
            continue
        if finding is not None:
            fired.add(name)
    return fired


_NAME_TO_FN: dict[str, CheckFn] = {fn.__name__: fn for fn in CANONICAL_CHECKS}


# --------------------------------------------------------------------------- #
# Battery of representative, COHERENT bundles.
#
# Each bundle carries kg_context / declared_modalities matching its analysis
# family AND a review_context that makes specific conditional-group checks fire.
# Firing contexts are drawn from the live calibration harness
# (test_calibration_cases_run_engine.py) and the deterministic check sources.
# --------------------------------------------------------------------------- #


def _fc_bundle() -> CodeReviewBundle:
    """Functional-connectivity run with an invalid correlation matrix + partial-corr gap."""
    return CodeReviewBundle(
        run_id="battery-fc",
        declared_modalities=["fmri", "bold"],
        kg_context={
            "analysis_family": "embedding_analysis",
            "statistical_method": "correlation_pearson",
        },
        review_context={
            "functional_connectivity": {"atlas": "schaefer400"},
            "partial_correlation": {
                "matrix_kind": "partial_correlation",
            },
        },
        stats_metrics={
            "corr_has_nan": True,
            "corr_symmetric": False,
            "corr_range_valid": False,
            "corr_n_regions": 1,
        },
    )


def _predictive_bundle() -> CodeReviewBundle:
    """Predictive / neuroAI run: subject-leaky CV split + post-hoc selection."""
    return CodeReviewBundle(
        run_id="battery-predictive",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "tribe_prediction",
            "statistical_method": "neural_encoding_prediction",
        },
        review_context={
            "predictive": True,
            "cross_validation": {"strategy": "kfold"},
            "split_manifest": {"folds": []},
            "preprocessing": {"selection_scope": "test_set"},
            "model_candidates": ["m1", "m2"],
            "required_group_keys": ["subject"],
            "grouped_split_keys": [],
            "split_unit": "sample",
            "split_strategy": "random_split",
            "selection": {"best_model": "m1"},
        },
    )


def _neuroai_selection_bundle() -> CodeReviewBundle:
    """neuroAI selection run: many candidates, winner, no multiplicity/holdout."""
    return CodeReviewBundle(
        run_id="battery-neuroai-selection",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "embedding_analysis",
            "statistical_method": "embedding_autoresearch",
        },
        review_context={
            "selection": {"best_model": "m2", "best_layer": "l2"},
            "model_candidates": ["m1", "m2", "m3", "m4"],
            "layer_candidates": ["l1", "l2", "l3"],
        },
    )


def _glm_design_bundle() -> CodeReviewBundle:
    """GLM run with a rank-deficient design matrix + estimability problems."""
    return CodeReviewBundle(
        run_id="battery-glm-design",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "glm",
            "statistical_method": "one_sample_t_test",
            "design_type": "one_sample",
        },
        review_context={
            "design_matrix": {"rank": 2, "n_columns": 4},
            "contrasts": [{"name": "A>B", "vector": [1, -1, 0, 0]}],
            "first_level": {"model": "spm"},
        },
        stats_metrics={
            "design_matrix_rank": 2,
            "design_matrix_n_columns": 4,
            "design_matrix_condition_number": 1e12,
        },
    )


def _glm_task_bundle() -> CodeReviewBundle:
    """Task GLM run: task-FC/PPI without evoked-response control + GSR + stimulus generalization."""
    return CodeReviewBundle(
        run_id="battery-glm-task",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "ppi",
            "statistical_method": "linear_regression",
        },
        review_context={
            "analysis_family": "ppi",
            "task": {"name": "nback"},
            "events": {"present": True},
            "mean_evoked_response_removed": False,
            "stimulus_generalization": True,
            "preprocessing": {"gsr": True},
            "gsr": True,
        },
    )


def _null_model_bundle() -> CodeReviewBundle:
    """Spatial / null-model run: surface data with volume cluster correction + bad permutation."""
    return CodeReviewBundle(
        run_id="battery-null-model",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "glm",
            "statistical_method": "permutation_test",
        },
        review_context={
            "data_domain": "surface",
            "correction_domain": "volume",
            "null_model": {"exchangeability_status": "invalid"},
            "map_map_correlation": True,
            "spatial_null_present": False,
        },
    )


def _leakage_bundle() -> CodeReviewBundle:
    """Preprocessing-leakage run: harmonization/standardization fit on full dataset + pseudoreplication."""
    return CodeReviewBundle(
        run_id="battery-leakage",
        declared_modalities=["fmri"],
        kg_context={
            "analysis_family": "tribe_prediction",
            "statistical_method": "linear_regression",
        },
        review_context={
            "predictive": True,
            "fit_scope_by_step": {
                "harmonization": "full_dataset",
                "standardization": "full_dataset",
            },
            "sample": {"declared_n": 200, "n_unique_subjects": 40},
        },
    )


def _value_domain_bundle() -> CodeReviewBundle:
    """Run that trips a value-domain contract violation (always-on floor)."""
    return CodeReviewBundle(
        run_id="battery-value-domain",
        declared_modalities=["fmri"],
        kg_context={"analysis_family": "embedding_analysis"},
        review_context={
            "value_domain_diagnostics": [
                {
                    "ok": False,
                    "severity": "error",
                    "contract": "correlation_range",
                    "name": "fc_edge",
                    "detail": "value 1.4 outside [-1, 1]",
                }
            ],
        },
    )


BATTERY: dict[str, Callable[[], CodeReviewBundle]] = {
    "fc": _fc_bundle,
    "predictive": _predictive_bundle,
    "neuroai_selection": _neuroai_selection_bundle,
    "glm_design": _glm_design_bundle,
    "glm_task": _glm_task_bundle,
    "null_model": _null_model_bundle,
    "leakage": _leakage_bundle,
    "value_domain": _value_domain_bundle,
}


# --------------------------------------------------------------------------- #
# Drift guard.
# --------------------------------------------------------------------------- #


def test_canonical_tuple_matches_router_universe() -> None:
    """Reconstructed tuple must be unique and a superset of every classified check.

    Guards two drift directions:
      * If distill_review adds a check that classifies into a routing group but
        this battery's CANONICAL_CHECKS omits it, the battery would silently
        stop covering it -- so every name the router classifies must be present.
      * Duplicate entries in the tuple would skew firing counts.
    """
    from brain_researcher.services.review.check_routing import _CHECK_TO_GROUP

    assert len(ALL_CHECK_NAMES) == len(set(ALL_CHECK_NAMES)), "duplicate check in tuple"

    classified = set(_CHECK_TO_GROUP)
    missing = classified - set(ALL_CHECK_NAMES)
    assert not missing, (
        "router classifies checks absent from the battery's canonical tuple "
        f"(update CANONICAL_CHECKS to match distill_review): {sorted(missing)}"
    )


def test_battery_actually_exercises_conditional_groups() -> None:
    """At least several CONDITIONAL-group checks must fire across the battery.

    Without this the finding-preservation assertion could pass vacuously (if no
    conditional check ever fires, routing can never drop a firing one). We
    require firing checks that classify into *non*-always-on groups.
    """
    conditional_fired: set[str] = set()
    floor_fired: set[str] = set()
    for build in BATTERY.values():
        bundle = build()
        for name in _fire(_NAME_TO_FN, bundle):
            group = classify_check(name)
            if group is None:
                continue
            if group in ALWAYS_ON_GROUPS:
                floor_fired.add(name)
            else:
                conditional_fired.add(name)
    assert len(conditional_fired) >= 4, (
        "battery does not exercise enough conditional-group checks; "
        f"only fired: {sorted(conditional_fired)}"
    )
    # Exercise the floor non-vacuously too: at least one always-on check fires.
    assert floor_fired, "battery does not exercise any always-on (floor) check"


@pytest.mark.parametrize("name", sorted(BATTERY), ids=sorted(BATTERY))
def test_routing_is_finding_preserving(name: str) -> None:
    """Routing never drops a check that actually fires on this bundle."""
    bundle = BATTERY[name]()
    fired = _fire(_NAME_TO_FN, bundle)

    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    selected = set(decision.selected)

    dropped_firing = fired - selected
    assert not dropped_firing, (
        f"[{name}] routing dropped checks that fire a finding on this bundle: "
        f"{sorted(dropped_firing)} (reasons: "
        f"{ {n: decision.skipped.get(n) for n in sorted(dropped_firing)} })"
    )


@pytest.mark.parametrize("name", sorted(BATTERY), ids=sorted(BATTERY))
def test_routing_keeps_safety_floor(name: str) -> None:
    """Every present always-on-group check survives routing, on every bundle."""
    bundle = BATTERY[name]()
    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    selected = set(decision.selected)

    # The safety floor groups are always active.
    assert ALWAYS_ON_GROUPS <= decision.active_groups

    floor_checks = {n for n in ALL_CHECK_NAMES if classify_check(n) in ALWAYS_ON_GROUPS}
    dropped_floor = floor_checks - selected
    assert (
        not dropped_floor
    ), f"[{name}] routing dropped safety-floor checks: {sorted(dropped_floor)}"
    # None of the floor checks may ever appear in `skipped`.
    assert not (floor_checks & set(decision.skipped)), (
        f"[{name}] safety-floor checks appear in skipped map: "
        f"{sorted(floor_checks & set(decision.skipped))}"
    )


@pytest.mark.parametrize("name", sorted(BATTERY), ids=sorted(BATTERY))
def test_routing_keeps_unclassified_checks(name: str) -> None:
    """Unclassified (claim/epistemic) checks are always kept (false-negative-averse)."""
    bundle = BATTERY[name]()
    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    selected = set(decision.selected)

    unclassified = {n for n in ALL_CHECK_NAMES if classify_check(n) is None}
    assert unclassified, "expected some unclassified checks in the tuple"
    assert unclassified <= selected, (
        f"[{name}] routing dropped unclassified checks: "
        f"{sorted(unclassified - selected)}"
    )


def test_routing_keeps_everything_when_no_family_signal() -> None:
    """A bundle with no coarse family signal must keep every check."""
    # FC matrix is broken but the bundle exposes no family/method/design/modality.
    bundle = CodeReviewBundle(
        run_id="battery-no-signal",
        review_context={},
        stats_metrics={"corr_has_nan": True, "corr_symmetric": False},
    )
    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    assert (
        not decision.skipped
    ), f"no-family-signal bundle dropped checks: {sorted(decision.skipped)}"
    assert set(decision.selected) == set(ALL_CHECK_NAMES)


def test_routing_degrades_to_keep_all_on_malformed_bundle() -> None:
    """Signal extraction failure degrades to running every check."""

    class _Boom:
        run_id = "boom"

        @property
        def kg_context(self):  # noqa: D401 - raises on access
            raise RuntimeError("kg_context blew up")

    decision = select_checks(_Boom(), ALL_CHECK_NAMES, log=False)
    assert set(decision.selected) == set(ALL_CHECK_NAMES)
    assert not decision.skipped


# --------------------------------------------------------------------------- #
# Shadow helper.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(BATTERY), ids=sorted(BATTERY))
def test_shadow_report_is_consistent_with_select_checks(name: str) -> None:
    """routing_shadow_report mirrors select_checks without altering it."""
    bundle = BATTERY[name]()
    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    report = routing_shadow_report(bundle, ALL_CHECK_NAMES)

    assert report["run_id"] == bundle.run_id
    assert report["would_skip"] == decision.skipped
    assert report["would_skip_count"] == len(decision.skipped)
    assert report["would_run_count"] == len(decision.selected)
    assert report["total"] == len(ALL_CHECK_NAMES)
    assert report["would_change"] is bool(decision.skipped)
    # Serialisable: sets coerced to sorted lists.
    assert isinstance(report["signals"]["modalities"], list)
    assert isinstance(report["active_groups"], list)


def test_shadow_report_never_drops_a_firing_check() -> None:
    """Across the battery, the shadow report never proposes skipping a firing check."""
    for build in BATTERY.values():
        bundle = build()
        fired = _fire(_NAME_TO_FN, bundle)
        report = routing_shadow_report(bundle, ALL_CHECK_NAMES)
        would_skip = set(report["would_skip"])
        assert not (fired & would_skip), (
            f"shadow report would skip firing checks on {bundle.run_id}: "
            f"{sorted(fired & would_skip)}"
        )


# --------------------------------------------------------------------------- #
# KNOWN RESIDUAL GAP (documented, not hidden).
# --------------------------------------------------------------------------- #


def test_routing_can_drop_on_mislabeled_bundle() -> None:
    """Document the boundary: routing is NOT finding-preserving for MISLABELED bundles.

    This is the central caveat before defaulting routing ON. The battery above
    proves preservation for *coherent* bundles. Here we construct an incoherent
    one -- a correlation matrix with NaN/asymmetry (so FC checks fire) but whose
    kg_context claims a pure GLM family and whose review_context carries only a
    GLM design key (no FC ``review_context`` key, no FC modality match because
    ``anat`` is declared). Routing legitimately (under its current rules) skips
    the ``correlation_matrix`` group, dropping firing FC checks.

    We assert this drop HAPPENS so the gap is tracked: if a future routing edit
    closes it (e.g. by also keying ``correlation_matrix`` off the presence of
    ``corr_*`` stats_metrics), this test will fail and should be updated to the
    stronger preservation guarantee.
    """
    bundle = CodeReviewBundle(
        run_id="battery-mislabeled",
        declared_modalities=["anat"],
        kg_context={
            "analysis_family": "glm",
            "statistical_method": "paired_t_test",
            "design_type": "repeated_measures",
        },
        review_context={"design_matrix": {"rank": 4}},
        stats_metrics={"corr_has_nan": True, "corr_symmetric": False},
    )
    fired = _fire(_NAME_TO_FN, bundle)
    assert {
        "corr_has_nan_check",
        "corr_symmetric_check",
    } <= fired, "expected FC checks to fire on the mislabeled bundle"

    decision = select_checks(bundle, ALL_CHECK_NAMES, log=False)
    selected = set(decision.selected)
    dropped_firing = fired - selected
    assert dropped_firing, (
        "mislabeled bundle no longer drops a firing check -- routing may have "
        "been hardened against this gap; update this guard to assert full "
        "finding-preservation if so."
    )
    # The dropped firing checks must be exactly the FC ones (stats_metrics-driven),
    # never a safety-floor check.
    assert dropped_firing <= {
        "corr_has_nan_check",
        "corr_symmetric_check",
        "corr_diag_check",
        "corr_range_check",
        "corr_positive_semidefinite_check",
        "corr_region_count_check",
    }
    floor_checks = {n for n in ALL_CHECK_NAMES if classify_check(n) in ALWAYS_ON_GROUPS}
    assert not (dropped_firing & floor_checks)
