"""Deep Research provider interface and caching utilities."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_RECENCY_DAYS = 180
DEFAULT_TOP_K = 10
DEFAULT_LANGUAGE = "en"
DEFAULT_LITERATURE_PROVIDER = "google_deep_research"
DEFAULT_AGENT = os.environ.get(
    "BR_DEEP_RESEARCH_AGENT", "deep-research-pro-preview-12-2025"
)
DEFAULT_FALLBACK_AGENT = os.environ.get(
    "BR_DEEP_RESEARCH_FALLBACK_AGENT", "deep-research"
)

_RECENT_KEYWORDS = (
    "latest",
    "recent",
    "today",
    "this year",
    "最新",
    "最近",
    "今天",
    "今年",
)


def _resolve_literature_provider(provider: Optional[str]) -> str:
    if provider:
        return provider
    return os.environ.get("BR_LITERATURE_PROVIDER", DEFAULT_LITERATURE_PROVIDER)


_SEMINAL_KEYWORDS = (
    "seminal",
    "foundational",
    "classic",
    "original",
    "奠基",
    "经典",
    "原始",
)

_URL_RE = re.compile(r"https?://[^\s\)\]\}<>]+")
_OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/_=-]{32,}$")
_TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "igshid",
}
_SEARCH_TRAIL_MAX = 80
_COMPLETED_INTERACTION_STATUSES = {"completed", "done", "succeeded", "success"}
_TERMINAL_ERROR_INTERACTION_STATUSES = {
    "cancelled",
    "canceled",
    "failed",
    "expired",
    "rejected",
}
_AGENT_ERROR_HINTS = (
    "agent",
    "invalid",
    "unknown",
    "not found",
    "unsupported",
    "does not exist",
    "unrecognized",
    "unrecognised",
    "missing",
)
_EXCEPTION_STATUS_ATTRS = ("status_code", "status", "code")
_EXCEPTION_RESPONSE_ATTRS = ("response", "http_response")
_PRIMARY_HOST_PATTERNS = (
    re.compile(r"(?:^|\.)doi\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)pubmed\.ncbi\.nlm\.nih\.gov$", re.IGNORECASE),
    re.compile(r"(?:^|\.)ncbi\.nlm\.nih\.gov$", re.IGNORECASE),
    re.compile(r"(?:^|\.)arxiv\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)biorxiv\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)medrxiv\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)nature\.com$", re.IGNORECASE),
    re.compile(r"(?:^|\.)science\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)cell\.com$", re.IGNORECASE),
    re.compile(r"(?:^|\.)openneuro\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)dandiarchive\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)zenodo\.org$", re.IGNORECASE),
    re.compile(r"(?:^|\.)figshare\.com$", re.IGNORECASE),
)
_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.IGNORECASE)
_PMID_PATTERN = re.compile(r"\bpmid[:\s]*\d{4,}\b", re.IGNORECASE)
_ARXIV_ID_PATTERN = re.compile(
    r"\barxiv\.org/(abs|pdf)/\d{4}\.\d{4,5}\b", re.IGNORECASE
)
_DATASET_ID_PATTERN = re.compile(
    r"\b(openneuro\.org/datasets/[a-z0-9_-]+|dandiarchive\.org/dandiset/\d{6}|zenodo\.org/record/\d+)\b",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _artifact_dir() -> Path:
    override = os.environ.get("BR_DEEP_RESEARCH_DIR")
    if override:
        return Path(override).expanduser()
    return _repo_root() / "artifacts" / "deep_research"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().split())


def _normalize_interaction_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-]+", "_", text)


def _sanitize_error_message(message: Any) -> str:
    sanitized = str(message or "")
    for env_key in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        secret = os.environ.get(env_key)
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = re.sub(r"AIza[0-9A-Za-z\-_]{20,}", "[REDACTED]", sanitized)
    sanitized = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]+", r"\1[REDACTED]", sanitized
    )
    sanitized = re.sub(
        r"(?i)(api[_-]?key['\"=:\s]+)[A-Za-z0-9._\-+/=]+", r"\1[REDACTED]", sanitized
    )
    return sanitized.strip()


def _coerce_status_code(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_exception_status_code(exc: Exception) -> Optional[int]:
    for attr in _EXCEPTION_STATUS_ATTRS:
        code = _coerce_status_code(getattr(exc, attr, None))
        if code is not None:
            return code
    for response_attr in _EXCEPTION_RESPONSE_ATTRS:
        response_obj = getattr(exc, response_attr, None)
        if response_obj is None:
            continue
        for attr in _EXCEPTION_STATUS_ATTRS:
            code = _coerce_status_code(getattr(response_obj, attr, None))
            if code is not None:
                return code
    return None


def _exception_payload(exc: Exception, *, context: str) -> Dict[str, Any]:
    error_type = exc.__class__.__name__
    message = _sanitize_error_message(str(exc))
    formatted = f"{error_type}: {message}" if message else error_type
    payload: Dict[str, Any] = {
        "error": f"{context} failed: {formatted}",
        "message": message or f"{context} failed",
        "error_type": error_type,
    }
    status_code = _extract_exception_status_code(exc)
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def _is_agent_configuration_error(message: str, status_code: Optional[int]) -> bool:
    lowered = (message or "").strip().lower()
    if not lowered and status_code is None:
        return False
    if status_code in {404, 422}:
        return True
    if status_code == 400 and ("agent" in lowered or "assistant" in lowered):
        return True
    hint_hits = sum(1 for hint in _AGENT_ERROR_HINTS if hint in lowered)
    if hint_hits >= 2:
        return True
    return False


def _agent_retry_candidates(agent: str) -> List[str]:
    primary = (agent or "").strip()
    env_fallback = (os.environ.get("BR_DEEP_RESEARCH_FALLBACK_AGENT") or "").strip()
    fallback_default = (DEFAULT_FALLBACK_AGENT or "").strip()
    candidates: List[str] = []
    for candidate in (primary, env_fallback, fallback_default, "deep-research"):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def apply_recency_policy(query: str, recency_days: Optional[int]) -> Optional[int]:
    if not query:
        return recency_days
    lowered = query.lower()
    if any(k in lowered for k in _SEMINAL_KEYWORDS):
        return None
    if any(k in lowered for k in _RECENT_KEYWORDS):
        return 30
    return recency_days


def build_idempotency_key(
    *,
    query: str,
    intent: str,
    recency_days: Optional[int],
    top_k: int,
    exclude_domains: Optional[Iterable[str]],
    language: str,
    provider: str = "google_deep_research",
    model: Optional[str] = None,
) -> str:
    payload = {
        "query": _normalize_query(query),
        "intent": intent,
        "recency_days": recency_days,
        "top_k": top_k,
        "exclude_domains": sorted(set(exclude_domains or [])),
        "language": language,
        "provider": provider,
        "model": model,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _artifact_path(idempotency_key: str) -> Path:
    return _artifact_dir() / f"{idempotency_key}.json"


def _pending_path(idempotency_key: str) -> Path:
    return _artifact_dir() / f"{idempotency_key}.pending.json"


def _json_safe(value: Any) -> Any:
    """Convert nested payloads to JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(inner) for inner in value]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _json_safe(value.dict())
        except Exception:
            pass
    return str(value)


