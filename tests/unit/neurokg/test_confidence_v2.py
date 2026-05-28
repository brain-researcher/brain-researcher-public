from brain_researcher.services.neurokg.scoring.confidence_v2 import (
    EvidenceSignal,
    compute_confidence_v2,
)


def test_confidence_v2_empty_inputs():
    result = compute_confidence_v2([])
    assert result.confidence == 0.0
    assert result.n_evidence == 0
    assert result.penalty == 1.0


def test_confidence_v2_conflict_and_uncertainty_penalize():
    support_only = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.9, 0.9, 0.9),
            EvidenceSignal("support", 0.85, 0.88, 0.9),
            EvidenceSignal("support", 0.8, 0.85, 0.9),
        ]
    )
    mixed = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.9, 0.9, 0.9),
            EvidenceSignal("conflict", 0.88, 0.9, 0.9),
            EvidenceSignal("uncertain", 0.75, 0.86, 0.9),
        ]
    )
    assert mixed.contradiction_density > 0.0
    assert mixed.uncertainty_density > 0.0
    assert support_only.confidence >= 0.65
    assert mixed.confidence <= 0.02
    assert mixed.confidence < support_only.confidence


def test_confidence_v2_uncertain_only_yields_near_zero_confidence():
    result = compute_confidence_v2(
        [
            EvidenceSignal("uncertain", 0.9, 0.9, 0.9),
            EvidenceSignal("uncertain", 0.85, 0.88, 0.85),
            EvidenceSignal("uncertain", 0.8, 0.86, 0.8),
        ]
    )
    assert result.uncertainty_density == 1.0
    assert result.confidence <= 1e-6


def test_confidence_v2_conflict_uncertainty_interaction_penalizes_extra():
    conflict_only = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.9, 0.9, 0.9),
            EvidenceSignal("conflict", 0.88, 0.9, 0.9),
        ]
    )
    conflict_plus_uncertainty = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.9, 0.9, 0.9),
            EvidenceSignal("conflict", 0.88, 0.9, 0.9),
            EvidenceSignal("uncertain", 0.75, 0.86, 0.9),
        ]
    )
    assert conflict_plus_uncertainty.uncertainty_density > 0.0
    assert conflict_plus_uncertainty.confidence < conflict_only.confidence
    assert conflict_plus_uncertainty.confidence <= 0.01


def test_confidence_v2_reliability_variance_penalizes():
    low_variance = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.8, 0.8, 0.9),
            EvidenceSignal("support", 0.8, 0.8, 0.9),
            EvidenceSignal("support", 0.8, 0.8, 0.9),
        ]
    )
    high_variance = compute_confidence_v2(
        [
            EvidenceSignal("support", 0.8, 0.8, 0.95),
            EvidenceSignal("support", 0.8, 0.8, 0.6),
            EvidenceSignal("support", 0.8, 0.8, 0.95),
        ]
    )
    assert high_variance.source_reliability_variance_norm > 0.0
    assert high_variance.confidence < low_variance.confidence
