"""Hybrid v1 retrieval implementation for BR-KG search.

Combines fulltext recall, vector recall, optional structured filters, and
returns compact explainability payloads. GFS evidence is policy-triggered
and bounded (single call, top-k docs, small evidence payload).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from brain_researcher.core.literature.gfs_store import search_gfs_auto
from brain_researcher.services.br_kg import query_service

FULLTEXT_K = 60
VECTOR_K = 60
FILTERED_CAP = 500
CACHE_TTL_SECONDS = 3600
GFS_TOP_K_DEFAULT = 10
MAX_EVIDENCE_PER_RESULT = 2
MAX_SNIPPETS_PER_DOC_DEFAULT = 2
SNIPPET_MAX_CHARS_DEFAULT = 300
EVIDENCE_BIND_LIMIT = 30

_NEGATIVE_MARKERS = (
    "deprecated",
    "removed",
    "do not use",
    "obsolete",
    "not recommended",
    "avoid",
    "should not",
)
_POSITIVE_MARKERS = (
    "recommended",
    "default",
    "standard",
    "we use",
    "we applied",
)
_NEGATIVE_HIGH = ("deprecated", "removed", "do not use", "obsolete")
_NEGATIVE_MEDIUM = ("not recommended", "avoid", "should not")
_CONFLICT_DISCOUNT = {"high": 0.5, "medium": 0.7, "low": 0.9}


_HYBRID_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class HybridConfig:
    w_fulltext: float = 0.60
    w_vector: float = 0.40
    w_gfs_boost: float = 0.25  # placeholder until GFS boost is wired
    fulltext_k: int = FULLTEXT_K
    vector_k: int = VECTOR_K
    filtered_cap: int = FILTERED_CAP
    gfs_top_k: int = GFS_TOP_K_DEFAULT
    max_evidence_per_result: int = MAX_EVIDENCE_PER_RESULT
    evidence_bind_limit: int = EVIDENCE_BIND_LIMIT
    gfs_enabled: bool = True
    max_snippets_per_doc: int = MAX_SNIPPETS_PER_DOC_DEFAULT
    snippet_max_chars: int = SNIPPET_MAX_CHARS_DEFAULT


def _now_ts() -> float:
    return time.time()


def _hash_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _get_cache(key: str) -> dict[str, Any] | None:
    entry = _HYBRID_CACHE.get(key)
    if not entry:
        return None
    if _now_ts() - entry["timestamp"] > CACHE_TTL_SECONDS:
        _HYBRID_CACHE.pop(key, None)
        return None
    return entry["value"]


def _set_cache(key: str, value: dict[str, Any]) -> None:
    _HYBRID_CACHE[key] = {"timestamp": _now_ts(), "value": value}


def _normalize_scores(values: Iterable[float]) -> list[float]:
    vals = list(values)
    if not vals:
        return []
    min_val = min(vals)
    max_val = max(vals)
    if max_val <= min_val:
        return [1.0 for _ in vals]
    return [(v - min_val) / (max_val - min_val) for v in vals]


def _build_explain_min(
    *,
    recall_fulltext: bool,
    recall_vector: bool,
    filters_matched: list[str],
    evidence_ids: list[str],
    gfs_on: bool,
    conflict_detected: bool = False,
    mapsto_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    if recall_fulltext:
        reason_codes.append("RECALL_FULLTEXT_HIT")
    if recall_vector:
        reason_codes.append("RECALL_VECTOR_HIT")
    for f in filters_matched:
        reason_codes.append(f"FILTER_MATCH_{f.upper()}")
    if evidence_ids:
        reason_codes.append("EVIDENCE_ATTACHED")
    if conflict_detected:
        reason_codes.append("CONFLICT_DETECTED")

    return {
        "reason_codes": reason_codes,
        "retrieval_trace_summary": f"hybrid(fulltext+vector)->rerank; gfs={'on' if gfs_on else 'off'}",
        "filters_matched": filters_matched,
        "mapsto_path": mapsto_path,
        "evidence_refs": evidence_ids,
    }


def _build_explain_full(
    *,
    score_breakdown: dict[str, Any],
    retrieval_trace_full: dict[str, Any],
    filtered_out_summary: dict[str, Any],
    conflict_flags: list[dict[str, Any]],
    mapsto_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "score_breakdown": score_breakdown,
        "retrieval_trace_full": retrieval_trace_full,
        "filtered_out_summary": filtered_out_summary,
        "conflict_flags": conflict_flags,
        "mapsto_path": mapsto_path,
    }


def _vector_search_fallback(
    query: str,
    node_types: Sequence[str] | None,
    k: int,
    vector_search_fn: Callable[..., Iterable[Any]] | None = None,
) -> list[dict[str, Any]]:
    if not vector_search_fn:
        return []
    try:
        results = vector_search_fn(
            query=query, node_types=list(node_types) if node_types else None, k=k
        )
    except Exception:
        return []

    output: list[dict[str, Any]] = []
    for res in results or []:
        node_id = getattr(res, "node_id", None) or res.get("node_id")
        node_type = getattr(res, "node_type", None) or res.get("node_type")
        score = getattr(res, "score", None) or res.get("score", 0.0)
        props = (
            getattr(res, "metadata", None)
            or res.get("properties")
            or res.get("metadata")
            or {}
        )
        label = props.get("label") or props.get("name") or props.get("title") or ""
        output.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "label": label,
                "properties": props,
                "vector_score": float(score or 0.0),
            }
        )
    return output


def _detect_evidence_intent(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    keywords = (
        "cite",
        "citation",
        "evidence",
        "source",
        "official",
        "guideline",
        "best practice",
        "recommended",
        "依据",
        "出处",
        "证据",
        "引用",
        "官方",
        "指南",
        "最佳实践",
    )
    return any(k in q for k in keywords)


def _infer_doc_role(text: str) -> str:
    t = _normalize_text(text)
    if any(k in t for k in ("guideline", "consensus", "best practice", "recommended")):
        return "guideline"
    if any(k in t for k in ("tool", "pipeline", "release", "version")):
        return "tooling_spec"
    return "general"


def _extract_year(text: str) -> int | None:
    match = re.search(r"(20\\d{2}|19\\d{2})", text or "")
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _is_exact_id_query(query: str) -> bool:
    if not query:
        return False
    text = query.strip()
    if " " in text:
        return False
    lowered = text.lower()
    if re.search(r"\bds\d{6}\b", lowered):
        return True
    if ":" in text:
        prefix = text.split(":", 1)[0].lower()
        if prefix in {
            "openneuro",
            "dataset",
            "task",
            "taskdef",
            "taskspec",
            "concept",
            "construct",
            "tool",
            "region",
            "cogatlas",
            "niclip",
        }:
            return True
    return False


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _alias_in_text(text_norm: str, alias_norm: str) -> bool:
    if not alias_norm:
        return False
    if len(alias_norm) <= 3:
        return f" {alias_norm} " in f" {text_norm} "
    return alias_norm in text_norm


def _extract_aliases(properties: dict[str, Any], label: str | None) -> list[str]:
    aliases: list[str] = []
    for key in (
        "aliases",
        "alias",
        "synonyms",
        "keywords",
        "name",
        "label",
        "title",
        "id",
    ):
        value = properties.get(key)
        if isinstance(value, list):
            aliases.extend([str(v) for v in value if v])
        elif isinstance(value, str):
            aliases.append(value)
    if label:
        aliases.append(label)
    return sorted({a.strip() for a in aliases if a and str(a).strip()})


def _polarity_from_text(text: str) -> str:
    t = _normalize_text(text)
    if any(marker in t for marker in _NEGATIVE_MARKERS):
        return "negative"
    if any(marker in t for marker in _POSITIVE_MARKERS):
        return "positive"
    return "neutral"


def _conflict_severity(texts: list[str]) -> str:
    joined = _normalize_text(" ".join(texts))
    if any(marker in joined for marker in _NEGATIVE_HIGH):
        return "high"
    if any(marker in joined for marker in _NEGATIVE_MEDIUM):
        return "medium"
    return "low"


def _detect_evidence_conflicts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not evidence:
        return []

    negative_texts = []
    positive_texts = []
    evidence_refs: list[str] = []
    doc_roles: list[str] = []
    for ev in evidence:
        evidence_refs.append(ev.get("evidence_id"))
        doc_role = ev.get("doc_role")
        if doc_role:
            doc_roles.append(str(doc_role))
        snippet = ev.get("snippet") or ""
        polarity = ev.get("polarity") or _polarity_from_text(snippet)
        if polarity == "negative":
            negative_texts.append(snippet)
        elif polarity == "positive":
            positive_texts.append(snippet)

    has_negative = bool(negative_texts)
    has_positive = bool(positive_texts)
    if not has_negative and not has_positive:
        return []

    severity = _conflict_severity(negative_texts)
    scope = (
        "tooling_spec"
        if any(r in {"tooling_spec", "guideline"} for r in doc_roles)
        else "general"
    )
    affects_confidence = scope in {"tooling_spec", "guideline"}
    discount = _CONFLICT_DISCOUNT.get(severity, 0.9) if affects_confidence else None

    if has_negative and has_positive:
        conflict_type = "evidence_semantic_conflict"
    else:
        conflict_type = "evidence_negative_only"

    details = {
        "rule": (
            "positive+negative evidence co-occur"
            if conflict_type == "evidence_semantic_conflict"
            else "negative evidence only"
        ),
        "negative_markers": list(_NEGATIVE_MARKERS),
        "confidence_discount": discount,
    }

    return [
        {
            "type": conflict_type,
            "scope": scope,
            "severity": severity,
            "affects_confidence": affects_confidence,
            "details": details,
            "evidence_refs": [ref for ref in evidence_refs if ref],
        }
    ]


def _detect_mapsto_ambiguity(properties: dict[str, Any]) -> dict[str, Any] | None:
    candidates = (
        properties.get("mapsto_candidates")
        or properties.get("mapsto_alternatives")
        or []
    )
    if not isinstance(candidates, list) or len(candidates) < 2:
        return None

    def _score(item: dict[str, Any]) -> float:
        return float(item.get("confidence") or item.get("score") or 0.0)

    sorted_candidates = sorted(candidates, key=_score, reverse=True)
    top1 = _score(sorted_candidates[0])
    top2 = _score(sorted_candidates[1])
    if top1 - top2 > 0.05:
        return None

    return {
        "type": "mapsto_ambiguous",
        "scope": "mapsto",
        "severity": "medium",
        "affects_confidence": False,
        "details": {
            "delta": top1 - top2,
            "delta_threshold": 0.05,
            "candidates": sorted_candidates[:3],
        },
        "evidence_refs": [],
    }


def _bind_gfs_evidence(
    hits: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    max_per_result: int,
    *,
    max_snippets_per_doc: int,
    snippet_max_chars: int,
) -> dict[str, list[dict[str, Any]]]:
    """Attach evidence hits to candidates via alias matching."""
    if not hits or not candidates:
        return {}

    text_hits: list[dict[str, Any]] = []
    for hit in hits:
        text = hit.get("text") or hit.get("snippet") or ""
        title = hit.get("title") or ""
        snippet = hit.get("snippet") or text[:snippet_max_chars]
        if len(snippet) > snippet_max_chars:
            snippet = snippet[:snippet_max_chars] + "..."
        text_hits.append(
            {
                "doc_id": hit.get("doc_id"),
                "title": title,
                "text": text,
                "snippet": snippet,
                "score": hit.get("score") or 0.0,
                "doc_role": hit.get("doc_role"),
                "year": hit.get("year"),
            }
        )

    evidence_by_key: dict[str, list[dict[str, Any]]] = {}
    for cand in candidates:
        alias_list = _extract_aliases(cand.get("properties", {}), cand.get("label"))
        alias_norms = [_normalize_text(a) for a in alias_list]
        matched: list[dict[str, Any]] = []
        for hit in text_hits:
            combined = _normalize_text(f"{hit['title']} {hit['text']}")
            if any(_alias_in_text(combined, alias_norm) for alias_norm in alias_norms):
                evidence_id = hashlib.sha256(
                    f"{cand.get('node_id')}|{hit.get('doc_id')}|{hit.get('snippet')}".encode()
                ).hexdigest()[:16]
                matched.append(
                    {
                        "evidence_id": f"ev_{evidence_id}",
                        "doc_id": hit.get("doc_id"),
                        "title": hit.get("title"),
                        "snippet": hit.get("snippet"),
                        "doc_role": hit.get("doc_role")
                        or _infer_doc_role(hit.get("snippet") or ""),
                        "year": hit.get("year") or _extract_year(hit.get("text") or ""),
                        "polarity": _polarity_from_text(hit.get("snippet") or ""),
                        "score": float(hit.get("score") or 0.0),
                    }
                )
            if len(matched) >= max_per_result:
                break
        if matched:
            # Group per doc_id and cap snippets per doc
            grouped: dict[str, list[dict[str, Any]]] = {}
            for ev in matched:
                doc_id = ev.get("doc_id") or "unknown_doc"
                grouped.setdefault(doc_id, []).append(ev)
            capped: list[dict[str, Any]] = []
            for doc_id, evs in grouped.items():
                evs_sorted = sorted(
                    evs, key=lambda e: e.get("score") or 0.0, reverse=True
                )
                capped.extend(evs_sorted[:max_snippets_per_doc])
            key = f"{cand.get('node_type')}:{cand.get('node_id')}"
            evidence_by_key[key] = capped[:max_per_result]
    return evidence_by_key


def hybrid_search_v1(
    *,
    query: str,
    node_types: Sequence[str] | None,
    filters: dict[str, Any] | None,
    limit: int,
    include_explain: bool,
    db=None,
    config: HybridConfig | None = None,
    search_nodes_fn: Callable[..., list[Any]] | None = None,
    search_datasets_fn: Callable[..., list[Any]] | None = None,
    vector_search_fn: Callable[..., Iterable[Any]] | None = None,
) -> dict[str, Any]:
    """Run hybrid_v1 retrieval.

    Returns a dict with `results`, `mode`, `degraded`, and `cache` fields.
    """
    config = config or HybridConfig()
    query = (query or "").strip()
    filters = filters or {}
    node_types_list = list(node_types) if node_types else None

    cache_key = _hash_key(
        {
            "mode": "hybrid_v1",
            "query": query,
            "node_types": node_types_list,
            "filters": filters,
            "limit": limit,
            "include_explain": include_explain,
            "gfs_top_k": config.gfs_top_k,
            "gfs_enabled": config.gfs_enabled,
            "version": "v1",
        }
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return {
            "results": cached["results"],
            "mode": "hybrid_v1",
            "degraded": cached["degraded"],
            "cache": {"hit": True},
        }

    degraded: list[str] = []
    filters_matched: list[str] = []

    # Fulltext recall
    fulltext_results: list[dict[str, Any]] = []
    if search_nodes_fn is None:
        search_nodes_fn = query_service.search_nodes
    if query:
        try:
            ft_nodes = search_nodes_fn(
                query, node_types=node_types_list, limit=config.fulltext_k, db=db
            )
            for node in ft_nodes:
                props = node.properties or {}
                fulltext_results.append(
                    {
                        "node_id": node.kg_id,
                        "node_type": node.node_type,
                        "label": node.label,
                        "properties": props,
                        "fulltext_score": float(node.score or 0.0),
                    }
                )
        except Exception:
            degraded.append("fulltext_unavailable")

    # Structured filter (dataset only MVP)
    filtered_candidates: dict[str, dict[str, Any]] | None = None
    filter_is_active = bool(filters)
    if filter_is_active:
        dataset_only = not node_types_list or all(
            nt.lower() == "dataset" for nt in node_types_list
        )
        if dataset_only:
            if search_datasets_fn is None:
                search_datasets_fn = query_service.search_datasets
            try:
                ds_results = search_datasets_fn(
                    text=query or None,
                    task_ids=filters.get("task"),
                    modality=filters.get("modality"),
                    min_subjects=filters.get("min_subjects"),
                    species=filters.get("species"),
                    limit=config.filtered_cap,
                    db=db,
                )
                filtered_candidates = {}
                for ds in ds_results:
                    filtered_candidates[ds.kg_id] = {
                        "node_id": ds.kg_id,
                        "node_type": "Dataset",
                        "label": ds.title or ds.dataset_id,
                        "properties": {
                            "dataset_id": ds.dataset_id,
                            "title": ds.title,
                            "tasks": ds.tasks,
                            "modalities": ds.modalities,
                            "n_subjects": ds.n_subjects,
                            "species": ds.species,
                        },
                        "fulltext_score": 0.0,
                    }
                # Record matched filters (for explain_min)
                if "source" in filters:
                    filters_matched.append("source")
                if "modality" in filters:
                    filters_matched.append("modality")
                if "min_subjects" in filters:
                    filters_matched.append("min_subjects")
                if "task" in filters:
                    filters_matched.append("task")
            except Exception:
                degraded.append("structured_filter_unavailable")

    # Vector recall (best-effort)
    vector_results: list[dict[str, Any]] = []
    if vector_search_fn is not None and query:
        vector_results = _vector_search_fallback(
            query, node_types_list, config.vector_k, vector_search_fn=vector_search_fn
        )
    else:
        # caller can inject vector_search_fn (e.g., via vector_api)
        pass

    if query and not vector_results:
        degraded.append("vector_unavailable")

    # Merge candidates
    combined: dict[str, dict[str, Any]] = {}
    for rec in fulltext_results:
        key = f"{rec['node_type']}:{rec['node_id']}"
        combined.setdefault(key, {}).update(rec)
    for rec in vector_results:
        key = f"{rec['node_type']}:{rec['node_id']}"
        combined.setdefault(key, {}).update(rec)

    # If filtered candidates exist, restrict to them
    if filtered_candidates is not None:
        combined = {
            f"{v['node_type']}:{k}": {**v, **combined.get(f"{v['node_type']}:{k}", {})}
            for k, v in filtered_candidates.items()
        }

    if not combined:
        results_payload = []
        response = {
            "results": results_payload,
            "mode": "hybrid_v1",
            "degraded": degraded,
            "cache": {"hit": False},
        }
        _set_cache(cache_key, {"results": results_payload, "degraded": degraded})
        return response

    combined_items = list(combined.values())

    # Normalize scores and compute base score
    fulltext_scores = [float(v.get("fulltext_score") or 0.0) for v in combined_items]
    vector_scores = [float(v.get("vector_score") or 0.0) for v in combined_items]
    fulltext_norms = _normalize_scores(fulltext_scores)
    vector_norms = _normalize_scores(vector_scores)
    base_scores = [
        config.w_fulltext * fulltext_norms[idx] + config.w_vector * vector_norms[idx]
        for idx in range(len(combined_items))
    ]

    # Optional GFS evidence (bounded, single call)
    gfs_meta = {
        "status": "none",
        "reason": "not_triggered",
        "stores_hit": [],
        "call_count": 0,
        "n_docs_hit": 0,
        "query_used": query,
    }
    gfs_hits: list[dict[str, Any]] = []
    gfs_on = False
    try:
        gfs_result = search_gfs_auto(
            query,
            top_k=config.gfs_top_k,
            gfs_enabled=config.gfs_enabled,
            include_explain=include_explain,
            result_count=len(combined_items),
            top_score=max(base_scores) if base_scores else 0.0,
            weak_evidence=len(combined_items) < 3,
            max_calls=2,
        )
        gfs_on = bool(gfs_result.get("triggered"))
        gfs_hits = gfs_result.get("hits") or []
        gfs_meta = {
            "status": gfs_result.get("status") or "error",
            "reason": gfs_result.get("reason"),
            "stores_hit": list(gfs_result.get("stores_hit") or []),
            "call_count": int(gfs_result.get("call_count") or 0),
            "model": gfs_result.get("model"),
            "n_docs_hit": len(gfs_hits),
            "query_used": gfs_result.get("query_used") or gfs_result.get("query"),
        }
    except Exception:
        gfs_meta = {
            "status": "error",
            "reason": "exception",
            "stores_hit": [],
            "call_count": 0,
            "n_docs_hit": 0,
            "query_used": query,
        }

    # Bind evidence for top N candidates only
    top_indices = sorted(
        range(len(base_scores)), key=lambda i: base_scores[i], reverse=True
    )[: config.evidence_bind_limit]
    candidates_for_binding = [combined_items[i] for i in top_indices]
    evidence_map = _bind_gfs_evidence(
        gfs_hits,
        candidates_for_binding,
        config.max_evidence_per_result,
        max_snippets_per_doc=config.max_snippets_per_doc,
        snippet_max_chars=config.snippet_max_chars,
    )

    results_payload: list[dict[str, Any]] = []
    gfs_scores = []
    for rec in combined_items:
        key = f"{rec.get('node_type')}:{rec.get('node_id')}"
        evidence_for_candidate = evidence_map.get(key, [])
        gfs_scores.append(
            max(
                (float(ev.get("score") or 0.0) for ev in evidence_for_candidate),
                default=0.0,
            )
        )
    gfs_norms = (
        _normalize_scores(gfs_scores)
        if (gfs_on and gfs_meta.get("status") == "ok")
        else [0.0] * len(gfs_scores)
    )

    from brain_researcher.services.br_kg.evidence.caveats import match_caveats

    for idx, rec in enumerate(combined_items):
        key = f"{rec.get('node_type')}:{rec.get('node_id')}"
        base_score = base_scores[idx]
        confidence = rec.get("properties", {}).get("confidence")

        evidence: list[dict[str, Any]] = evidence_map.get(key, [])
        evidence_ids: list[str] = [e["evidence_id"] for e in evidence]
        conflict_flags = _detect_evidence_conflicts(evidence)
        mapsto_flag = _detect_mapsto_ambiguity(rec.get("properties", {}))
        if mapsto_flag:
            conflict_flags.append(mapsto_flag)

        if confidence is not None:
            try:
                confidence_val = float(confidence)
            except (TypeError, ValueError):
                confidence_val = None
            if confidence_val is not None:
                discounts = [
                    flag.get("details", {}).get("confidence_discount")
                    for flag in conflict_flags
                    if flag.get("affects_confidence")
                ]
                discounts = [d for d in discounts if isinstance(d, int | float)]
                if discounts:
                    discount = min(discounts)
                    confidence_before = confidence_val
                    confidence_val = confidence_val * discount
                    for flag in conflict_flags:
                        if (
                            flag.get("affects_confidence")
                            and flag.get("details", {}).get("confidence_discount")
                            == discount
                        ):
                            flag["details"]["confidence_before"] = confidence_before
                            flag["details"]["confidence_after"] = confidence_val
                confidence = confidence_val
            else:
                confidence = None
        else:
            confidence = None

        final_score = base_score + config.w_gfs_boost * gfs_norms[idx]
        if confidence is not None:
            final_score = final_score * (0.5 + 0.5 * float(confidence))

        explain_min = _build_explain_min(
            recall_fulltext=bool(rec.get("fulltext_score")),
            recall_vector=bool(rec.get("vector_score")),
            filters_matched=filters_matched,
            evidence_ids=evidence_ids,
            gfs_on=gfs_on,
            conflict_detected=bool(conflict_flags),
            mapsto_path=None,
        )

        caveats = match_caveats(
            query=query,
            node_type=rec.get("node_type"),
            node_label=rec.get("label"),
        )

        result_item = {
            "id": rec.get("node_id"),
            "type": rec.get("node_type"),
            "label": rec.get("label"),
            "properties": rec.get("properties", {}),
            "score": float(final_score),
            "confidence": float(confidence) if confidence is not None else None,
            "evidence_status": (
                "ok"
                if evidence
                else (
                    "partial"
                    if gfs_meta.get("status") == "ok"
                    else gfs_meta.get("status", "none")
                )
            ),
            "evidence": evidence,
            "explain_min": explain_min,
        }
        if caveats:
            result_item["caveats"] = caveats

        if include_explain:
            score_breakdown = {
                "fulltext": fulltext_norms[idx],
                "vector": vector_norms[idx],
                "gfs_boost": gfs_norms[idx],
            }
            retrieval_trace_full = {
                "fulltext_k": config.fulltext_k,
                "vector_k": config.vector_k,
                "filtered_cap": config.filtered_cap,
            }
            filtered_out_summary = {
                "after_node_type_filter": len(fulltext_results),
                "after_structured_filter": len(combined),
                "after_rank_cut": min(limit, len(combined)),
            }
            result_item["explain_full"] = _build_explain_full(
                score_breakdown=score_breakdown,
                retrieval_trace_full=retrieval_trace_full,
                filtered_out_summary=filtered_out_summary,
                conflict_flags=conflict_flags,
                mapsto_path=None,
            )

        results_payload.append(result_item)

    # Sort and limit
    results_payload.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    results_payload = results_payload[: max(1, int(limit or 20))]

    response = {
        "results": results_payload,
        "mode": "hybrid_v1",
        "degraded": degraded,
        "cache": {"hit": False},
    }
    if config.gfs_enabled:
        response["gfs"] = gfs_meta
    _set_cache(cache_key, {"results": results_payload, "degraded": degraded})
    return response


__all__ = ["hybrid_search_v1", "HybridConfig"]
