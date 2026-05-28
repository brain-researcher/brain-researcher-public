"""Tests for claim/sensitivity/construct-validity review checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(
    *,
    review_context: dict | None = None,
    observed_artifacts: dict | None = None,
    plan_steps: list[dict] | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=plan_steps or [],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
        observed_artifacts=observed_artifacts or {},
        kg_context=kg_context or {},
    )


@pytest.mark.unit
class TestClaimInflationCheck:
    def test_flags_prediction_language_without_predictive_context(self):
        from brain_researcher.services.review.checks.claim_validity import (
            claim_inflation_check,
        )

        bundle = _bundle(
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Memory score can be predicted above chance from the map.",
                        }
                    ]
                }
            }
        )

        finding = claim_inflation_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CLAIM_INFLATION"
        assert finding.action == "warn"
        assert finding.reason_tags == ["claim_inflation"]
        assert "prediction language" in finding.message

    def test_flags_causal_language_without_causal_support(self):
        from brain_researcher.services.review.checks.claim_validity import (
            claim_inflation_check,
        )

        bundle = _bundle(
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "This network is the causal mechanism driving attention.",
                        }
                    ]
                }
            }
        )

        finding = claim_inflation_check(bundle)
        assert finding is not None
        assert "causal/mechanistic language" in finding.message

    def test_allows_prediction_language_with_predictive_context(self):
        from brain_researcher.services.review.checks.claim_validity import (
            claim_inflation_check,
        )

        bundle = _bundle(
            review_context={
                "scientific_review_profile": "predictive_model_review",
                "split": {
                    "split_unit": "subject",
                    "split_strategy_detail": "nested_cv",
                },
                "null_model": {
                    "permutation_baseline_spec": "label_shuffle",
                },
            },
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Memory score can be predicted above chance from the map.",
                        }
                    ]
                }
            },
        )

        assert claim_inflation_check(bundle) is None


@pytest.mark.unit
class TestReverseInferenceRiskCheck:
    def test_flags_region_to_process_inference_without_decoder_support(self):
        from brain_researcher.services.review.checks.claim_validity import (
            reverse_inference_risk_check,
        )

        bundle = _bundle(
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "TPJ activation indicates mentalizing during the task.",
                        }
                    ]
                }
            }
        )

        finding = reverse_inference_risk_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_REVERSE_INFERENCE_RISK"
        assert finding.action == "warn"
        assert finding.reason_tags == ["claim_inflation", "construct_validity"]

    def test_allows_reverse_inference_when_decoder_support_is_recorded(self):
        from brain_researcher.services.review.checks.claim_validity import (
            reverse_inference_risk_check,
        )

        bundle = _bundle(
            review_context={
                "construct_validity": {
                    "alternative_explanations": [],
                }
            },
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "TPJ activation indicates mentalizing during the task.",
                        }
                    ]
                },
                "source_summary": {
                    "decoder_support": "neurosynth decoder with forward inference",
                },
            },
        )

        assert reverse_inference_risk_check(bundle) is None


@pytest.mark.unit
class TestModelFitMechanismOverreachCheck:
    def test_flags_fit_language_presented_as_same_mechanism(self):
        from brain_researcher.services.review.checks.claim_validity import (
            model_fit_mechanism_overreach_check,
        )

        bundle = _bundle(
            kg_context={"analysis_family": "neural_encoding_prediction"},
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Because the LLM layer gives the best encoding score, the brain uses the same algorithm.",
                        }
                    ]
                }
            },
        )

        finding = model_fit_mechanism_overreach_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_MODEL_FIT_MECHANISM_OVERREACH"
        assert finding.action == "warn"
        assert finding.reason_tags == ["claim_inflation"]

    def test_allows_plain_encoding_fit_claim_without_equivalence_language(self):
        from brain_researcher.services.review.checks.claim_validity import (
            model_fit_mechanism_overreach_check,
        )

        bundle = _bundle(
            kg_context={"analysis_family": "neural_encoding_prediction"},
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "The LLM layer achieved the best encoding score on this dataset.",
                        }
                    ]
                }
            },
        )

        assert model_fit_mechanism_overreach_check(bundle) is None


@pytest.mark.unit
class TestControversialChoiceSensitivityCheck:
    def test_flags_gsr_without_sensitivity_record(self):
        from brain_researcher.services.review.checks.claim_validity import (
            controversial_choice_sensitivity_check,
        )

        bundle = _bundle(
            review_context={
                "preprocessing": {
                    "confounds": ["motion", "wm_csf", "gsr"],
                }
            }
        )

        finding = controversial_choice_sensitivity_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONTROVERSIAL_CHOICE_SENSITIVITY"
        assert finding.reason_tags == ["controversial_choice"]
        assert "gsr" in finding.message

    def test_allows_controversial_choice_with_robustness_checks(self):
        from brain_researcher.services.review.checks.claim_validity import (
            controversial_choice_sensitivity_check,
        )

        bundle = _bundle(
            review_context={
                "preprocessing": {
                    "confounds": ["gsr"],
                },
                "sensitivity": {
                    "robustness_checks": ["gsr_on_off"],
                },
            }
        )

        assert controversial_choice_sensitivity_check(bundle) is None


@pytest.mark.unit
class TestConstructValidityConfoundCheck:
    def test_flags_explicit_behavioral_imbalance_without_control(self):
        from brain_researcher.services.review.checks.claim_validity import (
            construct_validity_confound_check,
        )

        bundle = _bundle(
            review_context={
                "construct_validity": {
                    "behavioral_imbalance": {
                        "reaction_time": "large_group_difference",
                        "difficulty": True,
                    }
                }
            }
        )

        finding = construct_validity_confound_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONSTRUCT_VALIDITY_CONFOUND"
        assert finding.reason_tags == ["construct_validity", "confound"]
        assert "reaction_time" in finding.kg_evidence[0]

    def test_allows_explicit_behavioral_imbalance_with_covariate_control(self):
        from brain_researcher.services.review.checks.claim_validity import (
            construct_validity_confound_check,
        )

        bundle = _bundle(
            review_context={
                "construct_validity": {
                    "behavioral_imbalance": {
                        "accuracy": "condition_difference",
                    },
                    "controlled_covariates": ["accuracy"],
                }
            }
        )

        assert construct_validity_confound_check(bundle) is None
