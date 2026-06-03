"""DeepXiv MCP tool: structured arXiv / PMC paper access.

Carved out of ``mcp/server.py`` as the first step of splitting that monolith
into per-domain router modules. Importing this module registers the
``deepxiv`` tool on the shared FastMCP instance via the ``@mcp.tool()``
decorator (an import side effect), so ``server.py`` imports it for its effect.

Only deepxiv-exclusive code lives here. Shared symbols (the FastMCP instance,
the ``ALLOW_NETWORK`` gate, and the ``_normalize_deep_research_*`` identifier
helpers shared with the google-deep-research domain) are imported back from
``server`` rather than duplicated.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import request as urllib_request
from urllib.parse import quote

from brain_researcher.services.mcp.param_norm import (
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)
from brain_researcher.services.mcp.server import (
    ALLOW_NETWORK,
    _normalize_deep_research_doi,
    _normalize_deep_research_pii,
    _normalize_deep_research_pmcid,
    _normalize_deep_research_pmid,
    mcp,
)

# --- Categorical-arg contract: enum advertising + synonym coercion ----------
# ``deepxiv`` has two categorical params: a required ``action`` dispatcher
# (routed through ``resolve_enum_or_error`` so an unknown value still returns a
# one-shot-discoverable structured error listing the allowed actions) and an
# optional ``search_mode`` (coerced to a safe default). ``search_mode`` canonical
# values are the wire values the DeepXiv backend accepts ("bm25", "vector",
# "hybrid"); "keyword"/"semantic" are advertised-elsewhere synonyms folded in.
_DEEPXIV_ACTION_ALIASES: dict[str, str] = {
    "search": "search",
    "search_papers": "search",
    "find": "search",
    "brief": "brief",
    "summary": "brief",
    "head": "head",
    "section": "section",
    "preview": "preview",
    "raw": "raw",
    "full_text": "raw",
    "fulltext": "raw",
    "trending": "trending",
    "social_impact": "social_impact",
    "social": "social_impact",
    "pmc_head": "pmc_head",
    "pmc_full": "pmc_full",
    "pmc_json": "pmc_full",
    "semantic_scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "s2": "semantic_scholar",
}

_DEEPXIV_SEARCH_MODE_ALIASES: dict[str, str] = {
    "hybrid": "hybrid",
    "bm25": "bm25",
    "keyword": "bm25",
    "keywords": "bm25",
    "lexical": "bm25",
    "vector": "vector",
    "semantic": "vector",
    "embedding": "vector",
    "dense": "vector",
}

_deepxiv_reader: Any = None


def _get_deepxiv_reader() -> Any:
    global _deepxiv_reader
    if _deepxiv_reader is None:
        from deepxiv_sdk import Reader

        token = os.environ.get("DEEPXIV_TOKEN", "")
        _deepxiv_reader = Reader(token=token) if token else Reader()
    return _deepxiv_reader


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [s.strip() for s in value.split(",") if s.strip()] or None


def _deepxiv_fetch_json(url: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
    req = urllib_request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "brain-researcher-mcp/1.0",
        },
    )
    with urllib_request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    return payload if isinstance(payload, dict) else {}


def _deepxiv_pubmed_esearch_pmid(term: str) -> str:
    query = quote(term, safe="")
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax=1&term={query}"
    )
    payload = _deepxiv_fetch_json(url)
    result = payload.get("esearchresult")
    if not isinstance(result, dict):
        return ""
    id_list = result.get("idlist")
    if isinstance(id_list, list) and id_list:
        candidate = str(id_list[0] or "").strip()
        return candidate if candidate.isdigit() else ""
    return ""


def _deepxiv_pmc_idconv(identifier: str) -> dict[str, Any]:
    url = (
        "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
        f"?ids={quote(identifier, safe='')}&format=json"
    )
    payload = _deepxiv_fetch_json(url)
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return {}
    record = records[0]
    return record if isinstance(record, dict) else {}


def _deepxiv_resolve_pmc_identifier(paper_id: str) -> dict[str, Any]:
    requested_id = str(paper_id or "").strip()
    resolution: dict[str, Any] = {
        "requested_id": requested_id,
        "identifier_type": "unknown",
        "pmcid": None,
        "pmid": None,
        "doi": None,
        "pii": None,
        "in_pmc": False,
    }

    pmcid = _normalize_deep_research_pmcid(requested_id)
    if pmcid:
        resolution["identifier_type"] = "pmcid"
        resolution["pmcid"] = pmcid
        resolution["in_pmc"] = True
        return {"ok": True, "paper_id": pmcid, "resolution": resolution}

    doi = _normalize_deep_research_doi(requested_id)
    pii = _normalize_deep_research_pii(requested_id)
    pmid = _normalize_deep_research_pmid(requested_id)
    if doi:
        resolution["identifier_type"] = "doi"
        resolution["doi"] = doi
    elif pii:
        resolution["identifier_type"] = "pii"
        resolution["pii"] = pii
    elif pmid:
        resolution["identifier_type"] = "pmid"
        resolution["pmid"] = pmid
    else:
        return {
            "ok": False,
            "error": "deepxiv_bad_paper_id",
            "message": (
                "pmc_* actions require a PMCID directly, or a PMID/DOI/Cell PII "
                "that can be resolved to a PMCID."
            ),
            "data": resolution,
        }

    try:
        if resolution["identifier_type"] == "doi":
            resolution["pmid"] = _deepxiv_pubmed_esearch_pmid(f"{doi}[doi]") or None
            record = _deepxiv_pmc_idconv(doi)
        elif resolution["identifier_type"] == "pii":
            resolution["pmid"] = _deepxiv_pubmed_esearch_pmid(f"{pii}[aid]") or None
            record = (
                _deepxiv_pmc_idconv(str(resolution["pmid"]))
                if resolution["pmid"]
                else {}
            )
        else:
            record = _deepxiv_pmc_idconv(str(pmid))
    except Exception as exc:
        return {
            "ok": False,
            "error": "deepxiv_identifier_resolution_failed",
            "message": (
                "Failed to resolve the provided identifier to a PMCID before "
                f"calling a PMC route: {type(exc).__name__}: {exc}"
            ),
            "data": resolution,
        }

    resolved_pmcid = _normalize_deep_research_pmcid(record.get("pmcid"))
    resolved_pmid = _normalize_deep_research_pmid(
        record.get("pmid") or resolution.get("pmid")
    )
    resolved_doi = _normalize_deep_research_doi(
        record.get("doi") or resolution.get("doi")
    )
    if resolved_pmcid:
        resolution["pmcid"] = resolved_pmcid
        resolution["pmid"] = resolved_pmid or resolution.get("pmid")
        resolution["doi"] = resolved_doi or resolution.get("doi")
        resolution["in_pmc"] = True
        return {"ok": True, "paper_id": resolved_pmcid, "resolution": resolution}

    if resolved_pmid:
        resolution["pmid"] = resolved_pmid
    if resolved_doi:
        resolution["doi"] = resolved_doi
    return {
        "ok": False,
        "error": "deepxiv_pmc_unavailable",
        "message": "The provided identifier does not resolve to a PMCID.",
        "data": resolution,
    }


def _deepxiv_build_pmc_resolution_error(
    action: str, resolution_result: dict[str, Any]
) -> dict[str, Any]:
    data = resolution_result.get("data")
    details = data if isinstance(data, dict) else {}
    requested_id = str(details.get("requested_id") or "").strip()
    identifier_type = str(details.get("identifier_type") or "identifier").strip()
    pmid = str(details.get("pmid") or "").strip()
    doi = str(details.get("doi") or "").strip()
    pii = str(details.get("pii") or "").strip()
    parts = [f"{action} requires a PMCID."]
    if requested_id:
        parts.append(f"Received {identifier_type or 'identifier'} '{requested_id}'.")
    if pii and pii != requested_id:
        parts.append(f"Resolved Cell/Elsevier PII {pii}.")
    if pmid and pmid != requested_id:
        parts.append(f"Resolved PMID {pmid}.")
    if doi and doi != requested_id:
        parts.append(f"Resolved DOI {doi}.")
    if resolution_result.get("error") == "deepxiv_pmc_unavailable":
        parts.append("The article does not appear to be available in PubMed Central.")
    elif resolution_result.get("message"):
        parts.append(str(resolution_result["message"]).strip())
    parts.append(
        "Pass a PMCID for pmc_* actions, or use a non-PMC route for metadata-only "
        "lookups."
    )
    return {
        "ok": False,
        "error": resolution_result.get("error") or "deepxiv_bad_request",
        "message": " ".join(part for part in parts if part),
        "data": details,
    }


@mcp.tool()
def deepxiv(
    action: enum_str(
        (
            "search",
            "brief",
            "head",
            "section",
            "preview",
            "raw",
            "trending",
            "social_impact",
            "pmc_head",
            "pmc_full",
            "semantic_scholar",
        ),
        "DeepXiv action to perform",
    ),
    query: str | None = None,
    paper_id: str | None = None,
    section_name: str | None = None,
    limit: int = 10,
    search_mode: enum_str(
        ("hybrid", "vector", "bm25"),
        "search ranking mode ('bm25'/'keyword', 'vector'/'semantic', 'hybrid')",
    ) = "hybrid",
    categories: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    authors: str | None = None,
    min_citation: int | None = None,
    days: int = 7,
) -> dict[str, Any]:
    """Search and read arXiv / PMC papers via DeepXiv.

    Actions: search, brief, head, section, preview, raw, trending,
    social_impact, pmc_head, pmc_full, semantic_scholar.
    """
    if not ALLOW_NETWORK:
        return {
            "ok": False,
            "error": "network_blocked",
            "message": "Set BR_MCP_ALLOW_NETWORK=1 to enable DeepXiv API.",
        }

    action, action_err = resolve_enum_or_error(
        action, _DEEPXIV_ACTION_ALIASES, field="action"
    )
    if action_err is not None:
        return action_err
    search_mode = coerce_enum(
        search_mode, _DEEPXIV_SEARCH_MODE_ALIASES, "hybrid"
    )

    try:
        reader = _get_deepxiv_reader()
    except Exception as exc:
        return {"ok": False, "error": "deepxiv_import_error", "message": str(exc)}

    try:
        if action == "search":
            if not query:
                return {"ok": False, "error": "missing_query"}
            result = reader.search(
                query,
                size=limit,
                search_mode=search_mode,
                categories=_parse_csv(categories),
                authors=_parse_csv(authors),
                min_citation=min_citation,
                date_from=date_from,
                date_to=date_to,
            )
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "brief":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            result = reader.brief(paper_id)
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "head":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            result = reader.head(paper_id)
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "section":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            if not section_name:
                return {"ok": False, "error": "missing_section_name"}
            content = reader.section(paper_id, section_name)
            return {"ok": True, "content": content}

        elif action == "preview":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            result = reader.preview(paper_id)
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "raw":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            content = reader.raw(paper_id)
            return {"ok": True, "content": content}

        elif action == "trending":
            result = reader.trending(days=days, limit=limit)
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "social_impact":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            result = reader.social_impact(paper_id)
            if result is None:
                return {"ok": True, "data": None}
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "pmc_head":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            resolved = _deepxiv_resolve_pmc_identifier(paper_id)
            if resolved.get("ok") is not True:
                return _deepxiv_build_pmc_resolution_error(action, resolved)
            result = reader.pmc_head(str(resolved["paper_id"]))
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "pmc_full":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            resolved = _deepxiv_resolve_pmc_identifier(paper_id)
            if resolved.get("ok") is not True:
                return _deepxiv_build_pmc_resolution_error(action, resolved)
            result = reader.pmc_json(str(resolved["paper_id"]))
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        elif action == "semantic_scholar":
            if not paper_id:
                return {"ok": False, "error": "missing_paper_id"}
            result = reader.semantic_scholar(paper_id)
            return (
                {"ok": True, **result}
                if isinstance(result, dict)
                else {"ok": True, "data": result}
            )

        else:
            return {"ok": False, "error": f"unknown_action: {action}"}

    except Exception as exc:
        exc_type = type(exc).__name__
        error_key = {
            "AuthenticationError": "deepxiv_auth_error",
            "RateLimitError": "deepxiv_rate_limit",
            "NotFoundError": "deepxiv_not_found",
            "BadRequestError": "deepxiv_bad_request",
            "ServerError": "deepxiv_server_error",
        }.get(exc_type, "deepxiv_error")
        return {"ok": False, "error": error_key, "message": str(exc)}