def load_cached_result(idempotency_key: str) -> Optional[Dict[str, Any]]:
    path = _artifact_path(idempotency_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_result(idempotency_key: str, payload: Dict[str, Any]) -> None:
    path = _artifact_path(idempotency_key)
    _ensure_dir(path.parent)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=True, indent=2))


def save_pending(idempotency_key: str, payload: Dict[str, Any]) -> None:
    path = _pending_path(idempotency_key)
    _ensure_dir(path.parent)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=True, indent=2))


def load_pending(idempotency_key: str) -> Optional[Dict[str, Any]]:
    path = _pending_path(idempotency_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _is_opaque_token_like(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return False
    if any(char.isspace() for char in text):
        return False
    if text.upper().startswith("AUZIYQ") and len(text) >= 24:
        return True
    if len(text) < 40 or not _OPAQUE_TOKEN_RE.match(text):
        return False
    # High-entropy token-like strings (base64/base64url-ish) with no natural separators.
    if "." not in text and "/" not in text:
        return True
    return text.count("_") + text.count("-") >= 2 and len(text) >= 56


def _collect_preferred_text_candidates(
    payload: Any, candidates: List[str], *, accept_raw_strings: bool = False
) -> None:
    if payload is None:
        return
    if isinstance(payload, str):
        if accept_raw_strings:
            candidates.append(payload)
        return
    if isinstance(payload, list):
        for item in payload:
            _collect_preferred_text_candidates(
                item, candidates, accept_raw_strings=accept_raw_strings
            )
        return

    if isinstance(payload, dict):
        for key in ("text", "output_text", "summary", "content", "output"):
            value = payload.get(key)
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, (dict, list)):
                _collect_preferred_text_candidates(
                    value, candidates, accept_raw_strings=True
                )
        for key, value in payload.items():
            if key in {"text", "output_text", "summary", "content", "output"}:
                continue
            if isinstance(value, (dict, list)):
                _collect_preferred_text_candidates(
                    value, candidates, accept_raw_strings=False
                )


def _find_text(payload: Any) -> str:
    candidates: List[str] = []
    _collect_preferred_text_candidates(payload, candidates, accept_raw_strings=False)

    fallback = ""
    for candidate in candidates:
        normalized = _normalize_text(candidate)
        if not normalized:
            continue
        if not fallback:
            fallback = normalized
        if _is_opaque_token_like(normalized):
            continue
        return normalized
    if fallback and not _is_opaque_token_like(fallback):
        return fallback
    return ""


def _parse_search_trails(payload: Any) -> List[Dict[str, str]]:
    if not isinstance(payload, list):
        return []

    parsed: List[Dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip().lower() or "poll"
        if stage not in {"start", "poll", "sync_fallback"}:
            stage = "poll"
        tool = str(item.get("tool") or "").strip() or "deep_research"
        status = str(item.get("status") or "").strip() or "unknown"
        detail_raw = item.get("detail")
        detail = detail_raw.strip() if isinstance(detail_raw, str) else ""
        record = {
            "stage": stage,
            "tool": tool,
            "status": status,
            "detail": detail,
        }
        ts = item.get("ts")
        if isinstance(ts, str) and ts.strip():
            record["ts"] = ts.strip()
        parsed.append(record)

    return parsed


def _dedupe_trails(trails: List[Dict[str, str]]) -> List[Dict[str, str]]:
    unique: List[Dict[str, str]] = []
    seen = set()
    for entry in trails:
        key = "|".join(
            [
                entry.get("stage", ""),
                entry.get("tool", ""),
                entry.get("status", ""),
                entry.get("detail", ""),
                entry.get("ts", ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    if len(unique) > _SEARCH_TRAIL_MAX:
        return unique[-_SEARCH_TRAIL_MAX:]
    return unique


def _append_trail(
    trails: List[Dict[str, str]],
    *,
    stage: str,
    tool: str,
    status: str,
    detail: str,
) -> List[Dict[str, str]]:
    next_trails = list(trails)
    next_trails.append(
        {
            "stage": stage if stage in {"start", "poll", "sync_fallback", "sync_deepxiv"} else "poll",
            "tool": tool or "deep_research",
            "status": status or "unknown",
            "detail": detail,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(next_trails) > _SEARCH_TRAIL_MAX:
        return next_trails[-_SEARCH_TRAIL_MAX:]
    return next_trails


def _with_cache_hit_trail(
    result: Dict[str, Any], *, stage: str, tool: str
) -> Dict[str, Any]:
    copied = dict(result or {})
    existing = _parse_search_trails(copied.get("search_trails"))
    copied["search_trails"] = _append_trail(
        existing,
        stage=stage,
        tool=tool,
        status="cached",
        detail="Served from idempotency cache.",
    )
    return copied


def _extract_urls(text: str) -> List[str]:
    return list(dict.fromkeys(_URL_RE.findall(text or "")))


def _canonicalize_url(url: Optional[str]) -> Optional[str]:
    if not isinstance(url, str):
        return None
    candidate = url.strip()
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
    except Exception:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    hostname = re.sub(r"^www\.", "", (parsed.hostname or "").lower())
    if not hostname:
        return None
    port = parsed.port
    keep_port = bool(
        port
        and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        )
    )
    netloc = f"{hostname}:{port}" if keep_port else hostname
    path = parsed.path or "/"
    if path == "/":
        path = ""
    cleaned_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_QUERY_KEYS
    ]
    cleaned_query.sort(key=lambda kv: kv[0].lower())
    query = urlencode(cleaned_query, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _source_host(url: Optional[str]) -> Optional[str]:
    canonical = _canonicalize_url(url)
    if not canonical:
        return None
    try:
        host = urlsplit(canonical).hostname or ""
    except Exception:
        return None
    if not host:
        return None
    return re.sub(r"^www\.", "", host, flags=re.IGNORECASE)


def _display_url(url: Optional[str], max_len: int = 96) -> Optional[str]:
    canonical = _canonicalize_url(url)
    if not canonical:
        return None
    try:
        parsed = urlsplit(canonical)
    except Exception:
        return None
    host = re.sub(r"^www\.", "", parsed.hostname or "", flags=re.IGNORECASE)
    if not host:
        return None
    suffix = f"{parsed.path}{('?' + parsed.query) if parsed.query else ''}".rstrip("/")
    text = f"{host}{suffix}"
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _infer_source_type(url: Optional[str], title: Optional[str]) -> str:
    value = f"{url or ''} {title or ''}".lower()
    if any(k in value for k in ("openneuro", "dandi", "figshare", "zenodo", "dataset")):
        return "dataset"
    if any(
        k in value
        for k in ("pubmed", "doi.org", "arxiv", "biorxiv", "journal", "paper")
    ):
        return "paper"
    return "other"


def _has_stable_identifier(url: Optional[str], title: Optional[str]) -> bool:
    combined = f"{url or ''} {title or ''}".lower()
    return bool(
        _DOI_PATTERN.search(combined)
        or _PMID_PATTERN.search(combined)
        or _ARXIV_ID_PATTERN.search(combined)
        or _DATASET_ID_PATTERN.search(combined)
    )


def _has_primary_host(url: Optional[str]) -> bool:
    host = _source_host(url)
    if not host:
        return False
    return any(pattern.search(host) for pattern in _PRIMARY_HOST_PATTERNS)


def _compute_quality_summary(
    documents: List[Dict[str, Any]], text: str
) -> Dict[str, Any]:
    citable_count = 0
    primary_count = 0

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        url_value = doc.get("url") or doc.get("raw_url")
        canonical = _canonicalize_url(url_value) if isinstance(url_value, str) else None
        if not canonical:
            continue
        citable_count += 1
        title = doc.get("title") if isinstance(doc.get("title"), str) else None
        if _has_primary_host(canonical) or _has_stable_identifier(canonical, title):
            primary_count += 1

    has_text = bool((text or "").strip())
    return {
        "has_text": has_text,
        "citable_count": citable_count,
        "primary_count": primary_count,
    }


def _pick_first_str(record: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _extract_url_documents(raw_payload: Any) -> List[Dict[str, Any]]:
    url_keys = (
        "url",
        "uri",
        "link",
        "href",
        "source_url",
        "sourceUrl",
        "canonical_url",
        "canonicalUrl",
    )
    title_keys = ("title", "name", "label")
    snippet_keys = ("snippet", "summary", "text", "content", "quote")
    publisher_keys = ("publisher", "site_name", "siteName", "domain")
    published_at_keys = ("published_at", "publishedAt", "date", "published")

    documents: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    def _add_document(
        url: Optional[str],
        *,
        title: Optional[str],
        snippet: Optional[str],
        publisher: Optional[str],
        published_at: Optional[str],
    ) -> None:
        canonical = _canonicalize_url(url)
        if not canonical:
            return
        key = canonical.lower()
        if key in seen_urls:
            return
        seen_urls.add(key)
        documents.append(
            {
                "doc_id": f"doc_{len(documents) + 1}",
                "title": title,
                "url": canonical,
                "raw_url": url.strip()
                if isinstance(url, str) and url.strip()
                else canonical,
                "source_host": _source_host(canonical),
                "display_url": _display_url(canonical),
                "source_type": _infer_source_type(canonical, title),
                "publisher": publisher,
                "published_at": published_at,
                "snippets": [snippet] if snippet else [],
            }
        )

    def _visit(node: Any, parent: Optional[Dict[str, Any]] = None) -> None:
        if isinstance(node, list):
            for item in node:
                _visit(item, parent)
            return

        if isinstance(node, str):
            for url in _extract_urls(node):
                _add_document(
                    url,
                    title=_pick_first_str(parent or {}, title_keys),
                    snippet=_pick_first_str(parent or {}, snippet_keys),
                    publisher=_pick_first_str(parent or {}, publisher_keys),
                    published_at=_pick_first_str(parent or {}, published_at_keys),
                )
            return

        if not isinstance(node, dict):
            return

        direct_url = _pick_first_str(node, url_keys)
        if direct_url:
            _add_document(
                direct_url,
                title=_pick_first_str(node, title_keys),
                snippet=_pick_first_str(node, snippet_keys),
                publisher=_pick_first_str(node, publisher_keys),
                published_at=_pick_first_str(node, published_at_keys),
            )

        for value in node.values():
            _visit(value, node)

    _visit(raw_payload)
    return documents


def _parse_deep_research_output(
    raw_payload: Dict[str, Any],
    *,
    provider: str,
    model: Optional[str],
    recency_days: Optional[int],
    idempotency_key: str,
) -> Dict[str, Any]:
    text = _find_text(raw_payload)
    search_trails = _parse_search_trails(
        raw_payload.get("search_trails") if isinstance(raw_payload, dict) else None
    ) or _parse_search_trails(
        raw_payload.get("searchTrails") if isinstance(raw_payload, dict) else None
    )
    documents = _extract_url_documents(raw_payload)
    if not documents:
        urls = _extract_urls(text)
        documents = [
            {
                "doc_id": f"doc_{idx + 1}",
                "title": None,
                "url": _canonicalize_url(url) or url,
                "raw_url": url,
                "source_host": _source_host(url),
                "display_url": _display_url(url),
                "source_type": _infer_source_type(url, None),
                "publisher": None,
                "published_at": None,
                "snippets": [],
            }
            for idx, url in enumerate(urls)
        ]

    summary = text[:600] if text else ""
    quality = _compute_quality_summary(documents, text)
    has_useful_content = (
        bool(quality.get("has_text")) or int(quality.get("citable_count") or 0) > 0
    )
    status = "ok" if has_useful_content else "partial"
    status_reason = None if has_useful_content else "insufficient_content"

    return {
        "status": status,
        "status_reason": status_reason,
        "summary": summary,
        "synthesis_full_text": text or summary,
        "documents": documents,
        "claims": [],
        "quality": quality,
        "raw": raw_payload,
        "search_trails": _dedupe_trails(search_trails),
        "metadata": {
            "provider": provider,
            "model": model,
            "recency_days": recency_days,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": idempotency_key,
        },
    }


def _terminal_status_message(status: str, raw_payload: Any) -> str:
    fallback = f"Interaction reached terminal status '{status}'."
    if isinstance(raw_payload, dict):
        for key in (
            "error",
            "message",
            "detail",
            "reason",
            "failure_reason",
            "failureReason",
            "status_message",
            "statusMessage",
        ):
            value = raw_payload.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)[:500]
            if isinstance(value, dict):
                nested = _find_text(value)
                if nested:
                    return nested[:500]
    text = _find_text(raw_payload)
    if text:
        return text[:500]
    return fallback


def _resolve_file_search_stores(stores: Optional[Iterable[str]]) -> List[str]:
    if stores:
        store_list = list(stores)
    else:
        multi = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
        if multi:
            store_list = [s.strip() for s in multi.split(",") if s.strip()]
        else:
            store = (
                os.environ.get("FILE_SEARCH_STORE")
                or os.environ.get("BR_FILE_SEARCH_STORE")
                or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
                or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
            )
            store_list = [store] if store else []
    normalized = []
    for name in store_list:
        if not name:
            continue
        normalized.append(
            name if name.startswith("fileSearchStores/") else f"fileSearchStores/{name}"
        )
    return normalized


def _provider_start_google(
    *,
    prompt: str,
    agent: str,
    file_search_store_names: Optional[List[str]],
    previous_interaction_id: Optional[str],
) -> Dict[str, Any]:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Set GOOGLE_API_KEY or GEMINI_API_KEY.",
        }
    try:
        from google import genai
    except Exception as exc:
        return {"ok": False, **_exception_payload(exc, context="google-genai import")}

    client = genai.Client(api_key=api_key)
    if not hasattr(client, "interactions"):
        return {
            "ok": False,
            "error": "interactions_not_supported",
            "message": "Upgrade google-genai >= 1.55.0 for Interactions API.",
        }

    tools: List[Dict[str, Any]] = [{"type": "google_search"}]
    stores = _resolve_file_search_stores(file_search_store_names)
    if stores:
        tools.append({"type": "file_search", "file_search_store_names": stores})

    payload = {
        "input": prompt,
        "background": True,
    }
    if tools:
        payload["tools"] = tools
    if previous_interaction_id:
        payload["previous_interaction_id"] = previous_interaction_id

    agent_candidates = _agent_retry_candidates(agent)
    if not agent_candidates:
        agent_candidates = ["deep-research"]

    attempted_agents: List[str] = []
    last_error: Optional[Dict[str, Any]] = None

    for idx, candidate in enumerate(agent_candidates):
        attempted_agents.append(candidate)
        payload["agent"] = candidate
        try:
            interaction = client.interactions.create(**payload)
            interaction_id = getattr(interaction, "id", None) or getattr(
                interaction, "name", None
            )
            status = getattr(interaction, "status", None) or getattr(
                interaction, "state", None
            )
            response = (
                interaction.model_dump()
                if hasattr(interaction, "model_dump")
                else {"raw": str(interaction)}
            )
            return {
                "ok": True,
                "data": {
                    "interaction_id": interaction_id,
                    "status": status,
                    "response": response,
                    "agent": candidate,
                    "fallback_agent_used": idx > 0,
                },
            }
        except Exception as exc:
            error_payload = _exception_payload(exc, context="interactions.create")
            error_payload["attempted_agent"] = candidate
            error_payload["attempted_agents"] = list(attempted_agents)
            last_error = error_payload

            if idx >= len(agent_candidates) - 1:
                break
            if not _is_agent_configuration_error(
                error_payload.get("message", ""),
                _coerce_status_code(error_payload.get("status_code")),
            ):
                break

    if last_error:
        return {"ok": False, **last_error}
    return {"ok": False, "error": "interactions.create failed: unknown error"}


def _provider_get_google(interaction_id: str) -> Dict[str, Any]:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Set GOOGLE_API_KEY or GEMINI_API_KEY.",
        }
    try:
        from google import genai
    except Exception as exc:
        return {"ok": False, **_exception_payload(exc, context="google-genai import")}

    client = genai.Client(api_key=api_key)
    if not hasattr(client, "interactions"):
        return {
            "ok": False,
            "error": "interactions_not_supported",
            "message": "Upgrade google-genai >= 1.55.0 for Interactions API.",
        }

    try:
        try:
            interaction = client.interactions.get(interaction_id)
        except TypeError:
            interaction = client.interactions.get(name=interaction_id)
        interaction_id_out = getattr(interaction, "id", None) or getattr(
            interaction, "name", None
        )
        status = getattr(interaction, "status", None) or getattr(
            interaction, "state", None
        )
        response = (
            interaction.model_dump()
            if hasattr(interaction, "model_dump")
            else {"raw": str(interaction)}
        )
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id_out or interaction_id,
                "status": status,
                "response": response,
            },
        }
    except Exception as exc:
        return {"ok": False, **_exception_payload(exc, context="interactions.get")}


# ---------------------------------------------------------------------------
# DeepXiv sync provider
# ---------------------------------------------------------------------------


def _provider_sync_deepxiv(
    request: Dict[str, Any],
    *,
    idempotency_key: str,
) -> Dict[str, Any]:
    """Synchronous DeepXiv provider: search + brief for each hit."""
    query = _normalize_query(request.get("query", ""))
    if not query:
        return {"status": "error", "error": "missing_query"}

    recency_days = request.get("recency_days")
    top_k = int(request.get("top_k") or DEFAULT_TOP_K)

    try:
        from deepxiv_sdk import Reader
    except ImportError as exc:
        return {
            "status": "error",
            "error": "deepxiv_import_error",
            "message": str(exc),
        }

    token = os.environ.get("DEEPXIV_TOKEN", "")
    reader = Reader(token=token) if token else Reader()

    # Build search kwargs
    search_kwargs: Dict[str, Any] = {
        "size": min(top_k, 30),
        "search_mode": request.get("search_mode") or "hybrid",
    }
    categories = request.get("categories")
    if isinstance(categories, str):
        categories = [s.strip() for s in categories.split(",") if s.strip()]
    if categories:
        search_kwargs["categories"] = categories
    if request.get("date_from"):
        search_kwargs["date_from"] = request["date_from"]
    if request.get("date_to"):
        search_kwargs["date_to"] = request["date_to"]
    if recency_days is not None and int(recency_days) > 0:
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(recency_days))).strftime(
            "%Y-%m-%d"
        )
        search_kwargs.setdefault("date_from", cutoff)

    try:
        search_result = reader.search(query, **search_kwargs)
    except Exception as exc:
        return {
            "status": "error",
            "error": "deepxiv_search_error",
            "message": str(exc),
        }

    # Extract papers from search result
    papers: list = []
    if isinstance(search_result, dict):
        papers = search_result.get("results") or search_result.get("papers") or []
    elif isinstance(search_result, list):
        papers = search_result

    # Build normalized documents
    documents: List[Dict[str, Any]] = []
    tldrs: list = []
    for idx, paper in enumerate(papers[:top_k]):
        arxiv_id = (
            paper.get("arxiv_id")
            or paper.get("id")
            or paper.get("paper_id")
            or f"unknown_{idx}"
        )
        title = paper.get("title") or ""
        tldr = paper.get("tldr") or paper.get("abstract") or ""
        published_at = paper.get("publish_at") or paper.get("published_at") or None

        documents.append(
            {
                "doc_id": f"arxiv_{arxiv_id}",
                "title": title,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "raw_url": f"https://arxiv.org/abs/{arxiv_id}",
                "source_host": "arxiv.org",
                "display_url": f"arxiv.org/abs/{arxiv_id}",
                "source_type": "preprint",
                "publisher": None,
                "published_at": published_at,
                "snippets": [tldr] if tldr else [],
            }
        )
        if tldr:
            tldrs.append(f"[{arxiv_id}] {title}: {tldr[:300]}")

    synthesis = "\n\n".join(tldrs) if tldrs else ""
    summary = synthesis[:600] if synthesis else ""
    citable_count = len(documents)
    has_useful_content = citable_count > 0

    result = {
        "status": "ok" if has_useful_content else "partial",
        "status_reason": None if has_useful_content else "no_results",
        "summary": summary,
        "synthesis_full_text": synthesis,
        "documents": documents,
        "claims": [],
        "quality": {
            "has_text": bool(synthesis),
            "citable_count": citable_count,
            "primary_count": citable_count,
        },
        "raw": search_result,
        "search_trails": _dedupe_trails(
            _append_trail(
                [],
                stage="sync_deepxiv",
                tool="deepxiv_search",
                status="ok" if has_useful_content else "partial",
                detail=f"DeepXiv search returned {citable_count} papers.",
            )
        ),
        "metadata": {
            "provider": "deepxiv",
            "model": None,
            "recency_days": recency_days,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": idempotency_key,
        },
    }

    save_result(idempotency_key, result)
    return {
        "status": result["status"],
        "idempotency_key": idempotency_key,
        "result": result,
    }


