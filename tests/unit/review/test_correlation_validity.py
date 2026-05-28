"""Unit tests for deterministic correlation / FC validity checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.correlation_validity import (
    corr_diag_check,
    corr_positive_semidefinite_check,
    corr_range_check,
    corr_symmetric_check,
    partial_correlation_estimator_hazard_check,
    partial_correlation_required_diagnostics_check,
)


@pytest.mark.unit
class TestPartialCorrelationEstimatorHazardCheck:
    def test_blocks_partial_correlation_when_timepoints_do_not_exceed_rois(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "partial_correlation",
                "partial_correlation_estimator": "EmpiricalCovariance",
                "n_timepoints": 80,
                "n_rois": 100,
            }
        )

        finding = partial_correlation_estimator_hazard_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_SINGULAR"
        assert finding.severity == "critical"
        assert finding.action == "block"
        assert any("n_timepoints=80" in item for item in finding.kg_evidence)
        assert any("EmpiricalCovariance" in item for item in finding.kg_evidence)

    def test_blocks_partial_correlation_with_high_condition_number(self):
        bundle = CodeReviewBundle(
            review_context={
                "connectivity": {
                    "matrix_kind": "partial_correlation",
                    "precision_estimator": "GraphicalLassoCV",
                    "n_timepoints": 240,
                    "n_rois": 100,
                    "precision_condition_number": 1e12,
                }
            }
        )

        finding = partial_correlation_estimator_hazard_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_SINGULAR"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert any("precision_condition_number" in item for item in finding.kg_evidence)

    def test_blocks_partial_correlation_with_insufficient_estimator_rank(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "corr_matrix_kind": "partial corr",
                "n_timepoints": 240,
                "corr_n_regions": 120,
                "covariance_rank": 87,
            }
        )

        finding = partial_correlation_estimator_hazard_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_SINGULAR"
        assert finding.severity == "critical"
        assert any("covariance_rank=87" in item for item in finding.kg_evidence)

    def test_blocks_partial_correlation_with_near_zero_min_eig(self):
        bundle = CodeReviewBundle(
            review_context={
                "feature_contract": {
                    "matrix_kind": "precision-derived",
                    "precision_estimator": "LedoitWolf",
                    "n_timepoints": 240,
                    "n_rois": 100,
                    "min_eig": 1e-12,
                }
            }
        )

        finding = partial_correlation_estimator_hazard_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_SINGULAR"
        assert finding.severity == "critical"
        assert any("min_eig" in item for item in finding.kg_evidence)

    def test_does_not_apply_partial_hazard_to_pearson_fc(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "pearson_correlation",
                "n_timepoints": 80,
                "n_rois": 100,
                "precision_condition_number": 1e12,
            }
        )

        assert partial_correlation_estimator_hazard_check(bundle) is None


@pytest.mark.unit
class TestPartialCorrelationRequiredDiagnosticsCheck:
    def test_blocks_partial_correlation_without_stability_diagnostics(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "partial_correlation",
                "precision_estimator": "LedoitWolf",
                "n_rois": 100,
            }
        )

        finding = partial_correlation_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_MISSING_DIAGNOSTIC"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert any(
            "rank_or_condition_or_min_eig" in item for item in finding.kg_evidence
        )

    def test_blocks_empirical_partial_correlation_without_sample_size(self):
        bundle = CodeReviewBundle(
            review_context={
                "connectivity": {
                    "matrix_kind": "partial_correlation",
                    "precision_estimator": "EmpiricalCovariance",
                    "n_rois": 100,
                    "precision_condition_number": 1e4,
                }
            }
        )

        finding = partial_correlation_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_MATRIX_PARTIAL_MISSING_DIAGNOSTIC"
        assert any("effective_n_timepoints" in item for item in finding.kg_evidence)

    def test_allows_partial_correlation_with_required_diagnostics(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "partial_correlation",
                "precision_estimator": "GraphicalLassoCV",
                "n_rois": 100,
                "precision_condition_number": 1e4,
            }
        )

        assert partial_correlation_required_diagnostics_check(bundle) is None

    def test_ignores_pearson_correlation_without_partial_diagnostics(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "pearson_correlation",
                "n_rois": 100,
            }
        )

        assert partial_correlation_required_diagnostics_check(bundle) is None

    def test_does_not_block_regularized_partial_correlation_only_for_p_ge_n(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "partial_correlation",
                "precision_estimator": "GraphicalLassoCV",
                "n_timepoints": 80,
                "n_rois": 100,
                "precision_rank": 100,
                "precision_condition_number": 1e4,
            }
        )

        assert partial_correlation_estimator_hazard_check(bundle) is None

    def test_allows_well_conditioned_partial_correlation(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "matrix_kind": "partial_correlation",
                "precision_estimator": "LedoitWolf",
                "n_timepoints": 400,
                "n_rois": 100,
                "precision_rank": 100,
                "precision_condition_number": 1e4,
            }
        )

        assert partial_correlation_estimator_hazard_check(bundle) is None


@pytest.mark.unit
class TestCorrelationRangeCheck:
    def test_allows_out_of_range_values_when_artifact_declares_fisher_z_state(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "corr_range_valid": False,
                "corr_transform_state": "fisher_z",
            }
        )

        assert corr_range_check(bundle) is None

    def test_blocks_out_of_range_raw_correlation_values(self):
        bundle = CodeReviewBundle(stats_metrics={"corr_range_valid": False})

        finding = corr_range_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CORR_OUT_OF_RANGE"

    def test_skips_correlation_semantic_checks_for_structural_connectome(self):
        bundle = CodeReviewBundle(
            stats_metrics={
                "corr_matrix_kind": "structural_connectome",
                "corr_symmetric": False,
                "corr_diag_all_ones": False,
                "corr_range_valid": False,
                "corr_positive_semidefinite": False,
            }
        )

        assert corr_symmetric_check(bundle) is None
        assert corr_diag_check(bundle) is None
        assert corr_range_check(bundle) is None
        assert corr_positive_semidefinite_check(bundle) is None
