"""Claim/evidence/grounding pure helper functions for the GABRIEL pipeline.

This module contains pure top-level helper functions that build, normalise, and
score claim and evidence nodes produced by the GABRIEL extractor:

* text utilities: ``_first_sentence``
* sentence scoring: ``_sentence_candidates``, ``_content_tokens``, ``_best_grounded_quote``
* evidence predicates: ``_is_title_only_evidence``
* claim normalisation: ``_normalize_claim_kind``, ``_normalize_assumption_status``,
  ``_infer_claim_kind``, ``_infer_assumption_metadata``
* rule lookup: ``_first_rule_hit``
* polarity: ``_normalize_polarity``
* stable IDs: ``_claim_id``, ``_evidence_id``

All functions are private by convention (underscore-prefixed) and are re-exported
from ``gabriel_generator`` for backward compatibility.

Module-level constants that are used **exclusively** by this cluster are defined
here. ``STAT_DETAIL_PATTERN`` is shared with the main module and is therefore
lazy-imported from there.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brain_researcher.services.br_kg.etl.gabriel_generator import PublicationSeed

# ---------------------------------------------------------------------------
# Constants used exclusively by this cluster
# ---------------------------------------------------------------------------

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", flags=re.IGNORECASE)
GROUNDING_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "across",
    "brain",
    "study",
    "human",
}

_FAILED_REPLICATION_TOKENS = (
    "failed to replicate",
    "failure to replicate",
    "did not replicate",
    "failed replication",
)
_REPLICATION_TOKENS = (
    "replication",
    "replicated",
    "replicate",
)
_NULL_RESULT_TOKENS = (
    "no significant",
    "not significant",
    "null result",
    "no evidence",
    "did not observe",
    "did not find",
)
_CONTRADICTION_TOKENS = (
    "contrary to",
    "in contrast to",
    "inconsistent with",
    "conflicts with",
)
_SUFFICIENCY_TOKENS = ("sufficient", "fully explains", "accounts for")
_NECESSITY_TOKENS = ("necessary", "required for", "depends on")
_PROXY_TOKENS = ("proxy", "marker", "readout", "index of")
_GENERALIZATION_TOKENS = ("generalizes", "generalise", "across contexts", "across cohorts")


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------


def _first_sentence(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    first = pieces[0].strip() if pieces else cleaned
    return first[:600]


# ---------------------------------------------------------------------------
# Sentence scoring / grounding
# ---------------------------------------------------------------------------


def _sentence_candidates(publication: PublicationSeed) -> list[tuple[str, str]]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        STAT_DETAIL_PATTERN,  # lazy – shared constant
    )

    candidates: list[tuple[str, str]] = []
    if publication.abstract:
        for sentence in re.split(r"(?<=[.!?])\s+", publication.abstract.strip()):
            cleaned = sentence.strip()
            if cleaned:
                candidates.append(("abstract", cleaned[:600]))
    if publication.body:
        for sentence in re.split(r"(?<=[.!?])\s+", publication.body.strip()):
            cleaned = sentence.strip()
            if cleaned:
                section = "results" if STAT_DETAIL_PATTERN.search(cleaned) else "unknown"
                candidates.append((section, cleaned[:600]))
    if not candidates and publication.title.strip():
        candidates.append(("title", publication.title.strip()[:600]))
    return candidates


def _content_tokens(text: str | None) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(str(text or "").lower())
        if token and token.lower() not in GROUNDING_STOPWORDS
    }


def _best_grounded_quote(
    publication: PublicationSeed,
    *,
    trigger: str,
    target_label: str,
) -> tuple[str, str, bool]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        STAT_DETAIL_PATTERN,  # lazy – shared constant
    )

    best_sentence = ""
    best_section = "unknown"
    best_score = -1.0
    trigger_text = (trigger or "").strip().lower()
    label_text = (target_label or "").strip().lower()
    trigger_tokens = _content_tokens(trigger_text)
    label_tokens = _content_tokens(label_text)

    for section, sentence in _sentence_candidates(publication):
        sentence_lower = sentence.lower()
        sentence_tokens = _content_tokens(sentence_lower)
        trigger_phrase_hit = bool(trigger_text and trigger_text in sentence_lower)
        label_phrase_hit = bool(label_text and label_text in sentence_lower)
        trigger_overlap = len(sentence_tokens & trigger_tokens)
        label_overlap = len(sentence_tokens & label_tokens)
        grounded = (
            trigger_phrase_hit
            or label_phrase_hit
            or trigger_overlap >= 2
            or label_overlap >= 2
        )
        if not grounded:
            continue

        score = 0.0
        if trigger_phrase_hit:
            score += 3.0
        if label_phrase_hit:
            score += 2.0
        score += 0.75 * trigger_overlap
        score += 0.50 * label_overlap
        if section in {"abstract", "results"}:
            score += 0.25
        if STAT_DETAIL_PATTERN.search(sentence):
            score += 0.50

        if score > best_score:
            best_score = score
            best_sentence = sentence
            best_section = section

    return best_sentence, best_section, best_score >= 1.5


# ---------------------------------------------------------------------------
# Evidence predicates
# ---------------------------------------------------------------------------


def _is_title_only_evidence(
    publication: PublicationSeed,
    evidence: dict[str, Any],
) -> bool:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    section = _clean_text(evidence.get("section")) or ""
    quote = _clean_text(evidence.get("quote")) or ""
    title = _clean_text(publication.title) or ""
    return section.lower() == "title" or (quote and title and quote == title)


# ---------------------------------------------------------------------------
# Claim normalisation
# ---------------------------------------------------------------------------


def _normalize_claim_kind(value: Any) -> str:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    normalized = (_clean_text(value) or "").lower()
    if normalized in {
        "claim",
        "standard",
        "null_result",
        "replication",
        "failed_replication",
        "contradiction",
    }:
        return "claim" if normalized == "standard" else normalized
    return "claim"


def _normalize_assumption_status(value: Any) -> str | None:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    normalized = (_clean_text(value) or "").lower()
    if normalized in {"default", "challenged", "unknown"}:
        return normalized
    return None


def _infer_claim_kind(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if any(token in lowered for token in _FAILED_REPLICATION_TOKENS):
        return "failed_replication"
    if any(token in lowered for token in _NULL_RESULT_TOKENS):
        return "null_result"
    if any(token in lowered for token in _CONTRADICTION_TOKENS):
        return "contradiction"
    if any(token in lowered for token in _REPLICATION_TOKENS):
        return "replication"
    return "claim"


def _infer_assumption_metadata(
    *,
    text: str,
    target_label: str,
    claim_kind: str,
    grounded: bool,
) -> dict[str, Any]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    lowered = (_clean_text(text) or "").lower()
    label = _clean_text(target_label) or "the reported construct"
    assumption_type = "causal_driver"
    assumption_text = f"{label} is a primary driver of the reported effect."
    if any(token in lowered for token in _SUFFICIENCY_TOKENS):
        assumption_type = "sufficiency"
        assumption_text = f"{label} is sufficient to explain the reported effect."
    elif any(token in lowered for token in _NECESSITY_TOKENS):
        assumption_type = "necessity"
        assumption_text = f"{label} is necessary for the reported effect."
    elif any(token in lowered for token in _PROXY_TOKENS):
        assumption_type = "measurement_proxy"
        assumption_text = f"The measured signal is a valid proxy for {label}."
    elif any(token in lowered for token in _GENERALIZATION_TOKENS):
        assumption_type = "generalization"
        assumption_text = (
            f"The reported effect for {label} generalizes beyond the measured cohort."
        )

    challenged = claim_kind in {
        "null_result",
        "failed_replication",
        "contradiction",
    }
    defaultness_score = 0.78 if grounded else 0.32
    challengeability_score = 0.82 if challenged else 0.44
    assumption_confidence = 0.72 if grounded else 0.30
    return {
        "main_assumption_text": assumption_text,
        "assumption_type": assumption_type,
        "assumption_scope": label,
        "defaultness_score": defaultness_score,
        "challengeability_score": challengeability_score,
        "assumption_confidence": assumption_confidence,
        "assumption_status": "challenged" if challenged else "default",
    }


# ---------------------------------------------------------------------------
# Rule lookup
# ---------------------------------------------------------------------------


def _first_rule_hit(text: str, rules: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    for keyword, label, mapped_id in rules:
        if keyword in text:
            return keyword, label, mapped_id
    return None


# ---------------------------------------------------------------------------
# Polarity
# ---------------------------------------------------------------------------


def _normalize_polarity(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"supports", "support", "positive", "increases", "increase"}:
        return "supports"
    if normalized in {"refutes", "refute", "negative", "decreases", "decrease"}:
        return "refutes"
    if normalized in {"mixed", "conflicting", "contradictory"}:
        return "mixed"
    return "uncertain"


# ---------------------------------------------------------------------------
# Stable node IDs
# ---------------------------------------------------------------------------


def _claim_id(paper_id: str, target_id: str, claim_text: str, index: int) -> str:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _stable_hash,  # lazy
    )

    digest = _stable_hash(f"{paper_id}|{target_id}|{claim_text}|{index}")
    return f"claim:{digest}"


def _evidence_id(claim_id: str, quote: str, index: int) -> str:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _stable_hash,  # lazy
    )

    digest = _stable_hash(f"{claim_id}|{quote}|{index}")
    return f"evidence:{digest}"
