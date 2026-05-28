"""Online capability prediction helpers for planner reranking.

This module converts a user query into predicted capability/intent tokens using
existing in-repo rule systems:
- `match_intents()` synonym matching
- `capability_crosswalk.yaml` phrase mappings
- optional query-understanding intent hints
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from brain_researcher.services.agent.planner.config_loader import load_capability_crosswalk
from brain_researcher.services.agent.planner.synonyms_loader import match_intents

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")
_HINT_LINE = re.compile(r"^\[br_[a-z0-9_]+\]", re.IGNORECASE)
_TOKEN_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "quality_check": ("quality_control", "qc"),
    "quality_control": ("quality_check", "qc"),
}

_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "preprocessing": (
        "preprocess",
        "preprocessing",
        "denois",
        "despike",
        "motion",
        "registration",
        "alignment",
        "slice",
        "filter",
        "bandpass",
        "scrub",
        "resampling",
    ),
    "statistics": (
        "anova",
        "ancova",
        "glm",
        "inference",
        "permutation",
        "bootstrap",
        "cohen",
        "effect",
        "randomise",
        "clustsim",
        "regression",
        "hypothesis",
    ),
    "knowledge_graph": (
        "knowledge graph",
        "knowledge_graph",
        "neurokg",
        "ontology",
        "neurosynth",
        "literature",
        "cross-species",
    ),
    "workflow": (
        "workflow",
        "pipeline",
        "end-to-end",
        "orchestrate",
        "batch processing",
        "cross-validation",
        "reproducibility",
    ),
}

_CONSTRAINT_HINTS: dict[str, tuple[str, ...]] = {
    "condition": (
        "condition",
        "group",
        "cohort",
        "vs",
        "between",
        "within-subject",
        "paired",
    ),
    "sensitivity": (
        "sensitivity",
        "robust",
        "bootstrap",
        "stability",
        "resampling",
        "multiverse",
    ),
    "design": (
        "design",
        "constraint",
        "covariate",
        "interaction",
        "factorial",
        "random effect",
        "random intercept",
    ),
}


def _norm(value: str) -> str:
    raw = _WHITESPACE.sub(" ", str(value or "").strip().lower())
    return _NON_ALNUM.sub("_", raw).strip("_")


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _clean_query(query: str) -> str:
    lines: list[str] = []
    for line in str(query or "").splitlines():
        if _HINT_LINE.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _query_understanding_intents(query_understanding: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(query_understanding, Mapping):
        return []
    raw = query_understanding.get("intent")
    if raw is None:
        raw = query_understanding.get("intents")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Sequence):
        return [str(x) for x in raw if x]
    return []


def _crosswalk_matches(
    query: str,
    *,
    trigger_tokens: Sequence[str] | None = None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    cfg = load_capability_crosswalk()
    mappings = cfg.get("mappings", {}) if isinstance(cfg, dict) else {}
    if not isinstance(mappings, dict) or not mappings:
        return [], [], [], []

    triggers = {_norm(x) for x in (trigger_tokens or []) if x}
    q_lower = str(query or "").lower()

    matched_keys: list[str] = []
    ops: list[str] = []
    intents: list[str] = []
    domains: list[str] = []

    for key, spec in mappings.items():
        if not key or not isinstance(spec, dict):
            continue

        key_norm = _norm(str(key))
        triggered = bool(key_norm and key_norm in triggers)

        if not triggered:
            candidates = [str(key)] + [str(x) for x in (spec.get("aliases") or []) if x]
            for candidate in candidates:
                c = candidate.strip().lower()
                if not c:
                    continue
                if len(c) <= 3 and re.fullmatch(r"[a-z0-9_]+", c):
                    if re.search(rf"\b{re.escape(c)}\b", q_lower):
                        triggered = True
                        break
                elif c in q_lower:
                    triggered = True
                    break

        if not triggered:
            continue

        matched_keys.append(str(key))
        ops.extend([str(x) for x in (spec.get("to_operators") or []) if x])
        intents.extend([str(x) for x in (spec.get("to_intents") or []) if x])
        domains.extend([str(x) for x in (spec.get("domain_tags") or []) if x])

    return _dedupe(matched_keys), _dedupe(ops), _dedupe(intents), _dedupe(domains)


def _extract_domain_signals(
    *,
    query: str,
    predicted_capabilities: Sequence[str],
    predicted_intents: Sequence[str],
    crosswalk_domains: Sequence[str],
) -> list[str]:
    signals: list[str] = []
    q = str(query or "").lower()
    combined = " ".join(
        [str(x).lower() for x in (list(predicted_capabilities) + list(predicted_intents)) if x]
    )
    for domain, patterns in _DOMAIN_HINTS.items():
        if any(p and (p in q or p in combined) for p in patterns):
            signals.append(domain)
    signals.extend([str(x) for x in crosswalk_domains if x])
    return _dedupe(signals)


def _extract_constraint_signals(query: str) -> list[str]:
    q = str(query or "").lower()
    matched: list[str] = []
    for signal, patterns in _CONSTRAINT_HINTS.items():
        if any(p and p in q for p in patterns):
            matched.append(signal)
    return _dedupe(matched)


def _token_forms(value: str) -> set[str]:
    norm = _norm(value)
    if not norm:
        return set()
    out = {norm, norm.replace("_", " ")}
    out.update([x for x in norm.split("_") if x])
    for alt in _TOKEN_EQUIVALENTS.get(norm, ()):
        alt_norm = _norm(alt)
        if not alt_norm:
            continue
        out.add(alt_norm)
        out.add(alt_norm.replace("_", " "))
        out.update([x for x in alt_norm.split("_") if x])
    return out


def _matches_token(target: str, candidates: set[str]) -> bool:
    if target in candidates:
        return True
    for candidate in candidates:
        if len(target) < 2 or len(candidate) < 2:
            continue
        t_parts = [p for p in target.split("_") if p]
        c_parts = [p for p in candidate.split("_") if p]
        if len(t_parts) >= 2 and set(t_parts).issubset(set(c_parts)):
            return True
        if len(c_parts) >= 2 and set(c_parts).issubset(set(t_parts)):
            return True
    return False


def _tool_token_set(tool: Any) -> set[str]:
    values: list[str] = []
    for field in ("capabilities", "intents"):
        raw = getattr(tool, field, None) or []
        values.extend([str(x) for x in raw if x])
    values.extend(
        [
            str(getattr(tool, "id", "") or ""),
            str(getattr(tool, "name", "") or ""),
            str(getattr(tool, "package", "") or ""),
        ]
    )
    out: set[str] = set()
    for value in values:
        out.update(_token_forms(value))
    return out


@dataclass(frozen=True)
class CapabilityPrediction:
    """Predicted capability/intent signals for a query."""

    predicted_capabilities: list[str]
    predicted_intents: list[str]
    direct_intents: list[str]
    matched_crosswalk_keys: list[str]
    confidence: float
    debug: dict[str, Any] = field(default_factory=dict)
    domain_signals: list[str] = field(default_factory=list)
    constraint_signals: list[str] = field(default_factory=list)
    abstain_reason: str | None = None
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicted_capabilities": list(self.predicted_capabilities),
            "predicted_intents": list(self.predicted_intents),
            "direct_intents": list(self.direct_intents),
            "matched_crosswalk_keys": list(self.matched_crosswalk_keys),
            "confidence": float(self.confidence),
            "domain_signals": list(self.domain_signals),
            "constraint_signals": list(self.constraint_signals),
            "abstain_reason": self.abstain_reason,
            "score_breakdown": dict(self.score_breakdown or {}),
            "debug": dict(self.debug or {}),
        }


def predict_capabilities(
    *,
    query: str,
    modality: str | None = None,
    query_understanding: Mapping[str, Any] | None = None,
) -> CapabilityPrediction:
    """Predict capabilities/intents from online query signals."""

    clean_query = _clean_query(query)
    direct_intents = _dedupe(match_intents(clean_query, modality=modality))
    qur_intents = _dedupe(_query_understanding_intents(query_understanding))
    keys, ops, crosswalk_intents, crosswalk_domains = _crosswalk_matches(
        clean_query,
        trigger_tokens=qur_intents,
    )

    predicted_capabilities = _dedupe(direct_intents + ops)
    predicted_intents = _dedupe(qur_intents + crosswalk_intents + direct_intents)
    domain_signals = _extract_domain_signals(
        query=clean_query,
        predicted_capabilities=predicted_capabilities,
        predicted_intents=predicted_intents,
        crosswalk_domains=crosswalk_domains,
    )
    constraint_signals = _extract_constraint_signals(clean_query)

    confidence_components = {
        "intent": 0.45 if direct_intents else 0.0,
        "crosswalk": 0.30 if keys else 0.0,
        "query_understanding": 0.10 if qur_intents else 0.0,
        "domain": 0.15 if domain_signals else 0.0,
    }
    confidence = sum(confidence_components.values())
    if (predicted_capabilities or predicted_intents) and confidence <= 0.0:
        confidence = 0.2
    confidence = max(0.0, min(1.0, confidence))
    abstain_reason = None
    if not predicted_capabilities and not predicted_intents:
        if not direct_intents and not keys:
            abstain_reason = "no_intent_or_crosswalk_match"
        elif not direct_intents:
            abstain_reason = "no_direct_intent_match"
        else:
            abstain_reason = "no_capability_signals"

    return CapabilityPrediction(
        predicted_capabilities=predicted_capabilities,
        predicted_intents=predicted_intents,
        direct_intents=direct_intents,
        matched_crosswalk_keys=keys,
        confidence=confidence,
        domain_signals=domain_signals,
        constraint_signals=constraint_signals,
        abstain_reason=abstain_reason,
        score_breakdown=confidence_components,
        debug={
            "query_clean": clean_query,
            "query_understanding_intents": qur_intents,
            "crosswalk_operators": ops,
            "crosswalk_intents": crosswalk_intents,
            "crosswalk_domains": crosswalk_domains,
        },
    )


def score_tool_capability_match(
    tool: Any, prediction: CapabilityPrediction
) -> tuple[float, list[str]]:
    """Score tool match against predicted capabilities/intents.

    Returns:
        (score in [0,1], matched_labels)
    """
    strong_labels = _dedupe(
        list(prediction.direct_intents)
        + list((prediction.debug or {}).get("query_understanding_intents") or [])
    )
    labels = strong_labels or _dedupe(
        list(prediction.predicted_capabilities) + list(prediction.predicted_intents)
    )
    if not labels:
        return 0.0, []

    candidates = _tool_token_set(tool)
    if not candidates:
        return 0.0, []

    matched: list[str] = []
    for label in labels:
        if _matches_token(_norm(label), candidates):
            matched.append(label)

    if not matched:
        return 0.0, []
    return len(matched) / float(len(labels)), matched


__all__ = [
    "CapabilityPrediction",
    "predict_capabilities",
    "score_tool_capability_match",
]
