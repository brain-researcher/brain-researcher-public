"""Lightweight Google File Search wrapper for literature evidence."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from brain_researcher.core.grounding_references import anchors_from_gfs_hits

logger = logging.getLogger(__name__)


SUPPORTED_FILE_SEARCH_MODELS = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-pro-preview",
)

_PMCID_RE = re.compile(r"\bPMC\d+\b", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID[:\s]*([0-9]{4,})\b", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_DATASET_ID_RE = re.compile(r"\bds\d{6}\b", re.IGNORECASE)
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{3,}$")
_BUNDLE_TITLE_RE = re.compile(
    r"(?:^|/)(?:m\d+_)?pubget_papers_bundle_[0-9]+\.txt$",
    re.IGNORECASE,
)
_INLINE_TITLE_RE = re.compile(
    r"\btitle:\s*(.+?)(?=\s+\b(?:journal|year|license|source|authors?|pmcid|pmid|doi|doc_type)\b:|===DOC_END===|$)",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_JOURNAL_RE = re.compile(
    r"\bjournal:\s*(.+?)(?=\s+\b(?:year|license|source|authors?|pmcid|pmid|doi|title|doc_type)\b:|===DOC_END===|$)",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_YEAR_RE = re.compile(r"\byear:\s*([12][0-9]{3})\b", re.IGNORECASE)

_PUBLICATION_HINTS = (
    "paper",
    "papers",
    "publication",
    "publications",
    "full text",
    "full-text",
    "citation",
    "citations",
    "evidence",
    "guideline",
    "guidelines",
    "best practice",
    "best-practice",
    "recommend",
    "recommended",
    "recommendation",
    "pdf",
    "pmid",
    "pmcid",
    "doi",
    "journal",
    "method section",
    "methods section",
)
_CODE_HINTS = (
    "codebase",
    "repo",
    "repository",
    "source code",
    "source tree",
    "api",
    "apis",
    "schema",
    "schemas",
    "implementation",
    "function signature",
    "function signatures",
    "class definition",
    "tool registry",
    "code path",
)
_OPT_OUT_HINTS = (
    "no literature",
    "don't use literature",
    "do not use literature",
    "no file search",
    "don't use file search",
    "do not use file search",
    "no gfs",
    "without gfs",
    "skip file search",
)
_PAPER_STORE_HINTS = ("paper", "papers", "publication", "publications", "pmc", "oa")
_CODE_STORE_HINTS = ("code", "repo", "source", "tooling")
_DEFAULT_WEAK_RESULT_SCORE = 0.35


@dataclass(frozen=True)
class AutoGFSDecision:
    should_trigger: bool
    reason: str
    query_intent: str
    stores: List[str]
    call_budget: int
    weak_evidence: bool


def _is_supported_file_search_model(model: str) -> bool:
    return any(
        model == base or model.startswith(f"{base}-")
        for base in SUPPORTED_FILE_SEARCH_MODELS
    )


def _resolve_store(override: Optional[str] = None) -> Optional[str]:
    if override:
        return override
    return (
        os.environ.get("FILE_SEARCH_STORE")
        or os.environ.get("BR_FILE_SEARCH_STORE")
        or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
        or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
    )


def _resolve_stores(override: Optional[str] = None) -> List[str]:
    """Resolve file search store names from env or override.

    Priority:
    1. `override` (supports comma-separated values)
    2. `BR_FILE_SEARCH_STORE_NAMES` (comma-separated list)
    3. `FILE_SEARCH_STORE` / `BR_FILE_SEARCH_STORE` / legacy fallbacks
    4. Default codebase store

    Returns:
        Non-empty list of store names.
    """
    if override:
        override = override.strip()
        if override:
            if "," in override:
                stores = [s.strip() for s in override.split(",") if s.strip()]
                if stores:
                    return stores
                # Ignore invalid comma-only overrides and fall back to env.
            else:
                return [override]

    multi = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
    if multi:
        stores = [s.strip() for s in multi.split(",") if s.strip()]
        if stores:
            return stores

    store = _resolve_store()
    if store:
        return [store]

    return ["fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"]


def _resolve_model(override: Optional[str] = None) -> str:
    return (
        override
        or os.environ.get("BR_FILE_SEARCH_MODEL")
        or os.environ.get("DEFAULT_LLM_MODEL")
        or "gemini-3-flash-preview"
    )


def _load_google_genai() -> tuple[Any, Any]:
    from google import genai
    from google.genai import types

    return genai, types


def _run_gfs_generate_content(
    client: Any,
    *,
    model: str,
    query: str,
    config: Any,
    timeout_ms: int | None = None,
) -> Any:
    if timeout_ms is None or timeout_ms <= 0:
        return client.models.generate_content(
            model=model,
            contents=query,
            config=config,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.models.generate_content,
            model=model,
            contents=query,
            config=config,
        )
        try:
            return future.result(timeout=max(float(timeout_ms) / 1000.0, 0.001))
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"file_search timed out after {int(timeout_ms)}ms"
            ) from exc


def _looks_like_exact_lookup(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if _PMCID_RE.search(text) or _PMID_RE.search(text) or _DOI_RE.search(text):
        return True
    if _DATASET_ID_RE.search(lowered):
        return True
    if " " not in text and ":" in text:
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
    return (
        " " not in text
        and any(ch.isdigit() for ch in text)
        and bool(_OPAQUE_ID_RE.match(text))
    )


def _has_opt_out(query: str) -> bool:
    q = (query or "").lower()
    return any(marker in q for marker in _OPT_OUT_HINTS)


def _query_intent(query: str) -> str:
    q = (query or "").lower()
    papers = any(marker in q for marker in _PUBLICATION_HINTS)
    code = any(marker in q for marker in _CODE_HINTS)
    if papers and not code:
        return "papers"
    if code and not papers:
        return "code"
    if papers and code:
        return "mixed"
    return "generic"


def classify_store_kind(store_name: str) -> str:
    lowered = (store_name or "").lower()
    if any(marker in lowered for marker in _PAPER_STORE_HINTS):
        return "papers"
    if any(marker in lowered for marker in _CODE_STORE_HINTS):
        return "code"
    return "generic"


def route_gfs_stores(
    query: str,
    *,
    override: Optional[str] = None,
    stores: Optional[Sequence[str]] = None,
) -> List[str]:
    resolved = list(stores) if stores is not None else _resolve_stores(override)
    if not resolved:
        return []

    papers = [store for store in resolved if classify_store_kind(store) == "papers"]
    code = [store for store in resolved if classify_store_kind(store) == "code"]
    generic = [store for store in resolved if classify_store_kind(store) == "generic"]
    intent = _query_intent(query)

    if intent == "papers":
        ordered = [*papers, *generic, *code]
    elif intent == "code":
        ordered = [*code, *generic, *papers]
    else:
        ordered = [*resolved]
    return list(dict.fromkeys(ordered))


def should_trigger_auto_gfs(
    query: str,
    *,
    gfs_enabled: bool = True,
    include_explain: bool = False,
    result_count: Optional[int] = None,
    top_score: Optional[float] = None,
    weak_evidence: bool = False,
    store_override: Optional[str] = None,
) -> AutoGFSDecision:
    stores = route_gfs_stores(query, override=store_override)
    if not gfs_enabled:
        return AutoGFSDecision(
            should_trigger=False,
            reason="disabled",
            query_intent=_query_intent(query),
            stores=stores,
            call_budget=0,
            weak_evidence=False,
        )
    if not stores:
        return AutoGFSDecision(
            should_trigger=False,
            reason="unconfigured",
            query_intent=_query_intent(query),
            stores=[],
            call_budget=0,
            weak_evidence=False,
        )
    if _has_opt_out(query):
        return AutoGFSDecision(
            should_trigger=False,
            reason="query_opt_out",
            query_intent=_query_intent(query),
            stores=stores,
            call_budget=0,
            weak_evidence=False,
        )

    inferred_weak = bool(weak_evidence)
    if result_count is not None and result_count < 3:
        inferred_weak = True
    if top_score is not None and float(top_score) < 0.45:
        inferred_weak = True

    intent = _query_intent(query)
    exact_lookup = _looks_like_exact_lookup(query)
    if exact_lookup and not include_explain and not inferred_weak:
        return AutoGFSDecision(
            should_trigger=False,
            reason="exact_lookup_skip",
            query_intent=intent,
            stores=stores,
            call_budget=0,
            weak_evidence=inferred_weak,
        )

    if include_explain:
        reason = "include_explain"
        should = True
    elif intent in {"papers", "code", "mixed"}:
        reason = f"intent_{intent}"
        should = True
    elif inferred_weak:
        reason = "weak_evidence"
        should = True
    else:
        reason = "no_trigger"
        should = False

    call_budget = min(2 if inferred_weak else 1, max(1, len(stores))) if should else 0
    return AutoGFSDecision(
        should_trigger=should,
        reason=reason,
        query_intent=intent,
        stores=stores,
        call_budget=call_budget,
        weak_evidence=inferred_weak,
    )


def _extract_header_fields(text: str) -> Dict[str, str]:
    header: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"pmcid", "pmid", "doi", "title", "journal", "year"}:
            header.setdefault(key, value)
    header_window = " ".join(text.splitlines()[:8]).strip()
    if header_window:
        title_match = _INLINE_TITLE_RE.search(header_window)
        if title_match:
            header.setdefault("title", title_match.group(1).strip().strip(" ."))
        journal_match = _INLINE_JOURNAL_RE.search(header_window)
        if journal_match:
            header.setdefault("journal", journal_match.group(1).strip().strip(" ."))
        year_match = _INLINE_YEAR_RE.search(header_window)
        if year_match:
            header.setdefault("year", year_match.group(1).strip())
    return header


def _extract_identifiers(text: str) -> Dict[str, Optional[str]]:
    pmcid = None
    pmid = None
    doi = None
    if text:
        pmcid_match = _PMCID_RE.search(text)
        if pmcid_match:
            pmcid = pmcid_match.group(0)
        pmid_match = _PMID_RE.search(text)
        if pmid_match:
            pmid = pmid_match.group(1)
        doi_match = _DOI_RE.search(text)
        if doi_match:
            doi = doi_match.group(0)
    return {"pmcid": pmcid, "pmid": pmid, "doi": doi}


def _normalize_pmcid(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if text.upper().startswith("PMC"):
        return text.upper()
    digits = re.sub(r"\D+", "", text)
    return f"PMC{digits}" if digits else None


def _normalize_pmid(value: Optional[str]) -> Optional[str]:
    text = re.sub(r"\D+", "", (value or "").strip())
    return text or None


def _normalize_doi(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            lowered = text.lower()
    lowered = re.sub(r"\s+", "", lowered)
    lowered = lowered.rstrip(".,;:)]}")
    lowered = lowered.lstrip("([{")
    return lowered or None


def _looks_like_bundle_title(value: Optional[str]) -> bool:
    title = (value or "").strip()
    if not title:
        return False
    return bool(_BUNDLE_TITLE_RE.search(title))


def _preferred_title(*candidates: Optional[str]) -> Optional[str]:
    cleaned: List[str] = []
    for candidate in candidates:
        title = (candidate or "").strip()
        if not title:
            continue
        if _looks_like_bundle_title(title):
            continue
        cleaned.append(title)
    if cleaned:
        return cleaned[0]
    return None


def _fallback_display_title(text: str) -> Optional[str]:
    collapsed = re.sub(r"\s+", " ", (text or "")).strip()
    if not collapsed:
        return None
    if collapsed.startswith("===") or ":" in collapsed[:40]:
        return None
    sentence = re.split(r"(?<=[.!?])\s+", collapsed, maxsplit=1)[0].strip()
    if len(sentence) < 24:
        return None
    if len(sentence) > 120:
        sentence = sentence[:117].rstrip(" ,;:") + "..."
    return f"Paper excerpt: {sentence}"


def _title_from_text(text: str) -> Optional[str]:
    header = _extract_header_fields(text)
    explicit_title = (header.get("title") or "").strip()
    if explicit_title:
        return explicit_title

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    candidate = lines[0]
    if (
        len(candidate) < 12
        or len(candidate) > 300
        or candidate.startswith("===")
        or ":" in candidate
        or _looks_like_bundle_title(candidate)
    ):
        return None
    context = " ".join(lines[1:5]).lower()
    if any(
        marker in context
        for marker in ("journal:", "year:", "license:", "source:", "===text===")
    ):
        return candidate
    return None


def _normalized_hit_identity(hit: Dict[str, Any]) -> str:
    doi = _normalize_doi(hit.get("doi"))
    if doi:
        return f"doi:{doi}"
    pmcid = _normalize_pmcid(hit.get("pmcid"))
    if pmcid:
        return f"pmcid:{pmcid}"
    pmid = _normalize_pmid(hit.get("pmid"))
    if pmid:
        return f"pmid:{pmid}"
    title = _preferred_title(hit.get("title"))
    if title:
        return f"title:{title.casefold()}"
    text = re.sub(r"\s+", " ", str(hit.get("text") or "")).strip()
    if text:
        return f"text:{text[:160]}"
    doc_id = (hit.get("doc_id") or "").strip()
    if doc_id:
        return f"doc:{doc_id}"
    return "unknown"


def _metadata_signature(hit: Dict[str, Any]) -> Optional[str]:
    doi = _normalize_doi(hit.get("doi"))
    if doi:
        return f"doi:{doi}"
    pmcid = _normalize_pmcid(hit.get("pmcid"))
    if pmcid:
        return f"pmcid:{pmcid}"
    pmid = _normalize_pmid(hit.get("pmid"))
    if pmid:
        return f"pmid:{pmid}"
    if hit.get("_synthetic_title"):
        title = None
    else:
        title = _preferred_title(hit.get("title"))
    if title:
        return f"title:{title.casefold()}"
    return None


def _normalize_gfs_hit(
    *,
    raw_title: Optional[str],
    text: str,
    score: Any,
    doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    header = _extract_header_fields(text)
    ids = _extract_identifiers(text)
    pmcid = _normalize_pmcid(header.get("pmcid") or ids.get("pmcid"))
    pmid = _normalize_pmid(header.get("pmid") or ids.get("pmid"))
    doi = _normalize_doi(header.get("doi") or ids.get("doi"))
    real_title = _preferred_title(
        _title_from_text(text), header.get("title"), raw_title
    )
    synthetic_title = None
    if not real_title:
        synthetic_title = _fallback_display_title(text)
    title = real_title or synthetic_title
    hit: Dict[str, Any] = {
        "title": title,
        "score": score,
        "pmcid": pmcid,
        "pmid": pmid,
        "doi": doi,
        "snippet": (text[:300] + "...") if len(text) > 300 else text,
        "text": text,
        "_source_title": (raw_title or "").strip() or None,
        "_synthetic_title": bool(synthetic_title and not real_title),
    }
    if doc_id:
        hit["doc_id"] = doc_id
    return hit


def _retrieved_context_doc_id(ctx: Any, store_name: str) -> Optional[str]:
    """Extract a traceable document anchor from a Google File Search context."""
    if ctx is None:
        return None

    for attr in ("document_name", "uri", "id", "name", "path"):
        val = getattr(ctx, attr, None)
        if val:
            return str(val)

    title = (getattr(ctx, "title", None) or "").strip()
    if not title:
        return None

    lowered = title.lower()
    if _looks_like_bundle_title(title) or lowered.endswith(
        (".txt", ".pdf", ".md", ".json", ".csv")
    ):
        file_search_store = (
            getattr(ctx, "file_search_store", None) or store_name or ""
        ).strip()
        return f"{file_search_store}/files/{title}" if file_search_store else title

    return None


def _merge_hits(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    existing_score = float(existing.get("score") or 0.0)
    incoming_score = float(incoming.get("score") or 0.0)
    best_source = existing if existing_score >= incoming_score else incoming
    other = incoming if best_source is existing else existing
    best = dict(best_source)

    best["title"] = _preferred_title(best.get("title"), other.get("title"))
    for field in ("doi", "pmcid", "pmid", "doc_id"):
        if not best.get(field) and other.get(field):
            best[field] = other[field]
    if not best.get("snippet") and other.get("snippet"):
        best["snippet"] = other["snippet"]
    if not best.get("text") and other.get("text"):
        best["text"] = other["text"]
    best["score"] = (
        existing.get("score")
        if existing_score >= incoming_score
        else incoming.get("score")
    )
    return best


def _propagate_bundle_metadata(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_bundle: Dict[str, List[Dict[str, Any]]] = {}
    for hit in hits:
        source_title = (hit.get("_source_title") or "").strip()
        if not _looks_like_bundle_title(source_title):
            continue
        by_bundle.setdefault(source_title, []).append(hit)

    for bundle_title, bundle_hits in by_bundle.items():
        del bundle_title
        donors: Dict[str, Dict[str, Any]] = {}
        for hit in bundle_hits:
            sig = _metadata_signature(hit)
            if not sig:
                continue
            prev = donors.get(sig)
            donors[sig] = hit if prev is None else _merge_hits(prev, hit)
        if len(donors) != 1:
            continue
        donor = next(iter(donors.values()))
        for hit in bundle_hits:
            if _metadata_signature(hit):
                continue
            hit["title"] = _preferred_title(hit.get("title"), donor.get("title"))
            for field in ("doi", "pmcid", "pmid"):
                if not hit.get(field) and donor.get(field):
                    hit[field] = donor[field]
    return hits


def _finalize_hits(hits: List[Dict[str, Any]], *, top_k: int) -> List[Dict[str, Any]]:
    normalized_hits = _propagate_bundle_metadata(list(hits))
    dedup_hits: Dict[str, Dict[str, Any]] = {}
    for hit in normalized_hits:
        doc_id = _normalized_hit_identity(hit)
        prev = dedup_hits.get(doc_id)
        if prev is None:
            dedup_hits[doc_id] = hit
            continue
        dedup_hits[doc_id] = _merge_hits(prev, hit)

    sorted_hits = sorted(
        dedup_hits.values(),
        key=lambda h: h.get("score") or 0,
        reverse=True,
    )[:top_k]
    for hit in sorted_hits:
        hit.pop("_source_title", None)
        hit.pop("_synthetic_title", None)
    return sorted_hits


def _result_top_score(result: Dict[str, Any]) -> float:
    hits = result.get("hits") or []
    return max((float(hit.get("score") or 0.0) for hit in hits), default=0.0)


def _is_weak_gfs_result(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("status") != "ok":
        return True
    hits = result.get("hits") or []
    if len(hits) < 1:
        return True
    return _result_top_score(result) < _DEFAULT_WEAK_RESULT_SCORE


def search_gfs(
    query: str,
    *,
    top_k: int = 5,
    store: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_ms: int | None = None,
    max_stores: int | None = None,
) -> Dict[str, Any]:
    """Run a File Search query and return structured hits.

    Supports multiple stores via `BR_FILE_SEARCH_STORE_NAMES` (comma-separated).
    Results from all stores are merged and deduplicated by `doc_id`.

    Backwards compatibility: `store` is still populated (first store).

    Returns a dict with keys: status, query, store, stores, model, hits, summary.
    """
    stores = _resolve_stores(store)
    if max_stores is not None:
        try:
            bounded_max_stores = max(1, int(max_stores))
        except Exception:
            bounded_max_stores = 1
        stores = stores[:bounded_max_stores]
    if not stores:
        return {"status": "unconfigured", "reason": "No FILE_SEARCH_STORE configured"}

    model = _resolve_model(model)
    if not _is_supported_file_search_model(model):
        return {
            "status": "unsupported_model",
            "model": model,
            "supported": list(SUPPORTED_FILE_SEARCH_MODELS),
        }

    api_key = (
        api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        return {"status": "error", "error": "Missing GEMINI_API_KEY/GOOGLE_API_KEY"}

    try:
        genai, types = _load_google_genai()
    except Exception as exc:  # pragma: no cover - optional dependency
        return {"status": "error", "error": f"google-genai not available: {exc}"}

    client = genai.Client(api_key=api_key)

    # Query all stores and aggregate results
    all_hits: List[Dict[str, Any]] = []
    summaries: List[str] = []
    queried_stores: List[str] = []
    store_errors: List[Dict[str, str]] = []
    call_count = 0
    started_at = time.monotonic()

    for store_name in stores:
        call_count += 1
        tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[store_name],
                top_k=top_k,
            )
        )

        try:
            resp = _run_gfs_generate_content(
                client,
                model=model,
                query=query,
                config=types.GenerateContentConfig(tools=[tool]),
                timeout_ms=timeout_ms,
            )
        except Exception as exc:  # pragma: no cover - network/service errors
            logger.warning("file_search failed for %s: %s", store_name, exc)
            store_errors.append({"store": store_name, "error": str(exc)})
            continue

        queried_stores.append(store_name)
        summary = (resp.text or "")[:600]
        if summary:
            summaries.append(summary)

        cands = getattr(resp, "candidates", []) or []
        for cand in cands:
            gm = getattr(cand, "grounding_metadata", None)
            if not gm:
                continue
            for ch in getattr(gm, "grounding_chunks", []) or []:
                ctx = getattr(ch, "retrieved_context", None)
                text = getattr(ctx, "text", "") or ""
                doc_id = _retrieved_context_doc_id(ctx, store_name)
                hit = _normalize_gfs_hit(
                    raw_title=getattr(ctx, "title", "") or "",
                    text=text,
                    score=getattr(ch, "relevance_score", None),
                    doc_id=doc_id,
                )
                all_hits.append(hit)

    latency_ms = round((time.monotonic() - started_at) * 1000.0, 3)
    if not queried_stores:
        return {
            "status": "error",
            "query": query,
            "stores": stores,
            "model": model,
            "error": "file_search failed for all stores",
            "stores_attempted": stores,
            "stores_hit": [],
            "call_count": call_count,
            "latency_ms": latency_ms,
            "raw_hit_count": len(all_hits),
            "n_docs_hit": 0,
            "store_errors": store_errors,
        }

    sorted_hits = _finalize_hits(all_hits, top_k=top_k)

    return {
        "status": "ok",
        "query": query,
        "store": queried_stores[0],
        "stores": queried_stores,
        "stores_attempted": stores,
        "stores_hit": queried_stores,
        "model": model,
        "summary": " | ".join(summaries)[:600],
        "hits": sorted_hits,
        "anchors": anchors_from_gfs_hits(sorted_hits),
        "call_count": call_count,
        "latency_ms": latency_ms,
        "raw_hit_count": len(all_hits),
        "n_docs_hit": len(sorted_hits),
        "store_errors": store_errors,
    }


def search_gfs_auto(
    query: str,
    *,
    top_k: int = 5,
    store: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    gfs_enabled: bool = True,
    include_explain: bool = False,
    result_count: Optional[int] = None,
    top_score: Optional[float] = None,
    weak_evidence: bool = False,
    max_calls: int = 2,
) -> Dict[str, Any]:
    decision = should_trigger_auto_gfs(
        query,
        gfs_enabled=gfs_enabled,
        include_explain=include_explain,
        result_count=result_count,
        top_score=top_score,
        weak_evidence=weak_evidence,
        store_override=store,
    )
    if not decision.should_trigger:
        return {
            "status": "skipped",
            "query": query,
            "query_used": query,
            "reason": decision.reason,
            "query_intent": decision.query_intent,
            "stores": decision.stores,
            "stores_hit": [],
            "call_count": 0,
            "hits": [],
            "anchors": [],
            "summary": "",
            "triggered": False,
        }

    ordered_stores = decision.stores
    call_budget = min(max_calls, decision.call_budget or 1, len(ordered_stores))
    queried_stores: List[str] = []
    merged_hits: List[Dict[str, Any]] = []
    summaries: List[str] = []
    last_status = "error"
    last_error = None
    model_name = _resolve_model(model)

    for store_name in ordered_stores[:call_budget]:
        result = search_gfs(
            query,
            top_k=top_k,
            store=store_name,
            model=model_name,
            api_key=api_key,
        )
        queried_stores.append(store_name)
        last_status = str(result.get("status") or "error")
        if result.get("summary"):
            summaries.append(str(result["summary"]))
        if result.get("status") == "ok":
            merged_hits.extend(result.get("hits") or [])
            if not _is_weak_gfs_result(result):
                last_error = None
                break
        else:
            last_error = result.get("error") or result.get("reason")

    sorted_hits = _finalize_hits(merged_hits, top_k=top_k)
    if sorted_hits:
        status = "ok"
    elif last_status == "ok":
        status = "empty"
    else:
        status = last_status or "error"

    return {
        "status": status,
        "query": query,
        "query_used": query,
        "reason": decision.reason,
        "query_intent": decision.query_intent,
        "store": queried_stores[0] if queried_stores else None,
        "stores": ordered_stores,
        "stores_hit": queried_stores,
        "call_count": len(queried_stores),
        "model": model_name,
        "summary": " | ".join(summaries)[:600],
        "hits": sorted_hits,
        "anchors": anchors_from_gfs_hits(sorted_hits),
        "n_docs_hit": len(sorted_hits),
        "triggered": True,
        "error": last_error,
    }


__all__ = [
    "AutoGFSDecision",
    "SUPPORTED_FILE_SEARCH_MODELS",
    "classify_store_kind",
    "route_gfs_stores",
    "search_gfs",
    "search_gfs_auto",
    "should_trigger_auto_gfs",
]
