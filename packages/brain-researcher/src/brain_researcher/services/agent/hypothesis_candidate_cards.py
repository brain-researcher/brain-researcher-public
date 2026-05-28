"""Helpers for building hypothesis candidate cards from workflow outputs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from hashlib import sha1
from typing import Any

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.novelty_calibration_questions import (
    build_novelty_calibration_context,
    generate_novelty_calibration_questions,
)
from brain_researcher.services.memory.canonical import summarize_claim_families

_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "based",
    "between",
    "by",
    "can",
    "differ",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "latent",
    "mechanism",
    "of",
    "on",
    "or",
    "share",
    "should",
    "task",
    "tasks",
    "that",
    "the",
    "their",
    "to",
    "under",
    "using",
    "what",
    "which",
    "with",
}

_MODALITY_MISMATCH_GROUPS = (
    (
        {"visual", "image", "object", "scene"},
        {"auditory", "speech", "sound", "gustatory", "taste"},
    ),
    ({"reward", "decision"}, {"movie", "watching"}),
)

_OFF_TARGET_PATTERNS = (
    "streak mediator",
    "probe ",
)

_TEMPLATE_PATTERNS = (
    "shared latent mechanism",
    "may partially transfer",
    "under ood settings",
    "out-of-distribution coupling",
)

_GENERIC_MECHANISM_PATTERNS = (
    "shared latent mechanism",
    "partially shared latent mechanism",
    "shared latent representation",
    "shared task family demand profile",
    "shared task-family demand profile",
    "overlapping task structure",
    "shared ontology level construct",
    "shared ontology-level construct",
    "shared conceptual factor",
    "weak local bridge",
    "nearby task family",
    "loose analog",
)

_GENERIC_DIRECTION_PATTERNS = (
    "transfer above matched controls",
    "generalize above matched controls",
    "above matched controls",
    "above matched control",
    "should preserve above-control decoding",
    "should show above-control transfer",
    "should generalize to",
    "cross-condition performance",
)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_key(value: Any) -> str:
    text = _normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize_query(value: Any) -> list[str]:
    tokens = _normalize_key(value).split()
    return [
        token
        for token in tokens
        if token and token not in _QUERY_STOPWORDS and len(token) > 1
    ]


def _extract_overlap_terms(query: str, *texts: Any) -> list[str]:
    query_terms = _tokenize_query(query)
    if not query_terms:
        return []
    haystack = " ".join(_normalize_key(text) for text in texts if text)
    return [term for term in query_terms if term in haystack]


def _is_probable_kg_id(value: Any) -> bool:
    text = _normalize_text(value)
    if not text:
        return False
    if ":" in text and " " not in text:
        return True
    lowered = text.lower()
    return lowered.startswith(("node_", "node/", "kg_", "kg/"))


def _display_anchor_label(anchor_label: str, query: str) -> str:
    anchor_text = _normalize_text(anchor_label)
    if not anchor_text or _is_probable_kg_id(anchor_text):
        return _normalize_text(query) or "the anchored effect"
    return anchor_text


_GENERIC_GAP_RELATION_HINTS = frozenset({"", "related_to", "search_expanded"})

_METHOD_SIGNAL_TERMS = frozenset(
    {
        "analysis",
        "align",
        "alignment",
        "classify",
        "classification",
        "cluster",
        "clustering",
        "decode",
        "decoding",
        "denoise",
        "estimate",
        "estimation",
        "fit",
        "infer",
        "inference",
        "model",
        "normalize",
        "pipeline",
        "preprocess",
        "preprocessing",
        "register",
        "registration",
        "segment",
        "segmentation",
        "smooth",
        "threshold",
        "transform",
        "workflow",
    }
)

_DATA_SIGNAL_TERMS = frozenset(
    {
        "acquisition",
        "atlas",
        "bids",
        "cohort",
        "dataset",
        "datasets",
        "dwi",
        "eeg",
        "ecg",
        "fmri",
        "imaging",
        "mri",
        "modality",
        "modalities",
        "participant",
        "participants",
        "sample",
        "samples",
        "scan",
        "scans",
        "session",
        "sessions",
        "subject",
        "subjects",
        "task",
        "tasks",
        "trial",
        "trials",
    }
)

_QUALITY_BUCKET_RANKS = {
    "actual_idea_like": 0,
    "template_only": 1,
    "off_target": 2,
}

_GAP_TYPE_RANKS = {
    None: 0,
    "": 0,
    "evidence": 1,
    "method": 2,
    "data": 3,
    "ontology": 4,
}

_MIN_EMIT_CONFIDENCE = 0.10
_NET_NEGATIVE_CONFLICT_MULTIPLIER = 2.0
_NET_NEGATIVE_MIN_CONFLICTING = 3


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _contains_signal_term(text: str, terms: frozenset[str]) -> bool:
    normalized = _normalize_key(text)
    if not normalized:
        return False
    return bool(set(normalized.split()) & terms)


def _classification_text(
    *,
    query: str | None = None,
    statement: str | None = None,
    candidate_label: str | None = None,
    relation_hint: str | None = None,
) -> str:
    parts = [query, statement, candidate_label, relation_hint]
    return _normalize_text(" ".join(part for part in parts if part))


@lru_cache(maxsize=128)
def _probe_method_tool_support(goal: str) -> dict[str, Any]:
    goal_text = _normalize_text(goal)
    if not goal_text:
        return {
            "goal": goal_text,
            "match_count": 0,
            "total": 0,
            "callable_count": 0,
            "callable_tool_names": [],
        }

    try:
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        specs, total = registry.search_toolspecs(
            goal=goal_text,
            limit=8,
            offset=0,
            exposed_only=False,
            include_workflows=True,
        )
        callable_specs = [
            spec for spec in specs if registry.is_toolspec_runtime_callable(spec)
        ]
        return {
            "goal": goal_text,
            "match_count": len(specs),
            "total": total,
            "callable_count": len(callable_specs),
            "callable_tool_names": [
                str(getattr(spec, "name", "")).strip()
                for spec in callable_specs
                if str(getattr(spec, "name", "")).strip()
            ],
        }
    except Exception:
        return {
            "goal": goal_text,
            "match_count": 0,
            "total": 0,
            "callable_count": 0,
            "callable_tool_names": [],
        }


@lru_cache(maxsize=128)
def _probe_dataset_support(
    *,
    text: str,
    anchor_kg_id: str | None = None,
    candidate_kg_id: str | None = None,
) -> dict[str, Any]:
    text_value = _normalize_text(text)
    anchor_id = _normalize_text(anchor_kg_id)
    candidate_id = _normalize_text(candidate_kg_id)

    related_counts: dict[str, int] = {}
    search_count = 0

    try:
        from brain_researcher.services.neurokg import query_service

        for label, kg_id in (("anchor", anchor_id), ("candidate", candidate_id)):
            if not kg_id:
                continue
            try:
                related = query_service.related_datasets(kg_id, limit=3)
            except Exception:
                related = []
            related_counts[label] = len(related or [])

        if text_value:
            try:
                search_matches = query_service.search_datasets(text=text_value, limit=3)
            except Exception:
                search_matches = []
            search_count = len(search_matches or [])
    except Exception:
        return {
            "text": text_value,
            "anchor_kg_id": anchor_id or None,
            "candidate_kg_id": candidate_id or None,
            "related_dataset_counts": related_counts,
            "search_count": search_count,
        }

    return {
        "text": text_value,
        "anchor_kg_id": anchor_id or None,
        "candidate_kg_id": candidate_id or None,
        "related_dataset_counts": related_counts,
        "search_count": search_count,
    }


def _extract_claim_memory_context(value: Any) -> dict[str, Any]:
    payload = value
    if isinstance(payload, Mapping) and isinstance(
        payload.get("claim_memory"), Mapping
    ):
        payload = payload.get("claim_memory")
    if not isinstance(payload, Mapping):
        return {
            "ok": True,
            "count": 0,
            "cards": [],
            "supporting_claims": [],
            "conflicting_claims": [],
            "conditioning_claims": [],
            "summary": {},
            "claim_family_summary": summarize_claim_families([]),
        }
    return {
        "ok": bool(payload.get("ok", True)),
        "count": _coerce_int(payload.get("count")),
        "cards": list(payload.get("cards") or []),
        "supporting_claims": list(payload.get("supporting_claims") or []),
        "conflicting_claims": list(payload.get("conflicting_claims") or []),
        "conditioning_claims": list(payload.get("conditioning_claims") or []),
        "summary": dict(payload.get("summary") or {}),
        "used_target_hints": list(payload.get("used_target_hints") or []),
        "claim_family_summary": dict(payload.get("claim_family_summary") or {}),
    }


def _claim_memory_profile(context: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {
            "n_cards": 0,
            "n_supporting": 0,
            "n_conflicting": 0,
            "n_conditioning": 0,
            "n_claim_families": 0,
            "n_target_families": 0,
            "analytic_conditions": [],
            "target_ids": [],
            "canonical_claim_ids": [],
            "canonical_target_ids": [],
            "priority": "none",
        }

    summary = dict(context.get("summary") or {})
    cards = list(context.get("cards") or [])
    family_summary = dict(context.get("claim_family_summary") or {})
    if not family_summary:
        family_summary = summarize_claim_families(cards)
    supporting = _coerce_int(summary.get("n_supporting")) or len(
        list(context.get("supporting_claims") or [])
    )
    conflicting = _coerce_int(summary.get("n_conflicting")) or len(
        list(context.get("conflicting_claims") or [])
    )
    conditioning = _coerce_int(summary.get("n_conditioning")) or len(
        list(context.get("conditioning_claims") or [])
    )

    analytic_conditions: list[str] = []
    target_ids: list[str] = []
    canonical_claim_ids: list[str] = []
    canonical_target_ids: list[str] = []
    seen_conditions: set[str] = set()
    seen_targets: set[str] = set()
    seen_claim_ids: set[str] = set()
    seen_target_families: set[str] = set()
    for raw_card in cards:
        if not isinstance(raw_card, Mapping):
            continue
        for raw_condition in list(raw_card.get("analytic_conditions") or []):
            condition = _normalize_text(raw_condition)
            if not condition or condition.lower() in seen_conditions:
                continue
            seen_conditions.add(condition.lower())
            analytic_conditions.append(condition)
        for raw_target in list(raw_card.get("target_ids") or []):
            target_id = _normalize_text(raw_target)
            if not target_id or target_id.lower() in seen_targets:
                continue
            seen_targets.add(target_id.lower())
            target_ids.append(target_id)
        canonical_claim_id = _normalize_text(raw_card.get("canonical_claim_id"))
        if canonical_claim_id and canonical_claim_id.lower() not in seen_claim_ids:
            seen_claim_ids.add(canonical_claim_id.lower())
            canonical_claim_ids.append(canonical_claim_id)
        canonical_target_id = _normalize_text(raw_card.get("canonical_target_id"))
        if (
            canonical_target_id
            and canonical_target_id.lower() not in seen_target_families
        ):
            seen_target_families.add(canonical_target_id.lower())
            canonical_target_ids.append(canonical_target_id)

    if not canonical_claim_ids:
        for family in list(family_summary.get("claim_families") or []):
            if not isinstance(family, Mapping):
                continue
            family_id = _normalize_text(family.get("canonical_claim_id"))
            if family_id and family_id.lower() not in seen_claim_ids:
                seen_claim_ids.add(family_id.lower())
                canonical_claim_ids.append(family_id)
    if not canonical_target_ids:
        for family in list(family_summary.get("target_families") or []):
            if not isinstance(family, Mapping):
                continue
            family_id = _normalize_text(family.get("canonical_target_id"))
            if family_id and family_id.lower() not in seen_target_families:
                seen_target_families.add(family_id.lower())
                canonical_target_ids.append(family_id)

    priority = "none"
    if conflicting > 0:
        priority = "conflict_resolution"
    elif conditioning > 0:
        priority = "conditioning_sensitive"
    elif supporting > 0:
        priority = "background"

    return {
        "n_cards": _coerce_int(context.get("count")) or len(cards),
        "n_supporting": supporting,
        "n_conflicting": conflicting,
        "n_conditioning": conditioning,
        "n_claim_families": int(family_summary.get("n_claim_families") or 0),
        "n_target_families": int(family_summary.get("n_target_families") or 0),
        "analytic_conditions": analytic_conditions[:4],
        "target_ids": target_ids[:5],
        "canonical_claim_ids": canonical_claim_ids[:3],
        "canonical_target_ids": canonical_target_ids[:3],
        "dominant_claim_family_id": _normalize_text(
            (family_summary.get("dominant_claim_family") or {}).get(
                "canonical_claim_id"
            )
        )
        or None,
        "dominant_target_family_id": _normalize_text(
            (family_summary.get("dominant_target_family") or {}).get(
                "canonical_target_id"
            )
        )
        or None,
        "priority": priority,
    }


def _claim_memory_priority_rank(card: Mapping[str, Any]) -> int:
    priority_ranks = {
        "conflict_resolution": 0,
        "conditioning_resolution": 1,
        "conditioning_sensitive": 2,
        "background": 3,
        "unknown": 4,
        "low": 5,
        "conflict_risk": 6,
        "none": 7,
    }
    explicit_priority = _normalize_text(card.get("claim_memory_priority")).lower()
    explicit_rank = priority_ranks.get(explicit_priority, priority_ranks["none"])

    profile = card.get("claim_memory_profile")
    if not isinstance(profile, Mapping):
        provenance = card.get("provenance")
        if isinstance(provenance, Mapping):
            profile = provenance.get("claim_memory_profile")
    if not isinstance(profile, Mapping):
        return explicit_rank
    profile_priority = _normalize_text(profile.get("priority")).lower()
    if profile_priority in priority_ranks:
        profile_rank = priority_ranks[profile_priority]
    elif _coerce_int(profile.get("n_conflicting")) > 0:
        profile_rank = priority_ranks["conflict_resolution"]
    elif _coerce_int(profile.get("n_conditioning")) > 0:
        profile_rank = priority_ranks["conditioning_sensitive"]
    elif _coerce_int(profile.get("n_supporting")) > 0:
        profile_rank = priority_ranks["background"]
    else:
        profile_rank = priority_ranks["none"]
    return min(explicit_rank, profile_rank)


def _claim_memory_condition_text(profile: Mapping[str, Any] | None) -> str:
    if not isinstance(profile, Mapping):
        return ""
    conditions = [
        _normalize_text(value)
        for value in list(profile.get("analytic_conditions") or [])[:2]
        if _normalize_text(value)
    ]
    if not conditions:
        return ""
    return ", ".join(conditions)


def _claim_memory_profile_has_signal(profile: Mapping[str, Any] | None) -> bool:
    if not isinstance(profile, Mapping):
        return False
    return any(
        _coerce_int(profile.get(key)) > 0
        for key in ("n_cards", "n_supporting", "n_conflicting", "n_conditioning")
    )


def _claim_memory_summary_text(profile: Mapping[str, Any] | None) -> str:
    if not _claim_memory_profile_has_signal(profile):
        return ""
    n_supporting = _coerce_int(_safe_get(profile, "n_supporting", 0))
    n_conflicting = _coerce_int(_safe_get(profile, "n_conflicting", 0))
    n_conditioning = _coerce_int(_safe_get(profile, "n_conditioning", 0))
    parts: list[str] = []
    if n_conflicting > 0:
        label = "claim" if n_conflicting == 1 else "claims"
        parts.append(f"{n_conflicting} conflicting prior {label}")
    if n_conditioning > 0:
        label = "claim" if n_conditioning == 1 else "claims"
        parts.append(f"{n_conditioning} conditioning-sensitive prior {label}")
    if n_supporting > 0:
        label = "claim" if n_supporting == 1 else "claims"
        parts.append(f"{n_supporting} supporting prior {label}")
    text = "; ".join(parts)
    if not text:
        n_cards = _coerce_int(_safe_get(profile, "n_cards", 0))
        label = "card" if n_cards == 1 else "cards"
        text = f"{n_cards} prior claim memory {label}"
    n_families = _coerce_int(_safe_get(profile, "n_claim_families", 0))
    if n_families > 0:
        family_label = (
            "canonical claim family" if n_families == 1 else "canonical claim families"
        )
        text = f"{text} across {n_families} {family_label}"
    conditions_text = _claim_memory_condition_text(profile)
    if conditions_text:
        return f"{text}. Key analytic conditions: {conditions_text}."
    return f"{text}."


def _claim_memory_resolution_hint(profile: Mapping[str, Any] | None) -> str:
    if not _claim_memory_profile_has_signal(profile):
        return ""
    n_conflicting = _coerce_int(_safe_get(profile, "n_conflicting", 0))
    n_conditioning = _coerce_int(_safe_get(profile, "n_conditioning", 0))
    n_supporting = _coerce_int(_safe_get(profile, "n_supporting", 0))
    conditions_text = _claim_memory_condition_text(profile)
    if n_conflicting > 0:
        hint = "Use the first experiment to explain why prior claims diverged"
        if conditions_text:
            hint += f" under {conditions_text}"
        return f"{hint}."
    if n_conditioning > 0:
        if conditions_text:
            return (
                "Stage the first replication as a conditioning test that varies "
                f"{conditions_text}."
            )
        return (
            "Stage the first replication as a conditioning test rather than a single "
            "point estimate."
        )
    if n_supporting > 0:
        return (
            "Use the prior supporting claim as a positive control for the first test."
        )
    return ""


def _augment_idea_with_claim_memory(
    base_text: str,
    *,
    claim_memory_profile: Mapping[str, Any] | None = None,
) -> str:
    base = _normalize_text(base_text)
    if not base or not isinstance(claim_memory_profile, Mapping):
        return base
    conditions_text = _claim_memory_condition_text(claim_memory_profile)
    if _coerce_int(claim_memory_profile.get("n_conflicting")) > 0:
        suffix = "Frame it as a conflict-resolution candidate that explains why prior runs disagree"
        if conditions_text:
            suffix += f" under {conditions_text}"
        suffix += "."
        return f"{base} {suffix}"
    if _coerce_int(claim_memory_profile.get("n_conditioning")) > 0:
        suffix = "Frame it as a conditional replication"
        if conditions_text:
            suffix += f" across {conditions_text}"
        suffix += "."
        return f"{base} {suffix}"
    return base


def _extract_card_claim_memory_context(
    card: Mapping[str, Any], provenance: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    derived_memory = card.get("derived_memory")
    if isinstance(derived_memory, Mapping):
        return _extract_claim_memory_context(derived_memory)
    if isinstance(card.get("claim_memory"), Mapping):
        return _extract_claim_memory_context(card.get("claim_memory"))
    if isinstance(provenance, Mapping) and isinstance(
        provenance.get("claim_memory"), Mapping
    ):
        return _extract_claim_memory_context(provenance.get("claim_memory"))
    return _extract_claim_memory_context(None)


def _extract_card_claim_memory_profile(
    card: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = card.get("claim_memory_profile")
    if not isinstance(existing, Mapping) and isinstance(provenance, Mapping):
        existing = provenance.get("claim_memory_profile")
    if isinstance(existing, Mapping):
        return dict(existing)
    return _claim_memory_profile(context)


def _attach_claim_memory_fields(
    card: dict[str, Any],
    *,
    provenance: dict[str, Any],
    claim_memory_context: Mapping[str, Any] | None = None,
    claim_memory_profile: Mapping[str, Any] | None = None,
) -> None:
    if not _claim_memory_profile_has_signal(claim_memory_profile):
        return
    profile = dict(claim_memory_profile or {})
    summary_text = _claim_memory_summary_text(profile)
    resolution_hint = _claim_memory_resolution_hint(profile)
    card["claim_memory_profile"] = profile
    if summary_text:
        card["claim_memory_summary"] = summary_text
    if resolution_hint:
        card["claim_memory_resolution_hint"] = resolution_hint
    provenance["claim_memory_profile"] = profile
    family_summary = (
        dict(claim_memory_context.get("claim_family_summary") or {})
        if isinstance(claim_memory_context, Mapping)
        else {}
    )
    if family_summary:
        card["claim_family_summary"] = family_summary
        provenance["claim_family_summary"] = family_summary
    if summary_text:
        provenance["claim_memory_summary"] = summary_text
    if resolution_hint:
        provenance["claim_memory_resolution_hint"] = resolution_hint
    if (
        isinstance(claim_memory_context, Mapping)
        and _coerce_int(claim_memory_context.get("count")) > 0
    ):
        provenance["claim_memory"] = dict(claim_memory_context)


def _augment_minimal_test_with_claim_memory(
    base_text: str,
    *,
    claim_memory_profile: Mapping[str, Any] | None = None,
) -> str:
    base = _normalize_text(base_text)
    if not base or not isinstance(claim_memory_profile, Mapping):
        return base
    conditions_text = _claim_memory_condition_text(claim_memory_profile)
    if _coerce_int(claim_memory_profile.get("n_conflicting")) > 0:
        suffix = "Then explicitly resolve the prior conflicting claims"
        if conditions_text:
            suffix += f" by varying {conditions_text}"
        suffix += "."
        return f"{base} {suffix}"
    if _coerce_int(claim_memory_profile.get("n_conditioning")) > 0 and conditions_text:
        return (
            f"{base} Repeat the test while varying the suspected conditioning choices "
            f"({conditions_text})."
        )
    return base


def _augment_falsifier_with_claim_memory(
    base_text: str,
    *,
    claim_memory_profile: Mapping[str, Any] | None = None,
) -> str:
    base = _normalize_text(base_text)
    if not base or not isinstance(claim_memory_profile, Mapping):
        return base
    conditions_text = _claim_memory_condition_text(claim_memory_profile)
    if _coerce_int(claim_memory_profile.get("n_conflicting")) > 0:
        suffix = "Treat the hypothesis as falsified if the conflict remains unexplained"
        if conditions_text:
            suffix += f" after controlling for {conditions_text}"
        suffix += "."
        return f"{base} {suffix}"
    if _coerce_int(claim_memory_profile.get("n_conditioning")) > 0 and conditions_text:
        return (
            f"{base} Treat it as falsified if the predicted effect stays unchanged "
            f"across {conditions_text}."
        )
    return base


def _candidate_card_rerank_key(
    card: Mapping[str, Any], idx: int
) -> tuple[int, int, int, int]:
    claim_memory_rank = _claim_memory_priority_rank(card)
    quality_rank = _QUALITY_BUCKET_RANKS.get(
        str(_safe_get(card, "quality_bucket") or "").strip(), 1
    )
    gap_rank = _GAP_TYPE_RANKS.get(
        str(_safe_get(card, "gap_type") or "").strip() or None, 99
    )
    return claim_memory_rank, quality_rank, gap_rank, idx


def _rerank_candidate_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed_cards = list(enumerate(cards))
    indexed_cards.sort(key=lambda item: _candidate_card_rerank_key(item[1], item[0]))
    return [dict(card) for _idx, card in indexed_cards]


def _classify_verification_gap(
    *,
    kg_verification: Mapping[str, Any] | None,
    relation_hint: str,
    query: str | None = None,
    statement: str | None = None,
    candidate_label: str | None = None,
    anchor_kg_id: str | None = None,
    candidate_kg_id: str | None = None,
    verification_error: str | None = None,
    candidate_lane_filtered: Any = None,
    claim_memory_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify what is still missing to verify a candidate hypothesis.

    This stays conservative on purpose:
    - `ontology` is used only when the bridge is still generic and no retained typed
      evidence path remains.
    - `evidence` covers missing direct support, contradictory evidence, and cases
      where verification controls suppressed candidate-lane evidence.
    - `None` means the hypothesis is already supported or the verification failed
      before we could classify the gap reliably.
    """

    if verification_error or not isinstance(kg_verification, Mapping):
        return {"gap_type": None, "gap_specification": None, "gap_actionable": False}

    summary = _safe_get(kg_verification, "summary", {})
    summary = dict(summary) if isinstance(summary, Mapping) else {}
    verdict = _normalize_key(_safe_get(kg_verification, "verdict", "")).replace(
        " ", "_"
    )
    evidence_source_scope = (
        _normalize_key(_safe_get(kg_verification, "evidence_source_scope", "")).replace(
            " ", "_"
        )
        or "none"
    )
    relation_key = _normalize_key(relation_hint).replace(" ", "_")

    n_supporting = _coerce_int(
        summary.get("n_supporting", _safe_get(kg_verification, "n_supporting", 0))
    )
    n_conflicting = _coerce_int(
        summary.get("n_conflicting", _safe_get(kg_verification, "n_conflicting", 0))
    )
    n_external_supporting = _coerce_int(
        summary.get(
            "n_external_literature_supporting",
            _safe_get(kg_verification, "n_external_literature_supporting", 0),
        )
    )
    filtered_rows = _coerce_int(
        candidate_lane_filtered
        if candidate_lane_filtered is not None
        else summary.get("candidate_lane_filtered")
    )
    prior_conflicting = _coerce_int(_safe_get(claim_memory_profile, "n_conflicting", 0))
    prior_conditioning = _coerce_int(
        _safe_get(claim_memory_profile, "n_conditioning", 0)
    )
    prior_conditions_text = _claim_memory_condition_text(claim_memory_profile)

    if verdict == "supported" or (n_supporting + n_external_supporting) > 0:
        return {"gap_type": None, "gap_specification": None, "gap_actionable": False}

    if filtered_rows > 0 and evidence_source_scope == "none":
        row_label = "row" if filtered_rows == 1 else "rows"
        return {
            "gap_type": "evidence",
            "gap_specification": (
                f"Strict verification controls suppressed {filtered_rows} candidate-lane "
                f"evidence {row_label}. Inspect the filtered evidence or relax the "
                "verification controls before discarding this hypothesis."
            ),
            "gap_actionable": True,
        }

    if verdict in {"mixed", "conflicting"} or n_conflicting > 0:
        return {
            "gap_type": "evidence",
            "gap_specification": (
                "Conflicting evidence was retained for this relationship. The next "
                "step is a discriminating experiment or a narrower claim definition."
            ),
            "gap_actionable": True,
        }

    if (
        verdict in {"insufficient_evidence", "uncertain"}
        and evidence_source_scope == "none"
    ):
        if prior_conflicting > 0:
            specification = (
                "Prior run-derived claim memory already records conflicting experience "
                "for this relationship. The next step is a discriminating experiment "
                "that explains why those prior claims diverged."
            )
            if prior_conditions_text:
                specification += (
                    f" Start by varying the previously implicated analytic conditions "
                    f"({prior_conditions_text})."
                )
            return {
                "gap_type": "evidence",
                "gap_specification": specification,
                "gap_actionable": True,
            }
        if prior_conditioning > 0:
            specification = (
                "Prior run-derived claim memory suggests this relationship is sensitive "
                "to analytic conditions. The next step is a controlled replication that "
                "varies those conditioning choices."
            )
            if prior_conditions_text:
                specification += f" Focus first on {prior_conditions_text}."
            return {
                "gap_type": "evidence",
                "gap_specification": specification,
                "gap_actionable": True,
            }

    if (
        relation_key in _GENERIC_GAP_RELATION_HINTS
        and verdict in {"insufficient_evidence", "uncertain"}
        and evidence_source_scope == "none"
    ):
        relation_label = relation_hint or "related_to"
        return {
            "gap_type": "ontology",
            "gap_specification": (
                f"The current bridge is still typed only as '{relation_label}'. A more "
                "specific mechanism or ontology relation is needed before this "
                "hypothesis can be tested cleanly."
            ),
            "gap_actionable": False,
        }

    if evidence_source_scope in {"typed_path", "expanded_family"}:
        scope_label = evidence_source_scope.replace("_", " ")
        return {
            "gap_type": "evidence",
            "gap_specification": (
                f"Indirect KG support exists via {scope_label}, but no retained direct "
                "supporting evidence was found for this specific claim."
            ),
            "gap_actionable": True,
        }

    if evidence_source_scope == "external_literature":
        return {
            "gap_type": "evidence",
            "gap_specification": (
                "External literature hints exist, but no grounded KG support was "
                "retained for this specific claim."
            ),
            "gap_actionable": True,
        }

    if evidence_source_scope == "hybrid_kg_literature":
        return {
            "gap_type": "evidence",
            "gap_specification": (
                "Indirect KG and external-literature evidence exist, but they do not "
                "yet resolve into direct supporting evidence for this specific claim."
            ),
            "gap_actionable": True,
        }

    if (
        verdict in {"insufficient_evidence", "uncertain"}
        and evidence_source_scope == "none"
    ):
        classification_text = _classification_text(
            query=query,
            statement=statement,
            candidate_label=candidate_label,
            relation_hint=relation_hint,
        )
        method_signal = _contains_signal_term(classification_text, _METHOD_SIGNAL_TERMS)
        data_signal = _contains_signal_term(classification_text, _DATA_SIGNAL_TERMS)

        if method_signal and not data_signal:
            method_probe = _probe_method_tool_support(classification_text)
            if (
                _coerce_int(method_probe.get("match_count")) > 0
                and _coerce_int(method_probe.get("callable_count")) == 0
            ):
                return {
                    "gap_type": "method",
                    "gap_specification": (
                        "A method-oriented analysis is implied, but the registry did "
                        "not surface any callable tool for that capability. The next "
                        "step is to add or route through a callable analysis method."
                    ),
                    "gap_actionable": True,
                }

        if data_signal and not method_signal:
            dataset_probe = _probe_dataset_support(
                text=classification_text,
                anchor_kg_id=anchor_kg_id,
                candidate_kg_id=candidate_kg_id,
            )
            related_counts = dataset_probe.get("related_dataset_counts")
            related_total = 0
            if isinstance(related_counts, Mapping):
                related_total = sum(
                    _coerce_int(count) for count in related_counts.values()
                )
            if (
                related_total == 0
                and _coerce_int(dataset_probe.get("search_count")) == 0
            ):
                return {
                    "gap_type": "data",
                    "gap_specification": (
                        "The claim appears to require a dataset-backed test, but no "
                        "related BR-KG dataset or searchable dataset match was found. "
                        "The next step is to source or register the relevant data."
                    ),
                    "gap_actionable": True,
                }

    if verdict in {"insufficient_evidence", "uncertain"}:
        return {
            "gap_type": "evidence",
            "gap_specification": (
                "Current verification retained no direct supporting evidence for this "
                "relationship. The next step is a targeted study or a narrower claim."
            ),
            "gap_actionable": True,
        }

    return {"gap_type": None, "gap_specification": None, "gap_actionable": False}


