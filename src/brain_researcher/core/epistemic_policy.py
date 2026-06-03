"""Deterministic epistemic policy helpers for claims and evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from brain_researcher.core.contracts import (
    ClaimScopeV1,
    ClaimV1,
    ClaimVerdictV1,
    EpistemicConfidenceTierV1,
    EvidenceItemV1,
    EvidenceProvenanceV1,
)

_TIER_RANK = {
    EpistemicConfidenceTierV1.low: 0,
    EpistemicConfidenceTierV1.medium: 1,
    EpistemicConfidenceTierV1.high: 2,
}

_EVIDENCE_TIER_LABELS = {
    EvidenceProvenanceV1.single_study_direct: "Level A: single-study direct evidence",
    EvidenceProvenanceV1.cross_study_inference: "Level B: cross-study inference",
    EvidenceProvenanceV1.theoretical_prediction: "Level C: theoretical prediction",
    EvidenceProvenanceV1.unknown: "Level ?: unknown provenance",
}


@dataclass(frozen=True)
class EpistemicAssessment:
    evidence_provenance: EvidenceProvenanceV1
    claim_scope: ClaimScopeV1
    raw_data_available: bool | None
    direct_statistical_test: bool | None
    allowed_verdicts: tuple[ClaimVerdictV1, ...]
    recommended_confidence_tier: EpistemicConfidenceTierV1


def _evidence_by_id(
    evidence_items: Iterable[EvidenceItemV1],
) -> dict[str, EvidenceItemV1]:
    return {item.evidence_id: item for item in evidence_items if item.evidence_id}


def _first_non_null_bool(values: Iterable[bool | None]) -> bool | None:
    for value in values:
        if value is not None:
            return bool(value)
    return None


def _resolve_evidence_provenance(
    claim: ClaimV1,
    linked_evidence: list[EvidenceItemV1],
) -> EvidenceProvenanceV1:
    if claim.evidence_provenance is not None:
        return claim.evidence_provenance

    provenances = {
        item.evidence_provenance
        for item in linked_evidence
        if item.evidence_provenance is not None
    }
    if not provenances:
        return EvidenceProvenanceV1.unknown
    if EvidenceProvenanceV1.cross_study_inference in provenances:
        return EvidenceProvenanceV1.cross_study_inference
    if EvidenceProvenanceV1.theoretical_prediction in provenances:
        return EvidenceProvenanceV1.theoretical_prediction
    if EvidenceProvenanceV1.single_study_direct in provenances:
        return EvidenceProvenanceV1.single_study_direct
    return EvidenceProvenanceV1.unknown


def _resolve_claim_scope(
    claim: ClaimV1,
    evidence_provenance: EvidenceProvenanceV1,
) -> ClaimScopeV1:
    if claim.claim_scope is not None:
        return claim.claim_scope
    if evidence_provenance == EvidenceProvenanceV1.single_study_direct:
        return ClaimScopeV1.within_study
    if evidence_provenance in {
        EvidenceProvenanceV1.cross_study_inference,
        EvidenceProvenanceV1.theoretical_prediction,
    }:
        return ClaimScopeV1.cross_study
    return ClaimScopeV1.unknown


def _resolve_raw_data_available(
    claim: ClaimV1,
    linked_evidence: list[EvidenceItemV1],
) -> bool | None:
    if claim.raw_data_available is not None:
        return claim.raw_data_available
    return _first_non_null_bool(item.raw_data_available for item in linked_evidence)


def _resolve_direct_statistical_test(
    claim: ClaimV1,
    linked_evidence: list[EvidenceItemV1],
) -> bool | None:
    if claim.direct_statistical_test is not None:
        return claim.direct_statistical_test
    return _first_non_null_bool(item.direct_statistical_test for item in linked_evidence)


def allowed_claim_verdicts(
    *,
    evidence_provenance: EvidenceProvenanceV1,
    direct_statistical_test: bool | None,
) -> tuple[ClaimVerdictV1, ...]:
    if (
        evidence_provenance == EvidenceProvenanceV1.single_study_direct
        and direct_statistical_test is True
    ):
        return (
            ClaimVerdictV1.supported,
            ClaimVerdictV1.refuted,
            ClaimVerdictV1.mixed,
            ClaimVerdictV1.inconclusive,
        )
    if evidence_provenance == EvidenceProvenanceV1.cross_study_inference:
        return (
            ClaimVerdictV1.indirectly_supported,
            ClaimVerdictV1.suggestive,
            ClaimVerdictV1.mixed,
            ClaimVerdictV1.inconclusive,
        )
    if evidence_provenance == EvidenceProvenanceV1.theoretical_prediction:
        return (
            ClaimVerdictV1.predicted,
            ClaimVerdictV1.suggestive,
            ClaimVerdictV1.inconclusive,
        )
    return (
        ClaimVerdictV1.suggestive,
        ClaimVerdictV1.inconclusive,
    )


def recommended_confidence_tier(
    *,
    evidence_provenance: EvidenceProvenanceV1,
    raw_data_available: bool | None,
    direct_statistical_test: bool | None,
) -> EpistemicConfidenceTierV1:
    if evidence_provenance == EvidenceProvenanceV1.theoretical_prediction:
        return EpistemicConfidenceTierV1.low
    if evidence_provenance == EvidenceProvenanceV1.cross_study_inference:
        return EpistemicConfidenceTierV1.low
    if evidence_provenance == EvidenceProvenanceV1.single_study_direct:
        if direct_statistical_test is True and raw_data_available is True:
            return EpistemicConfidenceTierV1.high
        if direct_statistical_test is True:
            return EpistemicConfidenceTierV1.medium
    return EpistemicConfidenceTierV1.low


def evidence_tier_label(evidence_provenance: EvidenceProvenanceV1) -> str:
    return _EVIDENCE_TIER_LABELS.get(
        evidence_provenance,
        _EVIDENCE_TIER_LABELS[EvidenceProvenanceV1.unknown],
    )


def assess_claim_epistemics(
    claim: ClaimV1,
    evidence_items: Iterable[EvidenceItemV1],
) -> EpistemicAssessment:
    evidence_lookup = _evidence_by_id(evidence_items)
    linked_evidence = [
        evidence_lookup[evidence_id]
        for evidence_id in claim.evidence_ids
        if evidence_id in evidence_lookup
    ]
    evidence_provenance = _resolve_evidence_provenance(claim, linked_evidence)
    claim_scope = _resolve_claim_scope(claim, evidence_provenance)
    raw_data_available = _resolve_raw_data_available(claim, linked_evidence)
    direct_statistical_test = _resolve_direct_statistical_test(claim, linked_evidence)
    allowed_verdicts = allowed_claim_verdicts(
        evidence_provenance=evidence_provenance,
        direct_statistical_test=direct_statistical_test,
    )
    return EpistemicAssessment(
        evidence_provenance=evidence_provenance,
        claim_scope=claim_scope,
        raw_data_available=raw_data_available,
        direct_statistical_test=direct_statistical_test,
        allowed_verdicts=allowed_verdicts,
        recommended_confidence_tier=recommended_confidence_tier(
            evidence_provenance=evidence_provenance,
            raw_data_available=raw_data_available,
            direct_statistical_test=direct_statistical_test,
        ),
    )


def _downgraded_verdict(
    *,
    original_verdict: ClaimVerdictV1 | None,
    assessment: EpistemicAssessment,
) -> ClaimVerdictV1 | None:
    if original_verdict is None:
        return None
    if original_verdict in assessment.allowed_verdicts:
        return original_verdict

    if assessment.evidence_provenance == EvidenceProvenanceV1.cross_study_inference:
        if original_verdict in {
            ClaimVerdictV1.supported,
            ClaimVerdictV1.indirectly_supported,
        }:
            return ClaimVerdictV1.indirectly_supported
        if original_verdict == ClaimVerdictV1.mixed:
            return ClaimVerdictV1.mixed
        if original_verdict == ClaimVerdictV1.refuted:
            return ClaimVerdictV1.inconclusive
        return ClaimVerdictV1.suggestive

    if assessment.evidence_provenance == EvidenceProvenanceV1.theoretical_prediction:
        if original_verdict == ClaimVerdictV1.inconclusive:
            return ClaimVerdictV1.inconclusive
        if original_verdict == ClaimVerdictV1.suggestive:
            return ClaimVerdictV1.suggestive
        return ClaimVerdictV1.predicted

    if (
        assessment.evidence_provenance == EvidenceProvenanceV1.single_study_direct
        and assessment.direct_statistical_test is not True
    ):
        if original_verdict == ClaimVerdictV1.mixed:
            return ClaimVerdictV1.mixed
        if original_verdict == ClaimVerdictV1.refuted:
            return ClaimVerdictV1.inconclusive
        return ClaimVerdictV1.suggestive

    if assessment.allowed_verdicts:
        return assessment.allowed_verdicts[0]
    return original_verdict


def _display_verdict_label(
    *,
    verdict: ClaimVerdictV1 | None,
    assessment: EpistemicAssessment,
) -> str | None:
    calibrated_verdict = _downgraded_verdict(
        original_verdict=verdict,
        assessment=assessment,
    )
    if calibrated_verdict is None:
        return None
    if calibrated_verdict == ClaimVerdictV1.indirectly_supported:
        return "consistent_with"
    if calibrated_verdict == ClaimVerdictV1.predicted:
        return "predicted_by_analogy"
    return calibrated_verdict.value


def calibrate_claim_epistemics(
    claim: ClaimV1,
    evidence_items: Iterable[EvidenceItemV1],
) -> ClaimV1:
    """Return a claim copy calibrated to the linked evidence provenance.

    This is used when emitting human-facing sidecars so cross-study or theory-only
    evidence cannot be rendered with direct-support language.
    """

    assessment = assess_claim_epistemics(claim, evidence_items)
    calibrated_verdict = _downgraded_verdict(
        original_verdict=claim.verdict,
        assessment=assessment,
    )
    calibrated_tier = assessment.recommended_confidence_tier

    extra = dict(claim.extra or {})
    calibration = dict(extra.get("epistemic_calibration") or {})
    calibration.update(
        {
            "evidence_tier_label": evidence_tier_label(assessment.evidence_provenance),
            "display_verdict": _display_verdict_label(
                verdict=claim.verdict,
                assessment=assessment,
            ),
            "allowed_verdicts": [
                verdict.value for verdict in assessment.allowed_verdicts
            ],
            "recommended_confidence_tier": calibrated_tier.value,
            "evidence_provenance": assessment.evidence_provenance.value,
            "claim_scope": assessment.claim_scope.value,
            "raw_data_available": assessment.raw_data_available,
            "direct_statistical_test": assessment.direct_statistical_test,
        }
    )
    if claim.verdict is not None and calibrated_verdict != claim.verdict:
        calibration["original_verdict"] = claim.verdict.value
    if (
        claim.epistemic_confidence_tier is not None
        and claim.epistemic_confidence_tier != calibrated_tier
    ):
        calibration["original_confidence_tier"] = claim.epistemic_confidence_tier.value
    extra["epistemic_calibration"] = calibration

    return claim.model_copy(
        update={
            "verdict": calibrated_verdict,
            "epistemic_confidence_tier": calibrated_tier,
            "evidence_provenance": assessment.evidence_provenance,
            "claim_scope": assessment.claim_scope,
            "raw_data_available": assessment.raw_data_available,
            "direct_statistical_test": assessment.direct_statistical_test,
            "extra": extra,
        }
    )


def validate_claim_epistemics(
    claim: ClaimV1,
    evidence_items: Iterable[EvidenceItemV1],
) -> list[str]:
    assessment = assess_claim_epistemics(claim, evidence_items)
    issues: list[str] = []

    if claim.verdict is not None and claim.verdict not in assessment.allowed_verdicts:
        allowed = ", ".join(verdict.value for verdict in assessment.allowed_verdicts)
        issues.append(
            "claim "
            f"'{claim.claim_id}' uses verdict '{claim.verdict.value}' "
            f"but evidence provenance '{assessment.evidence_provenance.value}' "
            f"with direct_statistical_test={assessment.direct_statistical_test} "
            f"only permits: {allowed}."
        )

    if claim.epistemic_confidence_tier is not None:
        actual_rank = _TIER_RANK[claim.epistemic_confidence_tier]
        recommended_rank = _TIER_RANK[assessment.recommended_confidence_tier]
        if actual_rank > recommended_rank:
            issues.append(
                "claim "
                f"'{claim.claim_id}' declares confidence tier "
                f"'{claim.epistemic_confidence_tier.value}' "
                f"but evidence only supports "
                f"'{assessment.recommended_confidence_tier.value}'."
            )

    return issues


__all__ = [
    "EpistemicAssessment",
    "allowed_claim_verdicts",
    "assess_claim_epistemics",
    "calibrate_claim_epistemics",
    "evidence_tier_label",
    "recommended_confidence_tier",
    "validate_claim_epistemics",
]
