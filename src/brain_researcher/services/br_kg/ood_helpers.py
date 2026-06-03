"""OOD / hypothesis-grounding helpers for the KG query service.

Carved out of ``br_kg/query_service.py`` (decomposition slice 5). Holds the
out-of-distribution label/token utilities, traversal-seed selection, and
hypothesis-grounding scoring helpers used by ``sample_ood_hypothesis`` /
``synthesize_wow_candidate_cards`` (which stay in query_service as the public
orchestrators).

``query_service`` re-exports these names so existing ``query_service.<name>``
references keep resolving. The shared qs helpers (``_safe_float``,
``_tokenize_query``, ``_canonical_ood_node_type``, ``_infer_ood_hint_node_type``,
``_rank_ood_verification_partner``, ``_coalesce_node_label``,
``_tokenize_ood_label``) and the shared ``_HYPOTHESIS_GROUNDING_PRIORITY_*``
constants stay in ``query_service`` and are imported lazily inside the consumers,
avoiding an import cycle (verified both import orders). ``KGNodeSummary`` is a
type-hint-only dependency (``TYPE_CHECKING``).
"""

from __future__ import annotations

import re
import time
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brain_researcher.services.br_kg.query_service import KGNodeSummary


def _select_ood_verification_support_seed(
    *,
    touched_seeds: Sequence[str] | None,
    fallback_seeds: Sequence[str] | None,
    seed_types: Mapping[str, Any] | None,
    seed_labels: Mapping[str, Any] | None,
    candidate_type: str,
    exclude_ids: Collection[str] | None = None,
) -> str | None:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _canonical_ood_node_type,
        _infer_ood_hint_node_type,
        _rank_ood_verification_partner,
    )

    excluded = {
        str(value or "").strip()
        for value in (exclude_ids or [])
        if str(value or "").strip()
    }
    canonical_candidate_type = _canonical_ood_node_type(candidate_type)
    ranked: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    typed_map = seed_types or {}
    label_map = seed_labels or {}

    def _consider(seed_id: str, source_rank: int, ordinal: int) -> None:
        normalized = str(seed_id or "").strip()
        if not normalized or normalized in seen or normalized in excluded:
            return
        seen.add(normalized)
        node_type = _infer_ood_hint_node_type(
            normalized,
            typed_map.get(normalized),
        )
        has_label = bool(str(label_map.get(normalized) or "").strip())
        rank = _rank_ood_verification_partner(
            value=normalized,
            node_type=node_type,
            candidate_type=canonical_candidate_type,
            has_label=has_label,
        )
        ranked.append((rank, source_rank, ordinal, normalized))

    for ordinal, seed_id in enumerate(touched_seeds or []):
        _consider(seed_id, 0, ordinal)
    for ordinal, seed_id in enumerate(fallback_seeds or []):
        _consider(seed_id, 1, ordinal)

    if not ranked:
        return None
    ranked.sort()
    return ranked[0][3]


_HYPOTHESIS_PRIORITY1_SIMILARITY_FLOOR = 0.70


def _hypothesis_query_tokens(search_terms: Sequence[str]) -> set[str]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _tokenize_query

    tokens: set[str] = set()
    for term in search_terms:
        for token in _tokenize_query(term):
            tokens.add(token)
    return tokens


def _hypothesis_entity_overlap_count(
    entity: KGNodeSummary,
    *,
    query_tokens: set[str],
) -> int:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _coalesce_node_label,
        _tokenize_ood_label,
    )

    if not query_tokens:
        return 0
    label = _coalesce_node_label(
        entity.label,
        (entity.properties or {}).get("name") if entity.properties else None,
        (entity.properties or {}).get("title") if entity.properties else None,
        entity.kg_id,
    )
    label_tokens = set(_tokenize_ood_label(label))
    return len(label_tokens.intersection(query_tokens))


def _hypothesis_entity_type_priority(node_type: str | None) -> float:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _canonical_ood_node_type

    canonical = _canonical_ood_node_type(node_type)
    return {
        "BrainRegion": 5.0,
        "Task": 4.9,
        "TaskFamily": 4.7,
        "DiseaseTrait": 4.65,
        "Concept": 4.6,
        "Modality": 4.3,
        "Gene": 4.15,
        "Dataset": 3.8,
        "RiskLocus": 3.7,
        "Method": 3.5,
        "Tool": 3.0,
        "Atlas": 2.6,
        "Publication": 1.0,
        "Paper": 1.0,
        "Study": 1.0,
        "Collection": 0.8,
        "Term": 0.4,
        "Coordinate": 0.2,
    }.get(canonical, 1.5)


def _hypothesis_grounding_priority(entity: KGNodeSummary) -> int:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _HYPOTHESIS_GROUNDING_PRIORITY_1,
        _HYPOTHESIS_GROUNDING_PRIORITY_2,
        _HYPOTHESIS_GROUNDING_PRIORITY_3,
        _canonical_ood_node_type,
    )

    canonical = _canonical_ood_node_type(entity.node_type)
    kg_id = str(entity.kg_id or "").strip().lower()
    if canonical in _HYPOTHESIS_GROUNDING_PRIORITY_1:
        return 1
    if canonical in _HYPOTHESIS_GROUNDING_PRIORITY_2:
        return 2
    if canonical in _HYPOTHESIS_GROUNDING_PRIORITY_3 or kg_id.startswith(
        "ds:openneuro:"
    ):
        return 3
    return 2


