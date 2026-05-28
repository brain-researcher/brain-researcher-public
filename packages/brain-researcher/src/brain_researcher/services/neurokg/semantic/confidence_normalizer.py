"""Confidence normalization helpers for BR-KG lens evidence payloads."""

from __future__ import annotations

import math
from typing import Any, Mapping

_TIER_ALIASES: dict[str, str] = {
    "verified": "verified",
    "human_verified": "verified",
    "curated": "verified",
    "manual": "verified",
    "high": "high",
    "strong": "high",
    "medium": "medium",
    "moderate": "medium",
    "approximate": "medium",
    "estimated": "medium",
    "low": "low",
    "weak": "low",
    "unknown": "unknown",
}

_TIER_ANCHORS: dict[str, float] = {
    "verified": 0.95,
    "high": 0.82,
    "medium": 0.62,
    "low": 0.32,
    "unknown": 0.50,
}


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    for old, new in (("-", "_"), (" ", "_"), ("/", "_")):
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _coerce_confidence(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            out = float(text)
        except ValueError:
            return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _clamp_01(value: float) -> float:
    return min(1.0, max(0.0, value))


def canonicalize_confidence_tier(tier: Any) -> str | None:
    """Canonicalize confidence tier labels."""

    token = _normalize_token(tier)
    if not token:
        return None
    return _TIER_ALIASES.get(token, "unknown")


def infer_confidence_tier(normalized: float) -> str:
    """Infer canonical tier from normalized confidence value."""

    if normalized >= 0.9:
        return "verified"
    if normalized >= 0.75:
        return "high"
    if normalized >= 0.5:
        return "medium"
    return "low"


def normalize_confidence(
    *,
    confidence: Any = None,
    confidence_tier: Any = None,
) -> dict[str, Any]:
    """Normalize confidence into value/tier/approximate/basis."""

    parsed = _coerce_confidence(confidence)
    tier = canonicalize_confidence_tier(confidence_tier)

    if parsed is not None:
        normalized = _clamp_01(parsed)
        inferred_tier = infer_confidence_tier(normalized)
        if tier is None:
            basis = "confidence"
            resolved_tier = inferred_tier
            approximate = False
        else:
            basis = "confidence+tier"
            resolved_tier = tier
            approximate = tier != inferred_tier
        return {
            "normalized": normalized,
            "value": normalized,
            "tier": resolved_tier,
            "approximate": approximate,
            "basis": basis,
        }

    if tier is not None:
        normalized = _TIER_ANCHORS[tier]
        return {
            "normalized": normalized,
            "value": normalized,
            "tier": tier,
            "approximate": True,
            "basis": "tier",
        }

    normalized = _TIER_ANCHORS["unknown"]
    return {
        "normalized": normalized,
        "value": normalized,
        "tier": "unknown",
        "approximate": True,
        "basis": "default",
    }


def append_normalized_confidence_fields(
    item: Mapping[str, Any],
    *,
    confidence_key: str = "confidence",
    tier_key: str = "confidence_tier",
) -> dict[str, Any]:
    """Return an append-only enriched item with normalized confidence fields."""

    enriched = dict(item)
    normalized = normalize_confidence(
        confidence=item.get(confidence_key),
        confidence_tier=item.get(tier_key),
    )
    enriched["confidence_normalized"] = normalized["normalized"]
    enriched["confidence_tier_normalized"] = normalized["tier"]
    enriched["confidence_is_approximate"] = normalized["approximate"]
    enriched["confidence_normalization_basis"] = normalized["basis"]
    return enriched


__all__ = [
    "append_normalized_confidence_fields",
    "canonicalize_confidence_tier",
    "infer_confidence_tier",
    "normalize_confidence",
]
