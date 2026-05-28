"""Epistemic contract enums shared by claim and evidence artifacts."""

from __future__ import annotations

from enum import Enum


class EvidenceProvenanceV1(str, Enum):
    single_study_direct = "single_study_direct"
    cross_study_inference = "cross_study_inference"
    theoretical_prediction = "theoretical_prediction"
    unknown = "unknown"


class ClaimScopeV1(str, Enum):
    within_study = "within_study"
    cross_study = "cross_study"
    unknown = "unknown"


class EpistemicConfidenceTierV1(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ClaimVerdictV1(str, Enum):
    supported = "supported"
    refuted = "refuted"
    mixed = "mixed"
    inconclusive = "inconclusive"
    indirectly_supported = "indirectly_supported"
    suggestive = "suggestive"
    predicted = "predicted"


__all__ = [
    "ClaimScopeV1",
    "ClaimVerdictV1",
    "EpistemicConfidenceTierV1",
    "EvidenceProvenanceV1",
]
