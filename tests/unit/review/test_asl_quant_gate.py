"""Tests for wiring the retired ASL critic into the review gate (P1.4d)."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.asl_quant_gate import (
    asl_quantification_findings,
)


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


@pytest.mark.unit
def test_no_asl_contract_yields_no_findings():
    assert asl_quantification_findings(_bundle({})) == []
    assert asl_quantification_findings(_bundle({"asl_quant": {}})) == []


@pytest.mark.unit
def test_ill_formed_contract_skips_silently():
    # method_contract present but subject_summaries missing/empty -> skip
    assert (
        asl_quantification_findings(
            _bundle({"asl_quant": {"method_contract": {}, "subject_summaries": []}})
        )
        == []
    )


@pytest.mark.unit
def test_mixed_regime_without_separate_branches_blocks():
    findings = asl_quantification_findings(
        _bundle(
            {
                "asl_quant": {
                    "task_profile": "asl_cbf_quantification",
                    "method_contract": {"separate_single_and_multi_pld": False},
                    "subject_summaries": [
                        {"subject": "sub-01", "n_unique_plds": 1},
                        {"subject": "sub-02", "n_unique_plds": 5},
                    ],
                }
            }
        )
    )
    assert findings  # critic fired
    assert any(f.action == "block" for f in findings)


@pytest.mark.unit
def test_adapter_reads_nested_analysis_bundle_review_context():
    # contract reachable via artifacts.analysis_bundle.review_context as well
    bundle = CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        observed_artifacts={
            "analysis_bundle": {
                "review_context": {
                    "asl_quantification": {
                        "task_profile": "asl_cbf_quantification",
                        "method_contract": {"separate_single_and_multi_pld": False},
                        "subject_summaries": [
                            {"subject": "sub-01", "n_unique_plds": 1},
                            {"subject": "sub-02", "n_unique_plds": 5},
                        ],
                    }
                }
            }
        },
    )
    findings = asl_quantification_findings(bundle)
    assert any(f.action == "block" for f in findings)