def _relation_mechanism_hint(relation_hint: str) -> str:
    rel = _normalize_key(relation_hint).replace(" ", "_")
    if rel == "belongs_to_family":
        return "The candidate sits in a nearby task family and may preserve the same core process."
    if rel == "maps_to":
        return "The candidate appears to operationalize a nearby construct that may sharpen the query."
    if rel == "search_expanded":
        return "The candidate was surfaced by neighborhood expansion and should be treated as a loose analog until verified."
    if rel in {"associated_with", "co_activates", "asserts"}:
        return "The candidate is connected to the anchor through a nearby related-process bridge in the KG."
    return "The candidate is connected to the anchor through a weak local bridge and needs direct testing."


def _semantic_fidelity_flags(
    *,
    query: str,
    candidate_label: str,
    statement: str,
    relation_hint: str,
    evidence_scope: str | None,
    mechanism: str | None = None,
    prediction: str | None = None,
    independent_variable: str | None = None,
    dependent_variable: str | None = None,
    predicted_direction: str | None = None,
) -> list[str]:
    flags: list[str] = []
    overlap_terms = _extract_overlap_terms(query, candidate_label, statement)
    query_key = _normalize_key(query)
    candidate_key = _normalize_key(candidate_label)
    statement_key = _normalize_key(statement)
    relation_key = _normalize_key(relation_hint)
    mechanism_key = _normalize_key(mechanism)
    prediction_key = _normalize_key(prediction)
    independent_variable_key = _normalize_key(independent_variable)
    dependent_variable_key = _normalize_key(dependent_variable)
    predicted_direction_key = _normalize_key(predicted_direction)

    if not overlap_terms:
        flags.append("query_term_overlap_low")

    for positive_terms, negative_terms in _MODALITY_MISMATCH_GROUPS:
        if any(term in query_key for term in positive_terms) and any(
            term in candidate_key or term in statement_key for term in negative_terms
        ):
            flags.append("modality_or_domain_drift")
            break

    if any(pattern in statement_key for pattern in _OFF_TARGET_PATTERNS):
        flags.append("mediator_probe_collapse")

    if any(pattern in statement_key for pattern in _TEMPLATE_PATTERNS):
        flags.append("template_transfer_language")

    if any(pattern in mechanism_key for pattern in _GENERIC_MECHANISM_PATTERNS):
        flags.append("generic_mechanism")

    if any(pattern in prediction_key for pattern in _GENERIC_DIRECTION_PATTERNS):
        flags.append("generic_prediction")

    if not (
        independent_variable_key and dependent_variable_key and predicted_direction_key
    ):
        flags.append("missing_hypothesis_structure")

    comparator_terms = {"older", "younger", "age", "difference", "differ", "between"}
    if any(term in query_key for term in comparator_terms) and not any(
        term in statement_key or term in candidate_key for term in comparator_terms
    ):
        flags.append("comparator_dropped")

    if relation_key == "search_expanded" and evidence_scope in {
        "none",
        "expanded_family",
    }:
        flags.append("weak_search_expanded_bridge")

    return flags


