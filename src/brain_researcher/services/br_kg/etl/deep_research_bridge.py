"""Bridge deep-research outputs into Gabriel/KGGEN-compatible manifest seeds."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from brain_researcher.core.literature import deep_research
from brain_researcher.core.utils.env_loader import ensure_env_loaded

try:
    import requests
except Exception:  # pragma: no cover - dependency present in runtime env
    requests = None  # type: ignore[assignment]


BRIDGE_VERSION = "deep-research-gabriel-bridge/v1"
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.IGNORECASE)
_PMID_RE = re.compile(r"\b(?:pmid[:/ ]*)?(\d{4,})\b", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"\b(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})\b", re.IGNORECASE
)
_ARXIV_DOI_RE = re.compile(
    r"\b10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE
)
_ARXIV_TITLE_PREFIX_RE = re.compile(r"^\[\d{4}\.\d{4,5}(?:v\d+)?\]\s*", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_BOUNDARY_CHARS = ".?!\n"
_TITLE_MATCH_THRESHOLD = 0.86
_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "via",
    "with",
}
_GENERIC_TITLES = {
    "just a moment...",
    "just a moment",
    "attention required!",
    "access denied",
    "access denied.",
    "404 not found",
    "403 forbidden",
    "404 access denied",
    "404 page not found",
    "404 error",
    "not found",
    "forbidden",
    "error",
    "status page",
    "page not found",
    "internal server error",
    "service unavailable",
    "bad gateway",
    "pdf",
    "biorxiv",
    "researchgate",
    "sciencedaily",
    "abstract",
    "article",
    "download",
    "full text",
    "fulltext",
    "journal",
    "landing page",
    "manuscript",
    "paper",
    "preprint",
    "content",
    "supplement",
    "supplementary",
    "view article",
}
_VENUE_ONLY_TITLES = {
    "arxiv",
    "bioRxiv".lower(),
    "cell",
    "elsevier",
    "frontiers",
    "mdpi",
    "medrxiv",
    "nature",
    "plos",
    "pnas",
    "research square",
    "science",
    "springer",
    "the lancet",
    "wiley",
}


@dataclass
class CitationSnippet:
    raw_url: str
    snippet: str
    start_index: int | None = None
    end_index: int | None = None


@dataclass
class SourceSeed:
    raw_url: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    snippets: list[CitationSnippet] = field(default_factory=list)
    final_url: str | None = None
    resolved_title: str | None = None
    content_type: str | None = None
    resolution_error: str | None = None


@dataclass
class LinkValidationResult:
    final_url: str | None
    status: str
    validated_by: str | None = None
    matched_title: str | None = None
    reason: str | None = None
    match_score: float | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    return deep_research._json_safe(value)  # type: ignore[attr-defined]


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_title(value: Any) -> str | None:
    text = _normalize_space(value)
    if not text:
        return None
    text = re.sub(r"^[\|\-:\s]+", "", text)
    text = re.sub(r"[\|\-:\s]+$", "", text)
    text = re.sub(r"^\|\s*", "", text)
    text = re.sub(r"\s+\|\s+.*$", "", text)
    text = re.sub(r"\s+-\s+.*$", "", text)
    text = _normalize_space(text).strip(" |:-")
    lower = text.strip().lower()
    if lower in _GENERIC_TITLES or lower in _VENUE_ONLY_TITLES:
        return None
    if lower.startswith(("http://", "https://", "doi:", "pmid:", "arxiv:")):
        return None
    if _DOI_RE.search(lower):
        return None
    if any(
        marker in lower
        for marker in (
            "404",
            "403",
            "access denied",
            "not found",
            "status page",
            "attention required",
            "just a moment",
            "internal server error",
            "service unavailable",
            "bad gateway",
        )
    ):
        return None
    if re.fullmatch(r"[a-z0-9._/\-]+", lower) and (
        any(ch.isdigit() for ch in lower) or "." in lower or "/" in lower
    ):
        return None
    if text.strip().lower() in _GENERIC_TITLES:
        return None
    return text or None


def _canonicalize_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    return deep_research._canonicalize_url(candidate)  # type: ignore[attr-defined]


def _display_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return deep_research._display_url(value)  # type: ignore[attr-defined]


def _source_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return deep_research._source_host(value)  # type: ignore[attr-defined]


def _normalize_title_for_match(value: Any) -> str:
    text = _clean_title(value) or _normalize_space(value)
    if not text:
        return ""
    text = html.unescape(text)
    text = _ARXIV_TITLE_PREFIX_RE.sub("", text)
    text = re.sub(
        r"\(arxiv[:\s]*\d{4}\.\d{4,5}(?:v\d+)?\)", "", text, flags=re.IGNORECASE
    )
    text = _NON_ALNUM_RE.sub(" ", text.casefold())
    return _normalize_space(text)


def _title_tokens(value: Any) -> set[str]:
    return {
        token
        for token in _normalize_title_for_match(value).split()
        if token and token not in _TITLE_STOPWORDS
    }


def _title_match_score(left: Any, right: Any) -> float:
    left_norm = _normalize_title_for_match(left)
    right_norm = _normalize_title_for_match(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    shorter = min(len(left_norm), len(right_norm))
    if shorter >= 24 and (left_norm in right_norm or right_norm in left_norm):
        return 0.98

    seq_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = _title_tokens(left_norm)
    right_tokens = _title_tokens(right_norm)
    if not left_tokens or not right_tokens:
        return seq_ratio

    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(overlap) / len(union) if union else 0.0
    coverage = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
    return max(seq_ratio, jaccard, coverage)


def _extract_arxiv_id(value: Any) -> str | None:
    text = _normalize_space(value)
    if not text:
        return None
    match = _ARXIV_DOI_RE.search(text)
    if match:
        return match.group(1)
    match = _ARXIV_RE.search(text)
    if match:
        return match.group(1)
    return None


def _extract_doi(value: Any) -> str | None:
    text = _normalize_space(value)
    if not text:
        return None
    match = _DOI_RE.search(text)
    if not match:
        return None
    return match.group(0).lower()


def _canonical_scholarly_url(*values: Any) -> str | None:
    for value in values:
        arxiv_id = _extract_arxiv_id(value)
        if arxiv_id:
            return f"https://arxiv.org/abs/{arxiv_id}"
    for value in values:
        doi = _extract_doi(value)
        if doi:
            return f"https://doi.org/{doi}"
    for value in values:
        canonical = _canonicalize_url(value)
        if canonical:
            return canonical
    return None


def _uses_generic_source_title(title: str | None) -> bool:
    return _normalize_space(title).lower().startswith("deep research source")


def _session_get(
    url: str,
    *,
    session: requests.Session | None,
    timeout_sec: float,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    if session is not None:
        response = session.get(url, params=params, timeout=timeout_sec)
        response.raise_for_status()
        return response
    response = requests.get(url, params=params, timeout=timeout_sec)
    response.raise_for_status()
    return response


def _fetch_arxiv_metadata(
    arxiv_id: str,
    *,
    session: requests.Session | None,
    timeout_sec: float,
) -> dict[str, Any] | None:
    if not requests or not arxiv_id:
        return None
    try:
        response = _session_get(
            "https://export.arxiv.org/api/query",
            session=session,
            timeout_sec=timeout_sec,
            params={"id_list": arxiv_id},
        )
        try:
            root = ET.fromstring(response.text)
        finally:
            response.close()
        atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", atom_ns)
        if entry is None:
            return None
        title = _clean_title(
            entry.findtext("atom:title", default="", namespaces=atom_ns)
        )
        entry_id = _normalize_space(
            entry.findtext("atom:id", default="", namespaces=atom_ns)
        )
        canonical_url = _canonical_scholarly_url(entry_id, arxiv_id)
        if not title or not canonical_url:
            return None
        return {"title": title, "url": canonical_url}
    except Exception:
        return None


def _fetch_openalex_doi_metadata(
    doi: str,
    *,
    session: requests.Session | None,
    timeout_sec: float,
) -> dict[str, Any] | None:
    if not requests or not doi:
        return None
    try:
        response = _session_get(
            "https://api.openalex.org/works",
            session=session,
            timeout_sec=timeout_sec,
            params={"filter": f"doi:{doi}", "per-page": 1},
        )
        try:
            payload = response.json()
        finally:
            response.close()
        results = payload.get("results") or []
        if not results:
            return None
        record = results[0] or {}
        title = _clean_title(record.get("display_name") or record.get("title"))
        canonical_url = _canonical_scholarly_url(
            (record.get("primary_location") or {}).get("landing_page_url"),
            record.get("doi"),
            (record.get("ids") or {}).get("doi"),
        )
        if not title or not canonical_url:
            return None
        return {"title": title, "url": canonical_url}
    except Exception:
        return None


def _fetch_crossref_doi_metadata(
    doi: str,
    *,
    session: requests.Session | None,
    timeout_sec: float,
) -> dict[str, Any] | None:
    if not requests or not doi:
        return None
    try:
        response = _session_get(
            f"https://api.crossref.org/works/{doi}",
            session=session,
            timeout_sec=timeout_sec,
        )
        try:
            payload = response.json()
        finally:
            response.close()
        message = payload.get("message") or {}
        title_list = message.get("title") or []
        title = _clean_title(" ".join(str(item) for item in title_list if item))
        canonical_url = _canonical_scholarly_url(f"https://doi.org/{doi}")
        if not title or not canonical_url:
            return None
        return {"title": title, "url": canonical_url}
    except Exception:
        return None


def _lookup_openalex_title(
    title: str,
    *,
    session: requests.Session | None,
    timeout_sec: float,
) -> dict[str, Any] | None:
    if not requests or not title:
        return None
    try:
        response = _session_get(
            "https://api.openalex.org/works",
            session=session,
            timeout_sec=timeout_sec,
            params={"search": title, "per-page": 5},
        )
        try:
            payload = response.json()
        finally:
            response.close()
    except Exception:
        return None

    best: dict[str, Any] | None = None
    best_score = 0.0
    for record in payload.get("results") or []:
        candidate_title = _clean_title(
            record.get("display_name") or record.get("title")
        )
        if not candidate_title:
            continue
        score = _title_match_score(title, candidate_title)
        if score < best_score:
            continue
        canonical_url = _canonical_scholarly_url(
            (record.get("primary_location") or {}).get("landing_page_url"),
            record.get("doi"),
            (record.get("ids") or {}).get("doi"),
        )
        if not canonical_url:
            continue
        best = {"title": candidate_title, "url": canonical_url, "match_score": score}
        best_score = score
    return best


def _validate_paper_link(
    final_url: str | None,
    title: str | None,
    *,
    session: requests.Session | None,
    timeout_sec: float,
) -> LinkValidationResult:
    canonical_url = _canonicalize_url(final_url)
    clean_title = _clean_title(title)
    if not canonical_url:
        return LinkValidationResult(
            final_url=None, status="missing_url", reason="missing_url"
        )
    if not clean_title or _uses_generic_source_title(clean_title):
        return LinkValidationResult(
            final_url=canonical_url,
            status="skipped",
            reason="missing_or_generic_title",
        )

    arxiv_id = _extract_arxiv_id(canonical_url)
    if arxiv_id:
        arxiv_meta = _fetch_arxiv_metadata(
            arxiv_id,
            session=session,
            timeout_sec=timeout_sec,
        )
        if arxiv_meta:
            score = _title_match_score(clean_title, arxiv_meta.get("title"))
            if score >= _TITLE_MATCH_THRESHOLD:
                return LinkValidationResult(
                    final_url=arxiv_meta.get("url"),
                    status="confirmed",
                    validated_by="arxiv",
                    matched_title=arxiv_meta.get("title"),
                    match_score=score,
                )
            corrected = _lookup_openalex_title(
                clean_title,
                session=session,
                timeout_sec=timeout_sec,
            )
            if (
                corrected
                and corrected.get("match_score", 0.0) >= _TITLE_MATCH_THRESHOLD
            ):
                return LinkValidationResult(
                    final_url=corrected.get("url"),
                    status="corrected",
                    validated_by="openalex",
                    matched_title=corrected.get("title"),
                    reason=f"arxiv_title_mismatch:{arxiv_id}",
                    match_score=float(corrected.get("match_score") or 0.0),
                )
            return LinkValidationResult(
                final_url=None,
                status="dropped",
                validated_by="arxiv",
                matched_title=arxiv_meta.get("title"),
                reason=f"arxiv_title_mismatch:{arxiv_id}",
                match_score=score,
            )
        corrected = _lookup_openalex_title(
            clean_title,
            session=session,
            timeout_sec=timeout_sec,
        )
        if corrected and corrected.get("match_score", 0.0) >= _TITLE_MATCH_THRESHOLD:
            return LinkValidationResult(
                final_url=corrected.get("url"),
                status="corrected",
                validated_by="openalex",
                matched_title=corrected.get("title"),
                reason=f"arxiv_lookup_failed:{arxiv_id}",
                match_score=float(corrected.get("match_score") or 0.0),
            )
        return LinkValidationResult(
            final_url=None,
            status="dropped",
            validated_by="arxiv",
            reason=f"arxiv_lookup_failed:{arxiv_id}",
        )

    doi = _extract_doi(canonical_url)
    if doi:
        openalex_meta = _fetch_openalex_doi_metadata(
            doi,
            session=session,
            timeout_sec=timeout_sec,
        )
        if openalex_meta:
            score = _title_match_score(clean_title, openalex_meta.get("title"))
            if score >= _TITLE_MATCH_THRESHOLD:
                return LinkValidationResult(
                    final_url=openalex_meta.get("url"),
                    status="confirmed",
                    validated_by="openalex",
                    matched_title=openalex_meta.get("title"),
                    match_score=score,
                )

        crossref_meta = _fetch_crossref_doi_metadata(
            doi,
            session=session,
            timeout_sec=timeout_sec,
        )
        if crossref_meta:
            score = _title_match_score(clean_title, crossref_meta.get("title"))
            if score >= _TITLE_MATCH_THRESHOLD:
                return LinkValidationResult(
                    final_url=crossref_meta.get("url"),
                    status="confirmed",
                    validated_by="crossref",
                    matched_title=crossref_meta.get("title"),
                    match_score=score,
                )

        corrected = _lookup_openalex_title(
            clean_title,
            session=session,
            timeout_sec=timeout_sec,
        )
        if corrected and corrected.get("match_score", 0.0) >= _TITLE_MATCH_THRESHOLD:
            return LinkValidationResult(
                final_url=corrected.get("url"),
                status="corrected",
                validated_by="openalex",
                matched_title=corrected.get("title"),
                reason=f"doi_title_mismatch:{doi}",
                match_score=float(corrected.get("match_score") or 0.0),
            )

        return LinkValidationResult(
            final_url=None,
            status="dropped",
            validated_by="doi",
            reason=f"doi_title_mismatch:{doi}",
        )

    return LinkValidationResult(
        final_url=canonical_url,
        status="skipped",
        reason="non_identifier_url",
    )


def coerce_deep_research_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize deep-research payloads from core cache or MCP wrappers."""
    value: dict[str, Any] = dict(payload or {})
    if isinstance(value.get("result"), dict):
        value = dict(value["result"])
    elif value.get("ok") is True and isinstance(value.get("data"), dict):
        data = dict(value["data"])
        documents = data.get("documents")
        if not isinstance(documents, list):
            documents = [
                {
                    "doc_id": f"doc_{idx + 1}",
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "raw_url": item.get("url"),
                    "publisher": None,
                    "published_at": None,
                    "snippets": [],
                }
                for idx, item in enumerate(data.get("sources") or [])
                if isinstance(item, dict) and isinstance(item.get("url"), str)
            ]
        value = {
            "status": "ok" if value.get("ok") else "error",
            "summary": data.get("summary") or data.get("text") or "",
            "synthesis_full_text": data.get("summary") or data.get("text") or "",
            "documents": documents,
            "raw": data.get("raw_response") or data.get("response") or {},
            "metadata": {
                "provider": "google_deep_research",
                "interaction_id": data.get("interaction_id"),
            },
        }

    if not isinstance(value.get("documents"), list):
        raw_payload = value.get("raw")
        documents = deep_research._extract_url_documents(raw_payload)  # type: ignore[attr-defined]
        value["documents"] = documents
    if not value.get("synthesis_full_text"):
        value["synthesis_full_text"] = (
            value.get("summary")
            or value.get("text")
            or deep_research._find_text(value.get("raw") or value)  # type: ignore[attr-defined]
            or ""
        )
    if "raw" not in value:
        value["raw"] = {}
    return value


