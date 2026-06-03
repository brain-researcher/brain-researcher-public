"""Unit tests for the additional leakage / non-independence review checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.leakage_extra import (
    brainmap_correlation_spatial_null_check,
    leakage_preprocessing_fit_scope_check,
    leakage_pseudoreplication_check,
)


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


@pytest.mark.unit
class TestPreprocessingFitScopeCheck:
    def test_flags_standardization_outside_cv_via_mapping(self):
        bundle = _bundle(
            {
                "fit_scope_by_step": {
                    "standardization": "full_dataset",
                    "feature_selection": "train_fold_only",
                }
            }
        )
        finding = leakage_preprocessing_fit_scope_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE"
        assert finding.severity == "critical"
        assert finding.action == "block"
        assert any("REVIEW_LEAKAGE_SCALER_FULL" in e for e in finding.kg_evidence)
        assert any("standardization" in e for e in finding.kg_evidence)
        assert "leakage" in finding.reason_tags

    def test_flags_harmonization_and_confound_regression(self):
        bundle = _bundle(
            {
                "preprocessing": {
                    "fit_scope_by_step": {
                        "harmonization": "all_data",
                        "confound_regression": "outside_cv",
                    }
                }
            }
        )
        finding = leakage_preprocessing_fit_scope_check(bundle)
        assert finding is not None
        rule_ids_blob = " ".join(finding.kg_evidence)
        assert "REVIEW_LEAKAGE_HARMONIZATION_FULL" in rule_ids_blob
        assert "REVIEW_LEAKAGE_RESIDUALIZER_FULL" in rule_ids_blob

    def test_flags_structured_pipeline_steps_list(self):
        bundle = _bundle(
            {
                "pipeline_steps": [
                    {"step": "scaler", "fit_scope": "full_dataset"},
                    {"step": "model", "fit_scope": "train_fold_only"},
                ]
            }
        )
        finding = leakage_preprocessing_fit_scope_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE"

    def test_error_severity_for_variance_mask_only(self):
        bundle = _bundle(
            {"fit_scope_by_step": {"variance_mask": "full_dataset"}}
        )
        finding = leakage_preprocessing_fit_scope_check(bundle)
        assert finding is not None
        assert finding.severity == "error"

    def test_no_finding_for_train_fold_only(self):
        bundle = _bundle(
            {
                "fit_scope_by_step": {
                    "standardization": "train_fold_only",
                    "harmonization": "per_fold",
                }
            }
        )
        assert leakage_preprocessing_fit_scope_check(bundle) is None

    def test_no_finding_when_no_provenance(self):
        assert leakage_preprocessing_fit_scope_check(_bundle()) is None

    def test_ignores_unknown_step_names(self):
        bundle = _bundle({"fit_scope_by_step": {"some_unrelated_step": "full_dataset"}})
        assert leakage_preprocessing_fit_scope_check(bundle) is None


@pytest.mark.unit
class TestPseudoreplicationCheck:
    def test_flags_repeated_as_independent(self):
        bundle = _bundle({"declared_n": 400, "n_unique_subjects": 100})
        finding = leakage_pseudoreplication_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_LEAKAGE_REPEATED_AS_INDEP"
        assert finding.severity == "error"
        assert any("declared_n=400" in e for e in finding.kg_evidence)
        assert "pseudoreplication" in finding.reason_tags

    def test_flags_from_subject_id_list(self):
        bundle = _bundle(
            {"n_observations": 6, "subject_ids": ["s1", "s1", "s2", "s2", "s3", "s3"]}
        )
        finding = leakage_pseudoreplication_check(bundle)
        assert finding is not None
        assert any("n_unique_subjects=3" in e for e in finding.kg_evidence)

    def test_no_finding_when_balanced(self):
        bundle = _bundle({"declared_n": 100, "n_unique_subjects": 100})
        assert leakage_pseudoreplication_check(bundle) is None

    def test_no_finding_when_repeated_measures_modeled(self):
        bundle = _bundle(
            {
                "declared_n": 400,
                "n_unique_subjects": 100,
                "repeated_measures_modeled": True,
            }
        )
        assert leakage_pseudoreplication_check(bundle) is None

    def test_no_finding_when_inference_at_subject_unit(self):
        bundle = _bundle(
            {
                "design": {
                    "declared_n": 400,
                    "n_unique_subjects": 100,
                    "independence_unit": "subject",
                }
            }
        )
        assert leakage_pseudoreplication_check(bundle) is None

    def test_no_finding_without_counts(self):
        assert leakage_pseudoreplication_check(_bundle()) is None


@pytest.mark.unit
class TestBrainmapSpatialNullCheck:
    def test_flags_map_correlation_without_spatial_null(self):
        bundle = _bundle(
            {
                "inference": {
                    "map_map_correlation": True,
                    "spatial_null_present": False,
                }
            }
        )
        finding = brainmap_correlation_spatial_null_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_INFERENCE_NO_SPIN_TEST"
        assert finding.severity == "error"
        assert "spatial_null" in finding.reason_tags

    def test_no_finding_when_spatial_null_present(self):
        bundle = _bundle(
            {
                "inference": {
                    "map_map_correlation": True,
                    "spatial_null_method": "spin_test",
                }
            }
        )
        assert brainmap_correlation_spatial_null_check(bundle) is None

    def test_no_finding_without_explicit_absence_marker(self):
        # Claim present but no explicit spatial_null_present=False marker:
        # stays silent to remain high-precision.
        bundle = _bundle({"inference": {"map_map_correlation": True}})
        assert brainmap_correlation_spatial_null_check(bundle) is None

    def test_no_finding_when_no_claim(self):
        bundle = _bundle({"inference": {"spatial_null_present": False}})
        assert brainmap_correlation_spatial_null_check(bundle) is None

    def test_required_but_absent_fires(self):
        bundle = _bundle(
            {
                "map_correspondence": {"r": 0.6},
                "spatial_null_required": True,
            }
        )
        finding = brainmap_correlation_spatial_null_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_INFERENCE_NO_SPIN_TEST"
