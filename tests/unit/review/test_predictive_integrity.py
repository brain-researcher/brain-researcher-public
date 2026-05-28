"""Unit tests for predictive integrity review checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


@pytest.mark.unit
class TestPredictiveFisherZInputDomainCheck:
    def test_flags_outside_unit_interval_fraction(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_fisher_z_input_domain_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "preprocessing": {
                    "fisher_z_applied": True,
                    "outside_unit_interval_fraction": 0.08,
                },
            }
        )

        finding = predictive_fisher_z_input_domain_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == [
            "predictive",
            "preprocessing",
            "data_contract",
        ]
        assert any("fisher_z_applied=True" in item for item in finding.kg_evidence)
        assert any(
            "outside_unit_interval_fraction=0.08" in item
            for item in finding.kg_evidence
        )

    def test_flags_already_fisher_z_transform_state(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_fisher_z_input_domain_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "preprocessing": {
                    "fisher_z_applied": True,
                    "input_transform_state": "already_fisher_z",
                },
            }
        )

        finding = predictive_fisher_z_input_domain_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN"
        assert finding.action == "block"
        assert any("already_fisher_z" in item for item in finding.kg_evidence)

    def test_ignores_missing_fisher_z_or_zero_fraction(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_fisher_z_input_domain_check,
        )

        no_fisher_z_bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "preprocessing": {"outside_unit_interval_fraction": 0.08},
            }
        )
        zero_fraction_bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "feature_diagnostics": {
                    "fisher_z_applied": True,
                    "outside_unit_interval_fraction": 0.0,
                },
            }
        )

        assert predictive_fisher_z_input_domain_check(no_fisher_z_bundle) is None
        assert predictive_fisher_z_input_domain_check(zero_fraction_bundle) is None


@pytest.mark.unit
class TestPredictiveCvLeakageCheck:
    def test_flags_explicit_full_dataset_feature_selection_scope(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_cv_leakage_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "preprocessing": {
                    "feature_selection_scope": "full_dataset",
                    "standardization_scope": "train_only",
                },
            }
        )

        finding = predictive_cv_leakage_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_CV_LEAKAGE"
        assert finding.action == "block"
        assert "leakage" in finding.reason_tags
        assert "predictive" in finding.reason_tags
        assert any("feature_selection_scope" in item for item in finding.kg_evidence)

    def test_flags_explicit_cv_leakage_boolean(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_cv_leakage_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "provenance": {"cv_leakage": True},
            }
        )

        finding = predictive_cv_leakage_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_CV_LEAKAGE"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert "leakage" in finding.reason_tags
        assert any("cv_leakage" in item for item in finding.kg_evidence)

    def test_ignores_safe_train_only_scopes(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_cv_leakage_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "preprocessing": {
                    "feature_selection_scope": "train_only",
                    "harmonization_fit_scope": "within_train_fold",
                    "standardization_scope": "train_fold_only",
                },
            }
        )

        assert predictive_cv_leakage_check(bundle) is None

    def test_ignores_missing_provenance(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_cv_leakage_check,
        )

        bundle = _bundle({"scientific_review_profile": "predictive_model_review"})
        assert predictive_cv_leakage_check(bundle) is None


@pytest.mark.unit
class TestPredictiveSplitIntegrityCheck:
    def test_flags_explicit_train_test_overlap(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_split_integrity_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "split": {
                    "split_unit": "subject",
                    "train_subject_ids": ["sub-01", "sub-02"],
                    "test_subject_ids": ["sub-02", "sub-03"],
                    "train_test_independence": True,
                },
            }
        )

        finding = predictive_split_integrity_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_SPLIT_INTEGRITY"
        assert finding.action == "block"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("sub-02" in item for item in finding.kg_evidence)

    def test_flags_explicit_false_train_test_independence(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_split_integrity_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "train_test_independence": False,
            }
        )

        finding = predictive_split_integrity_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PREDICTIVE_SPLIT_INTEGRITY"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any(
            "train_test_independence=False" in item for item in finding.kg_evidence
        )

    def test_ignores_disjoint_explicit_splits(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_split_integrity_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "split": {
                    "split_unit": "subject",
                    "train_subject_ids": ["sub-01", "sub-02"],
                    "test_subject_ids": ["sub-03", "sub-04"],
                    "validation_subject_ids": ["sub-05"],
                },
            }
        )

        assert predictive_split_integrity_check(bundle) is None

    def test_ignores_missing_split_membership(self):
        from brain_researcher.services.review.checks.predictive_integrity import (
            predictive_split_integrity_check,
        )

        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "split": {"split_unit": "subject"},
            }
        )

        assert predictive_split_integrity_check(bundle) is None