def load_deep_research_result(
    *,
    interaction_id: str | None = None,
    result_json_path: Path | None = None,
) -> dict[str, Any]:
    ensure_env_loaded()
    if result_json_path is not None:
        payload = json.loads(result_json_path.read_text(encoding="utf-8"))
        return coerce_deep_research_result(payload)
    if not interaction_id:
        raise ValueError("interaction_id or result_json_path is required")
    fetched = deep_research.deep_research_get(interaction_id=interaction_id)
    status = str(fetched.get("status") or "").strip().lower()
    if status not in {"ok", "cached", "partial"}:
        raise RuntimeError(
            f"deep_research_get did not return a usable result: {json.dumps(fetched, ensure_ascii=True)}"
        )
    result = fetched.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("deep_research_get returned no result payload")
    return coerce_deep_research_result(result)


def _collect_annotation_blocks(payload: Any) -> list[tuple[str, list[dict[str, Any]]]]:
    blocks: list[tuple[str, list[dict[str, Any]]]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        text = node.get("text")
        annotations = node.get("annotations")
        if isinstance(text, str) and isinstance(annotations, list):
            items = [item for item in annotations if isinstance(item, dict)]
            if items:
                blocks.append((text, items))
        for value in node.values():
            if isinstance(value, dict | list):
                _walk(value)

    _walk(payload)
    return blocks


def _trim_boundary_left(text: str, index: int, floor: int) -> int:
    if index <= floor:
        return floor
    boundary = max(text.rfind(ch, floor, index) for ch in _BOUNDARY_CHARS)
    return floor if boundary < floor else boundary + 1


def _trim_boundary_right(text: str, index: int, ceiling: int) -> int:
    if index >= ceiling:
        return ceiling
    candidates = [text.find(ch, index, ceiling) for ch in _BOUNDARY_CHARS]
    candidates = [item for item in candidates if item >= 0]
    return ceiling if not candidates else min(candidates) + 1


def extract_annotation_snippets(
    raw_payload: dict[str, Any],
    *,
    context_chars: int = 220,
) -> list[CitationSnippet]:
    snippets: list[CitationSnippet] = []
    seen: set[tuple[str, str]] = set()
    for text, annotation_items in _collect_annotation_blocks(raw_payload):
        for item in annotation_items:
            raw_url = _canonicalize_url(
                item.get("source")
                or item.get("url")
                or item.get("uri")
                or item.get("href")
            )
            if not raw_url:
                continue
            try:
                start = int(item.get("start_index"))
                end = int(item.get("end_index"))
            except Exception:
                start = 0
                end = 0
            if start < 0:
                start = 0
            if end < start:
                end = start
            floor = max(0, start - max(0, int(context_chars)))
            ceiling = min(len(text), end + max(0, int(context_chars)))
            left = _trim_boundary_left(text, start, floor)
            right = _trim_boundary_right(text, end, ceiling)
            snippet = _normalize_space(text[left:right])
            if not snippet:
                continue
            key = (raw_url, snippet)
            if key in seen:
                continue
            seen.add(key)
            snippets.append(
                CitationSnippet(
                    raw_url=raw_url,
                    snippet=snippet,
                    start_index=start,
                    end_index=end,
                )
            )
    return snippets


def _derive_url_title(url: str | None) -> str | None:
    if not url:
        return None
    try:
        path = urlsplit(url).path or ""
    except Exception:
        return None
    name = Path(path).name
    if not name:
        return None
    stem = re.sub(r"\.[A-Za-z0-9]{2,6}$", "", name)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    if len(stem) < 4:
        return None
    return _clean_title(stem[:160])


def _resolve_source_metadata(
    raw_url: str,
    *,
    session: Any = None,
    timeout_sec: float = 10.0,
) -> dict[str, Any]:
    if requests is None:
        return {"final_url": raw_url, "resolved_title": None, "content_type": None}
    own_session = session is None
    session = session or requests.Session()
    try:
        response = session.get(
            raw_url,
            allow_redirects=True,
            stream=True,
            timeout=(5.0, timeout_sec),
            headers={"User-Agent": "Mozilla/5.0 (BrainResearcher bridge)"},
        )
        final_url = _canonicalize_url(getattr(response, "url", None)) or raw_url
        content_type = str(response.headers.get("content-type") or "").strip() or None
        title: str | None = None
        if content_type and "html" in content_type.lower():
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(8192):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                lower = chunk.lower()
                if b"</title" in lower or total >= 65536:
                    break
            if chunks:
                raw_text = b"".join(chunks).decode(
                    getattr(response, "encoding", None) or "utf-8",
                    errors="ignore",
                )
                match = _TITLE_TAG_RE.search(raw_text)
                if match:
                    title = _clean_title(html.unescape(match.group(1)))
        response.close()
        if own_session:
            session.close()
        return {
            "final_url": final_url,
            "resolved_title": title,
            "content_type": content_type,
        }
    except Exception as exc:
        if own_session:
            try:
                session.close()
            except Exception:
                pass
        return {
            "final_url": raw_url,
            "resolved_title": None,
            "content_type": None,
            "resolution_error": str(exc),
        }


def _choose_paper_id(final_url: str | None, title: str | None) -> str:
    combined = f"{final_url or ''} {title or ''}"
    doi_match = _DOI_RE.search(combined)
    if doi_match:
        return f"doi:{doi_match.group(0).lower()}"
    arxiv_match = _ARXIV_RE.search(combined)
    if arxiv_match:
        return f"arxiv:{arxiv_match.group(1)}"
    pmid_match = _PMID_RE.search(combined)
    if pmid_match:
        return f"pmid:{pmid_match.group(1)}"
    fallback = final_url or title or "deep-research-source"
    return f"url:{_stable_hash(fallback)[:16]}"


def _choose_title(source: SourceSeed, *, index: int) -> str:
    for candidate in (
        source.resolved_title,
        *(doc.get("title") for doc in source.documents if isinstance(doc, dict)),
        _derive_url_title(source.final_url),
    ):
        title = _clean_title(candidate)
        if title:
            return title
    host = _source_host(source.final_url or source.raw_url)
    if host:
        return f"Deep research source {index} ({host})"
    return f"Deep research source {index}"


def _build_seed_abstract(
    source: SourceSeed,
    *,
    summary_title: str | None,
    max_snippets: int,
    max_chars: int,
) -> str:
    unique_snippets: list[str] = []
    seen: set[str] = set()
    for item in source.snippets:
        snippet = _normalize_space(item.snippet)
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        unique_snippets.append(snippet)
        if len(unique_snippets) >= max_snippets:
            break
    if len(unique_snippets) < max_snippets:
        for doc in source.documents:
            if not isinstance(doc, dict):
                continue
            snippets = doc.get("snippets")
            if not isinstance(snippets, list):
                continue
            for raw_snippet in snippets:
                snippet = _normalize_space(raw_snippet)
                if not snippet or snippet in seen:
                    continue
                seen.add(snippet)
                unique_snippets.append(snippet)
                if len(unique_snippets) >= max_snippets:
                    break
            if len(unique_snippets) >= max_snippets:
                break
    if not unique_snippets:
        return ""
    text = "\n\n".join(unique_snippets).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def build_source_seeds(
    result: dict[str, Any],
    *,
    max_sources: int = 0,
    max_snippets_per_source: int = 4,
    snippet_context_chars: int = 220,
    max_abstract_chars: int = 4000,
    resolve_redirects: bool = True,
    resolve_timeout_sec: float = 10.0,
    validate_identifiers: bool = False,
) -> list[dict[str, Any]]:
    normalized = coerce_deep_research_result(result)
    documents = normalized.get("documents") or []
    raw_payload = normalized.get("raw") or {}
    summary_title = _clean_title(
        (normalized.get("summary") or normalized.get("synthesis_full_text") or "")
        .splitlines()[0]
        .lstrip("#")
        .strip()
    )

    sources_by_raw_url: dict[str, SourceSeed] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        raw_url = _canonicalize_url(doc.get("url") or doc.get("raw_url"))
        if not raw_url:
            continue
        seed = sources_by_raw_url.setdefault(raw_url, SourceSeed(raw_url=raw_url))
        seed.documents.append(doc)

    for snippet in extract_annotation_snippets(
        raw_payload, context_chars=snippet_context_chars
    ):
        seed = sources_by_raw_url.setdefault(
            snippet.raw_url, SourceSeed(raw_url=snippet.raw_url)
        )
        seed.snippets.append(snippet)

    network_session = (
        requests.Session()
        if (requests and (resolve_redirects or validate_identifiers))
        else None
    )
    grouped: dict[str, SourceSeed] = {}
    for raw_url, seed in sorted(sources_by_raw_url.items()):
        if resolve_redirects:
            resolved = _resolve_source_metadata(
                raw_url,
                session=network_session,
                timeout_sec=resolve_timeout_sec,
            )
            seed.final_url = _canonicalize_url(resolved.get("final_url")) or raw_url
            seed.resolved_title = _clean_title(resolved.get("resolved_title"))
            seed.content_type = resolved.get("content_type")
            seed.resolution_error = (
                _normalize_space(resolved.get("resolution_error") or "") or None
            )
        else:
            seed.final_url = raw_url

        group_key = seed.final_url or raw_url
        merged = grouped.get(group_key)
        if merged is None:
            grouped[group_key] = seed
            continue
        merged.documents.extend(seed.documents)
        merged.snippets.extend(seed.snippets)
        if not merged.resolved_title and seed.resolved_title:
            merged.resolved_title = seed.resolved_title
        if not merged.content_type and seed.content_type:
            merged.content_type = seed.content_type
        if merged.raw_url != raw_url:
            merged.documents.append({"raw_url_alias": raw_url})
    ordered_sources = sorted(
        grouped.values(),
        key=lambda item: (
            -len(item.snippets),
            _choose_title(item, index=1).lower(),
            item.final_url or item.raw_url,
        ),
    )
    if max_sources > 0:
        ordered_sources = ordered_sources[:max_sources]

    seeds: list[dict[str, Any]] = []
    try:
        for index, source in enumerate(ordered_sources, start=1):
            final_url = source.final_url or source.raw_url
            title = _choose_title(source, index=index)
            validation = LinkValidationResult(final_url=final_url, status="skipped")
            if validate_identifiers:
                validation = _validate_paper_link(
                    final_url,
                    title,
                    session=network_session,
                    timeout_sec=resolve_timeout_sec,
                )
                final_url = validation.final_url
                if validation.matched_title and _uses_generic_source_title(title):
                    title = validation.matched_title
            paper_id = _choose_paper_id(final_url, title)
            paper = {
                "id": paper_id,
                "title": title,
                "abstract": _build_seed_abstract(
                    source,
                    summary_title=summary_title,
                    max_snippets=max_snippets_per_source,
                    max_chars=max_abstract_chars,
                ),
                "journal": _source_host(final_url),
                "url": final_url,
                "raw_url": source.raw_url,
                "source_host": _source_host(final_url),
                "display_url": _display_url(final_url),
                "bridge_meta": {
                    "snippet_count": len(source.snippets),
                    "document_count": len(
                        [doc for doc in source.documents if isinstance(doc, dict)]
                    ),
                    "resolved_title": source.resolved_title,
                    "content_type": source.content_type,
                    "resolution_error": source.resolution_error,
                    "link_validation_status": validation.status,
                    "link_validation_source": validation.validated_by,
                    "link_validation_reason": validation.reason,
                    "link_validation_title": validation.matched_title,
                    "link_validation_score": validation.match_score,
                },
            }
            seeds.append(
                {
                    "paper": paper,
                    "deep_research_source": {
                        "url": final_url,
                        "raw_url": source.raw_url,
                        "snippets": [item.snippet for item in source.snippets],
                    },
                }
            )
    finally:
        if network_session is not None:
            network_session.close()
    return seeds


def write_gabriel_manifest_from_deep_research(
    result: dict[str, Any],
    *,
    output_dir: Path,
    run_id: str | None = None,
    interaction_id: str | None = None,
    max_sources: int = 0,
    max_snippets_per_source: int = 4,
    snippet_context_chars: int = 220,
    max_abstract_chars: int = 4000,
    resolve_redirects: bool = True,
    resolve_timeout_sec: float = 10.0,
    validate_identifiers: bool = True,
) -> dict[str, Any]:
    normalized = coerce_deep_research_result(result)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    seeds = build_source_seeds(
        normalized,
        max_sources=max_sources,
        max_snippets_per_source=max_snippets_per_source,
        snippet_context_chars=snippet_context_chars,
        max_abstract_chars=max_abstract_chars,
        resolve_redirects=resolve_redirects,
        resolve_timeout_sec=resolve_timeout_sec,
        validate_identifiers=validate_identifiers,
    )

    run_name = run_id or (
        f"deep-research-bridge-{interaction_id}"
        if interaction_id
        else f"deep-research-bridge-{_stable_hash(json.dumps(normalized, sort_keys=True, default=str))[:12]}"
    )
    seed_path = output_dir / "seed.jsonl"
    manifest_path = output_dir / "manifest.json"
    bridge_summary_path = output_dir / "bridge_summary.json"
    result_copy_path = output_dir / "deep_research_result.json"

    with seed_path.open("w", encoding="utf-8") as handle:
        for seed in seeds:
            handle.write(json.dumps(seed, ensure_ascii=True) + "\n")

    generated_at = _utc_now_iso()
    manifest = {
        "run_id": run_name,
        "created_at": generated_at,
        "generator_version": BRIDGE_VERSION,
        "prompt_template_version": "n/a",
        "source": "deep_research_bridge",
        "source_details": {
            "interaction_id": interaction_id,
            "documents_total": len(normalized.get("documents") or []),
            "papers_selected": len(seeds),
            "resolve_redirects": bool(resolve_redirects),
            "summary_title": (
                (normalized.get("summary") or "").splitlines()[0][:200]
                if normalized.get("summary")
                else None
            ),
        },
        "query": {
            "max_sources": max_sources,
            "max_snippets_per_source": max_snippets_per_source,
            "snippet_context_chars": snippet_context_chars,
        },
        "options": {
            "max_abstract_chars": max_abstract_chars,
            "resolve_redirects": bool(resolve_redirects),
            "resolve_timeout_sec": float(resolve_timeout_sec),
        },
        "paths": {
            "run_dir": str(output_dir),
            "manifest_path": str(manifest_path),
            "seed_path": str(seed_path),
            "bridge_summary_path": str(bridge_summary_path),
            "deep_research_result_path": str(result_copy_path),
        },
        "counts": {
            "publications_selected": len(seeds),
            "shards": 1,
            "records_generated": 0,
            "records_llm": 0,
            "records_heuristic": 0,
            "llm_errors": 0,
            "llm_failure_reasons": {},
        },
        "shards": [
            {
                "shard_id": 0,
                "path": str(seed_path),
                "publications": len(seeds),
                "records": 0,
                "records_llm": 0,
                "records_heuristic": 0,
                "errors": 0,
                "failure_reasons": {},
            }
        ],
        "ingest": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
            "records_ingested": 0,
            "shards_completed": 0,
            "shards_failed": 0,
        },
    }

    summary = {
        "generated_at": generated_at,
        "run_id": run_name,
        "inputs": {
            "interaction_id": interaction_id,
            "documents_total": len(normalized.get("documents") or []),
            "resolve_redirects": bool(resolve_redirects),
            "max_sources": max_sources,
            "max_snippets_per_source": max_snippets_per_source,
            "snippet_context_chars": snippet_context_chars,
            "max_abstract_chars": max_abstract_chars,
        },
        "counts": {
            "papers_selected": len(seeds),
            "papers_with_snippets": sum(
                1
                for seed in seeds
                if int(
                    (
                        (seed.get("paper") or {})
                        .get("bridge_meta", {})
                        .get("snippet_count")
                    )
                    or 0
                )
                > 0
            ),
            "resolved_urls": sum(
                1
                for seed in seeds
                if (
                    (seed.get("paper") or {}).get("url")
                    and (seed.get("paper") or {}).get("url")
                    != (seed.get("paper") or {}).get("raw_url")
                )
            ),
        },
        "artifacts": {
            "manifest_path": str(manifest_path),
            "seed_path": str(seed_path),
            "bridge_summary_path": str(bridge_summary_path),
            "deep_research_result_path": str(result_copy_path),
        },
    }

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    bridge_summary_path.write_text(
        json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    result_copy_path.write_text(
        json.dumps(_json_safe(normalized), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return summary
