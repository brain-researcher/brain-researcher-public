"""Conflict/uncertainty-aware confidence scoring helpers for query-time ranking."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean, pstdev, pvariance

_EPS = 1e-6
CONFIDENCE_SCORING_VERSION_V2 = "v2"

_COVERAGE_DECAY = 6.0
_UNCERTAIN_EVIDENCE_WEIGHT = 0.2
_UNCERTAINTY_DOMINANCE_WEIGHT = 0.75

_BASE_WEIGHT_COVERAGE = 0.42
_BASE_WEIGHT_DOMINANCE = 0.28
_BASE_WEIGHT_QUALITY = 0.30

_PENALTY_WEIGHT_CONTRADICTION = 0.72
_PENALTY_WEIGHT_UNCERTAINTY = 0.72
_PENALTY_WEIGHT_QUALITY_SPREAD = 0.10
_PENALTY_WEIGHT_SOURCE_VARIANCE = 0.10
_PENALTY_WEIGHT_CONFLICT_UNCERTAINTY_INTERACTION = 0.22
_PENALTY_EXPONENT = 1.8


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_direction(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"supports", "support", "positive"}:
        return "support"
    if text in {"refutes", "refute", "conflict", "negative"}:
        return "conflict"
    if text in {"uncertain", "mixed"}:
        return "uncertain"
    return "neutral"


@dataclass(frozen=True)
class EvidenceSignal:
    direction: str
    strength: float
    quality: float
    source_reliability: float


@dataclass(frozen=True)
class ConfidenceSignals:
    confidence: float
    coverage: float
    dominance: float
    contradiction_density: float
    uncertainty_density: float
    quality_spread_norm: float
    source_reliability_variance_norm: float
    penalty: float
    support_strength: float
    conflict_strength: float
    uncertainty_strength: float
    n_evidence: int
    q_mean: float

    def as_dict(self, *, ndigits: int = 4) -> dict[str, float | int | str]:
        return {
            "scoring_version": CONFIDENCE_SCORING_VERSION_V2,
            "confidence": round(self.confidence, ndigits),
            "coverage": round(self.coverage, ndigits),
            "dominance": round(self.dominance, ndigits),
            "contradiction_density": round(self.contradiction_density, ndigits),
            "uncertainty_density": round(self.uncertainty_density, ndigits),
            "quality_spread_norm": round(self.quality_spread_norm, ndigits),
            "source_reliability_variance_norm": round(
                self.source_reliability_variance_norm, ndigits
            ),
            "penalty": round(self.penalty, ndigits),
            "support_strength": round(self.support_strength, ndigits),
            "conflict_strength": round(self.conflict_strength, ndigits),
            "uncertainty_strength": round(self.uncertainty_strength, ndigits),
            "n_evidence": int(self.n_evidence),
            "q_mean": round(self.q_mean, ndigits),
        }


def _normalize_signals(
    evidence_signals: Sequence[EvidenceSignal],
) -> list[EvidenceSignal]:
    normalized: list[EvidenceSignal] = []
    for item in evidence_signals:
        direction = _normalize_direction(item.direction)
        normalized.append(
            EvidenceSignal(
                direction=direction,
                strength=_clip01(item.strength),
                quality=_clip01(item.quality),
                source_reliability=_clip01(item.source_reliability),
            )
        )
    return normalized


def compute_confidence_v2(
    evidence_signals: Sequence[EvidenceSignal],
) -> ConfidenceSignals:
    """Compute confidence with explicit contradiction/uncertainty penalties."""

    signals = _normalize_signals(evidence_signals)
    if not signals:
        return ConfidenceSignals(
            confidence=0.0,
            coverage=0.0,
            dominance=0.0,
            contradiction_density=0.0,
            uncertainty_density=0.0,
            quality_spread_norm=0.0,
            source_reliability_variance_norm=0.0,
            penalty=1.0,
            support_strength=0.0,
            conflict_strength=0.0,
            uncertainty_strength=0.0,
            n_evidence=0,
            q_mean=0.5,
        )

    support_strength = sum(
        item.strength for item in signals if item.direction == "support"
    )
    conflict_strength = sum(
        item.strength for item in signals if item.direction == "conflict"
    )
    uncertainty_strength = sum(
        item.strength for item in signals if item.direction == "uncertain"
    )

    quality_values = [item.quality for item in signals]
    reliability_values = [item.source_reliability for item in signals]

    signal_sum = support_strength + conflict_strength
    total_strength = signal_sum + uncertainty_strength
    contradiction_density = (
        2.0 * min(support_strength, conflict_strength) / max(signal_sum, _EPS)
    )
    uncertainty_density = uncertainty_strength / max(total_strength, _EPS)

    quality_spread = pstdev(quality_values) if len(quality_values) > 1 else 0.0
    quality_spread_norm = min(1.0, quality_spread / 0.35)
    reliability_variance = (
        pvariance(reliability_values) if len(reliability_values) > 1 else 0.0
    )
    source_reliability_variance_norm = min(1.0, reliability_variance / 0.08)

    n_evidence = len(signals)
    n_support = sum(1 for item in signals if item.direction == "support")
    n_conflict = sum(1 for item in signals if item.direction == "conflict")
    n_uncertain = sum(1 for item in signals if item.direction == "uncertain")
    n_effective = float(n_support + n_conflict) + _UNCERTAIN_EVIDENCE_WEIGHT * float(
        n_uncertain
    )
    coverage = 1.0 - math.exp(-n_effective / _COVERAGE_DECAY)
    dominance = (
        abs(support_strength - conflict_strength)
        / max(signal_sum + _UNCERTAINTY_DOMINANCE_WEIGHT * uncertainty_strength, _EPS)
        if signal_sum > 0
        else 0.0
    )
    q_mean = mean(quality_values) if quality_values else 0.5

    certainty_factor = 1.0 - uncertainty_density
    base = (
        _BASE_WEIGHT_COVERAGE * coverage
        + _BASE_WEIGHT_DOMINANCE * dominance
        + _BASE_WEIGHT_QUALITY * q_mean
    ) * certainty_factor
    penalty = _clip01(
        1.0
        - (
            _PENALTY_WEIGHT_CONTRADICTION * contradiction_density
            + _PENALTY_WEIGHT_UNCERTAINTY * uncertainty_density
            + _PENALTY_WEIGHT_QUALITY_SPREAD * quality_spread_norm
            + _PENALTY_WEIGHT_SOURCE_VARIANCE * source_reliability_variance_norm
            + _PENALTY_WEIGHT_CONFLICT_UNCERTAINTY_INTERACTION
            * contradiction_density
            * uncertainty_density
        )
    )
    confidence = _clip01(base * math.pow(penalty, _PENALTY_EXPONENT))

    return ConfidenceSignals(
        confidence=confidence,
        coverage=coverage,
        dominance=dominance,
        contradiction_density=contradiction_density,
        uncertainty_density=uncertainty_density,
        quality_spread_norm=quality_spread_norm,
        source_reliability_variance_norm=source_reliability_variance_norm,
        penalty=penalty,
        support_strength=support_strength,
        conflict_strength=conflict_strength,
        uncertainty_strength=uncertainty_strength,
        n_evidence=n_evidence,
        q_mean=q_mean,
    )


__all__ = [
    "CONFIDENCE_SCORING_VERSION_V2",
    "ConfidenceSignals",
    "EvidenceSignal",
    "compute_confidence_v2",
]
