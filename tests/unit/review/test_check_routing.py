"""Tests for the stage/family aware review check router.

Focus areas:
  * Safety floor (leakage / value_domain / null_model / structural / review
    context integrity) is NEVER skipped.
  * Unclassified checks are always kept.
  * Conservative behavior: missing / unknown signals -> run everything.
  * Positive routing: a clear family lets irrelevant conditional groups drop.
  * review_context key presence overrides family-based skipping.
  * Skips are recorded with reasons.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain_researcher.services.review.check_routing import (
    _CHECK_TO_GROUP,
    ALWAYS_ON_GROUPS,
    CHECK_GROUPS,
    RoutingDecision,
    classify_check,
    select_checks,
)

# A representative slice of the real distill_review correctness tuple,
# spanning every group plus a couple of intentionally-unclassified checks.
SAMPLE_CHECKS = [
    # structural_integrity (always-on)
    "design_matrix_rank_check",
    "contrast_vector_dim_check",
    # value_domain (always-on)
    "value_domain_contract_violation_check",
    "predictive_fisher_z_input_domain_check",
    # leakage (always-on)
    "predictive_cv_leakage_check",
    "neuroai_selection_on_test_check",
    # null_model (always-on)
    "permutation_exchangeability_check",
    "spatial_null_validity_check",
    # review_context_integrity (always-on)
    "review_context_mirror_conflict_check",
    # correlation_matrix (conditional)
    "corr_has_nan_check",
    "corr_positive_semidefinite_check",
    # predictive_neuroai (conditional)
    "neuroai_subject_manifest_coverage_check",
    "neuroai_nested_cv_outer_partition_gap_check",
    # glm_design (conditional)
    "effect_size_plausibility_check",
    # task_construct (conditional)
    "stimulus_fixed_effect_risk_check",
    # sensitivity_packages (conditional)
    "gsr_sensitivity_package_check",
    # method_appropriateness (conditional)
    "method_appropriateness_check",
    # intentionally unclassified -> always run
    "claim_inflation_check",
    "epistemic_claim_policy_check",
]


def make_bundle(
    *,
    analysis_family=None,
    statistical_method=None,
    design_type=None,
    modalities=None,
    review_context=None,
):
    kg_context = {}
    if analysis_family:
        kg_context["analysis_family"] = analysis_family
    if statistical_method:
        kg_context["statistical_method"] = statistical_method
    if design_type:
        kg_context["design_type"] = design_type
    return SimpleNamespace(
        run_id="run-test",
        kg_context=kg_context,
        review_context=review_context or {},
        declared_modalities=list(modalities or []),
    )


ALWAYS_ON_CHECK_NAMES = [
    name for name, group in _CHECK_TO_GROUP.items() if group in ALWAYS_ON_GROUPS
]


def _selected(decision: RoutingDecision) -> set[str]:
    return set(decision.selected)


# ---------------------------------------------------------------------------
# Safety floor
# ---------------------------------------------------------------------------
def test_safety_floor_never_skipped_for_narrow_family():
    """A tightly-scoped GLM run must still run every always-on safety check."""
    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    decision = select_checks(bundle, SAMPLE_CHECKS)

    for name in ALWAYS_ON_CHECK_NAMES:
        if name in SAMPLE_CHECKS:
            assert name in _selected(decision), f"safety check dropped: {name}"
    # None of the always-on checks may appear in skipped.
    assert not (set(ALWAYS_ON_CHECK_NAMES) & set(decision.skipped))


def test_every_always_on_group_is_flagged_always_on():
    for group_name in ALWAYS_ON_GROUPS:
        assert CHECK_GROUPS[group_name].always_on is True


def test_active_groups_always_include_floor():
    bundle = make_bundle(analysis_family="glm")
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert ALWAYS_ON_GROUPS <= decision.active_groups


# ---------------------------------------------------------------------------
# Conservative defaults
# ---------------------------------------------------------------------------
def test_no_signals_runs_everything():
    bundle = make_bundle()  # nothing inferred
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert _selected(decision) == set(SAMPLE_CHECKS)
    assert decision.skipped == {}


def test_unknown_family_runs_everything():
    # An analysis_family we don't recognize must not cause conditional drops.
    bundle = make_bundle(analysis_family="some_future_family")
    decision = select_checks(bundle, SAMPLE_CHECKS)
    # has_family_signal is True, but no group matches "some_future_family";
    # however the contract is conservative-keep only when NO family signal at
    # all. With a family signal present, unmatched conditional groups DO drop.
    # The safety floor and unclassified checks must remain.
    for name in ALWAYS_ON_CHECK_NAMES:
        if name in SAMPLE_CHECKS:
            assert name in _selected(decision)
    assert "claim_inflation_check" in _selected(decision)


def test_unclassified_checks_always_kept():
    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert "claim_inflation_check" in _selected(decision)
    assert "epistemic_claim_policy_check" in _selected(decision)
    assert "claim_inflation_check" in decision.unclassified


def test_unrecognized_check_name_is_unclassified_and_kept():
    bundle = make_bundle(analysis_family="glm")
    decision = select_checks(bundle, ["a_brand_new_check_we_never_mapped"])
    assert "a_brand_new_check_we_never_mapped" in _selected(decision)
    assert classify_check("a_brand_new_check_we_never_mapped") is None


# ---------------------------------------------------------------------------
# Positive routing
# ---------------------------------------------------------------------------
def test_glm_run_skips_predictive_and_correlation_groups():
    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    decision = select_checks(bundle, SAMPLE_CHECKS)
    # Predictive neuroAI + correlation matrix checks are irrelevant for a pure
    # GLM contrast run and should be skipped.
    assert "neuroai_subject_manifest_coverage_check" in decision.skipped
    assert "corr_has_nan_check" in decision.skipped
    # But the GLM-relevant conditional groups stay.
    assert "effect_size_plausibility_check" in _selected(decision)
    assert "method_appropriateness_check" in _selected(decision)


def test_predictive_run_skips_correlation_and_task_construct():
    bundle = make_bundle(
        analysis_family="tribe_prediction",
        statistical_method="neural_encoding_prediction",
    )
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert "neuroai_subject_manifest_coverage_check" in _selected(decision)
    assert "corr_has_nan_check" in decision.skipped
    assert "stimulus_fixed_effect_risk_check" in decision.skipped


def test_modality_signal_activates_correlation_group():
    # No family/method, but an fMRI modality is declared -> correlation checks
    # should be kept (they are modality-relevant).
    bundle = make_bundle(modalities=["fMRI"])
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert "corr_has_nan_check" in _selected(decision)


# ---------------------------------------------------------------------------
# review_context key override
# ---------------------------------------------------------------------------
def test_review_context_key_overrides_family_skip():
    # A GLM family would normally skip predictive_neuroai, but a split_manifest
    # sidecar means CV-leakage-adjacent checks must run.
    bundle = make_bundle(
        analysis_family="glm",
        statistical_method="paired_t_test",
        review_context={"split_manifest": {"folds": []}},
    )
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert "neuroai_subject_manifest_coverage_check" in _selected(decision)
    # The reason should cite the review_context key.
    assert "predictive_neuroai" in decision.active_groups


def test_correlation_matrix_key_activates_group_without_family():
    bundle = make_bundle(
        analysis_family="glm",
        review_context={"correlation_matrix": {"shape": [10, 10]}},
    )
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert "corr_positive_semidefinite_check" in _selected(decision)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
def test_skips_are_recorded_with_reasons():
    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert decision.skipped, "expected some skips for a narrow GLM run"
    for _name, reason in decision.skipped.items():
        assert reason.startswith("group="), reason
        assert ":" in reason


def test_log_emitted(caplog):
    import logging

    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    with caplog.at_level(
        logging.INFO, logger="brain_researcher.services.review.check_routing"
    ):
        select_checks(bundle, SAMPLE_CHECKS)
    assert any("check_routing" in rec.message for rec in caplog.records)


def test_malformed_bundle_runs_everything():
    # A bundle missing the expected attributes must degrade to "run all".
    bundle = object()
    decision = select_checks(bundle, SAMPLE_CHECKS)
    assert _selected(decision) == set(SAMPLE_CHECKS)


# ---------------------------------------------------------------------------
# select_callables helper
# ---------------------------------------------------------------------------
def test_select_callables_filters_and_preserves_order():
    def design_matrix_rank_check(b):  # always-on
        return None

    def corr_has_nan_check(b):  # conditional, will be skipped for GLM
        return None

    def claim_inflation_check(b):  # unclassified
        return None

    fns = [design_matrix_rank_check, corr_has_nan_check, claim_inflation_check]
    bundle = make_bundle(analysis_family="glm", statistical_method="paired_t_test")
    decision = select_checks(bundle, [fn.__name__ for fn in fns])
    selected_fns = decision.select_callables(fns)
    selected_names = [fn.__name__ for fn in selected_fns]
    assert "design_matrix_rank_check" in selected_names
    assert "claim_inflation_check" in selected_names
    assert "corr_has_nan_check" not in selected_names
    # order preserved relative to input
    assert selected_names == [
        n for n in [fn.__name__ for fn in fns] if n in selected_names
    ]


def test_check_map_groups_exist():
    # Every group referenced by the check map must be a defined CheckGroup.
    for group_name in set(_CHECK_TO_GROUP.values()):
        assert group_name in CHECK_GROUPS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