def _quality_bucket_from_flags(flags: list[str]) -> tuple[str, str, str | None]:
    if any(
        flag in flags
        for flag in (
            "modality_or_domain_drift",
            "mediator_probe_collapse",
            "comparator_dropped",
        )
    ):
        return "off_target", "rejected", flags[0]
    if any(
        flag in flags
        for flag in (
            "query_term_overlap_low",
            "template_transfer_language",
            "weak_search_expanded_bridge",
            "generic_mechanism",
            "generic_prediction",
            "missing_hypothesis_structure",
        )
    ):
        return "template_only", "needs_rewrite", flags[0]
    return "actual_idea_like", "rewritten", None


def _verification_support_profile(
    kg_verification: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(kg_verification, Mapping):
        return {
            "verdict": "",
            "confidence": 0.0,
            "n_supporting": 0,
            "n_external_supporting": 0,
            "n_conflicting": 0,
            "n_external_conflicting": 0,
        }

    summary = _safe_get(kg_verification, "summary", {})
    summary = dict(summary) if isinstance(summary, Mapping) else {}
    return {
        "verdict": _normalize_key(_safe_get(kg_verification, "verdict", "")).replace(
            " ", "_"
        ),
        "confidence": _coerce_float(_safe_get(kg_verification, "confidence", 0.0)),
        "n_supporting": _coerce_int(
            summary.get("n_supporting", _safe_get(kg_verification, "n_supporting", 0))
        ),
        "n_external_supporting": _coerce_int(
            summary.get(
                "n_external_literature_supporting",
                _safe_get(kg_verification, "n_external_literature_supporting", 0),
            )
        ),
        "n_conflicting": _coerce_int(
            summary.get("n_conflicting", _safe_get(kg_verification, "n_conflicting", 0))
        ),
        "n_external_conflicting": _coerce_int(
            summary.get(
                "n_external_literature_conflicting",
                _safe_get(kg_verification, "n_external_literature_conflicting", 0),
            )
        ),
    }


def _emit_rejection_reason(
    *,
    quality_bucket: str,
    rewrite_status: str,
    kg_verification: Mapping[str, Any] | None,
) -> str | None:
    if quality_bucket != "actual_idea_like":
        return f"quality_bucket:{quality_bucket}"
    if rewrite_status != "rewritten":
        return f"rewrite_status:{rewrite_status}"

    profile = _verification_support_profile(kg_verification)
    verdict = str(profile["verdict"])
    confidence = float(profile["confidence"])
    support_total = int(profile["n_supporting"]) + int(profile["n_external_supporting"])
    conflicting = int(profile["n_conflicting"]) + int(profile["n_external_conflicting"])

    if verdict in {"conflicting", "mixed"}:
        return "verification:conflicting"

    if (
        conflicting >= _NET_NEGATIVE_MIN_CONFLICTING
        and conflicting > support_total
        and conflicting
        >= max(
            _NET_NEGATIVE_MIN_CONFLICTING,
            int(support_total * _NET_NEGATIVE_CONFLICT_MULTIPLIER),
        )
    ):
        return "verification:net_negative_evidence"

    if (
        verdict in {"insufficient_evidence", "uncertain"}
        and confidence < _MIN_EMIT_CONFIDENCE
    ):
        return "verification:confidence_too_low"

    return None


def _statement_mechanism_text(
    *,
    statement: str,
    relation_hint: str,
    candidate_label: str,
    mechanism: str = "",
) -> str:
    explicit_mechanism = _normalize_text(mechanism)
    if explicit_mechanism:
        return explicit_mechanism
    raw = _normalize_text(statement)
    lowered = raw.lower()
    if " because " in lowered:
        rationale = raw[lowered.index(" because ") + len(" because ") :].strip(" .")
        if rationale:
            return rationale[0].upper() + rationale[1:]
    if " rather than " in lowered:
        contrast = raw[lowered.index(" rather than ") :].strip(" .")
        if contrast:
            return (
                f"{candidate_label} should reflect the active query-linked process "
                f"{contrast}"
            )
    return _relation_mechanism_hint(relation_hint)


def _independent_variable_text(
    *,
    query: str,
    candidate_label: str,
    relation_hint: str,
    claim_type: str = "",
) -> str:
    claim_key = _normalize_key(claim_type).replace(" ", "_")
    relation_key = _normalize_key(relation_hint).replace(" ", "_")
    if claim_key == "mechanism":
        return (
            f"Isolating versus removing signal attributed to {candidate_label} while "
            f"holding the '{query}' contrast fixed."
        )
    if claim_key == "confound":
        return (
            f"Explicitly controlling, balancing, or stratifying {candidate_label} "
            f"within the '{query}' contrast."
        )
    if claim_key == "contradiction_resolution":
        return (
            f"Stratifying the '{query}' analysis by the condition tied to "
            f"{candidate_label}."
        )
    if claim_key == "transfer":
        return (
            f"Evaluating conditions that emphasize {candidate_label} versus matched "
            f"control conditions within '{query}'."
        )
    if relation_key == "maps_to":
        return (
            f"A matched contrast that manipulates '{query}' while testing whether "
            f"{candidate_label} sharpens the construct."
        )
    return (
        f"A matched task contrast that manipulates '{query}' while holding nearby "
        "task demands constant."
    )


def _dependent_variable_text(
    *,
    anchor_label: str,
    candidate_label: str,
    claim_type: str = "",
) -> str:
    claim_key = _normalize_key(claim_type).replace(" ", "_")
    if claim_key == "contradiction_resolution":
        return f"The consistency of findings anchored on {anchor_label}."
    return (
        f"{candidate_label}-linked signal, defined as the preregistered activation, "
        f"decoding, or connectivity metric for the effect anchored on {anchor_label}."
    )


def _predicted_direction_text(
    *,
    query: str,
    anchor_label: str,
    candidate_label: str,
    relation_hint: str,
    claim_type: str = "",
    prediction: str = "",
) -> str:
    explicit_prediction = _normalize_text(prediction)
    if explicit_prediction:
        return explicit_prediction
    display_anchor = _display_anchor_label(anchor_label, query)
    claim_key = _normalize_key(claim_type).replace(" ", "_")
    relation_key = _normalize_key(relation_hint).replace(" ", "_")
    if claim_key == "mechanism":
        return (
            f"Removing or attenuating the {candidate_label}-linked signal should weaken "
            f"the preregistered effect anchored on {display_anchor}, while isolating it "
            "should preserve the effect relative to matched controls."
        )
    if claim_key == "confound":
        return (
            f"Explicitly controlling {candidate_label} should reduce the apparent effect "
            f"anchored on {display_anchor} relative to the uncontrolled analysis."
        )
    if claim_key == "contradiction_resolution":
        return (
            f"Stratifying by {candidate_label} should turn the mixed effect around "
            f"{display_anchor} into a more directional and internally consistent pattern."
        )
    if relation_key == "maps_to":
        return (
            f"The {candidate_label}-linked signal should become stronger or more "
            "selective in the query-manipulated condition than in the matched control."
        )
    if relation_key == "belongs_to_family":
        return (
            f"The {candidate_label}-linked signal should preserve the same directional "
            "effect as the anchor contrast under the matched control."
        )
    if relation_key in {"associated_with", "co_activates", "asserts"}:
        return (
            f"The {candidate_label}-linked signal should covary with the anchor effect "
            "and remain dissociable from the matched control condition."
        )
    return (
        f"The {candidate_label}-linked signal should change directionally under the "
        "query manipulation relative to the matched control."
    )


def _structured_testable_hypothesis_text(
    *,
    query: str,
    anchor_label: str,
    candidate_label: str,
    relation_hint: str,
    statement: str,
    mechanism: str = "",
    prediction: str = "",
    claim_type: str = "",
    quality_bucket: str,
) -> tuple[str, str, str, str, str]:
    if quality_bucket == "off_target":
        return "", "", "", "", ""

    display_anchor = _display_anchor_label(anchor_label, query)
    hypothesis_claim = _normalize_text(statement)
    if not hypothesis_claim:
        hypothesis_claim = (
            f"{candidate_label} should show a dissociable effect for {display_anchor}."
        )
    if hypothesis_claim[-1] not in ".!?":
        hypothesis_claim = f"{hypothesis_claim}."

    independent_variable = _independent_variable_text(
        query=query,
        candidate_label=candidate_label,
        relation_hint=relation_hint,
        claim_type=claim_type,
    )
    dependent_variable = _dependent_variable_text(
        anchor_label=display_anchor,
        candidate_label=candidate_label,
        claim_type=claim_type,
    )
    predicted_direction = _predicted_direction_text(
        query=query,
        anchor_label=display_anchor,
        candidate_label=candidate_label,
        relation_hint=relation_hint,
        claim_type=claim_type,
        prediction=prediction,
    )
    mechanism = _statement_mechanism_text(
        statement=statement,
        relation_hint=relation_hint,
        candidate_label=candidate_label,
        mechanism=mechanism,
    )
    hypothesis = "\n".join(
        (
            f"Hypothesis: {hypothesis_claim}",
            f"Mechanism: {mechanism}",
            f"Independent variable: {independent_variable}",
            f"Dependent variable: {dependent_variable}",
            f"Prediction: {predicted_direction}",
        )
    )
    return (
        hypothesis,
        independent_variable,
        dependent_variable,
        predicted_direction,
        mechanism,
    )


def _idea_text(
    *,
    query: str,
    candidate_label: str,
    quality_bucket: str,
    relation_hint: str,
) -> str:
    if quality_bucket == "off_target":
        return f"Do not promote {candidate_label} as an idea for '{query}' until the semantic mismatch is fixed."
    if quality_bucket == "template_only":
        return f"Test whether {candidate_label} provides a tighter experimental handle on '{query}' than the current loose KG bridge suggests."
    return (
        f"Test whether {candidate_label} carries a dissociable mechanism for '{query}' "
        "under a matched control contrast."
    )


def _testable_hypothesis_text(
    *,
    query: str,
    candidate_label: str,
    relation_hint: str,
    quality_bucket: str,
) -> str:
    del query, candidate_label, relation_hint, quality_bucket
    return ""


def _minimal_test_text(
    *,
    query: str,
    candidate_label: str,
    quality_bucket: str,
    fallback: str,
) -> str:
    if quality_bucket == "off_target":
        return "Reject or re-anchor this candidate before designing a test."
    if quality_bucket == "template_only":
        return f"Run one matched comparison between '{query}' and {candidate_label} with a direct control task before promoting this candidate."
    if fallback:
        return fallback
    return (
        f"Manipulate '{query}' against a matched control and test whether the "
        f"preregistered {candidate_label}-linked signal changes in the predicted direction."
    )


def _falsifier_text(
    *,
    query: str,
    candidate_label: str,
    quality_bucket: str,
    fallback: str,
) -> str:
    if quality_bucket == "off_target":
        return "Reject if the candidate cannot be re-anchored to the original query semantics."
    if quality_bucket == "template_only":
        return f"Reject if {candidate_label} shows no effect or transfer advantage over matched control tasks for '{query}'."
    if fallback:
        return fallback
    return (
        f"Reject if the {candidate_label}-linked signal fails to change in the "
        f"predicted direction under the matched '{query}' manipulation."
    )


def _summarize_candidate_cards(cards: list[dict[str, Any]]) -> dict[str, Any]:
    quality_bucket_counts: dict[str, int] = {}
    rewrite_status_counts: dict[str, int] = {}
    gap_type_counts: dict[str, int] = {}
    for card in cards:
        quality = str(card.get("quality_bucket") or "").strip()
        rewrite = str(card.get("rewrite_status") or "").strip()
        gap_type = str(card.get("gap_type") or "").strip()
        if quality:
            quality_bucket_counts[quality] = quality_bucket_counts.get(quality, 0) + 1
        if rewrite:
            rewrite_status_counts[rewrite] = rewrite_status_counts.get(rewrite, 0) + 1
        if gap_type:
            gap_type_counts[gap_type] = gap_type_counts.get(gap_type, 0) + 1
    return {
        "n_candidate_cards": len(cards),
        "quality_bucket_counts": quality_bucket_counts,
        "rewrite_status_counts": rewrite_status_counts,
        "gap_type_counts": gap_type_counts,
    }


def _candidate_label_from_card(card: Mapping[str, Any], idx: int) -> str:
    title = _normalize_text(
        card.get("title")
        or card.get("label")
        or _safe_get(_safe_get(card, "provenance", {}), "candidate_kg_id")
        or f"candidate_{idx}"
    )
    for suffix in (
        " hypothesis candidate",
        " OOD hypothesis",
        " contradiction frontier",
        " assumption crack",
        " transfer",
    ):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title or f"candidate_{idx}"


def _source_stage_mechanism_hint(source_stage: str, relation_hint: str) -> str:
    stage_key = _normalize_key(source_stage).replace(" ", "_")
    if stage_key == "assumption_cracks":
        return "This candidate challenges a default field assumption rather than extending a nearby node bridge."
    if stage_key == "contradiction_frontiers":
        return "This candidate is anchored in a contradiction frontier and should be tested as a competing explanation."
    if stage_key == "analogy_transfers":
        return "This candidate imports a method family from outside the local neighborhood and should be treated as a deliberate frontier transfer."
    return _relation_mechanism_hint(relation_hint)


def rewrite_candidate_cards(
    cards: list[dict[str, Any]],
    *,
    query: str,
) -> list[dict[str, Any]]:
    rewritten: list[dict[str, Any]] = []
    for idx, raw_card in enumerate(cards, start=1):
        card = dict(raw_card)
        prefilled_flags = [
            _normalize_key(flag).replace(" ", "_")
            for flag in list(card.get("semantic_fidelity_flags") or [])
            if _normalize_key(flag)
        ]
        has_structured_fields = all(
            _normalize_text(card.get(field))
            for field in (
                "mechanism",
                "independent_variable",
                "dependent_variable",
                "predicted_direction",
                "testable_hypothesis",
            )
        )
        if (
            str(card.get("idea") or "").strip()
            and str(card.get("mechanism") or "").strip()
            and str(card.get("quality_bucket") or "").strip() == "actual_idea_like"
            and str(card.get("rewrite_status") or "").strip() == "rewritten"
            and has_structured_fields
            and not {
                "template_transfer_language",
                "generic_mechanism",
                "generic_prediction",
                "missing_hypothesis_structure",
            }
            & set(prefilled_flags)
        ):
            provenance = card.get("provenance")
            provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
            claim_memory_context = _extract_card_claim_memory_context(card, provenance)
            claim_memory_profile = _extract_card_claim_memory_profile(
                card,
                provenance=provenance,
                context=claim_memory_context,
            )
            sampled_verification = provenance.get("sampled_hypothesis_verification")
            sampled_verification = (
                dict(sampled_verification)
                if isinstance(sampled_verification, Mapping)
                else {}
            )
            gap = _classify_verification_gap(
                kg_verification=card.get("kg_verification")
                if isinstance(card.get("kg_verification"), Mapping)
                else None,
                relation_hint=str(
                    provenance.get("relation_hint") or card.get("relation_hint") or ""
                ).strip(),
                query=query,
                statement=str(
                    card.get("raw_hypothesis")
                    or card.get("hypothesis")
                    or card.get("summary")
                    or ""
                ).strip(),
                candidate_label=_candidate_label_from_card(card, idx),
                anchor_kg_id=(str(provenance.get("seed_kg_id") or "").strip() or None),
                candidate_kg_id=(
                    str(provenance.get("candidate_kg_id") or "").strip() or None
                ),
                verification_error=str(
                    sampled_verification.get("verification_error") or ""
                ).strip()
                or None,
                candidate_lane_filtered=sampled_verification.get(
                    "candidate_lane_filtered"
                ),
                claim_memory_profile=claim_memory_profile,
            )
            card.update(gap)
            if sampled_verification:
                provenance["sampled_hypothesis_verification"] = {
                    **sampled_verification,
                    **gap,
                }
            emit_rejection = _emit_rejection_reason(
                quality_bucket="actual_idea_like",
                rewrite_status="rewritten",
                kg_verification=card.get("kg_verification")
                if isinstance(card.get("kg_verification"), Mapping)
                else None,
            )
            if emit_rejection:
                continue
            card["idea"] = _augment_idea_with_claim_memory(
                str(card.get("idea") or "").strip(),
                claim_memory_profile=claim_memory_profile,
            )
            card["minimal_discriminating_test"] = (
                _augment_minimal_test_with_claim_memory(
                    str(card.get("minimal_discriminating_test") or "").strip(),
                    claim_memory_profile=claim_memory_profile,
                )
            )
            card["falsifier_hint"] = _augment_falsifier_with_claim_memory(
                str(card.get("falsifier_hint") or "").strip(),
                claim_memory_profile=claim_memory_profile,
            )
            _attach_claim_memory_fields(
                card,
                provenance=provenance,
                claim_memory_context=claim_memory_context,
                claim_memory_profile=claim_memory_profile,
            )
            card["provenance"] = provenance
            rewritten.append(card)
            continue

        provenance = card.get("provenance")
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        claim_memory_context = _extract_card_claim_memory_context(card, provenance)
        claim_memory_profile = _extract_card_claim_memory_profile(
            card,
            provenance=provenance,
            context=claim_memory_context,
        )
        relation_hint = str(
            provenance.get("relation_hint") or card.get("relation_hint") or ""
        ).strip()
        source_stage = str(provenance.get("source_stage") or "").strip()
        raw_hypothesis = _normalize_text(
            card.get("raw_hypothesis") or card.get("hypothesis") or card.get("summary")
        )
        candidate_label = _candidate_label_from_card(card, idx)
        kg_verification = card.get("kg_verification")
        evidence_scope = (
            str(_safe_get(kg_verification, "evidence_source_scope") or "").strip()
            if isinstance(kg_verification, Mapping)
            else None
        )
        sampled_verification = provenance.get("sampled_hypothesis_verification")
        sampled_verification = (
            dict(sampled_verification)
            if isinstance(sampled_verification, Mapping)
            else {}
        )
        explicit_mechanism = _normalize_text(
            card.get("mechanism") or sampled_verification.get("mechanism") or ""
        )
        explicit_prediction = _normalize_text(
            card.get("prediction") or sampled_verification.get("prediction") or ""
        )
        card["raw_hypothesis"] = raw_hypothesis
        provisional_quality_bucket = "actual_idea_like"
        (
            structured_hypothesis,
            independent_variable,
            dependent_variable,
            predicted_direction,
            mechanism,
        ) = _structured_testable_hypothesis_text(
            query=query,
            anchor_label=str(provenance.get("seed_kg_id") or query),
            candidate_label=candidate_label,
            relation_hint=relation_hint or source_stage,
            statement=raw_hypothesis,
            mechanism=explicit_mechanism,
            prediction=explicit_prediction,
            quality_bucket=provisional_quality_bucket,
        )
        flags = _semantic_fidelity_flags(
            query=query,
            candidate_label=candidate_label,
            statement=raw_hypothesis,
            relation_hint=relation_hint or source_stage,
            evidence_scope=evidence_scope,
            mechanism=mechanism,
            prediction=explicit_prediction or predicted_direction,
            independent_variable=independent_variable,
            dependent_variable=dependent_variable,
            predicted_direction=predicted_direction,
        )
        quality_bucket, rewrite_status, rejection_reason = _quality_bucket_from_flags(
            flags
        )
        (
            structured_hypothesis,
            independent_variable,
            dependent_variable,
            predicted_direction,
            mechanism,
        ) = _structured_testable_hypothesis_text(
            query=query,
            anchor_label=str(provenance.get("seed_kg_id") or query),
            candidate_label=candidate_label,
            relation_hint=relation_hint or source_stage,
            statement=raw_hypothesis,
            mechanism=explicit_mechanism or mechanism,
            prediction=explicit_prediction or predicted_direction,
            quality_bucket=quality_bucket,
        )
        card["idea"] = _idea_text(
            query=query,
            candidate_label=candidate_label,
            quality_bucket=quality_bucket,
            relation_hint=relation_hint or source_stage,
        )
        card["idea"] = _augment_idea_with_claim_memory(
            card["idea"],
            claim_memory_profile=claim_memory_profile,
        )
        card["mechanism"] = mechanism or _source_stage_mechanism_hint(
            source_stage, relation_hint
        )
        card["prediction"] = explicit_prediction or predicted_direction
        card["independent_variable"] = independent_variable
        card["dependent_variable"] = dependent_variable
        card["predicted_direction"] = predicted_direction
        card["testable_hypothesis"] = structured_hypothesis
        card["hypothesis"] = structured_hypothesis or raw_hypothesis
        card["rewrite_status"] = rewrite_status
        card["quality_bucket"] = quality_bucket
        card["rejection_reason"] = rejection_reason
        card["semantic_fidelity_flags"] = flags
        card["minimal_discriminating_test"] = _minimal_test_text(
            query=query,
            candidate_label=candidate_label,
            quality_bucket=quality_bucket,
            fallback=_normalize_text(card.get("minimal_discriminating_test")),
        )
        card["minimal_discriminating_test"] = _augment_minimal_test_with_claim_memory(
            card["minimal_discriminating_test"],
            claim_memory_profile=claim_memory_profile,
        )
        card["falsifier_hint"] = _falsifier_text(
            query=query,
            candidate_label=candidate_label,
            quality_bucket=quality_bucket,
            fallback=_normalize_text(card.get("falsifier_hint")),
        )
        card["falsifier_hint"] = _augment_falsifier_with_claim_memory(
            card["falsifier_hint"],
            claim_memory_profile=claim_memory_profile,
        )
        provenance["semantic_fidelity_flags"] = flags
        provenance["rewrite_status"] = rewrite_status
        provenance["quality_bucket"] = quality_bucket
        gap = _classify_verification_gap(
            kg_verification=kg_verification
            if isinstance(kg_verification, Mapping)
            else None,
            relation_hint=relation_hint or source_stage,
            query=query,
            statement=raw_hypothesis,
            candidate_label=candidate_label,
            anchor_kg_id=(str(provenance.get("seed_kg_id") or "").strip() or None),
            candidate_kg_id=(
                str(provenance.get("candidate_kg_id") or "").strip() or None
            ),
            verification_error=str(
                sampled_verification.get("verification_error") or ""
            ).strip()
            or None,
            candidate_lane_filtered=sampled_verification.get("candidate_lane_filtered"),
            claim_memory_profile=claim_memory_profile,
        )
        card.update(gap)
        if sampled_verification:
            provenance["sampled_hypothesis_verification"] = {
                **sampled_verification,
                **gap,
            }
        emit_rejection = _emit_rejection_reason(
            quality_bucket=quality_bucket,
            rewrite_status=rewrite_status,
            kg_verification=kg_verification
            if isinstance(kg_verification, Mapping)
            else None,
        )
        if emit_rejection:
            card["rewrite_status"] = "rejected"
            card["rejection_reason"] = emit_rejection
            provenance["rewrite_status"] = "rejected"
            provenance["quality_bucket"] = quality_bucket
            provenance["emit_rejection_reason"] = emit_rejection
            _attach_claim_memory_fields(
                card,
                provenance=provenance,
                claim_memory_context=claim_memory_context,
                claim_memory_profile=claim_memory_profile,
            )
            card["provenance"] = provenance
            continue
        _attach_claim_memory_fields(
            card,
            provenance=provenance,
            claim_memory_context=claim_memory_context,
            claim_memory_profile=claim_memory_profile,
        )
        card["provenance"] = provenance
        rewritten.append(card)
    return _rerank_candidate_cards(rewritten)


def _merge_candidate_cards(
    *,
    workflow_cards: list[dict[str, Any]],
    frontier_cards: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    if top_n <= 0:
        return []
    if not frontier_cards:
        return workflow_cards[:top_n]

    frontier_cap = min(len(frontier_cards), max(1, top_n // 2))
    primary_cap = max(0, top_n - frontier_cap)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(card: Mapping[str, Any]) -> None:
        if len(merged) >= top_n:
            return
        card_dict = dict(card)
        card_id = str(card_dict.get("card_id") or "").strip()
        title = str(card_dict.get("title") or "").strip().lower()
        dedupe_key = card_id or title
        if dedupe_key and dedupe_key in seen:
            return
        if dedupe_key:
            seen.add(dedupe_key)
        merged.append(card_dict)

    for card in workflow_cards[:primary_cap]:
        _push(card)
    for card in frontier_cards[:frontier_cap]:
        _push(card)
    for card in workflow_cards[primary_cap:]:
        _push(card)
    for card in frontier_cards[frontier_cap:]:
        _push(card)
    return merged[:top_n]


def _safe_get(mapping: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    return mapping.get(key, default)


@lru_cache(maxsize=1)
def _load_direction_patterns() -> list[dict[str, str]]:
    path = resolve_from_config("hypothesis", "direction_patterns.v1.json")
    if not path.exists():
        return []

    raw = json.loads(path.read_text(encoding="utf-8"))
    patterns = raw.get("patterns") if isinstance(raw, dict) else None
    if not isinstance(patterns, list):
        return []

    out: list[dict[str, str]] = []
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        out.append(
            {
                "id": str(pattern.get("id") or "").strip(),
                "label": str(pattern.get("label") or "").strip(),
                "taste_axis": str(pattern.get("taste_axis") or "").strip(),
                "minimal_test_template": str(
                    pattern.get("minimal_test_template") or ""
                ).strip(),
                "falsifier_template": str(
                    pattern.get("falsifier_template") or ""
                ).strip(),
            }
        )
    return [p for p in out if p["id"]]


def _format_template(template: str, ctx: dict[str, str]) -> str:
    out = template
    for key, value in ctx.items():
        out = out.replace("{" + key + "}", value)
    return out


def _direction_from_prediction_text(prediction: str) -> str:
    prediction_key = _normalize_key(prediction)
    if not prediction_key:
        return ""
    if "preserve above control" in prediction_key and "degrade" in prediction_key:
        return (
            "remain above matched-control baselines when the candidate signal is "
            "isolated, and decrease when it is removed"
        )
    if "reduce" in prediction_key or "eliminate" in prediction_key:
        return "decrease toward matched-control baselines"
    if "degrade" in prediction_key or "drop" in prediction_key:
        return "decrease relative to matched-control baselines"
    if "generalize" in prediction_key or "transfer" in prediction_key:
        return "remain above matched-control baselines"
    if "consistent pattern" in prediction_key or "more consistent" in prediction_key:
        return "become more consistent across stratified conditions"
    if (
        "selectively change" in prediction_key
        or "change held out decoding" in prediction_key
    ):
        return "change selectively relative to matched controls"
    return ""


def _extract_step_result(
    workflow_result: Mapping[str, Any], step_id: str
) -> Mapping[str, Any]:
    steps = _safe_get(workflow_result, "steps", {})
    step_payload = _safe_get(steps, step_id, {})
    data_payload = _safe_get(step_payload, "data", {})
    step_result = _safe_get(data_payload, "result", {})
    return step_result if isinstance(step_result, Mapping) else {}


def _extract_seed_ids(workflow_result: Mapping[str, Any], step_id: str) -> list[str]:
    steps = _safe_get(workflow_result, "steps", {})
    step_payload = _safe_get(steps, step_id, {})
    data_payload = _safe_get(step_payload, "data", {})
    raw = _safe_get(data_payload, "resolved_seed_kg_ids", [])
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _build_leverage_lookup(
    leverage_result: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in _safe_get(leverage_result, "items", []):
        if not isinstance(item, Mapping):
            continue
        kg_id = str(item.get("kg_id") or "").strip()
        if kg_id:
            out[kg_id] = item
    return out


def _extract_contradiction_signal(
    workflow_result: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    contradiction_result = _extract_step_result(workflow_result, "contradiction_scan")
    motifs = _safe_get(contradiction_result, "motifs", [])
    if not isinstance(motifs, list) or not motifs:
        return None, {"motif_count": 0}

    top = motifs[0] if isinstance(motifs[0], Mapping) else {}
    publication = (
        str(
            _safe_get(
                top,
                "publication_label",
                _safe_get(top, "publication_id", "unknown source"),
            )
        ).strip()
        or "unknown source"
    )
    support_count = int(_safe_get(top, "support_count", 0) or 0)
    conflict_count = int(_safe_get(top, "conflict_count", 0) or 0)
    contradiction_density = _safe_get(top, "contradiction_density")
    motif_score = _safe_get(top, "motif_score")
    text = (
        f"Contradiction probe: prioritize evidence from {publication} "
        f"(support/conflict={support_count}/{conflict_count})."
    )
    return text, {
        "motif_count": len(motifs),
        "publication": publication,
        "support_count": support_count,
        "conflict_count": conflict_count,
        "contradiction_density": contradiction_density,
        "motif_score": motif_score,
    }


def _extract_topology_signal(
    workflow_result: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    topology_result = _extract_step_result(workflow_result, "topology_shift_scan")
    proposals = _safe_get(topology_result, "proposals", [])
    if not isinstance(proposals, list) or not proposals:
        return None, {"proposal_count": 0}

    top = proposals[0] if isinstance(proposals[0], Mapping) else {}
    edge = _safe_get(top, "edge", {})
    source_id = str(_safe_get(edge, "source_id", "source")).strip() or "source"
    target_id = str(_safe_get(edge, "target_id", "target")).strip() or "target"
    rel_type = str(_safe_get(edge, "rel_type", "RELATED_TO")).strip() or "RELATED_TO"
    delta = _safe_get(top, "delta")
    target_weight = _safe_get(top, "target_weight")

    delta_text = ""
    if isinstance(delta, int | float):
        delta_text = f" (delta={delta:+.3f})"

    text = (
        "Topology-shift probe: monitor edge "
        f"{source_id} -[{rel_type}]-> {target_id}{delta_text}."
    )
    return text, {
        "proposal_count": len(proposals),
        "edge": {
            "source_id": source_id,
            "target_id": target_id,
            "rel_type": rel_type,
        },
        "delta": delta,
        "target_weight": target_weight,
    }


def _extract_principle_controller_meta(
    workflow_result: Mapping[str, Any],
) -> dict[str, Any]:
    ood_result = _extract_step_result(workflow_result, "ood_sampling")
    update_result = _extract_step_result(workflow_result, "principle_state_update")
    init_result = _extract_step_result(workflow_result, "principle_state_init")

    active_principle = (
        _safe_get(update_result, "active_principle")
        or _safe_get(ood_result, "active_principle")
        or _safe_get(init_result, "active_principle")
    )
    posterior = (
        _safe_get(update_result, "posterior")
        or _safe_get(ood_result, "principle_posterior")
        or _safe_get(init_result, "posterior")
        or {}
    )
    anomaly_flags = _safe_get(update_result, "anomaly_flags")
    if not isinstance(anomaly_flags, list):
        anomaly_flags = _safe_get(ood_result, "anomaly_flags")
    if not isinstance(anomaly_flags, list):
        anomaly_flags = _safe_get(init_result, "anomaly_flags")
    if not isinstance(anomaly_flags, list):
        anomaly_flags = []

    principle_id = ""
    principle_label = ""
    if isinstance(active_principle, Mapping):
        principle_id = str(active_principle.get("principle_id") or "").strip()
        principle_label = str(active_principle.get("label") or "").strip()

    return {
        "principle_session_key": str(
            _safe_get(update_result, "session_key")
            or _safe_get(ood_result, "principle_session_key")
            or _safe_get(init_result, "session_key")
            or ""
        ).strip()
        or None,
        "active_principle": dict(active_principle)
        if isinstance(active_principle, Mapping)
        else None,
        "active_principle_id": principle_id or None,
        "active_principle_label": principle_label or None,
        "principle_posterior": dict(posterior)
        if isinstance(posterior, Mapping)
        else {},
        "principle_confidence": _safe_get(update_result, "principle_confidence")
        or _safe_get(ood_result, "principle_confidence")
        or _safe_get(init_result, "principle_confidence"),
        "selection_reason": str(
            _safe_get(update_result, "selection_reason")
            or _safe_get(ood_result, "selection_reason")
            or _safe_get(init_result, "selection_reason")
            or ""
        ).strip()
        or None,
        "anomaly_flags": [
            str(flag).strip() for flag in anomaly_flags if str(flag).strip()
        ],
        "controller_mode": str(
            _safe_get(update_result, "controller_mode")
            or _safe_get(ood_result, "controller_mode")
            or _safe_get(init_result, "controller_mode")
            or ""
        ).strip()
        or None,
        "enabled": bool(
            _safe_get(update_result, "enabled", _safe_get(init_result, "enabled"))
        ),
    }


def _verification_lookup_key(
    *,
    rank: Any,
    candidate_kg_id: Any,
    statement: Any,
) -> tuple[str, str, str]:
    return (
        str(rank or "").strip(),
        str(candidate_kg_id or "").strip(),
        str(statement or "").strip(),
    )


def _extract_verification_lookup(
    workflow_result: Mapping[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    verify_result = _extract_step_result(workflow_result, "verify_sampled_hypotheses")
    candidate_lane_mode = (
        str(_safe_get(verify_result, "candidate_lane_mode", "")).strip() or None
    )
    verify_summary = (
        dict(_safe_get(verify_result, "summary"))
        if isinstance(_safe_get(verify_result, "summary"), Mapping)
        else {}
    )
    tested = _safe_get(verify_result, "tested_hypotheses", [])
    if not isinstance(tested, list):
        return {}

    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in tested:
        if not isinstance(item, Mapping):
            continue
        hypothesis = item.get("hypothesis")
        if not isinstance(hypothesis, Mapping):
            hypothesis = {}
        statement = str(
            item.get("statement") or hypothesis.get("statement") or ""
        ).strip()
        candidate_kg_id = str(
            item.get("candidate_kg_id") or hypothesis.get("candidate_kg_id") or ""
        ).strip()
        key = _verification_lookup_key(
            rank=item.get("rank") or hypothesis.get("rank"),
            candidate_kg_id=candidate_kg_id,
            statement=statement,
        )
        lookup[key] = {
            "rank": item.get("rank") or hypothesis.get("rank"),
            "candidate_kg_id": candidate_kg_id or None,
            "statement": statement or None,
            "candidate_lane_mode": candidate_lane_mode,
            "candidate_lane_filtered": verify_summary.get("candidate_lane_filtered"),
            "entity_hints_used": list(item.get("entity_hints_used") or [])
            if isinstance(item.get("entity_hints_used"), list)
            else [],
            "kg_verification": dict(item.get("kg_verification"))
            if isinstance(item.get("kg_verification"), Mapping)
            else None,
            "verification_error": str(item.get("verification_error") or "").strip()
            or None,
        }
    return lookup


def _score_novelty_from_memory(
    hypothesis: str,
    memory_store: Any,
) -> tuple[str, str, str]:
    """Return (novelty_signal, claim_memory_priority, reason).

    novelty_signal / claim_memory_priority:
      "conflict_resolution" — at least one conflicting claim found
      "low"                 — ≥2 supporting claims, no conflicts
      "unknown"             — no relevant memory or store unavailable
    """
    if memory_store is None:
        return "unknown", "none", ""
    try:
        result = memory_store.search(
            query=hypothesis,
            card_type="claim_memory",
            filters={"status": "active"},
            limit=3,
        )
        matches = list(result.get("cards") or [])
    except Exception:
        return "unknown", "none", ""
    n_supporting = sum(
        1 for m in matches if len(m.get("supporting_evidence") or []) > 0
    )
    n_conflicting = sum(
        1 for m in matches if len(m.get("conflicting_evidence") or []) > 0
    )
    if n_conflicting >= 1:
        reason = str((matches[0] if matches else {}).get("claim_text") or "")
        return "conflict_resolution", "conflict_resolution", reason
    if n_supporting >= 2 and n_conflicting == 0:
        return "low", "low", ""
    return "unknown", "none", ""


def build_candidate_cards_from_workflow_result(
    workflow_result: Mapping[str, Any],
    *,
    query: str,
    top_n: int = 5,
    memory_store: Any = None,
) -> list[dict[str, Any]]:
    """Project workflow novelty outputs into normalized candidate cards."""

    if top_n <= 0:
        return []

    leverage_result = _extract_step_result(workflow_result, "leverage")
    ood_result = _extract_step_result(workflow_result, "ood_sampling")
    leverage_lookup = _build_leverage_lookup(leverage_result)
    contradiction_signal, contradiction_meta = _extract_contradiction_signal(
        workflow_result
    )
    topology_signal, topology_meta = _extract_topology_signal(workflow_result)
    controller_meta = _extract_principle_controller_meta(workflow_result)
    verification_lookup = _extract_verification_lookup(workflow_result)
    hypotheses = _safe_get(ood_result, "hypotheses", [])
    if not isinstance(hypotheses, list):
        hypotheses = []

    seed_ids = _extract_seed_ids(workflow_result, "leverage")
    default_anchor = seed_ids[0] if seed_ids else "seed construct"
    patterns = _load_direction_patterns()
    if not patterns:
        patterns = [
            {
                "id": "controlled_ood_search",
                "label": "Controlled OOD search",
                "taste_axis": "controlled_ood_search",
                "minimal_test_template": "Run a minimal discriminating test for {anchor} vs {candidate}.",
                "falsifier_template": "Reject if no stable difference appears for {anchor} vs {candidate}.",
            }
        ]

    cards: list[dict[str, Any]] = []
    for idx, row in enumerate(hypotheses, start=1):
        if len(cards) >= top_n:
            break
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_kg_id") or "").strip()
        anchor = str(row.get("seed_kg_id") or default_anchor).strip() or default_anchor
        relation_hint = (
            str(row.get("relation_hint") or "related_to").strip() or "related_to"
        )
        statement = str(row.get("statement") or "").strip()
        if not statement:
            statement = (
                f"{anchor} may show out-of-distribution coupling with "
                f"{candidate_id or 'candidate node'} via {relation_hint.lower()}."
            )
        row_mechanism = _normalize_text(row.get("mechanism"))
        row_prediction = _normalize_text(row.get("prediction"))
        row_claim_type = str(row.get("claim_type") or "").strip()

        leverage_row = leverage_lookup.get(candidate_id, {})
        candidate_label = str(
            _safe_get(leverage_row, "label", candidate_id or f"candidate_{idx}")
        ).strip()
        pattern = patterns[(idx - 1) % len(patterns)]
        fmt_ctx = {
            "anchor": anchor,
            "candidate": candidate_label or candidate_id or "candidate node",
            "relation": relation_hint.lower(),
            "query": query,
        }
        minimal_test = _normalize_text(row.get("minimal_test")) or _format_template(
            pattern["minimal_test_template"], fmt_ctx
        )
        falsifier_hint = _normalize_text(row.get("falsifier")) or _format_template(
            pattern["falsifier_template"], fmt_ctx
        )
        card_id_src = f"{anchor}|{candidate_id}|{statement}"
        card_id = f"cand_{sha1(card_id_src.encode('utf-8')).hexdigest()[:10]}"
        active_principle = (
            row.get("active_principle")
            if isinstance(row.get("active_principle"), Mapping)
            else controller_meta.get("active_principle")
        )
        principle_confidence = row.get("principle_confidence")
        if principle_confidence is None:
            principle_confidence = controller_meta.get("principle_confidence")
        selection_reason = (
            str(
                row.get("selection_reason")
                or controller_meta.get("selection_reason")
                or ""
            ).strip()
            or None
        )
        anomaly_flags = row.get("anomaly_flags")
        if not isinstance(anomaly_flags, list):
            anomaly_flags = controller_meta.get("anomaly_flags") or []
        principle_session_key = (
            str(
                row.get("principle_session_key")
                or controller_meta.get("principle_session_key")
                or ""
            ).strip()
            or None
        )
        verification_entry = verification_lookup.get(
            _verification_lookup_key(
                rank=row.get("rank"),
                candidate_kg_id=candidate_id,
                statement=statement,
            )
        )
        kg_verification = (
            dict(verification_entry.get("kg_verification"))
            if isinstance(_safe_get(verification_entry, "kg_verification"), Mapping)
            else None
        )
        verification_error = (
            str(_safe_get(verification_entry, "verification_error") or "").strip()
            or None
        )
        candidate_lane_filtered = _safe_get(
            verification_entry, "candidate_lane_filtered"
        )
        evidence_scope = (
            str(_safe_get(kg_verification, "evidence_source_scope") or "").strip()
            or None
        )
        claim_memory_context = _extract_claim_memory_context(row.get("derived_memory"))
        claim_memory_profile = _claim_memory_profile(claim_memory_context)
        provisional_quality_bucket = "actual_idea_like"
        (
            rewritten_hypothesis,
            independent_variable,
            dependent_variable,
            predicted_direction,
            mechanism,
        ) = _structured_testable_hypothesis_text(
            query=query,
            anchor_label=anchor,
            candidate_label=candidate_label or candidate_id or f"candidate_{idx}",
            relation_hint=relation_hint,
            statement=statement,
            mechanism=row_mechanism,
            prediction=row_prediction,
            claim_type=row_claim_type,
            quality_bucket=provisional_quality_bucket,
        )
        fidelity_flags = _semantic_fidelity_flags(
            query=query,
            candidate_label=candidate_label,
            statement=statement,
            relation_hint=relation_hint,
            evidence_scope=evidence_scope,
            mechanism=mechanism,
            prediction=row_prediction or predicted_direction,
            independent_variable=independent_variable,
            dependent_variable=dependent_variable,
            predicted_direction=predicted_direction,
        )
        quality_bucket, rewrite_status, rejection_reason = _quality_bucket_from_flags(
            fidelity_flags
        )
        idea = _idea_text(
            query=query,
            candidate_label=candidate_label or candidate_id or f"candidate_{idx}",
            quality_bucket=quality_bucket,
            relation_hint=relation_hint,
        )
        idea = _augment_idea_with_claim_memory(
            idea,
            claim_memory_profile=claim_memory_profile,
        )
        (
            rewritten_hypothesis,
            independent_variable,
            dependent_variable,
            predicted_direction,
            mechanism,
        ) = _structured_testable_hypothesis_text(
            query=query,
            anchor_label=anchor,
            candidate_label=candidate_label or candidate_id or f"candidate_{idx}",
            relation_hint=relation_hint,
            statement=statement,
            mechanism=row_mechanism or mechanism,
            prediction=row_prediction or predicted_direction,
            claim_type=row_claim_type,
            quality_bucket=quality_bucket,
        )
        final_minimal_test = _minimal_test_text(
            query=query,
            candidate_label=candidate_label or candidate_id or f"candidate_{idx}",
            quality_bucket=quality_bucket,
            fallback=minimal_test,
        )
        final_minimal_test = _augment_minimal_test_with_claim_memory(
            final_minimal_test,
            claim_memory_profile=claim_memory_profile,
        )
        final_falsifier = _falsifier_text(
            query=query,
            candidate_label=candidate_label or candidate_id or f"candidate_{idx}",
            quality_bucket=quality_bucket,
            fallback=falsifier_hint,
        )
        final_falsifier = _augment_falsifier_with_claim_memory(
            final_falsifier,
            claim_memory_profile=claim_memory_profile,
        )
        final_hypothesis = rewritten_hypothesis or statement
        gap = _classify_verification_gap(
            kg_verification=kg_verification,
            relation_hint=relation_hint,
            query=query,
            statement=statement,
            candidate_label=candidate_label,
            anchor_kg_id=anchor,
            candidate_kg_id=candidate_id,
            verification_error=verification_error,
            candidate_lane_filtered=candidate_lane_filtered,
            claim_memory_profile=claim_memory_profile,
        )
        emit_rejection = _emit_rejection_reason(
            quality_bucket=quality_bucket,
            rewrite_status=rewrite_status,
            kg_verification=kg_verification,
        )
        if emit_rejection:
            continue

        provenance = {
            "source_workflow": str(workflow_result.get("workflow") or ""),
            "source_tools": [
                "neurokg.find_structural_leverage",
                "neurokg.principle_state_init",
                "neurokg.sample_ood_hypothesis",
                "neurokg.verify_sampled_hypotheses",
                "neurokg.detect_contradiction_motifs",
                "neurokg.detect_topology_shifts",
                "neurokg.principle_state_update",
            ],
            "seed_kg_id": anchor,
            "candidate_kg_id": candidate_id,
            "relation_hint": relation_hint,
            "novelty_score": row.get("novelty_score"),
            "ood_score": row.get("ood_score"),
            "principle_score": row.get("principle_score"),
            "semantic_fidelity_flags": fidelity_flags,
            "rewrite_status": rewrite_status,
            "quality_bucket": quality_bucket,
            "emit_rejection_reason": None,
            "prediction": row_prediction or predicted_direction,
            "leverage_score": leverage_row.get("leverage_score"),
            "contradiction": contradiction_meta,
            "topology_shift": topology_meta,
            "principle_controller": {
                "principle_session_key": principle_session_key,
                "active_principle_id": (
                    str(active_principle.get("principle_id") or "").strip()
                    if isinstance(active_principle, Mapping)
                    else controller_meta.get("active_principle_id")
                ),
                "active_principle_label": (
                    str(active_principle.get("label") or "").strip()
                    if isinstance(active_principle, Mapping)
                    else controller_meta.get("active_principle_label")
                ),
                "active_principle": dict(active_principle)
                if isinstance(active_principle, Mapping)
                else None,
                "posterior": row.get("principle_posterior")
                if isinstance(row.get("principle_posterior"), Mapping)
                else controller_meta.get("principle_posterior"),
                "confidence": principle_confidence,
                "selection_reason": selection_reason,
                "anomaly_flags": [
                    str(flag).strip() for flag in anomaly_flags if str(flag).strip()
                ],
                "controller_mode": controller_meta.get("controller_mode"),
                "enabled": controller_meta.get("enabled"),
            },
            "sampled_hypothesis_verification": {
                "rank": _safe_get(verification_entry, "rank"),
                "candidate_kg_id": _safe_get(verification_entry, "candidate_kg_id"),
                "statement": _safe_get(verification_entry, "statement"),
                "candidate_lane_mode": _safe_get(
                    verification_entry, "candidate_lane_mode"
                ),
                "candidate_lane_filtered": _safe_get(
                    verification_entry, "candidate_lane_filtered"
                ),
                "entity_hints_used": _safe_get(
                    verification_entry, "entity_hints_used", []
                ),
                "verification_error": _safe_get(
                    verification_entry, "verification_error"
                ),
                "gap_type": gap["gap_type"],
                "gap_specification": gap["gap_specification"],
                "gap_actionable": gap["gap_actionable"],
                "kg_verification": kg_verification,
            },
        }
        card = {
            "card_id": card_id,
            "title": f"{candidate_label} hypothesis candidate",
            "hypothesis": final_hypothesis,
            "raw_hypothesis": statement,
            "idea": idea,
            "mechanism": mechanism,
            "prediction": row_prediction or predicted_direction,
            "independent_variable": independent_variable,
            "dependent_variable": dependent_variable,
            "predicted_direction": predicted_direction,
            "testable_hypothesis": rewritten_hypothesis,
            "rewrite_status": rewrite_status,
            "quality_bucket": quality_bucket,
            "rejection_reason": rejection_reason,
            "semantic_fidelity_flags": fidelity_flags,
            "gap_type": gap["gap_type"],
            "gap_specification": gap["gap_specification"],
            "gap_actionable": gap["gap_actionable"],
            "kg_verification": kg_verification,
            "taste_axis": pattern["taste_axis"],
            "minimal_discriminating_test": final_minimal_test,
            "falsifier_hint": final_falsifier,
            "contradiction_probe": contradiction_signal,
            "topology_shift_probe": topology_signal,
            "active_principle": dict(active_principle)
            if isinstance(active_principle, Mapping)
            else None,
            "principle_confidence": principle_confidence,
            "principle_session_key": principle_session_key,
            "selection_reason": selection_reason,
            "anomaly_flags": [
                str(flag).strip() for flag in anomaly_flags if str(flag).strip()
            ],
            "provenance": provenance,
        }
        _attach_claim_memory_fields(
            card,
            provenance=provenance,
            claim_memory_context=claim_memory_context,
            claim_memory_profile=claim_memory_profile,
        )
        novelty_signal, mem_priority, mem_reason = _score_novelty_from_memory(
            final_hypothesis, memory_store
        )
        card["novelty_signal"] = novelty_signal
        if not card.get("claim_memory_priority") or card.get("claim_memory_priority") == "none":
            card["claim_memory_priority"] = mem_priority
        if not card.get("claim_memory_reason"):
            card["claim_memory_reason"] = mem_reason
        cards.append(card)

    _priority_order = {"conflict_resolution": 0, "unknown": 1, "low": 2, "none": 3}
    cards.sort(
        key=lambda c: _priority_order.get(
            c.get("claim_memory_priority", "none"), 3
        )
    )
    return _rerank_candidate_cards(cards)


def synthesize_candidate_cards_payload(
    *,
    query: str,
    top_n: int = 5,
    source_workflow: str = "workflow_hypothesis_candidate_cards",
    frontier_mode: str = "off",
    resolved_seed_kg_ids: list[str] | None = None,
    leverage_result: Mapping[str, Any] | None = None,
    principle_state_init_result: Mapping[str, Any] | None = None,
    ood_result: Mapping[str, Any] | None = None,
    verify_result: Mapping[str, Any] | None = None,
    contradiction_result: Mapping[str, Any] | None = None,
    topology_result: Mapping[str, Any] | None = None,
    principle_state_update_result: Mapping[str, Any] | None = None,
    wow_candidate_cards: list[dict[str, Any]] | None = None,
    wow_summary: Mapping[str, Any] | None = None,
    wow_warnings: list[str] | None = None,
) -> dict[str, Any]:
    synthetic_workflow = {
        "workflow": source_workflow,
        "steps": {
            "leverage": {
                "data": {
                    "result": dict(leverage_result or {}),
                    "resolved_seed_kg_ids": list(resolved_seed_kg_ids or []),
                }
            },
            "principle_state_init": {
                "data": {"result": dict(principle_state_init_result or {})}
            },
            "ood_sampling": {"data": {"result": dict(ood_result or {})}},
            "verify_sampled_hypotheses": {
                "data": {"result": dict(verify_result or {})}
            },
            "contradiction_scan": {
                "data": {"result": dict(contradiction_result or {})}
            },
            "topology_shift_scan": {"data": {"result": dict(topology_result or {})}},
            "principle_state_update": {
                "data": {"result": dict(principle_state_update_result or {})}
            },
        },
    }
    workflow_cards = build_candidate_cards_from_workflow_result(
        synthetic_workflow,
        query=query,
        top_n=top_n,
    )
    frontier_cards: list[dict[str, Any]] = []
    if str(frontier_mode or "").strip().lower() == "frontier":
        frontier_cards = rewrite_candidate_cards(
            list(wow_candidate_cards or []),
            query=query,
        )
        for card in frontier_cards:
            provenance = card.get("provenance")
            if isinstance(provenance, Mapping):
                card["provenance"] = {
                    **dict(provenance),
                    "frontier_mode": "frontier",
                }
        frontier_cards = _rerank_candidate_cards(frontier_cards)
    candidate_cards = _merge_candidate_cards(
        workflow_cards=workflow_cards,
        frontier_cards=frontier_cards,
        top_n=top_n,
    )
    summary = _summarize_candidate_cards(candidate_cards)
    summary["frontier_mode"] = str(frontier_mode or "off").strip().lower() or "off"
    summary["n_workflow_cards"] = len(workflow_cards)
    summary["n_frontier_cards"] = len(frontier_cards)
    if isinstance(wow_summary, Mapping):
        summary["frontier_summary"] = dict(wow_summary)
    novelty_calibration = generate_novelty_calibration_questions(
        build_novelty_calibration_context(
            query=query,
            candidate_cards=candidate_cards,
            summary=summary,
        )
    )
    return {
        "ok": True,
        "mode": "hypothesis_candidate_cards",
        "candidate_cards": candidate_cards,
        "summary": summary,
        "novelty_calibration_questions": novelty_calibration[
            "novelty_calibration_questions"
        ],
        "novelty_calibration_meta": novelty_calibration["novelty_calibration_meta"],
        "kind": "candidate_cards",
        "payload": {"items": candidate_cards},
        "warnings": list(wow_warnings or []),
    }


def find_candidate_cards_payload(obj: Any) -> list[dict[str, Any]]:
    """Best-effort recursive extraction for candidate card payloads."""

    out: list[dict[str, Any]] = []

    def _walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("kind") == "candidate_cards":
                payload = value.get("payload", {})
                items = payload.get("items", []) if isinstance(payload, Mapping) else []
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, Mapping):
                            out.append(dict(item))
            cards = value.get("candidate_cards")
            if isinstance(cards, list):
                for card in cards:
                    if isinstance(card, Mapping):
                        out.append(dict(card))
            for nested in value.values():
                _walk(nested)
            return
        if isinstance(value, list):
            for nested in value:
                _walk(nested)

    _walk(obj)
    return out


def find_novelty_calibration_payload(obj: Any) -> dict[str, Any] | None:
    """Return first nested novelty-calibration payload, if present."""

    if isinstance(obj, Mapping):
        questions = obj.get("novelty_calibration_questions")
        meta = obj.get("novelty_calibration_meta")
        if isinstance(questions, list) and isinstance(meta, Mapping):
            return {
                "novelty_calibration_questions": [
                    dict(item) for item in questions if isinstance(item, Mapping)
                ],
                "novelty_calibration_meta": dict(meta),
            }
        for nested in obj.values():
            found = find_novelty_calibration_payload(nested)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for nested in obj:
            found = find_novelty_calibration_payload(nested)
            if found is not None:
                return found
    return None


def find_workflow_result(obj: Any) -> Mapping[str, Any] | None:
    """Return first nested workflow result dict with workflow+steps keys."""

    if isinstance(obj, Mapping):
        if (
            "workflow" in obj
            and "steps" in obj
            and isinstance(obj.get("steps"), Mapping)
        ):
            return obj
        for nested in obj.values():
            found = find_workflow_result(nested)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for nested in obj:
            found = find_workflow_result(nested)
            if found is not None:
                return found
    return None
