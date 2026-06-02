"""Cross-profile reuse of predictive/connectivity checks inside autoresearch."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchReviewBundle,
)
from brain_researcher.services.review.autoresearch_scientific_review import (
    _correctness_verdict,
    _shared_correctness_findings,
)


def _bundle(review_context: dict | None = None) -> AutoresearchReviewBundle:
    return AutoresearchReviewBundle(
        task_id="liu_component_v1",
        autoresearch_dir="/tmp/x",
        fingerprint="abc",
        ledger_row_count=1,
        review_context=review_context or {},
    )


@pytest.mark.unit
def test_shared_findings_block_confirmatory_predictive_missing_diagnostics():
    bundle = _bundle(
        {
            "scientific_review_profile": "predictive_model_review",
            "claim_contract": {
                "confirmatory_or_exploratory": "confirmatory",
                "claim_strength": "final",
            },
        }
    )

    findings = _shared_correctness_findings(bundle)

    rule_ids = {f.rule_id for f in findings}
    assert "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC" in rule_ids
    blocking = [f for f in findings if f.action == "block"]
    assert blocking, "confirmatory predictive run must produce a block finding"


@pytest.mark.unit
def test_shared_findings_warn_for_exploratory_predictive_missing_diagnostics():
    bundle = _bundle(
        {
            "scientific_review_profile": "predictive_model_review",
            "confirmatory_or_exploratory": "exploratory",
        }
    )

    findings = _shared_correctness_findings(bundle)

    governance = [
        f for f in findings if f.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
    ]
    assert governance
    assert governance[0].action == "warn"


@pytest.mark.unit
def test_shared_findings_flag_partial_corr_p_ge_n_under_empirical_estimator():
    bundle = _bundle(
        {
            "feature_contract": {
                "matrix_kind": "partial_correlation",
                "precision_estimator": "EmpiricalCovariance",
                "n_rois": 100,
                "n_timepoints": 50,
            }
        }
    )

    findings = _shared_correctness_findings(bundle)

    rule_ids = {f.rule_id for f in findings}
    assert "REVIEW_MATRIX_PARTIAL_SINGULAR" in rule_ids


@pytest.mark.unit
def test_shared_findings_silent_on_regularized_partial_corr_with_p_ge_n():
    bundle = _bundle(
        {
            "feature_contract": {
                "matrix_kind": "partial_correlation",
                "precision_estimator": "GraphicalLassoCV",
                "n_rois": 100,
                "n_timepoints": 50,
                "precision_rank": 100,
                "precision_condition_number": 1e4,
            }
        }
    )

    findings = _shared_correctness_findings(bundle)

    rule_ids = {f.rule_id for f in findings}
    assert "REVIEW_MATRIX_PARTIAL_SINGULAR" not in rule_ids


@pytest.mark.unit
def test_shared_findings_no_op_for_empty_review_context():
    bundle = _bundle({})

    assert _shared_correctness_findings(bundle) == []


@pytest.mark.unit
def test_correctness_verdict_promotes_block_when_shared_check_fires():
    bundle = _bundle(
        {
            "scientific_review_profile": "predictive_model_review",
            "claim_contract": {
                "confirmatory_or_exploratory": "confirmatory",
                "claim_strength": "final",
            },
        }
    )

    verdict = _correctness_verdict(bundle)

    assert verdict.decision == "block"
    assert any(
        f.rule_id == "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC" for f in verdict.findings
    )