def deep_research_start(request: Dict[str, Any]) -> Dict[str, Any]:
    query = _normalize_query(request.get("query", ""))
    intent = request.get("intent") or "deep_research"
    recency_days = apply_recency_policy(
        query, request.get("recency_days", DEFAULT_RECENCY_DAYS)
    )
    top_k = int(request.get("top_k") or DEFAULT_TOP_K)
    exclude_domains = request.get("exclude_domains") or []
    language = request.get("language") or DEFAULT_LANGUAGE
    provider = _resolve_literature_provider(request.get("provider"))
    model = request.get("model")

    if provider == "deepxiv":
        return {
            "status": "error",
            "error": "unsupported_provider",
            "message": "DeepXiv is sync-only; use deep_research_sync with provider=deepxiv.",
        }

    idempotency_key = request.get("idempotency_key") or build_idempotency_key(
        query=query,
        intent=intent,
        recency_days=recency_days,
        top_k=top_k,
        exclude_domains=exclude_domains,
        language=language,
        provider=provider,
        model=model,
    )

    cached = load_cached_result(idempotency_key)
    if cached:
        return {
            "status": "cached",
            "idempotency_key": idempotency_key,
            "result": _with_cache_hit_trail(
                cached, stage="start", tool="google_deep_research_start"
            ),
            "cached": True,
        }

    prompt = query
    if recency_days is not None and int(recency_days) > 0:
        prompt = f"Prefer sources from the last {int(recency_days)} days.\n{query}"
    if language and language.lower() != "en":
        prompt = f"Answer in {language}.\n{prompt}"

    response = _provider_start_google(
        prompt=prompt,
        agent=request.get("agent") or DEFAULT_AGENT,
        file_search_store_names=request.get("file_search_store_names"),
        previous_interaction_id=request.get("previous_interaction_id"),
    )
    if not response.get("ok"):
        error_payload = {
            "status": "error",
            "error": response.get("error"),
            "message": response.get("message"),
        }
        for key in ("error_type", "status_code", "attempted_agent", "attempted_agents"):
            if response.get(key) is not None:
                error_payload[key] = response.get(key)
        return error_payload

    data = response.get("data", {})
    interaction_id = data.get("interaction_id")
    status = data.get("status")

    start_trails = _append_trail(
        [],
        stage="start",
        tool="google_deep_research_start",
        status=(status or "pending"),
        detail="Google interactions start.",
    )
    save_pending(
        idempotency_key,
        {
            "interaction_id": interaction_id,
            "status": status,
            "request": {
                "query": query,
                "intent": intent,
                "recency_days": recency_days,
                "top_k": top_k,
                "exclude_domains": exclude_domains,
                "language": language,
                "provider": provider,
                "model": model,
            },
            "search_trails": start_trails,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "status": status or "pending",
        "interaction_id": interaction_id,
        "idempotency_key": idempotency_key,
        "cached": False,
    }


def deep_research_get(
    *,
    interaction_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    pending = load_pending(idempotency_key) or {} if idempotency_key else {}
    pending_trails = _parse_search_trails(pending.get("search_trails"))

    if idempotency_key:
        cached = load_cached_result(idempotency_key)
        if cached:
            return {
                "status": "cached",
                "idempotency_key": idempotency_key,
                "result": _with_cache_hit_trail(
                    cached, stage="poll", tool="google_deep_research_get"
                ),
                "cached": True,
            }

    if not interaction_id and idempotency_key:
        interaction_id = pending.get("interaction_id")

    if not interaction_id:
        return {"status": "error", "error": "missing_interaction_id"}

    response = _provider_get_google(interaction_id)
    if not response.get("ok"):
        error_payload = {
            "status": "error",
            "error": response.get("error"),
            "message": response.get("message"),
        }
        for key in ("error_type", "status_code"):
            if response.get(key) is not None:
                error_payload[key] = response.get(key)
        return error_payload

    data = response.get("data", {})
    status = _normalize_interaction_status(data.get("status"))
    raw_payload = data.get("response") or {}

    if status in _COMPLETED_INTERACTION_STATUSES:
        key = idempotency_key or build_idempotency_key(
            query=_normalize_query(""),
            intent="deep_research",
            recency_days=None,
            top_k=DEFAULT_TOP_K,
            exclude_domains=None,
            language=DEFAULT_LANGUAGE,
            provider="google_deep_research",
            model=None,
        )
        result = _parse_deep_research_output(
            raw_payload,
            provider="google_deep_research",
            model=None,
            recency_days=None,
            idempotency_key=key,
        )
        merged_trails = _dedupe_trails(
            pending_trails + _parse_search_trails(result.get("search_trails"))
        )
        merged_trails = _append_trail(
            merged_trails,
            stage="poll",
            tool="google_deep_research_get",
            status=status or "completed",
            detail="Interaction completed.",
        )
        result["search_trails"] = merged_trails
        save_result(key, result)
        return {
            "status": result.get("status"),
            "idempotency_key": key,
            "result": result,
        }

    if status in _TERMINAL_ERROR_INTERACTION_STATUSES:
        interaction_id_out = data.get("interaction_id") or interaction_id
        detail = _terminal_status_message(status, raw_payload)
        terminal_trails = _append_trail(
            pending_trails,
            stage="poll",
            tool="google_deep_research_get",
            status=status,
            detail=f"Interaction reached terminal status '{status}'.",
        )
        if idempotency_key:
            next_pending = dict(pending or {})
            next_pending["interaction_id"] = interaction_id_out
            next_pending["status"] = status
            next_pending["terminal_error"] = detail
            next_pending["updated_at"] = datetime.now(timezone.utc).isoformat()
            next_pending["search_trails"] = terminal_trails
            save_pending(idempotency_key, next_pending)
        return {
            "status": "error",
            "error": f"interaction_{status}",
            "message": detail,
            "interaction_status": status,
            "interaction_id": interaction_id_out,
            "idempotency_key": idempotency_key,
        }

    if idempotency_key:
        next_pending = dict(pending or {})
        next_pending["interaction_id"] = data.get("interaction_id") or interaction_id
        next_pending["status"] = status or "running"
        next_pending["updated_at"] = datetime.now(timezone.utc).isoformat()
        next_pending["search_trails"] = _append_trail(
            pending_trails,
            stage="poll",
            tool="google_deep_research_get",
            status=status or "running",
            detail="Polling interaction status.",
        )
        save_pending(idempotency_key, next_pending)

    return {
        "status": status or "running",
        "interaction_id": data.get("interaction_id") or interaction_id,
        "idempotency_key": idempotency_key,
    }


def deep_research_sync(request: Dict[str, Any]) -> Dict[str, Any]:
    """Sync fast-path (primarily for cache hits or debugging)."""
    query = _normalize_query(request.get("query", ""))
    intent = request.get("intent") or "deep_research"
    recency_days = apply_recency_policy(
        query, request.get("recency_days", DEFAULT_RECENCY_DAYS)
    )
    top_k = int(request.get("top_k") or DEFAULT_TOP_K)
    exclude_domains = request.get("exclude_domains") or []
    language = request.get("language") or DEFAULT_LANGUAGE
    provider = _resolve_literature_provider(request.get("provider"))
    model = request.get("model")

    idempotency_key = request.get("idempotency_key") or build_idempotency_key(
        query=query,
        intent=intent,
        recency_days=recency_days,
        top_k=top_k,
        exclude_domains=exclude_domains,
        language=language,
        provider=provider,
        model=model,
    )

    cached = load_cached_result(idempotency_key)
    if cached:
        cache_stage = "sync_deepxiv" if provider == "deepxiv" else "sync_fallback"
        cache_tool = "deepxiv_search" if provider == "deepxiv" else "google_deep_research_sync"
        return {
            "status": "cached",
            "idempotency_key": idempotency_key,
            "result": _with_cache_hit_trail(
                cached, stage=cache_stage, tool=cache_tool
            ),
        }

    if provider == "deepxiv":
        return _provider_sync_deepxiv(request, idempotency_key=idempotency_key)

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"status": "error", "error": "missing_api_key"}

    try:
        from google import genai
    except Exception as exc:
        payload = _exception_payload(exc, context="google-genai import")
        return {
            "status": "error",
            "error": payload.get("error"),
            "message": payload.get("message"),
            "error_type": payload.get("error_type"),
            **(
                {"status_code": payload.get("status_code")}
                if payload.get("status_code") is not None
                else {}
            ),
        }

    recency_hint = ""
    if recency_days is not None and int(recency_days) > 0:
        recency_hint = f"Prefer sources from the last {int(recency_days)} days.\n"

    system_instruction = (
        "You are a careful research assistant. Use Google Search to ground claims. "
        "Cite sources with URLs. If uncertain, say so."
    )

    prompt = (
        f"{recency_hint}Task: {query}\n\n"
        "Deliverables:\n"
        "1) Executive summary (5-10 bullets)\n"
        "2) Detailed findings with inline citations (URLs)\n"
        "3) Source list (URLs) at the end\n"
    )
    if language and language.lower() != "en":
        prompt = f"Answer in {language}.\n{prompt}"

    try:
        client = genai.Client(api_key=api_key)
        normalized_exclude_domains = [
            domain for domain in (exclude_domains or []) if domain
        ]
        try:
            if normalized_exclude_domains:
                google_search = genai.types.GoogleSearch(
                    exclude_domains=normalized_exclude_domains
                )
            else:
                google_search = genai.types.GoogleSearch()
        except TypeError:
            # Some SDK versions do not support exclude_domains in GoogleSearch().
            google_search = genai.types.GoogleSearch()
        except Exception as exc:
            if "exclude_domains" in str(exc).lower():
                google_search = genai.types.GoogleSearch()
            else:
                raise
        tools = [genai.types.Tool(google_search=google_search)]
        config = genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            response_modalities=["text"],
            max_output_tokens=int(request.get("max_output_tokens") or 2048),
            temperature=float(request.get("temperature") or 0.2),
        )
        resolved_model = (
            model or os.environ.get("DEFAULT_CODING_MODEL") or "gemini-3-flash-preview"
        )
        resp = client.models.generate_content(
            model=resolved_model, contents=prompt, config=config
        )
        payload = {"text": getattr(resp, "text", None)}
        if hasattr(resp, "model_dump"):
            payload["response"] = resp.model_dump()
    except Exception as exc:
        error_payload = _exception_payload(exc, context="models.generate_content")
        return {
            "status": "error",
            "error": error_payload.get("error"),
            "message": error_payload.get("message"),
            "error_type": error_payload.get("error_type"),
            **(
                {"status_code": error_payload.get("status_code")}
                if error_payload.get("status_code") is not None
                else {}
            ),
        }

    result = _parse_deep_research_output(
        payload,
        provider=provider,
        model=resolved_model,
        recency_days=recency_days,
        idempotency_key=idempotency_key,
    )
    result["search_trails"] = _append_trail(
        _parse_search_trails(result.get("search_trails")),
        stage="sync_fallback",
        tool="google_deep_research_sync",
        status=result.get("status") or "ok",
        detail="Synchronous deep research execution.",
    )
    save_result(idempotency_key, result)
    return {
        "status": result.get("status"),
        "idempotency_key": idempotency_key,
        "result": result,
    }


__all__ = [
    "DEFAULT_LITERATURE_PROVIDER",
    "apply_recency_policy",
    "build_idempotency_key",
    "deep_research_start",
    "deep_research_get",
    "deep_research_sync",
    "load_cached_result",
    "save_result",
]
