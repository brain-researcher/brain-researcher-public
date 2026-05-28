"""Unit tests for deterministic review_context validity checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.review_context_validity import (
    predictive_required_diagnostics_check,
)


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


@pytest.mark.unit
class TestPredictiveRequiredDiagnosticsCheck:
    def test_blocks_confirmatory_predictive_claim_missing_fit_scope(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "claim_contract": {
                    "confirmatory_or_exploratory": "confirmatory",
                    "claim_strength": "final",
                },
                "split_manifest_path": "artifacts/splits.json",
                "review_probes": {
                    "label_permutation_null": {
                        "pipeline_scope": "full_pipeline",
                        "generated_by": "br_full_pipeline_permutation_harness",
                        "input_scope": "workflow_invocation",
                        "pipeline_invocation_sha256": "workflow-digest",
                    }
                },
            }
        )

        finding = predictive_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert finding.reason_tags == ["predictive", "coverage", "data_contract"]
        assert any("fit_scope_by_step" in item for item in finding.kg_evidence)

    def test_warns_exploratory_predictive_claim_missing_diagnostics(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "confirmatory_or_exploratory": "exploratory",
            }
        )

        finding = predictive_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
        assert finding.severity == "warn"
        assert finding.action == "warn"

    def test_allows_predictive_claim_with_required_diagnostics(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "claim_contract": {
                    "confirmatory_or_exploratory": "confirmatory",
                    "claim_strength": "final",
                },
                "split": {"split_manifest_sha256": "abc123"},
                "preprocessing": {
                    "fit_scope_by_step": {
                        "standard_scaler": "train_fold_only",
                        "variance_mask": "train_fold_only",
                    }
                },
                "null_model": {
                    "permutation_null": {
                        "status": "ok",
                        "pipeline_scope": "full_pipeline",
                        "generated_by": "br_full_pipeline_permutation_harness",
                        "input_scope": "workflow_invocation",
                        "pipeline_invocation_sha256": "workflow-digest",
                        "n_permutations": 1000,
                    }
                },
            }
        )

        assert predictive_required_diagnostics_check(bundle) is None

    def test_exploratory_feature_matrix_probe_still_warns_missing_full_pipeline(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "confirmatory_or_exploratory": "exploratory",
                "split": {"split_manifest_sha256": "abc123"},
                "preprocessing": {
                    "fit_scope_by_step": {
                        "standard_scaler": "train_fold_only",
                    }
                },
                "review_probes": {
                    "label_permutation_null": {
                        "pipeline_scope": "feature_matrix_only",
                        "generated_by": "permutation_testing_tool",
                        "input_scope": "feature_matrix",
                        "n_permutations": 1000,
                    }
                },
            }
        )

        finding = predictive_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.severity == "warn"
        assert finding.action == "warn"
        assert any(
            "full_pipeline_permutation_null" in item for item in finding.kg_evidence
        )

    def test_confirmatory_requires_trusted_full_pipeline_probe_provenance(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "claim_contract": {
                    "confirmatory_or_exploratory": "confirmatory",
                    "claim_strength": "final",
                },
                "split": {"split_manifest_sha256": "abc123"},
                "preprocessing": {
                    "fit_scope_by_step": {
                        "standard_scaler": "train_fold_only",
                    }
                },
                "null_model": {
                    "permutation_null": {
                        "status": "ok",
                        "pipeline_scope": "full_pipeline",
                        "n_permutations": 1000,
                    }
                },
            }
        )

        finding = predictive_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
        assert finding.action == "block"
        assert any(
            "full_pipeline_permutation_null" in item for item in finding.kg_evidence
        )

    def test_baseline_spec_alone_does_not_satisfy_confirmatory_permutation_probe(self):
        bundle = _bundle(
            {
                "scientific_review_profile": "predictive_model_review",
                "claim_contract": {
                    "confirmatory_or_exploratory": "confirmatory",
                    "claim_strength": "final",
                },
                "split": {"fold_manifest_path": "artifacts/folds.json"},
                "cv_contract": {
                    "fit_scope_by_step": {
                        "standard_scaler": "train_fold_only",
                    }
                },
                "null_model": {"permutation_baseline_spec": "shuffle y within folds"},
            }
        )

        finding = predictive_required_diagnostics_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
        assert finding.action == "block"
        assert any(
            "full_pipeline_permutation_null" in item for item in finding.kg_evidence
        )

    def test_ignores_non_predictive_claims(self):
        bundle = _bundle(
            {
                "claim_contract": {
                    "confirmatory_or_exploratory": "confirmatory",
                    "claim_strength": "final",
                }
            }
        )

        assert predictive_required_diagnostics_check(bundle) is None
