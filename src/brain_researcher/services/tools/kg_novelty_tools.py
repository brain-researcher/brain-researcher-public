"""Wrapper tools for BR-KG novelty and invariance analyses."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.shared.r2toolsagent_principle_controller import (
    initialize_principle_state,
    update_principle_state,
)
from brain_researcher.services.tools.hypothesis_candidate_cards import (
    synthesize_candidate_cards_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _dedupe_ids(values: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


_ANCHOR_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "based",
    "for",
    "from",
    "human",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "using",
    "with",
}

_ANCHOR_TYPE_PRIORITY = {
    "Task": 5.0,
    "Concept": 4.5,
    "CognitiveConcept": 4.5,
    "OntologyConcept": 4.5,
    "TaskFamily": 4.0,
    "Dataset": 3.5,
    "Publication": 3.0,
    "Tool": 2.5,
    "Collection": 2.0,
}

_ANCHOR_TYPE_CAPS = {
    "Publication": 2,
    "Collection": 1,
    "ToolVersion": 0,
}

_ANCHOR_ALIAS_GROUPS = {
    "modality": {
        "fmri": ("fmri", "functional mri", "functional magnetic resonance imaging"),
        "bold": ("bold",),
    },
    "operation": {
        "decoding": ("decoding", "decode", "cross-decoding"),
        "reconstruction": ("reconstruction", "reconstruct"),
        "representation": ("representation", "representational"),
        "mvpa": ("mvpa", "multivoxel pattern analysis"),
    },
    "domain": {
        "image": ("image", "images"),
        "visual": ("visual", "vision"),
        "scene": ("scene", "scenes", "natural scenes"),
        "object": ("object", "objects"),
    },
}

_ANCHOR_SPECIAL_QUERIES = [
    {
        "requires": ("fmri", "decoding", "image"),
        "queries": (
            "visual image reconstruction",
            "natural scenes decoding",
            "mvpa decoding",
        ),
    },
    {
        "requires": ("fmri", "decoding", "visual"),
        "queries": (
            "visual image reconstruction",
            "natural scenes decoding",
        ),
    },
]


def _normalize_anchor_text(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("-based", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _tokenize_anchor_text(value: str | None) -> list[str]:
    tokens = _normalize_anchor_text(value).split()
    return [
        token
        for token in tokens
        if token and token not in _ANCHOR_QUERY_STOPWORDS and len(token) > 1
    ]


def _expand_anchor_alias_hits(query_text: str) -> dict[str, list[str]]:
    normalized = _normalize_anchor_text(query_text)
    hits: dict[str, list[str]] = {}
    for group, alias_map in _ANCHOR_ALIAS_GROUPS.items():
        group_hits: list[str] = []
        for canonical, aliases in alias_map.items():
            if any(alias in normalized for alias in aliases):
                group_hits.append(canonical)
        if group_hits:
            hits[group] = group_hits
    return hits


def _build_anchor_search_queries(query_text: str) -> list[str]:
    normalized = _normalize_anchor_text(query_text)
    if not normalized:
        return []

    queries: list[str] = [normalized]
    alias_hits = _expand_anchor_alias_hits(normalized)
    modalities = alias_hits.get("modality", [])
    operations = alias_hits.get("operation", [])
    domains = alias_hits.get("domain", [])

    for modality in modalities:
        for operation in operations:
            queries.append(f"{modality} {operation}")
    for domain in domains:
        for operation in operations:
            queries.append(f"{domain} {operation}")
    for modality in modalities:
        for domain in domains:
            for operation in operations:
                queries.append(f"{modality} {domain} {operation}")
    for spec in _ANCHOR_SPECIAL_QUERIES:
        required = spec["requires"]
        if all(req in modalities + operations + domains for req in required):
            queries.extend(spec["queries"])

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        candidate = re.sub(r"\s+", " ", str(query or "").strip())
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _node_attr(node: Any, key: str) -> Any:
    if hasattr(node, key):
        return getattr(node, key)
    if isinstance(node, dict):
        return node.get(key)
    return None


def _score_anchor_node(
    *,
    label: str,
    node_type: str,
    query_variants: Sequence[str],
    query_terms: Sequence[str],
    alias_hits: dict[str, list[str]],
) -> tuple[float, list[str]]:
    label_norm = _normalize_anchor_text(label)
    reasons: list[str] = []
    score = _ANCHOR_TYPE_PRIORITY.get(node_type, 1.0)

    matched_queries = [
        variant
        for variant in query_variants
        if variant and variant.lower() in label_norm
    ]
    if matched_queries:
        score += 4.0 + 0.75 * len(matched_queries)
        reasons.append(f"matched_queries={matched_queries[:3]}")

    overlapping_terms = [term for term in query_terms if term and term in label_norm]
    if overlapping_terms:
        score += 0.7 * len(overlapping_terms)
        reasons.append(f"overlap_terms={overlapping_terms[:5]}")

    for group, hits in alias_hits.items():
        matched = [hit for hit in hits if hit in label_norm]
        if matched:
            score += 1.1 * len(matched)
            reasons.append(f"{group}_hits={matched[:3]}")

    if node_type in {"Publication", "Collection"} and not matched_queries:
        score -= 1.0
    if node_type == "ToolVersion":
        score -= 3.0

    return score, reasons


def _resolve_seed_context(
    *,
    seed_kg_ids: Sequence[str] | None,
    query: str | None,
    search_limit: int = 8,
) -> tuple[list[str], list[dict[str, Any]]]:
    seeds = _dedupe_ids(seed_kg_ids)
    if seeds:
        bundle = [{"kg_id": seed, "source": "explicit_seed"} for seed in seeds]
        return seeds, bundle

    query_text = str(query or "").strip()
    if not query_text:
        return [], []

    query_variants = _build_anchor_search_queries(query_text)
    if not query_variants:
        query_variants = [_normalize_anchor_text(query_text)]
    query_terms = list(dict.fromkeys(_tokenize_anchor_text(" ".join(query_variants))))
    alias_hits = _expand_anchor_alias_hits(query_text)
    per_query_limit = max(3, min(search_limit, 6))

    ranked: dict[str, dict[str, Any]] = {}
    for variant in query_variants[:6]:
        try:
            nodes = query_service.search_nodes(variant, limit=per_query_limit)
        except TypeError:
            nodes = query_service.search_nodes(variant)
        for node in nodes or []:
            kg_id = str(_node_attr(node, "kg_id") or "").strip()
            if not kg_id:
                continue
            label = str(_node_attr(node, "label") or kg_id).strip()
            node_type = str(_node_attr(node, "node_type") or "").strip() or "Unknown"
            score, reasons = _score_anchor_node(
                label=label,
                node_type=node_type,
                query_variants=query_variants,
                query_terms=query_terms,
                alias_hits=alias_hits,
            )
            if score <= 0:
                continue
            dedupe_key = f"{node_type}:{_normalize_anchor_text(label) or kg_id.lower()}"
            bucket = ranked.setdefault(
                dedupe_key,
                {
                    "kg_id": kg_id,
                    "label": label,
                    "node_type": node_type,
                    "score": float(score),
                    "matched_queries": [],
                    "match_reasons": [],
                },
            )
            bucket["score"] = max(float(bucket["score"]), float(score))
            matched_queries = bucket["matched_queries"]
            if variant not in matched_queries:
                matched_queries.append(variant)
            match_reasons = bucket["match_reasons"]
            for reason in reasons:
                if reason not in match_reasons:
                    match_reasons.append(reason)

    ranked_rows = sorted(
        ranked.values(),
        key=lambda item: (-float(item["score"]), str(item["label"]).lower()),
    )
    bundle: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for item in ranked_rows:
        node_type = str(item.get("node_type") or "")
        cap = _ANCHOR_TYPE_CAPS.get(node_type)
        if cap is not None and type_counts.get(node_type, 0) >= cap:
            continue
        bundle.append(item)
        type_counts[node_type] = type_counts.get(node_type, 0) + 1
        if len(bundle) >= search_limit:
            break
    resolved = [str(item["kg_id"]) for item in bundle]
    return resolved, bundle


def _resolve_seed_kg_ids(
    *,
    seed_kg_ids: Sequence[str] | None,
    query: str | None,
    search_limit: int = 8,
) -> list[str]:
    resolved, _bundle = _resolve_seed_context(
        seed_kg_ids=seed_kg_ids,
        query=query,
        search_limit=search_limit,
    )
    return resolved


def _is_kg_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    indicators = (
        "network_blocked_by_policy",
        "unable to connect to neo4j",
        "failed to dns resolve address",
        "localhost:7687",
        "connection refused",
        "service unavailable",
        "neo4j",
    )
    return any(token in message for token in indicators)


def _pseudo_seed_id(query: str | None) -> str:
    normalized = str(query or "").strip().lower() or "unknown_query"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"query:{digest}"


_FALLBACK_CANDIDATE_LABELS = [
    "Class-specific latent bottleneck",
    "Subject-specific concept axis drift",
    "Decoder objective mismatch component",
    "Cross-subject alignment failure mode",
    "Semantic granularity underfit factor",
]


def _build_fallback_leverage_result(
    *,
    seed_kg_ids: list[str],
    limit: int,
    reason: str,
) -> dict[str, Any]:
    seeds = seed_kg_ids or ["query:fallback"]
    n = max(1, min(limit, len(_FALLBACK_CANDIDATE_LABELS)))
    items: list[dict[str, Any]] = []
    for idx in range(n):
        label = _FALLBACK_CANDIDATE_LABELS[idx]
        base = 0.78 - idx * 0.08
        items.append(
            {
                "kg_id": f"fallback:candidate_{idx + 1}",
                "label": label,
                "node_type": "FallbackCandidate",
                "candidate_type": "Concept",
                "seeds_touched": [seeds[0]],
                "relations": ["ASSOCIATED_WITH"],
                "quality_flags": ["type:Concept", "rel:ASSOCIATED_WITH"],
                "novelty_score": round(max(0.2, base), 6),
                "coherence_score": round(max(0.2, 0.68 - idx * 0.05), 6),
                "feasibility_score": round(max(0.2, 0.66 - idx * 0.04), 6),
                "bridge_score": round(max(0.2, 0.62 - idx * 0.06), 6),
                "diversity_score": round(max(0.2, 0.54 - idx * 0.05), 6),
                "leverage_score": round(max(0.2, base - 0.04), 6),
                "score_breakdown": {
                    "novelty_score": round(max(0.2, base), 6),
                    "coherence_score": round(max(0.2, 0.68 - idx * 0.05), 6),
                    "feasibility_score": round(max(0.2, 0.66 - idx * 0.04), 6),
                    "bridge_score": round(max(0.2, 0.62 - idx * 0.06), 6),
                    "diversity_score": round(max(0.2, 0.54 - idx * 0.05), 6),
                },
            }
        )
    return {
        "ok": True,
        "mode": "structural_leverage_fallback",
        "seed_kg_ids": seeds,
        "items": items,
        "summary": {"n_seeds": len(seeds), "n_candidates": len(items)},
        "warnings": [
            f"KG unavailable; returned fallback leverage candidates: {reason}"
        ],
    }


def _build_fallback_ood_result(
    *,
    seed_kg_ids: list[str],
    n_samples: int,
    reason: str,
) -> dict[str, Any]:
    seeds = seed_kg_ids or ["query:fallback"]
    n = max(1, min(n_samples, len(_FALLBACK_CANDIDATE_LABELS)))
    hypotheses: list[dict[str, Any]] = []
    for idx in range(n):
        label = _FALLBACK_CANDIDATE_LABELS[idx]
        hypotheses.append(
            {
                "rank": idx + 1,
                "seed_kg_id": seeds[0],
                "candidate_kg_id": f"fallback:candidate_{idx + 1}",
                "candidate_type": "Concept",
                "claim_type": "bridge",
                "statement": (
                    f"{seeds[0]} may depend on {label.lower()} as a latent bottleneck "
                    "that constrains out-of-distribution decoding transfer."
                ),
                "mechanism": (
                    f"{label} is treated as a structured latent factor rather than a raw graph neighbor."
                ),
                "prediction": (
                    f"Model variants that account for {label.lower()} should outperform matched baselines on held-out transfer."
                ),
                "minimal_test": (
                    f"Compare baseline decoding against a stratified analysis that explicitly models {label.lower()}."
                ),
                "falsifier": (
                    f"Reject this fallback candidate if {label.lower()}-aware modeling does not improve transfer performance."
                ),
                "rewrite_mode": "fallback",
                "relation_hint": "ASSOCIATED_WITH",
                "verification_status": "unverified",
                "verification_reason": "kg_fallback",
                "verification_evidence": {},
                "anchor_nodes": [
                    {"kg_id": seeds[0], "label": seeds[0]},
                    {
                        "kg_id": f"fallback:candidate_{idx + 1}",
                        "label": label,
                    },
                ],
                "quality_flags": ["fallback", "type:Concept", "rel:ASSOCIATED_WITH"],
                "novelty_score": round(max(0.15, 0.74 - idx * 0.07), 6),
                "coherence_score": round(max(0.15, 0.62 - idx * 0.05), 6),
                "feasibility_score": round(max(0.15, 0.60 - idx * 0.04), 6),
                "ood_score": round(max(0.15, 0.77 - idx * 0.06), 6),
                "score_breakdown": {
                    "novelty_score": round(max(0.15, 0.74 - idx * 0.07), 6),
                    "coherence_score": round(max(0.15, 0.62 - idx * 0.05), 6),
                    "feasibility_score": round(max(0.15, 0.60 - idx * 0.04), 6),
                },
            }
        )
    return {
        "ok": True,
        "mode": "ood_hypothesis_sampling_fallback",
        "seed_kg_ids": seeds,
        "hypotheses": hypotheses,
        "vetoed_candidates": [],
        "summary": {
            "n_requested": n_samples,
            "n_hypotheses": len(hypotheses),
            "n_returned": len(hypotheses),
            "n_quality_passed": len(hypotheses),
            "n_rejected_pre_synthesis": 0,
            "n_rejected_post_synthesis": 0,
            "n_rewrite_failed": 0,
            "n_vetoed": 0,
        },
        "warnings": [f"KG unavailable; returned fallback OOD hypotheses: {reason}"],
    }


def _build_fallback_contradiction_result(
    *,
    seed_kg_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "contradiction_motifs_fallback",
        "seed_kg_ids": seed_kg_ids,
        "motifs": [],
        "summary": {"n_input_evidence": 0, "n_motifs": 0},
        "warnings": [f"KG unavailable; contradiction motifs skipped: {reason}"],
    }


def _build_fallback_topology_result(
    *,
    seed_kg_ids: list[str],
    mode: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": f"topology_shift_{mode}_fallback",
        "seed_kg_ids": seed_kg_ids,
        "proposals": [],
        "applied_count": 0,
        "summary": {"n_scanned": 0, "n_proposals": 0},
        "warnings": [f"KG unavailable; topology-shift scan skipped: {reason}"],
    }


def _build_fallback_hypothesis_testing_result(
    *,
    seed_kg_ids: list[str],
    n_samples: int,
    reason: str,
) -> dict[str, Any]:
    sampled = _build_fallback_ood_result(
        seed_kg_ids=seed_kg_ids,
        n_samples=n_samples,
        reason=reason,
    )
    return {
        "ok": True,
        "mode": "hypothesis_testing_fallback",
        "seed_kg_ids": seed_kg_ids,
        "sampled_hypotheses": list(sampled.get("hypotheses") or []),
        "tested_hypotheses": [],
        "sampled_summary": dict(sampled.get("summary") or {}),
        "summary": {
            "n_input_seeds": len(seed_kg_ids),
            "n_sampled": len(sampled.get("hypotheses") or []),
            "n_returned": len(sampled.get("hypotheses") or []),
            "n_tested": 0,
            "n_verify_failed": 0,
            "n_supported": 0,
            "n_mixed": 0,
            "n_insufficient_evidence": 0,
            "n_conflicting": 0,
            "n_uncertain": 0,
        },
        "warnings": [f"KG unavailable; hypothesis testing skipped: {reason}"],
    }


def _build_fallback_verify_sampled_result(
    *,
    seed_kg_ids: list[str],
    sampled_hypotheses: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "sampled_hypothesis_verification_fallback",
        "seed_kg_ids": seed_kg_ids,
        "sampled_hypotheses": list(sampled_hypotheses),
        "tested_hypotheses": [],
        "summary": {
            "n_input_seeds": len(seed_kg_ids),
            "n_input_hypotheses": len(sampled_hypotheses),
            "n_tested": 0,
            "n_verify_failed": 0,
            "n_supported": 0,
            "n_mixed": 0,
            "n_insufficient_evidence": 0,
            "n_conflicting": 0,
            "n_uncertain": 0,
        },
        "warnings": [
            f"KG unavailable; sampled-hypothesis verification skipped: {reason}"
        ],
    }


def _validation_error(exc: Exception) -> ToolResult:
    return ToolResult(status="error", error=f"Invalid arguments: {exc}")


def _success_result(
    func_name: str,
    result: Any,
    seed_kg_ids: list[str],
    *,
    resolved_anchor_bundle: list[dict[str, Any]] | None = None,
) -> ToolResult:
    return ToolResult(
        status="success",
        data={
            "result": result,
            "resolved_seed_kg_ids": seed_kg_ids,
            "resolved_anchor_bundle": list(resolved_anchor_bundle or []),
        },
        metadata={"query_service_function": func_name},
    )


class FindStructuralLeverageArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task text query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter",
    )
    direction: str = Field(
        default="both",
        description="Neighbor traversal direction (in, out, both)",
    )
    limit: int = Field(default=20, ge=1, le=200, description="Maximum results")
    taste_mode: str = Field(
        default="novelty_first",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )


class DetectContradictionMotifsArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional hypothesis statement to audit for contradictory evidence",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional seed KG IDs used as entity hints",
    )
    evidence_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional pre-collected evidence rows",
    )
    max_evidence: int = Field(
        default=80,
        ge=1,
        le=500,
        description="Maximum evidence rows used in motif scan",
    )


class FindContradictionFrontiersArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task text query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter applied to seed neighborhood scans",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum frontiers")
    max_evidence: int = Field(
        default=80,
        ge=1,
        le=500,
        description="Maximum evidence rows used in contradiction discovery",
    )


class MineAssumptionCracksArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task text query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    contradiction_frontiers: dict[str, Any] | None = Field(
        default=None,
        description="Optional contradiction frontier payload from workflow context",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum cracks")


class FindAnalogyTransfersArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task text query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter applied to seed neighborhood scans",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum transfers")


class SynthesizeWowCandidateCardsArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task text query used to contextualize cards",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs",
    )
    contradiction_frontiers: dict[str, Any] | None = Field(
        default=None,
        description="Optional contradiction frontier payload from workflow context",
    )
    assumption_cracks: dict[str, Any] | None = Field(
        default=None,
        description="Optional assumption crack payload from workflow context",
    )
    analogy_transfers: dict[str, Any] | None = Field(
        default=None,
        description="Optional analogy transfer payload from workflow context",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum wow candidate cards",
    )


class SampleOODHypothesisArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter",
    )
    n_samples: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of OOD hypotheses to generate",
    )
    taste_mode: str = Field(
        default="novelty_first",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )
    controller_mode: str = Field(
        default="legacy",
        description="Controller mode: legacy | principle_v0",
    )
    leverage_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional precomputed leverage rows from workflow context",
    )
    leverage_context: dict[str, Any] | None = Field(
        default=None,
        description="Optional full leverage result used to preserve semantic seed context",
    )
    principle_state: dict[str, Any] | None = Field(
        default=None,
        description="Optional principle controller state from workflow context",
    )


class PrincipleStateInitArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Construct/task query used to key the principle session",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Resolved seed KG IDs for stable session keying",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter used by the workflow",
    )
    taste_mode: str = Field(
        default="novelty_first",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )
    controller_mode: str = Field(
        default="legacy",
        description="Controller mode: legacy | principle_v0",
    )
    leverage_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional leverage rows used to annotate selection events",
    )


class PrincipleStateUpdateArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Construct/task query used to key the principle session",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Resolved seed KG IDs for stable session keying",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter used by the workflow",
    )
    taste_mode: str = Field(
        default="novelty_first",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )
    controller_mode: str = Field(
        default="legacy",
        description="Controller mode: legacy | principle_v0",
    )
    principle_state: dict[str, Any] | None = Field(
        default=None,
        description="Optional controller state from principle_state_init",
    )
    ood_result: dict[str, Any] | None = Field(
        default=None,
        description="Optional OOD sampling result payload from workflow context",
    )
    contradiction_result: dict[str, Any] | None = Field(
        default=None,
        description="Optional contradiction scan result payload from workflow context",
    )
    topology_result: dict[str, Any] | None = Field(
        default=None,
        description="Optional topology shift result payload from workflow context",
    )


class DetectTopologyShiftsArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    mode: str = Field(
        default="proposal",
        description="proposal | detect (alias of proposal) | apply",
    )
    limit: int = Field(default=50, ge=1, le=500, description="Maximum edges to scan")
    taste_mode: str = Field(
        default="novelty_first",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )
    patch_id: str | None = Field(default=None, description="Optional patch id (apply)")
    update_reason: str | None = Field(
        default=None,
        description="Optional update reason (apply)",
    )
    now_iso: str | None = Field(default=None, description="Optional ISO timestamp")


class SampleAndVerifyHypothesesArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional construct/task query used to resolve seed KG nodes",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit seed KG IDs; takes precedence over query",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional relation filter for the sampling stage",
    )
    n_samples: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of hypotheses to sample before KG verification",
    )
    verify_top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Optional cap on how many sampled hypotheses to verify",
    )
    taste_mode: str = Field(
        default="balanced",
        description="Taste scoring mode: novelty_first | balanced | evidence_first",
    )
    strictness: str = Field(
        default="high_recall",
        description="Verification strictness: high_recall | conservative",
    )
    candidate_lane_mode: str = Field(
        default="broad",
        description="Candidate-lane evidence mode: broad | strict",
    )
    use_external_literature: bool = Field(
        default=False,
        description="Whether to augment verification with external literature search",
    )
    external_literature_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum external literature documents folded into each verification",
    )
    external_literature_recency_days: int = Field(
        default=365,
        ge=0,
        le=3650,
        description="Recency window for external literature search",
    )
    external_literature_exclude_domains: list[str] | None = Field(
        default=None,
        description="Optional domains to exclude from external literature search",
    )
    allowed_node_types: list[str] | None = Field(
        default=None,
        description="Optional allowed KG node types for verification",
    )
    max_evidence: int = Field(
        default=60,
        ge=1,
        le=500,
        description="Maximum evidence rows used in verification",
    )
    max_paths: int = Field(
        default=60,
        ge=1,
        le=500,
        description="Maximum paths returned by verification",
    )
    min_evidence_score: float | None = Field(
        default=None,
        description="Optional lower bound on evidence score",
    )
    include_subgraph: bool = Field(
        default=False,
        description="Whether to include verification subgraph payloads",
    )
    include_path_details: bool = Field(
        default=False,
        description="Whether to include detailed path payloads",
    )
    confidence_scoring_version: str = Field(
        default="v2",
        description="Confidence scoring version passed to KG verification",
    )


class VerifySampledHypothesesArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional originating free-text query used for external literature search",
    )
    sampled_hypotheses: list[dict[str, Any]] = Field(
        description="Precomputed sampled hypotheses to verify against KG evidence",
    )
    seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Optional seed KG IDs used to contextualize verification output",
    )
    verify_top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Optional cap on how many sampled hypotheses to verify",
    )
    strictness: str = Field(
        default="high_recall",
        description="Verification strictness: high_recall | conservative",
    )
    candidate_lane_mode: str = Field(
        default="broad",
        description="Candidate-lane evidence mode: broad | strict",
    )
    use_external_literature: bool = Field(
        default=False,
        description="Whether to augment verification with external literature search",
    )
    external_literature_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum external literature documents folded into each verification",
    )
    external_literature_recency_days: int = Field(
        default=365,
        ge=0,
        le=3650,
        description="Recency window for external literature search",
    )
    external_literature_exclude_domains: list[str] | None = Field(
        default=None,
        description="Optional domains to exclude from external literature search",
    )
    allowed_node_types: list[str] | None = Field(
        default=None,
        description="Optional allowed KG node types for verification",
    )
    max_evidence: int = Field(
        default=60,
        ge=1,
        le=500,
        description="Maximum evidence rows used in verification",
    )
    max_paths: int = Field(
        default=60,
        ge=1,
        le=500,
        description="Maximum paths returned by verification",
    )
    min_evidence_score: float | None = Field(
        default=None,
        description="Optional lower bound on evidence score",
    )
    include_subgraph: bool = Field(
        default=False,
        description="Whether to include verification subgraph payloads",
    )
    include_path_details: bool = Field(
        default=False,
        description="Whether to include detailed path payloads",
    )
    confidence_scoring_version: str = Field(
        default="v2",
        description="Confidence scoring version passed to KG verification",
    )


class SynthesizeHypothesisCandidateCardsArgs(BaseModel):
    query: str = Field(
        description="Original free-text query used to drive candidate generation",
    )
    frontier_mode: str = Field(
        default="off",
        description="Candidate merge mode: off | frontier",
    )
    top_n: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of cards to synthesize",
    )
    source_workflow: str = Field(
        default="workflow_hypothesis_candidate_cards",
        description="Workflow id used in provenance",
    )
    resolved_seed_kg_ids: list[str] | None = Field(
        default=None,
        description="Resolved seed KG IDs from the leverage stage",
    )
    leverage_result: dict[str, Any] | None = Field(
        default=None,
        description="Leverage-stage result payload",
    )
    principle_state_init_result: dict[str, Any] | None = Field(
        default=None,
        description="Initial principle-controller state payload",
    )
    ood_result: dict[str, Any] | None = Field(
        default=None,
        description="OOD sampling result payload",
    )
    verify_result: dict[str, Any] | None = Field(
        default=None,
        description="Sampled-hypothesis verification result payload",
    )
    contradiction_result: dict[str, Any] | None = Field(
        default=None,
        description="Contradiction scan result payload",
    )
    topology_result: dict[str, Any] | None = Field(
        default=None,
        description="Topology-shift scan result payload",
    )
    principle_state_update_result: dict[str, Any] | None = Field(
        default=None,
        description="Updated principle-controller state payload",
    )
    contradiction_frontiers_result: dict[str, Any] | None = Field(
        default=None,
        description="Frontier contradiction result payload for frontier_mode",
    )
    assumption_cracks_result: dict[str, Any] | None = Field(
        default=None,
        description="Assumption-crack result payload for frontier_mode",
    )
    analogy_transfers_result: dict[str, Any] | None = Field(
        default=None,
        description="Analogy-transfer result payload for frontier_mode",
    )


class FindStructuralLeverageTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.find_structural_leverage"

    def get_tool_description(self) -> str:
        return "Find high-leverage nodes/edges that could shift construct-level interpretations."

    def get_args_schema(self):
        return FindStructuralLeverageArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = FindStructuralLeverageArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            if not seeds:
                query_text = str(args.query or "").strip()
                if query_text:
                    seeds = [_pseudo_seed_id(query_text)]
                else:
                    return ToolResult(
                        status="error",
                        error="Provide seed_kg_ids or a query that resolves to KG nodes",
                    )
            result = query_service.find_structural_leverage(
                seed_kg_ids=seeds,
                relation_types=args.relation_types,
                direction=args.direction,
                limit=args.limit,
                taste={"mode": args.taste_mode},
            )
            return _success_result(
                "find_structural_leverage",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc):
                fallback_seeds = seeds or [_pseudo_seed_id(args.query)]
                fallback = _build_fallback_leverage_result(
                    seed_kg_ids=fallback_seeds,
                    limit=args.limit,
                    reason=str(exc),
                )
                return _success_result(
                    "find_structural_leverage_fallback",
                    fallback,
                    fallback_seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class DetectContradictionMotifsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.detect_contradiction_motifs"

    def get_tool_description(self) -> str:
        return "Detect repeated contradiction motifs around a construct/task query."

    def get_args_schema(self):
        return DetectContradictionMotifsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = DetectContradictionMotifsArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            if not seeds and not (args.query or args.evidence_items):
                return ToolResult(
                    status="error",
                    error="Provide query, seed_kg_ids, or evidence_items",
                )
            result = query_service.detect_contradiction_motifs(
                hypothesis=args.query,
                seed_kg_ids=seeds or None,
                evidence_items=args.evidence_items,
                max_evidence=args.max_evidence,
            )
            return _success_result(
                "detect_contradiction_motifs",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc):
                fallback = _build_fallback_contradiction_result(
                    seed_kg_ids=seeds,
                    reason=str(exc),
                )
                return _success_result(
                    "detect_contradiction_motifs_fallback",
                    fallback,
                    seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class FindContradictionFrontiersTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.find_contradiction_frontiers"

    def get_tool_description(self) -> str:
        return "Find contradiction-heavy frontiers around a topic or seed neighborhood."

    def get_args_schema(self):
        return FindContradictionFrontiersArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = FindContradictionFrontiersArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            result = query_service.find_contradiction_frontiers(
                query=args.query,
                seed_kg_ids=seeds or None,
                relation_types=args.relation_types,
                limit=args.limit,
                max_evidence=args.max_evidence,
            )
            return _success_result(
                "find_contradiction_frontiers",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class MineAssumptionCracksTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.mine_assumption_cracks"

    def get_tool_description(self) -> str:
        return "Mine challenged default assumptions from contradiction-heavy frontiers."

    def get_args_schema(self):
        return MineAssumptionCracksArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = MineAssumptionCracksArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            result = query_service.mine_assumption_cracks(
                query=args.query,
                seed_kg_ids=seeds or None,
                contradiction_frontiers=args.contradiction_frontiers,
                limit=args.limit,
            )
            return _success_result(
                "mine_assumption_cracks",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class FindAnalogyTransfersTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.find_analogy_transfers"

    def get_tool_description(self) -> str:
        return "Find method-family transfers that are absent in the local target neighborhood."

    def get_args_schema(self):
        return FindAnalogyTransfersArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = FindAnalogyTransfersArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            result = query_service.find_analogy_transfers(
                query=args.query,
                seed_kg_ids=seeds or None,
                relation_types=args.relation_types,
                limit=args.limit,
            )
            return _success_result(
                "find_analogy_transfers",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class SynthesizeWowCandidateCardsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.synthesize_wow_candidate_cards"

    def get_tool_description(self) -> str:
        return "Synthesize wow-style candidate cards from contradictions, assumptions, and transfers."

    def get_args_schema(self):
        return SynthesizeWowCandidateCardsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = SynthesizeWowCandidateCardsArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            result = query_service.synthesize_wow_candidate_cards(
                query=args.query,
                seed_kg_ids=seeds or None,
                contradiction_frontiers=args.contradiction_frontiers,
                assumption_cracks=args.assumption_cracks,
                analogy_transfers=args.analogy_transfers,
                limit=args.limit,
            )
            return _success_result(
                "synthesize_wow_candidate_cards",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class PrincipleStateInitTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.principle_state_init"

    def get_tool_description(self) -> str:
        return "Initialize or restore thin principle-controller state for hypothesis reranking."

    def get_args_schema(self):
        return PrincipleStateInitArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            args = PrincipleStateInitArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        seeds, anchor_bundle = _resolve_seed_context(
            seed_kg_ids=args.seed_kg_ids,
            query=args.query,
        )
        query_text = str(args.query or "").strip()
        if not seeds and query_text:
            seeds = [_pseudo_seed_id(query_text)]
        result = initialize_principle_state(
            query=query_text,
            seed_kg_ids=seeds,
            relation_types=args.relation_types,
            taste_mode=args.taste_mode,
            controller_mode=args.controller_mode,
            leverage_items=args.leverage_items,
        )
        return _success_result(
            "principle_state_init",
            result,
            seeds,
            resolved_anchor_bundle=anchor_bundle,
        )


class SampleOODHypothesisTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.sample_ood_hypothesis"

    def get_tool_description(self) -> str:
        return "Sample out-of-distribution hypotheses from KG structure and evidence context."

    def get_args_schema(self):
        return SampleOODHypothesisArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = SampleOODHypothesisArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            if not seeds:
                query_text = str(args.query or "").strip()
                if query_text:
                    seeds = [_pseudo_seed_id(query_text)]
                else:
                    return ToolResult(
                        status="error",
                        error="Provide seed_kg_ids or a query that resolves to KG nodes",
                    )
            result = query_service.sample_ood_hypothesis(
                seed_kg_ids=seeds,
                relation_types=args.relation_types,
                limit=args.n_samples,
                taste={"mode": args.taste_mode},
                leverage_items=args.leverage_items,
                leverage_context=args.leverage_context,
                principle_state=args.principle_state,
            )
            return _success_result(
                "sample_ood_hypothesis",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc):
                fallback_seeds = seeds or [_pseudo_seed_id(args.query)]
                fallback = _build_fallback_ood_result(
                    seed_kg_ids=fallback_seeds,
                    n_samples=args.n_samples,
                    reason=str(exc),
                )
                return _success_result(
                    "sample_ood_hypothesis_fallback",
                    fallback,
                    fallback_seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class DetectTopologyShiftsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.detect_topology_shifts"

    def get_tool_description(self) -> str:
        return "Detect topology-level shifts for a construct/task across conditions."

    def get_args_schema(self):
        return DetectTopologyShiftsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        mode = "proposal"
        try:
            args = DetectTopologyShiftsArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            mode = str(args.mode or "proposal").strip().lower()
            if mode == "detect":
                mode = "proposal"
            if mode not in {"proposal", "apply"}:
                return ToolResult(
                    status="error",
                    error="mode must be one of: proposal, detect, apply",
                )
            result = query_service.detect_topology_shifts(
                seed_kg_ids=seeds or None,
                limit=args.limit,
                taste={"mode": args.taste_mode},
                mode=mode,
                patch_id=args.patch_id,
                update_reason=args.update_reason,
                now_iso=args.now_iso,
            )
            return _success_result(
                "detect_topology_shifts",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc) and mode != "apply":
                fallback = _build_fallback_topology_result(
                    seed_kg_ids=seeds,
                    mode=mode,
                    reason=str(exc),
                )
                return _success_result(
                    "detect_topology_shifts_fallback",
                    fallback,
                    seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class PrincipleStateUpdateTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.principle_state_update"

    def get_tool_description(self) -> str:
        return (
            "Update thin principle-controller state using OOD output and anomaly scans."
        )

    def get_args_schema(self):
        return PrincipleStateUpdateArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            args = PrincipleStateUpdateArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        seeds, anchor_bundle = _resolve_seed_context(
            seed_kg_ids=args.seed_kg_ids,
            query=args.query,
        )
        query_text = str(args.query or "").strip()
        if not seeds and query_text:
            seeds = [_pseudo_seed_id(query_text)]
        result = update_principle_state(
            query=query_text,
            seed_kg_ids=seeds,
            relation_types=args.relation_types,
            taste_mode=args.taste_mode,
            controller_mode=args.controller_mode,
            principle_state=args.principle_state,
            ood_result=args.ood_result,
            contradiction_result=args.contradiction_result,
            topology_result=args.topology_result,
        )
        return _success_result(
            "principle_state_update",
            result,
            seeds,
            resolved_anchor_bundle=anchor_bundle,
        )


class SynthesizeHypothesisCandidateCardsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.synthesize_hypothesis_candidate_cards"

    def get_tool_description(self) -> str:
        return "Rewrite verified KG hypothesis candidates into structured idea/hypothesis cards."

    def get_args_schema(self):
        return SynthesizeHypothesisCandidateCardsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            args = SynthesizeHypothesisCandidateCardsArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        frontier_mode = str(args.frontier_mode or "off").strip().lower() or "off"
        wow_payload: dict[str, Any] = {}
        wow_candidate_cards: list[dict[str, Any]] = []
        if frontier_mode == "frontier":
            wow_payload = query_service.synthesize_wow_candidate_cards(
                query=args.query,
                seed_kg_ids=args.resolved_seed_kg_ids,
                contradiction_frontiers=args.contradiction_frontiers_result,
                assumption_cracks=args.assumption_cracks_result,
                analogy_transfers=args.analogy_transfers_result,
                limit=args.top_n,
            )
            wow_candidate_cards = list(wow_payload.get("candidate_cards") or [])

        result = synthesize_candidate_cards_payload(
            query=args.query,
            top_n=args.top_n,
            source_workflow=args.source_workflow,
            frontier_mode=frontier_mode,
            resolved_seed_kg_ids=args.resolved_seed_kg_ids,
            leverage_result=args.leverage_result,
            principle_state_init_result=args.principle_state_init_result,
            ood_result=args.ood_result,
            verify_result=args.verify_result,
            contradiction_result=args.contradiction_result,
            topology_result=args.topology_result,
            principle_state_update_result=args.principle_state_update_result,
            wow_candidate_cards=wow_candidate_cards,
            wow_summary=wow_payload.get("summary"),
            wow_warnings=list(wow_payload.get("warnings") or []),
        )
        return _success_result(
            "synthesize_hypothesis_candidate_cards",
            result,
            list(args.resolved_seed_kg_ids or []),
        )


class VerifySampledHypothesesTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.verify_sampled_hypotheses"

    def get_tool_description(self) -> str:
        return "Verify a precomputed set of sampled hypotheses with KG evidence."

    def get_args_schema(self):
        return VerifySampledHypothesesArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            args = VerifySampledHypothesesArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        seeds, anchor_bundle = _resolve_seed_context(
            seed_kg_ids=args.seed_kg_ids,
            query=None,
        )
        try:
            result = query_service.verify_sampled_hypotheses(
                sampled_hypotheses=args.sampled_hypotheses,
                query=args.query,
                seed_kg_ids=seeds,
                verify_top_k=args.verify_top_k,
                strictness=args.strictness,
                candidate_lane_mode=args.candidate_lane_mode,
                use_external_literature=args.use_external_literature,
                external_literature_top_k=args.external_literature_top_k,
                external_literature_recency_days=args.external_literature_recency_days,
                external_literature_exclude_domains=args.external_literature_exclude_domains,
                allowed_node_types=args.allowed_node_types,
                max_evidence=args.max_evidence,
                max_paths=args.max_paths,
                min_evidence_score=args.min_evidence_score,
                include_subgraph=args.include_subgraph,
                include_path_details=args.include_path_details,
                confidence_scoring_version=args.confidence_scoring_version,
            )
            return _success_result(
                "verify_sampled_hypotheses",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc):
                fallback = _build_fallback_verify_sampled_result(
                    seed_kg_ids=seeds,
                    sampled_hypotheses=list(args.sampled_hypotheses or []),
                    reason=str(exc),
                )
                return _success_result(
                    "verify_sampled_hypotheses_fallback",
                    fallback,
                    seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class SampleAndVerifyHypothesesTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "br_kg.sample_and_verify_hypotheses"

    def get_tool_description(self) -> str:
        return "Sample OOD hypotheses from KG seeds and immediately verify top candidates with KG evidence."

    def get_args_schema(self):
        return SampleAndVerifyHypothesesArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        seeds: list[str] = []
        anchor_bundle: list[dict[str, Any]] = []
        try:
            args = SampleAndVerifyHypothesesArgs(**kwargs)
        except Exception as exc:
            return _validation_error(exc)

        try:
            seeds, anchor_bundle = _resolve_seed_context(
                seed_kg_ids=args.seed_kg_ids,
                query=args.query,
            )
            if not seeds:
                query_text = str(args.query or "").strip()
                if query_text:
                    seeds = [_pseudo_seed_id(query_text)]
                else:
                    return ToolResult(
                        status="error",
                        error="Provide seed_kg_ids or a query that resolves to KG nodes",
                    )
            result = query_service.sample_and_verify_hypotheses(
                seed_kg_ids=seeds,
                query=args.query,
                relation_types=args.relation_types,
                sample_limit=args.n_samples,
                verify_top_k=args.verify_top_k,
                taste={"mode": args.taste_mode},
                strictness=args.strictness,
                candidate_lane_mode=args.candidate_lane_mode,
                use_external_literature=args.use_external_literature,
                external_literature_top_k=args.external_literature_top_k,
                external_literature_recency_days=args.external_literature_recency_days,
                external_literature_exclude_domains=args.external_literature_exclude_domains,
                allowed_node_types=args.allowed_node_types,
                max_evidence=args.max_evidence,
                max_paths=args.max_paths,
                min_evidence_score=args.min_evidence_score,
                include_subgraph=args.include_subgraph,
                include_path_details=args.include_path_details,
                confidence_scoring_version=args.confidence_scoring_version,
            )
            return _success_result(
                "sample_and_verify_hypotheses",
                result,
                seeds,
                resolved_anchor_bundle=anchor_bundle,
            )
        except Exception as exc:
            if _is_kg_unavailable_error(exc):
                fallback_seeds = seeds or [_pseudo_seed_id(args.query)]
                fallback = _build_fallback_hypothesis_testing_result(
                    seed_kg_ids=fallback_seeds,
                    n_samples=args.n_samples,
                    reason=str(exc),
                )
                return _success_result(
                    "sample_and_verify_hypotheses_fallback",
                    fallback,
                    fallback_seeds,
                    resolved_anchor_bundle=anchor_bundle,
                )
            return ToolResult(status="error", error=str(exc))


class KGNoveltyTools:
    """Factory for KG novelty wrapper tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            FindStructuralLeverageTool(),
            DetectContradictionMotifsTool(),
            FindContradictionFrontiersTool(),
            MineAssumptionCracksTool(),
            FindAnalogyTransfersTool(),
            SynthesizeWowCandidateCardsTool(),
            PrincipleStateInitTool(),
            SampleOODHypothesisTool(),
            SynthesizeHypothesisCandidateCardsTool(),
            VerifySampledHypothesesTool(),
            SampleAndVerifyHypothesesTool(),
            DetectTopologyShiftsTool(),
            PrincipleStateUpdateTool(),
        ]


def get_all_tools() -> list[NeuroToolWrapper]:
    return KGNoveltyTools().get_all_tools()


__all__ = [
    "DetectContradictionMotifsTool",
    "DetectTopologyShiftsTool",
    "FindAnalogyTransfersTool",
    "FindContradictionFrontiersTool",
    "FindStructuralLeverageTool",
    "KGNoveltyTools",
    "MineAssumptionCracksTool",
    "PrincipleStateInitTool",
    "PrincipleStateUpdateTool",
    "SampleAndVerifyHypothesesTool",
    "SampleOODHypothesisTool",
    "SynthesizeHypothesisCandidateCardsTool",
    "SynthesizeWowCandidateCardsTool",
    "VerifySampledHypothesesTool",
    "get_all_tools",
]
