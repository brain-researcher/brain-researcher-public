from __future__ import annotations

import pytest

from brain_researcher.services.neurokg.etl.evaluation.claim_first_vs_mention_bootstrap import (
    build_recommendation,
    compute_condition_metrics,
    validate_claim_first_counts,
    validate_control_cleanup,
)


def _evidence_item(*, with_claim_spine: bool) -> dict[str, object]:
    return {
        "publication": {"kg_id": "pmid:40000001"},
        "claim": {"kg_id": "claim:1"} if with_claim_spine else None,
        "evidence_span": {"kg_id": "evidence:1"} if with_claim_spine else None,
    }


def _result_row(
    *,
    expected_verdict: str,
    verdict: str,
    evidence_mode: str,
    evidence_source_scope: str,
    query_time_s: float,
    with_evidence: bool,
    with_claim_spine: bool,
    with_top_paths: bool = True,
) -> dict[str, object]:
    evidence = [_evidence_item(with_claim_spine=with_claim_spine)] if with_evidence else []
    return {
        "expected_verdict": expected_verdict,
        "result": {
            "verdict": verdict,
            "evidence_mode": evidence_mode,
            "evidence_source_scope": evidence_source_scope,
            "supporting_evidence": evidence if verdict == "supported" else [],
            "conflicting_evidence": evidence if verdict == "conflicting" else [],
            "uncertain_evidence": [],
            "neutral_evidence": [],
            "top_paths": [{"preview": "a -> b"}] if with_top_paths else [],
            "summary": {"query_time_s": query_time_s},
        },
    }


def test_validate_control_cleanup_accepts_claim_spine_removal_and_mention_preservation() -> None:
    before = {
        "Claim": 2,
        "EvidenceSpan": 2,
        "MeasurementRun": 2,
        "REPORTS_CLAIM": 2,
        "SUPPORTS": 2,
        "GENERATED": 4,
        "MENTIONS": 1,
        "MENTIONS_REGION": 1,
    }
    after = {
        "Claim": 0,
        "EvidenceSpan": 0,
        "MeasurementRun": 0,
        "REPORTS_CLAIM": 0,
        "SUPPORTS": 0,
        "GENERATED": 0,
        "MENTIONS": 1,
        "MENTIONS_REGION": 1,
    }

    validate_control_cleanup(before=before, after=after)


def test_validate_control_cleanup_rejects_mention_drift() -> None:
    before = {
        "Claim": 2,
        "EvidenceSpan": 2,
        "MeasurementRun": 2,
        "REPORTS_CLAIM": 2,
        "SUPPORTS": 2,
        "GENERATED": 4,
        "MENTIONS": 1,
        "MENTIONS_REGION": 1,
    }
    after = {
        "Claim": 0,
        "EvidenceSpan": 0,
        "MeasurementRun": 0,
        "REPORTS_CLAIM": 0,
        "SUPPORTS": 0,
        "GENERATED": 0,
        "MENTIONS": 0,
        "MENTIONS_REGION": 1,
    }

    with pytest.raises(RuntimeError, match="MENTIONS"):
        validate_control_cleanup(before=before, after=after)


def test_validate_claim_first_counts_can_skip_fixed_footprint() -> None:
    validate_claim_first_counts({"Claim": 99}, expected_footprint=None)


def test_compute_condition_metrics_uses_all_hypotheses_for_auditability_rate() -> None:
    rows = [
        _result_row(
            expected_verdict="supported",
            verdict="supported",
            evidence_mode="shared",
            evidence_source_scope="direct",
            query_time_s=1.2,
            with_evidence=True,
            with_claim_spine=True,
        ),
        _result_row(
            expected_verdict="insufficient_evidence",
            verdict="insufficient_evidence",
            evidence_mode="none",
            evidence_source_scope="none",
            query_time_s=0.8,
            with_evidence=False,
            with_claim_spine=False,
            with_top_paths=False,
        ),
    ]

    metrics = compute_condition_metrics(rows)

    assert metrics["n_hypotheses"] == 2
    assert metrics["accuracy"] == 1.0
    assert metrics["macro_f1"] == 1.0
    assert metrics["supporting_nonempty_rate"] == 0.5
    assert metrics["top_paths_nonempty_rate"] == 0.5
    assert metrics["auditability_pass_rate"] == 0.5
    assert metrics["mean_query_time_s"] == 1.0
    assert metrics["evidence_mode_counts"] == {"shared": 1, "none": 1}
    assert metrics["evidence_source_scope_counts"] == {"direct": 1, "none": 1}


def test_build_recommendation_prefers_claim_first_when_auditability_improves() -> None:
    recommendation = build_recommendation(
        {"auditability_pass_rate": 1.0, "accuracy": 1.0},
        {"auditability_pass_rate": 0.0, "accuracy": 1.0},
    )

    assert recommendation == {
        "recommendation": "continue_p1",
        "auditability_delta": 1.0,
        "accuracy_delta": 0.0,
    }


def test_build_recommendation_deprioritizes_on_accuracy_regression() -> None:
    recommendation = build_recommendation(
        {"auditability_pass_rate": 1.0, "accuracy": 0.5},
        {"auditability_pass_rate": 0.0, "accuracy": 1.0},
    )

    assert recommendation["recommendation"] == "deprioritize_p1"
    assert recommendation["accuracy_delta"] == -0.5
