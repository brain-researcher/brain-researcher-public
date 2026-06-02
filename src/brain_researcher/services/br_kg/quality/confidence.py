"""Confidence scoring utilities for Neo4j relationships."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_CONFIDENCE_VERSION = "conf_v1_k10"
DEFAULT_K = 10

METHOD_CONF = {
    "exact_id": 1.00,
    "curated_manual": 0.95,
    "rule_high_precision": 0.90,
    "string_match": 0.75,
    "fuzzy_match": 0.65,
    "embedding_match": 0.60,
    "llm_extracted": 0.45,
}

SOURCE_CONF = {
    "official_spec": 0.95,
    "major_ontology": 0.95,
    "peer_reviewed": 0.90,
    "aggregator_db": 0.80,
    "scraped_web": 0.65,
}


def support_keys(evidence: Dict[str, Any]) -> List[str]:
    """Return de-dup keys for a single evidence item (pmid > doi > dataset)."""
    pmid = evidence.get("pmid") or evidence.get("PMID")
    if pmid:
        return [f"pmid:{pmid}"]

    doi = evidence.get("doi") or evidence.get("DOI")
    if doi:
        return [f"doi:{str(doi).strip().lower()}"]

    dataset_key = evidence.get("dataset_key") or evidence.get("dataset_id")
    if dataset_key:
        return [f"dataset:{dataset_key}"]

    source = evidence.get("source") or evidence.get("prov_source") or "unknown"
    item_id = evidence.get("source_item_id") or evidence.get("id") or "unknown"
    return [f"src:{source}|id:{item_id}"]


def compute_support_counts(evidence_items: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    raw = 0
    unique_keys: set[str] = set()
    for ev in evidence_items:
        raw += 1
        for key in support_keys(ev):
            unique_keys.add(key)
    return raw, len(unique_keys)


def compute_diversity(evidence_items: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    sources: set[str] = set()
    types: set[str] = set()
    for ev in evidence_items:
        src = (
            ev.get("source")
            or ev.get("prov_source")
            or ev.get("provenance", {}).get("source")
        )
        if src:
            sources.add(str(src))
        etype = ev.get("evidence_type") or ev.get("type")
        if etype:
            types.add(str(etype))
    return len(sources), len(types)


def compute_prov_base_conf(
    prov_source: Optional[str],
    prov_method: Optional[str],
    *,
    method_conf: Optional[Dict[str, float]] = None,
    source_conf: Optional[Dict[str, float]] = None,
) -> float:
    method_conf = method_conf or METHOD_CONF
    source_conf = source_conf or SOURCE_CONF
    method_score = method_conf.get(str(prov_method), 0.7)
    source_score = source_conf.get(str(prov_source), 0.7)
    return max(0.0, min(1.0, method_score * source_score))


def compute_support_factor(support_unique: int, k: int = DEFAULT_K) -> float:
    if support_unique <= 0:
        return 0.0
    return 1.0 - math.exp(-float(support_unique) / float(k))


def compute_diversity_factor(
    source_diversity: int, evidence_type_diversity: int
) -> float:
    factor = 0.6 + 0.2 * float(source_diversity) + 0.2 * float(evidence_type_diversity)
    return max(0.0, min(1.0, factor))


def compute_confidence(
    *,
    support_unique: int,
    source_diversity: int,
    evidence_type_diversity: int,
    prov_base_conf: float,
    match_score: Optional[float] = None,
    k: int = DEFAULT_K,
) -> Tuple[float, Dict[str, float]]:
    support_factor = compute_support_factor(support_unique, k=k)
    diversity_factor = compute_diversity_factor(
        source_diversity, evidence_type_diversity
    )
    base = prov_base_conf
    if match_score is not None:
        base *= float(match_score)
    confidence = max(0.0, min(1.0, base * support_factor * diversity_factor))
    components = {
        "support_factor": support_factor,
        "diversity_factor": diversity_factor,
        "prov_base_conf": prov_base_conf,
        "match_score": float(match_score) if match_score is not None else 1.0,
    }
    return confidence, components


def compute_confidence_from_props(
    rel_props: Dict[str, Any],
    *,
    k: int = DEFAULT_K,
    confidence_version: str = DEFAULT_CONFIDENCE_VERSION,
) -> Optional[Dict[str, Any]]:
    evidence_items = rel_props.get("evidence") or rel_props.get("supports") or []
    support_raw = rel_props.get("support_count_raw")
    support_unique = rel_props.get("support_count_unique")

    if support_raw is None or support_unique is None:
        raw_count, unique_count = compute_support_counts(evidence_items)
        support_raw = support_raw if support_raw is not None else raw_count
        support_unique = support_unique if support_unique is not None else unique_count

    if support_raw == 0 and support_unique == 0:
        return None

    source_diversity = rel_props.get("source_diversity")
    evidence_type_diversity = rel_props.get("evidence_type_diversity")
    if source_diversity is None or evidence_type_diversity is None:
        source_diversity_calc, evidence_type_diversity_calc = compute_diversity(
            evidence_items
        )
        source_diversity = (
            source_diversity if source_diversity is not None else source_diversity_calc
        )
        evidence_type_diversity = (
            evidence_type_diversity
            if evidence_type_diversity is not None
            else evidence_type_diversity_calc
        )

    provenance = rel_props.get("provenance")
    provenance_map = provenance if isinstance(provenance, dict) else {}
    prov_source = rel_props.get("prov_source") or provenance_map.get("source")
    prov_method = rel_props.get("prov_method") or provenance_map.get("method")
    prov_base_conf = rel_props.get("prov_base_conf")
    if prov_base_conf is None:
        prov_base_conf = compute_prov_base_conf(prov_source, prov_method)

    match_score = rel_props.get("match_score")
    confidence, components = compute_confidence(
        support_unique=int(support_unique or 0),
        source_diversity=int(source_diversity or 0),
        evidence_type_diversity=int(evidence_type_diversity or 0),
        prov_base_conf=float(prov_base_conf),
        match_score=float(match_score) if match_score is not None else None,
        k=k,
    )

    return {
        "confidence": confidence,
        "confidence_version": confidence_version,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "support_count_raw": int(support_raw or 0),
        "support_count_unique": int(support_unique or 0),
        "source_diversity": int(source_diversity or 0),
        "evidence_type_diversity": int(evidence_type_diversity or 0),
        "prov_base_conf": float(prov_base_conf),
        "prov_source": prov_source,
        "prov_method": prov_method,
        "confidence_components": components,
    }


__all__ = [
    "compute_confidence",
    "compute_confidence_from_props",
    "compute_diversity",
    "compute_prov_base_conf",
    "compute_support_counts",
    "support_keys",
]
