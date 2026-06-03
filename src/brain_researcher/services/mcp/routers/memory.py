"""Derived-memory MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the
``memory_write`` / ``memory_search`` / ``memory_get`` tools on the shared
FastMCP instance via the ``@mcp.tool()`` decorator (an import side effect),
so ``server.py`` imports it for its effect.

``MemoryStore`` and ``MEMORY_CARD_TYPES`` are imported from their canonical
package (the same source ``server`` uses); ``RUN_ROOT``, the response-slimming
helpers, and the search limit constants are imported back from ``server``;
``RUN_ROOT`` is read live from ``runstore``.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.services.mcp import runstore as _runstore
from brain_researcher.services.mcp.param_norm import (
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)
from brain_researcher.services.mcp.server import (
    _MEMORY_SEARCH_DEFAULT_LIMIT,
    _MEMORY_SEARCH_TEXT_LIMIT,
    _first_text_value,
    _memory_response_without_embeddings,
    _slim_memory_search_response,
    mcp,
)
from brain_researcher.services.memory import MEMORY_CARD_TYPES, MemoryStore

# Canonical memory card types (mirrors MEMORY_CARD_TYPES in services.memory.models)
# advertised on the tool schemas; aliases map common synonyms -> canonical and
# every canonical value -> itself so coercion never drops a valid value.
_MEMORY_CARD_TYPE_VALUES: tuple[str, ...] = (
    "episodic_run_memory",
    "claim_memory",
    "claim_relation_event",
    "code_review_verdict",
)
_MEMORY_CARD_TYPE_ALIASES: dict[str, str] = {
    "episodic_run_memory": "episodic_run_memory",
    "episodic": "episodic_run_memory",
    "episodic_memory": "episodic_run_memory",
    "run_memory": "episodic_run_memory",
    "run": "episodic_run_memory",
    "claim_memory": "claim_memory",
    "claim": "claim_memory",
    "claim_relation_event": "claim_relation_event",
    "claim_relation": "claim_relation_event",
    "relation_event": "claim_relation_event",
    "relation": "claim_relation_event",
    "code_review_verdict": "code_review_verdict",
    "code_review": "code_review_verdict",
    "review_verdict": "code_review_verdict",
    "review": "code_review_verdict",
    "verdict": "code_review_verdict",
}


@mcp.tool()
def memory_write(
    card_type: enum_str(_MEMORY_CARD_TYPE_VALUES, "derived memory card type"),
    card_data: dict[str, Any],
    include_embedding_vector: bool = False,
) -> dict[str, Any]:
    """Validate and persist a derived memory card or relation event."""
    supported_card_types = sorted(MEMORY_CARD_TYPES)
    try:
        normalized_type, card_type_error = resolve_enum_or_error(
            _first_text_value(card_type),
            _MEMORY_CARD_TYPE_ALIASES,
            field="card_type",
        )
        if card_type_error is not None:
            return {
                "ok": False,
                "error": "memory_write_failed",
                "message": f"unsupported memory card type: {card_type}",
                "supported_card_types": supported_card_types,
                "allowed": card_type_error.get("allowed"),
                "received": card_type_error.get("received"),
            }
        if not isinstance(card_data, dict):
            raise ValueError("card_data must be an object")
        response = MemoryStore(run_root=_runstore.RUN_ROOT).write(normalized_type, card_data)
        return _memory_response_without_embeddings(
            response,
            include_embedding_vector=include_embedding_vector,
        )
    except Exception as exc:
        payload = {"ok": False, "error": "memory_write_failed", "message": str(exc)}
        if "unsupported memory card type" in str(exc):
            payload["supported_card_types"] = supported_card_types
        return payload


@mcp.tool()
def memory_search(
    query: str = "",
    card_type: enum_str(_MEMORY_CARD_TYPE_VALUES, "filter to a derived memory card type")
    | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = _MEMORY_SEARCH_DEFAULT_LIMIT,
    include_full_cards: bool = False,
    include_embedding_vector: bool = False,
    max_card_text_chars: int = _MEMORY_SEARCH_TEXT_LIMIT,
) -> dict[str, Any]:
    """Search derived memory cards using structured filters and semantic similarity."""
    try:
        normalized_query = _first_text_value(query) or ""
        raw_type = _first_text_value(card_type)
        # card_type is optional: keep None/unset as "no filter"; coerce synonyms
        # of a supplied value to canonical (unknown -> None so it never narrows wrongly).
        normalized_type = (
            coerce_enum(raw_type, _MEMORY_CARD_TYPE_ALIASES, "") if raw_type else ""
        )
        if filters is not None and not isinstance(filters, dict):
            raise ValueError("filters must be an object when provided")
        response = MemoryStore(run_root=_runstore.RUN_ROOT).search(
            normalized_query,
            card_type=normalized_type or None,
            filters=filters,
            limit=limit,
        )
        return _slim_memory_search_response(
            response,
            include_full_cards=bool(include_full_cards),
            include_embedding_vector=bool(include_embedding_vector),
            max_card_text_chars=max_card_text_chars,
        )
    except Exception as exc:
        return {"ok": False, "error": "memory_search_failed", "message": str(exc)}


@mcp.tool()
def memory_get(
    card_id: str,
    include_embedding_vector: bool = False,
) -> dict[str, Any]:
    """Fetch one derived memory card or relation event by id."""
    try:
        normalized_card_id = _first_text_value(card_id)
        if not normalized_card_id:
            raise ValueError("card_id is required")
        response = MemoryStore(run_root=_runstore.RUN_ROOT).get(normalized_card_id)
        return _memory_response_without_embeddings(
            response,
            include_embedding_vector=include_embedding_vector,
        )
    except Exception as exc:
        return {"ok": False, "error": "memory_get_failed", "message": str(exc)}
