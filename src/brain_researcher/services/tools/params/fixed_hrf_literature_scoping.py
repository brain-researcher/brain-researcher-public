"""Helpers for scoping-review style fixed-HRF fMRI literature searches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from brain_researcher.core.literature.gfs_store import search_gfs_auto
from brain_researcher.core.literature.references import STATIC_METHOD_REFS

_HRF_BUCKETS = (
    "canonical_hrf",
    "derivative_basis",
    "fir_flobs",
    "model_comparison",
    "other",
)

_CANONICAL_TERMS = (
    "canonical hrf",
    "spm hrf",
    "spm canonical",
    "glover hrf",
    "hrf basis",
)
_DERIVATIVE_TERMS = (
    "temporal derivative",
    "derivative basis",
    "hrf derivative",
    "latency",
)
_FIR_FLOBS_TERMS = (
    "fir",
    "finite impulse response",
    "flobs",
    "basis function",
)
_MODEL_COMPARISON_TERMS = (
    "compare",
    "comparison",
    "benchmark",
    "tradeoff",
    "optimization",
)


@dataclass(frozen=True)
class FixedHrfLiteratureScopingParameters:
    """Parameters for a fixed-HRF scoping review search."""

    query: str | None = None
    scope_label: str = "fixed-HRF fMRI methods"
    task: str | None = None
    top_k: int = 8
    store: str | None = None
    model: str | None = None
    gfs_enabled: bool = True
    include_static: bool = True
    max_calls: int = 2


def fixed_hrf_literature_scoping_from_payload(
    payload: dict[str, object],
) -> FixedHrfLiteratureScopingParameters:
    """Build typed scoping parameters from a payload."""

    return FixedHrfLiteratureScopingParameters(
        query=str(payload["query"]) if payload.get("query") else None,
        scope_label=str(payload.get("scope_label", "fixed-HRF fMRI methods")),
        task=str(payload["task"]) if payload.get("task") else None,
        top_k=int(payload.get("top_k", 8)),
        store=str(payload["store"]) if payload.get("store") else None,
        model=str(payload["model"]) if payload.get("model") else None,
        gfs_enabled=bool(payload.get("gfs_enabled", True)),
        include_static=bool(payload.get("include_static", True)),
        max_calls=int(payload.get("max_calls", 2)),
    )


def build_fixed_hrf_scoping_query(params: FixedHrfLiteratureScopingParameters) -> str:
    """Build a review-oriented query for fixed-HRF literature scoping."""

    parts: list[str] = []
    if params.query:
        parts.append(params.query.strip())
    if params.task:
        parts.append(params.task.strip())
    parts.extend(
        [
            params.scope_label,
            "scoping review",
            "fixed HRF",
            "canonical HRF",
            "temporal derivative",
            "FIR",
            "FLOBS",
            "first-level fMRI model",
            "hemodynamic response function",
        ]
    )
    seen: set[str] = set()
    normalized: list[str] = []
    for part in parts:
        token = " ".join(str(part).split())
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(token)
    return " ".join(normalized)


def _hit_text(hit: dict[str, Any]) -> str:
    parts = [
        hit.get("title"),
        hit.get("snippet"),
        hit.get("text"),
        hit.get("summary"),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def bucket_fixed_hrf_hit(hit: dict[str, Any]) -> str:
    """Assign a hit to a coarse fixed-HRF literature bucket."""

    text = _hit_text(hit)
    if any(term in text for term in _FIR_FLOBS_TERMS):
        return "fir_flobs"
    if any(term in text for term in _DERIVATIVE_TERMS):
        return "derivative_basis"
    if any(term in text for term in _CANONICAL_TERMS):
        return "canonical_hrf"
    if any(term in text for term in _MODEL_COMPARISON_TERMS):
        return "model_comparison"
    return "other"


def summarize_fixed_hrf_hits(
    hits: list[dict[str, Any]], *, top_k: int = 5
) -> dict[str, Any]:
    """Summarize a scoping-review hit set into coarse evidence buckets."""

    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in _HRF_BUCKETS}
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        buckets[bucket_fixed_hrf_hit(hit)].append(hit)

    top_titles = [
        str(hit.get("title") or hit.get("doc_id") or "untitled")
        for hit in hits[:top_k]
        if isinstance(hit, dict)
    ]
    return {
        "total_hits": len(hits),
        "bucket_counts": {bucket: len(items) for bucket, items in buckets.items()},
        "bucket_examples": {
            bucket: [
                {
                    "title": str(item.get("title") or item.get("doc_id") or "untitled"),
                    "doc_id": item.get("doc_id"),
                    "score": item.get("score"),
                }
                for item in items[:3]
            ]
            for bucket, items in buckets.items()
            if items
        },
        "top_titles": top_titles,
    }


def gather_fixed_hrf_static_refs() -> list[dict[str, Any]]:
    """Return the static HRF anchors used to frame the scoping review."""

    refs: list[dict[str, Any]] = []
    for key in (("hrf", "canonical"), ("hrf", "derivs"), ("hrf", "fir")):
        ref = STATIC_METHOD_REFS.get(key)
        if ref is not None:
            refs.append(ref.to_dict())
    return refs


def run_fixed_hrf_literature_scoping(
    params: FixedHrfLiteratureScopingParameters,
) -> dict[str, Any]:
    """Run a scoping-review style literature search for fixed-HRF methods."""

    query = build_fixed_hrf_scoping_query(params)
    search_result = search_gfs_auto(
        query,
        top_k=params.top_k,
        store=params.store,
        model=params.model,
        gfs_enabled=params.gfs_enabled,
        weak_evidence=True,
        max_calls=params.max_calls,
    )
    hits = list(search_result.get("hits") or [])
    summary = summarize_fixed_hrf_hits(hits, top_k=params.top_k)
    static_refs = gather_fixed_hrf_static_refs() if params.include_static else []

    return {
        "review_type": "scoping_review",
        "scope_label": params.scope_label,
        "scope_note": (
            "This is a scoping review, not an unbiased census; it is intentionally "
            "biased toward fixed-HRF fMRI method families and basis-function variants."
        ),
        "search_query": query,
        "search": search_result,
        "hits": hits,
        "hit_summary": summary,
        "static_refs": static_refs,
        "limitations": [
            "Search is deliberately review-oriented rather than exhaustive.",
            "Coverage depends on configured file-search stores and their indexing.",
        ],
    }


__all__ = [
    "FixedHrfLiteratureScopingParameters",
    "bucket_fixed_hrf_hit",
    "build_fixed_hrf_scoping_query",
    "fixed_hrf_literature_scoping_from_payload",
    "gather_fixed_hrf_static_refs",
    "run_fixed_hrf_literature_scoping",
    "summarize_fixed_hrf_hits",
]