def _hypothesis_grounding_similarity(entity: KGNodeSummary) -> float:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _safe_float

    return _safe_float(entity.score, 0.0)


def _hypothesis_grounding_sort_priority(entity: KGNodeSummary) -> int:
    priority = _hypothesis_grounding_priority(entity)
    if (
        priority == 1
        and _hypothesis_grounding_similarity(entity)
        < _HYPOTHESIS_PRIORITY1_SIMILARITY_FLOOR
    ):
        return 2
    return priority


def _select_traversal_seeds(
    seeds: Sequence[str],
    *,
    input_seed_ids: Sequence[str],
    seed_scores: dict[str, Any],
    seed_provenance: dict[str, list[str]],
    max_traversal_seeds: int,
) -> list[str]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _safe_float

    """Prefer direct semantic seeds while bounding repeated neighbor traversals."""

    input_seed_set = {str(seed or "").strip().lower() for seed in input_seed_ids}
    ranked: list[tuple[tuple[int, float, str], str]] = []
    for seed in seeds:
        seed_id = str(seed or "").strip()
        if not seed_id:
            continue
        provenance_entries = [
            str(item or "") for item in seed_provenance.get(seed_id) or []
        ]
        if any(
            entry.startswith("search_expanded_from:") for entry in provenance_entries
        ):
            continue
        priority = 2
        if seed_id.lower() in input_seed_set:
            priority = 0
        elif any(entry == "direct" for entry in provenance_entries):
            priority = 1
        ranked.append(
            (
                (
                    priority,
                    -_safe_float(seed_scores.get(seed_id), 0.0),
                    seed_id,
                ),
                seed_id,
            )
        )

    ordered = [seed_id for _, seed_id in sorted(ranked)]
    if max_traversal_seeds <= 0:
        return ordered
    return ordered[:max_traversal_seeds]


def _ood_focus_terms(label: str, *, limit: int = 3) -> list[str]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _tokenize_ood_label

    tokens = _tokenize_ood_label(label)
    if not tokens:
        return []
    ranked = sorted(set(tokens), key=lambda token: (-len(token), token))
    return ranked[:limit]


def _ood_compact_label(label: str, *, max_words: int = 8) -> str:
    text = re.sub(r"\s+", " ", str(label or "").strip())
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "..."


_OOD_DUPLICATE_LABEL_TOKENS = {
    "candidate",
    "candidates",
    "task",
    "tasks",
    "test",
    "tests",
    "scale",
    "scales",
    "battery",
    "inventory",
    "questionnaire",
    "questionnaires",
    "measure",
    "measures",
    "assessment",
    "assessments",
}


def _ood_candidate_family_tokens(label: str) -> set[str]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _tokenize_ood_label

    return {
        token
        for token in _tokenize_ood_label(label)
        if token not in _OOD_DUPLICATE_LABEL_TOKENS
    }


def _ood_labels_are_near_duplicates(label_a: str, label_b: str) -> bool:
    compact_a = _ood_compact_label(label_a, max_words=12).lower()
    compact_b = _ood_compact_label(label_b, max_words=12).lower()
    if compact_a and compact_b and compact_a == compact_b:
        return True
    if compact_a and compact_b and (compact_a in compact_b or compact_b in compact_a):
        return True

    tokens_a = _ood_candidate_family_tokens(label_a)
    tokens_b = _ood_candidate_family_tokens(label_b)
    if not tokens_a or not tokens_b:
        return False

    shared = tokens_a.intersection(tokens_b)
    if not shared:
        return False
    overlap = float(len(shared)) / float(max(1, min(len(tokens_a), len(tokens_b))))
    if overlap >= 0.75:
        return True
    return len(shared) >= 4 and min(len(tokens_a), len(tokens_b)) >= 4


_OOD_WEAK_VARIANT_TOKENS = frozenset(
    {
        "activation",
        "analysis",
        "contrast",
        "decoding",
        "effect",
        "fmri",
        "paradigm",
        "real",
        "response",
        "signal",
        "study",
        "test",
        "time",
    }
)


def _ood_normalize_clause(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).rstrip(" .")


def _ood_family_overlap_stats(
    anchor_label: str,
    candidate_label: str,
) -> tuple[set[str], set[str], set[str], float]:
    anchor_tokens = _ood_candidate_family_tokens(anchor_label)
    candidate_tokens = _ood_candidate_family_tokens(candidate_label)
    if not anchor_tokens or not candidate_tokens:
        return anchor_tokens, candidate_tokens, set(), 0.0
    shared = anchor_tokens.intersection(candidate_tokens)
    overlap = float(len(shared)) / float(
        max(1, min(len(anchor_tokens), len(candidate_tokens)))
    )
    return anchor_tokens, candidate_tokens, shared, overlap


def _ood_distinctive_candidate_tokens(
    anchor_label: str,
    candidate_label: str,
) -> set[str]:
    anchor_tokens, candidate_tokens, _, _ = _ood_family_overlap_stats(
        anchor_label,
        candidate_label,
    )
    return {
        token
        for token in candidate_tokens.difference(anchor_tokens)
        if token not in _OOD_WEAK_VARIANT_TOKENS
    }


def _ood_budget_exhausted(deadline_monotonic: float | None) -> bool:
    if deadline_monotonic is None:
        return False
    return time.monotonic() >= deadline_monotonic
