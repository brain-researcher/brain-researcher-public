"""Tests for controversial-choice sensitivity-package review checks."""

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
class TestGsrSensitivityPackageCheck:
    def test_flags_gsr_without_on_off_sensitivity(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            gsr_sensitivity_package_check,
        )

        bundle = _bundle(
            review_context={
                "preprocessing": {
                    "confounds": ["motion", "wm_csf", "gsr"],
                }
            }
        )

        finding = gsr_sensitivity_package_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_GSR_SENSITIVITY_PACKAGE"
        assert finding.action == "warn"
        assert finding.reason_tags == ["controversial_choice", "gsr"]
        assert "GSR on/off sensitivity package" in finding.message

    def test_allows_gsr_with_on_off_sensitivity(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            gsr_sensitivity_package_check,
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

        assert gsr_sensitivity_package_check(bundle) is None


@pytest.mark.unit
class TestDynamicFcSensitivityPackageCheck:
    def test_flags_dynamic_fc_without_null_model(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            dynamic_fc_sensitivity_package_check,
        )

        bundle = _bundle(
            review_context={
                "sensitivity": {
                    "controversial_choices": ["dynamic_fc"],
                    "robustness_checks": ["window_length_sensitivity"],
                }
            },
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Dynamic connectivity varied across the task.",
                        }
                    ]
                }
            },
        )

        finding = dynamic_fc_sensitivity_package_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_DYNAMIC_FC_SENSITIVITY_PACKAGE"
        assert finding.reason_tags == [
            "controversial_choice",
            "dynamic_fc",
            "null_mismatch",
        ]
        assert "null model" in finding.message

    def test_allows_dynamic_fc_with_null_model_and_window_sensitivity(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            dynamic_fc_sensitivity_package_check,
        )

        bundle = _bundle(
            review_context={
                "sensitivity": {
                    "controversial_choices": ["dynamic_fc"],
                    "robustness_checks": ["window_length_sensitivity"],
                },
                "null_model": {
                    "null_model_spec": {
                        "resampling_method": "phase_randomization",
                    }
                },
            },
            observed_artifacts={
                "claim_report": {
                    "claims": [
                        {
                            "claim_text": "Dynamic connectivity varied across the task.",
                        }
                    ]
                }
            },
        )

        assert dynamic_fc_sensitivity_package_check(bundle) is None


@pytest.mark.unit
class TestGraphAtlasHrfSensitivityPackageCheck:
    def test_flags_graph_atlas_hrf_without_choice_specific_sensitivity(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            graph_atlas_hrf_sensitivity_package_check,
        )

        bundle = _bundle(
            review_context={
                "preprocessing": {
                    "graph_threshold": "proportional_threshold",
                    "atlas_name": "destrieux_surface_fsaverage5",
                    "hrf_model": "canonical",
                },
                "sensitivity": {
                    "controversial_choices": [
                        "graph_thresholding",
                        "atlas",
                        "hrf",
                    ],
                    "robustness_checks": ["threshold_sweep"],
                },
            }
        )

        finding = graph_atlas_hrf_sensitivity_package_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_GRAPH_ATLAS_HRF_SENSITIVITY_PACKAGE"
        assert finding.reason_tags == ["controversial_choice", "atlas", "hrf"]
        assert "atlas" in finding.message
        assert "hrf" in finding.message

    def test_allows_graph_atlas_hrf_with_choice_specific_sensitivity(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            graph_atlas_hrf_sensitivity_package_check,
        )

        bundle = _bundle(
            review_context={
                "preprocessing": {
                    "graph_threshold": "proportional_threshold",
                    "atlas_name": "destrieux_surface_fsaverage5",
                    "hrf_model": "canonical",
                },
                "sensitivity": {
                    "robustness_checks": [
                        "threshold_sweep",
                        "atlas_sensitivity",
                        "hrf_sensitivity",
                    ]
                },
            }
        )

        assert graph_atlas_hrf_sensitivity_package_check(bundle) is None


@pytest.mark.unit
class TestSensitivityPackagesConservativeDefaults:
    def test_ignores_bundle_without_relevant_choice(self):
        from brain_researcher.services.review.checks.sensitivity_packages import (
            dynamic_fc_sensitivity_package_check,
            graph_atlas_hrf_sensitivity_package_check,
            gsr_sensitivity_package_check,
        )

        bundle = _bundle()

        assert gsr_sensitivity_package_check(bundle) is None
        assert dynamic_fc_sensitivity_package_check(bundle) is None
        assert graph_atlas_hrf_sensitivity_package_check(bundle) is None
