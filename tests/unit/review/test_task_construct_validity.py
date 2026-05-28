"""Tests for task/construct-validity review checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(
    *,
    review_context: dict | None = None,
    observed_artifacts: dict | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
        observed_artifacts=observed_artifacts or {},
        kg_context=kg_context or {},
    )


@pytest.mark.unit
class TestStimulusFixedEffectRiskCheck:
    def test_flags_broad_stimulus_generalization_without_randomization_support(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            stimulus_fixed_effect_risk_check,
        )

        bundle = _bundle(
            review_context={
                "task_validity": {
                    "stimulus_generalization": {
                        "scope": "broad stimulus-class generalization",
                        "claim": "generalize across stimuli",
                    }
                }
            }
        )

        finding = stimulus_fixed_effect_risk_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_STIMULUS_FIXED_EFFECT_RISK"
        assert finding.action == "warn"
        assert finding.reason_tags == ["construct_validity", "stimulus_fixed_effect"]
        assert "stimulus-randomization" in finding.message

    def test_allows_broad_generalization_with_explicit_randomization_support(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            stimulus_fixed_effect_risk_check,
        )

        bundle = _bundle(
            review_context={
                "task_validity": {
                    "stimulus_generalization": {
                        "scope": "broad stimulus-class generalization",
                    },
                    "stimulus_randomization": {
                        "randomized": True,
                        "independent_stimulus_set": True,
                    },
                }
            }
        )

        assert stimulus_fixed_effect_risk_check(bundle) is None


@pytest.mark.unit
class TestBehavioralImbalanceNotModeledCheck:
    def test_flags_explicit_rt_accuracy_difficulty_eye_movement_imbalance(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            behavioral_imbalance_not_modeled_check,
        )

        bundle = _bundle(
            review_context={
                "construct_validity": {
                    "behavioral_imbalance": {
                        "reaction_time": "large_group_difference",
                        "accuracy": "condition_difference",
                        "difficulty": True,
                        "eye_movement": "large_group_difference",
                    }
                }
            }
        )

        finding = behavioral_imbalance_not_modeled_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_BEHAVIORAL_IMBALANCE_NOT_MODELED"
        assert finding.action == "warn"
        assert finding.reason_tags == ["construct_validity", "confound"]
        assert "reaction_time" in finding.kg_evidence[0]

    def test_allows_when_controls_cover_the_explicit_imbalances(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            behavioral_imbalance_not_modeled_check,
        )

        bundle = _bundle(
            review_context={
                "construct_validity": {
                    "behavioral_imbalance": {
                        "reaction_time": "large_group_difference",
                        "accuracy": "condition_difference",
                    },
                    "controlled_covariates": [
                        "reaction_time",
                        "accuracy",
                    ],
                },
                "preprocessing": {
                    "confounds": ["reaction_time", "accuracy"],
                },
            }
        )

        assert behavioral_imbalance_not_modeled_check(bundle) is None


@pytest.mark.unit
class TestTaskFcPpiEvokedResponseControlCheck:
    def test_flags_ppi_with_explicit_insufficient_evoked_response_removal(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            task_fc_ppi_evoked_response_control_check,
        )

        bundle = _bundle(
            review_context={
                "task_connectivity": {
                    "analysis_type": "PPI",
                    "evoked_response_removal_status": "insufficient",
                    "mean_evoked_response_control": False,
                }
            },
            kg_context={"analysis_family": "ppi"},
        )

        finding = task_fc_ppi_evoked_response_control_check(bundle)
        assert finding is not None
        assert (
            finding.rule_id == "REVIEW_TASK_FC_PPI_EVOKED_RESPONSE_CONTROL_MISSING"
        )
        assert finding.action == "warn"
        assert finding.reason_tags == ["construct_validity", "connectivity"]
        assert "analysis_family=ppi" in finding.kg_evidence[0]

    def test_allows_when_mean_evoked_response_control_is_recorded(self):
        from brain_researcher.services.review.checks.task_construct_validity import (
            task_fc_ppi_evoked_response_control_check,
        )

        bundle = _bundle(
            review_context={
                "task_connectivity": {
                    "analysis_type": "task_fc",
                    "mean_evoked_response_control": True,
                    "evoked_response_removal_status": "complete",
                }
            },
            kg_context={"analysis_family": "task_fc"},
        )

        assert task_fc_ppi_evoked_response_control_check(bundle) is None
