"""Unit tests for the circularity / confound review checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.circularity_confound import (
    demographic_confound_uncontrolled_check,
    double_dipping_check,
)


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


@pytest.mark.unit
class TestDoubleDippingCheck:
    def test_fires_on_same_contrast_source(self):
        bundle = _bundle({"roi_provenance": {"source": "same_contrast"}})
        finding = double_dipping_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CIRCULARITY_DOUBLE_DIPPING"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert "circularity" in finding.reason_tags
        assert any("same_contrast" in e for e in finding.kg_evidence)

    def test_fires_when_selection_equals_test_source(self):
        bundle = _bundle(
            {
                "roi_provenance": {
                    "source": "group_activation_map",
                    "test_source": "group_activation_map",
                }
            }
        )
        finding = double_dipping_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CIRCULARITY_DOUBLE_DIPPING"

    def test_fires_on_explicit_independence_false(self):
        bundle = _bundle({"roi_provenance": {"selection_test_independence": False}})
        finding = double_dipping_check(bundle)
        assert finding is not None
        assert any(
            "selection_test_independence=False" in e for e in finding.kg_evidence
        )

    def test_fires_on_explicit_circular_flag(self):
        bundle = _bundle({"selection": {"roi_provenance": {"circular": True}}})
        finding = double_dipping_check(bundle)
        assert finding is not None

    def test_allows_independent_localizer(self):
        # C17 analogue: independent localizer -> ROI -> test => allow.
        bundle = _bundle(
            {
                "roi_provenance": {
                    "source": "localizer_contrast",
                    "test_source": "main_effect_contrast",
                    "independent_localizer": True,
                }
            }
        )
        assert double_dipping_check(bundle) is None

    def test_independence_true_suppresses_same_source(self):
        bundle = _bundle(
            {
                "roi_provenance": {
                    "source": "same_contrast",
                    "selection_test_independence": True,
                }
            }
        )
        assert double_dipping_check(bundle) is None

    def test_no_provenance_no_finding(self):
        assert double_dipping_check(_bundle({})) is None

    def test_distinct_independent_sources_no_finding(self):
        bundle = _bundle(
            {
                "roi_provenance": {
                    "source": "independent_localizer_run",
                    "test_source": "main_task_run",
                }
            }
        )
        assert double_dipping_check(bundle) is None

    def test_does_not_fire_on_prose(self):
        # Prose mentioning double dipping must NOT trigger the check.
        bundle = _bundle(
            {"notes": "we worried about double dipping and circular ROI selection"}
        )
        assert double_dipping_check(bundle) is None


@pytest.mark.unit
class TestDemographicConfoundCheck:
    def test_fires_on_significant_age_not_covaried(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"significant": True}},
                "model_covariates": ["sex", "motion"],
            }
        )
        finding = demographic_confound_uncontrolled_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_CONFOUND_DEMOGRAPHIC_UNCONTROLLED"
        assert finding.severity == "error"
        assert finding.action == "block"
        assert "confound" in finding.reason_tags
        assert any("age" in e for e in finding.kg_evidence)

    def test_fires_on_significant_p_value(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"p": 0.001}},
                "model_covariates": ["motion"],
            }
        )
        finding = demographic_confound_uncontrolled_check(bundle)
        assert finding is not None

    def test_list_form(self):
        bundle = _bundle(
            {
                "confounds": {
                    "demographic_deltas": [
                        {"variable": "sex", "significant": True},
                        {"variable": "age", "significant": False},
                    ]
                },
                "model_covariates": ["age"],
            }
        )
        finding = demographic_confound_uncontrolled_check(bundle)
        assert finding is not None
        assert any("sex" in e for e in finding.kg_evidence)

    def test_allows_when_covaried(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"significant": True}},
                "model_covariates": ["age", "sex"],
            }
        )
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_alias_match_gender_covaries_sex(self):
        bundle = _bundle(
            {
                "demographic_balance": {"sex": {"significant": True}},
                "model_covariates": ["gender"],
            }
        )
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_no_fire_when_not_significant(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"significant": False, "p": 0.42}},
                "model_covariates": ["motion"],
            }
        )
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_no_fire_when_covariates_absent(self):
        # Insufficient provenance: no declared covariates => do not fire.
        bundle = _bundle({"demographic_balance": {"age": {"significant": True}}})
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_custom_alpha(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"p": 0.03}, "alpha": 0.01},
                "model_covariates": ["motion"],
            }
        )
        # p=0.03 not < alpha=0.01 => no finding.
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_does_not_fire_on_prose(self):
        bundle = _bundle(
            {"notes": "groups differed in age but we did not adjust for it"}
        )
        assert demographic_confound_uncontrolled_check(bundle) is None

    def test_stat_model_nested_covariates(self):
        bundle = _bundle(
            {
                "demographic_balance": {"age": {"significant": True}},
                "statistics": {"stat_model": {"covariates": ["age"]}},
            }
        )
        assert demographic_confound_uncontrolled_check(bundle) is None
