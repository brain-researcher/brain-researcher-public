from brain_researcher.core.contracts import (
    ClaimScopeV1,
    ClaimV1,
    ClaimVerdictV1,
    EpistemicConfidenceTierV1,
    EvidenceItemV1,
    EvidenceProvenanceV1,
    EvidenceType,
)
from brain_researcher.core.epistemic_policy import (
    allowed_claim_verdicts,
    assess_claim_epistemics,
    calibrate_claim_epistemics,
    validate_claim_epistemics,
)


def test_cross_study_inference_cannot_use_supported_verdict() -> None:
    evidence = EvidenceItemV1(
        evidence_id="ev-1",
        type=EvidenceType.file,
        ref="paper-1",
        evidence_provenance=EvidenceProvenanceV1.cross_study_inference,
        raw_data_available=False,
        direct_statistical_test=False,
    )
    claim = ClaimV1(
        claim_id="claim-1",
        claim_text="Right TPJ is stronger than left TPJ.",
        verdict=ClaimVerdictV1.supported,
        epistemic_confidence_tier=EpistemicConfidenceTierV1.high,
        evidence_provenance=EvidenceProvenanceV1.cross_study_inference,
        claim_scope=ClaimScopeV1.cross_study,
        raw_data_available=False,
        direct_statistical_test=False,
        evidence_ids=["ev-1"],
    )

    issues = validate_claim_epistemics(claim, [evidence])

    assert any("uses verdict 'supported'" in issue for issue in issues)
    assert any("declares confidence tier 'high'" in issue for issue in issues)


def test_single_study_direct_with_direct_test_allows_supported() -> None:
    evidence = EvidenceItemV1(
        evidence_id="ev-1",
        type=EvidenceType.artifact,
        ref="analysis.json#/claims/0",
        evidence_provenance=EvidenceProvenanceV1.single_study_direct,
        raw_data_available=True,
        direct_statistical_test=True,
    )
    claim = ClaimV1(
        claim_id="claim-1",
        claim_text="Condition A exceeds condition B in TPJ.",
        verdict=ClaimVerdictV1.supported,
        epistemic_confidence_tier=EpistemicConfidenceTierV1.high,
        evidence_ids=["ev-1"],
    )

    assessment = assess_claim_epistemics(claim, [evidence])

    assert assessment.allowed_verdicts == (
        ClaimVerdictV1.supported,
        ClaimVerdictV1.refuted,
        ClaimVerdictV1.mixed,
        ClaimVerdictV1.inconclusive,
    )
    assert assessment.recommended_confidence_tier == EpistemicConfidenceTierV1.high
    assert validate_claim_epistemics(claim, [evidence]) == []


def test_theoretical_prediction_allows_predicted_only() -> None:
    allowed = allowed_claim_verdicts(
        evidence_provenance=EvidenceProvenanceV1.theoretical_prediction,
        direct_statistical_test=False,
    )
    assert allowed == (
        ClaimVerdictV1.predicted,
        ClaimVerdictV1.suggestive,
        ClaimVerdictV1.inconclusive,
    )


def test_calibrate_claim_epistemics_downgrades_cross_study_support() -> None:
    evidence = EvidenceItemV1(
        evidence_id="ev-1",
        type=EvidenceType.file,
        ref="paper-1",
        evidence_provenance=EvidenceProvenanceV1.cross_study_inference,
        raw_data_available=False,
        direct_statistical_test=False,
    )
    claim = ClaimV1(
        claim_id="claim-1",
        claim_text="EA > EuA in TPJ for stranger trust.",
        verdict=ClaimVerdictV1.supported,
        epistemic_confidence_tier=EpistemicConfidenceTierV1.high,
        evidence_ids=["ev-1"],
    )

    calibrated = calibrate_claim_epistemics(claim, [evidence])

    assert calibrated.verdict == ClaimVerdictV1.indirectly_supported
    assert calibrated.epistemic_confidence_tier == EpistemicConfidenceTierV1.low
    assert calibrated.evidence_provenance == EvidenceProvenanceV1.cross_study_inference
    assert calibrated.claim_scope == ClaimScopeV1.cross_study
    calibration = calibrated.extra["epistemic_calibration"]
    assert calibration["display_verdict"] == "consistent_with"
    assert calibration["original_verdict"] == "supported"
    assert calibration["original_confidence_tier"] == "high"
