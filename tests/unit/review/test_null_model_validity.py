"""Tests for explicit null-model validity checks."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.null_model_validity import (
    permutation_exchangeability_check,
    spatial_null_validity_check,
    surface_volume_correction_domain_mismatch_check,
)


def _bundle(
    review_context: dict | None = None,
    observed_artifacts: dict | None = None,
    stats_metrics: dict | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
        observed_artifacts=observed_artifacts or {},
        stats_metrics=stats_metrics or {},
        kg_context=kg_context or {},
    )


@pytest.mark.unit
class TestPermutationExchangeabilityCheck:
    def test_no_metadata_returns_none(self):
        bundle = _bundle()
        assert permutation_exchangeability_check(bundle) is None

    def test_explicit_invalid_exchangeability_blocks(self):
        bundle = _bundle(
            review_context={
                "null_model": {
                    "permutation_manifest": {
                        "scheme": "restricted",
                        "exchangeability_status": "violated",
                        "blocks": ["subject"],
                    }
                }
            }
        )

        finding = permutation_exchangeability_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_PERMUTATION_EXCHANGEABILITY_INVALID"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["null_mismatch"]

    def test_explicit_valid_exchangeability_does_not_block(self):
        bundle = _bundle(
            review_context={
                "null_model": {
                    "permutation_manifest": {
                        "scheme": "restricted",
                        "exchangeability_status": "valid",
                        "blocks": ["subject"],
                    }
                }
            }
        )

        assert permutation_exchangeability_check(bundle) is None


@pytest.mark.unit
class TestSpatialNullValidityCheck:
    def test_no_metadata_returns_none(self):
        bundle = _bundle()
        assert spatial_null_validity_check(bundle) is None

    def test_explicit_invalid_spatial_null_blocks(self):
        bundle = _bundle(
            review_context={
                "null_model": {
                    "spatial_null": {
                        "method": "spin_test",
                        "valid": False,
                        "domain": "surface",
                    }
                }
            }
        )

        finding = spatial_null_validity_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_SPATIAL_NULL_INVALID"
        assert finding.action == "block"
        assert finding.severity == "error"

    def test_explicit_valid_spatial_null_does_not_block(self):
        bundle = _bundle(
            review_context={
                "spatial_null": {
                    "method": "brain_smash",
                    "status": "valid",
                    "domain": "volume",
                }
            }
        )

        assert spatial_null_validity_check(bundle) is None


@pytest.mark.unit
class TestSurfaceVolumeMismatchCheck:
    def test_no_metadata_returns_none(self):
        bundle = _bundle()
        assert surface_volume_correction_domain_mismatch_check(bundle) is None

    def test_explicit_surface_volume_mismatch_blocks(self):
        bundle = _bundle(
            review_context={
                "data_domain": "surface",
                "cluster_correction_domain": "volume",
            }
        )

        finding = surface_volume_correction_domain_mismatch_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_SURFACE_VOLUME_CORRECTION_DOMAIN_MISMATCH"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["null_mismatch"]

    def test_matching_surface_domains_do_not_block(self):
        bundle = _bundle(
            review_context={
                "analysis_domain": "surface",
                "multiple_comparison_domain": "surface",
            }
        )

        assert surface_volume_correction_domain_mismatch_check(bundle) is None
