import pytest

from brain_researcher.services.neurokg.semantic.confidence_normalizer import (
    append_normalized_confidence_fields,
    canonicalize_confidence_tier,
    infer_confidence_tier,
    normalize_confidence,
)


def test_canonicalize_confidence_tier_aliases():
    assert canonicalize_confidence_tier("human-verified") == "verified"
    assert canonicalize_confidence_tier("moderate") == "medium"
    assert canonicalize_confidence_tier("unexpected-tier") == "unknown"
    assert canonicalize_confidence_tier(None) is None


def test_infer_confidence_tier_thresholds():
    assert infer_confidence_tier(0.91) == "verified"
    assert infer_confidence_tier(0.80) == "high"
    assert infer_confidence_tier(0.60) == "medium"
    assert infer_confidence_tier(0.20) == "low"


def test_normalize_confidence_from_numeric():
    result = normalize_confidence(confidence=0.77)
    assert result["normalized"] == pytest.approx(0.77)
    assert result["value"] == pytest.approx(0.77)
    assert result["tier"] == "high"
    assert result["approximate"] is False
    assert result["basis"] == "confidence"


def test_normalize_confidence_clamps_bounds():
    low = normalize_confidence(confidence=-2.0)
    high = normalize_confidence(confidence=3.5)
    assert low["normalized"] == pytest.approx(0.0)
    assert high["normalized"] == pytest.approx(1.0)


def test_normalize_confidence_from_tier_when_numeric_missing():
    result = normalize_confidence(confidence=None, confidence_tier="manual")
    assert result["normalized"] == pytest.approx(0.95)
    assert result["tier"] == "verified"
    assert result["approximate"] is True
    assert result["basis"] == "tier"


def test_normalize_confidence_marks_mismatch_as_approximate():
    result = normalize_confidence(confidence=0.2, confidence_tier="high")
    assert result["normalized"] == pytest.approx(0.2)
    assert result["tier"] == "high"
    assert result["approximate"] is True
    assert result["basis"] == "confidence+tier"


def test_normalize_confidence_defaults_when_missing():
    result = normalize_confidence(confidence=None, confidence_tier=None)
    assert result["normalized"] == pytest.approx(0.5)
    assert result["tier"] == "unknown"
    assert result["approximate"] is True
    assert result["basis"] == "default"


def test_append_normalized_confidence_fields_is_append_only():
    item = {"id": "edge:1", "confidence": "0.88", "confidence_tier": "curated"}
    enriched = append_normalized_confidence_fields(item)

    assert item == {"id": "edge:1", "confidence": "0.88", "confidence_tier": "curated"}
    assert enriched["id"] == "edge:1"
    assert enriched["confidence_normalized"] == pytest.approx(0.88)
    assert enriched["confidence_tier_normalized"] == "verified"
    assert enriched["confidence_is_approximate"] is True
    assert enriched["confidence_normalization_basis"] == "confidence+tier"
