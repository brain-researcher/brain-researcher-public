"""Intent synonym loader for catalog-driven planner.

The pure synonym-map helpers were relocated to
``services/shared/toolsagent_synonyms_loader`` so the lower ``services/tools``
layer can depend on them without importing from ``services/agent``. This module
re-exports those helpers and additionally provides ``match_intents_from_text``,
which depends on the agent-internal capability catalog and therefore stays here.

See the shared module for the synonym-file loading semantics and modality
scoping documentation.
"""

from __future__ import annotations

# Re-export the pure synonym-map helpers from the shared layer so existing
# callers (planner.*, tools.registry) keep working against this module path.
from brain_researcher.services.shared.toolsagent_synonyms_loader import (
    RE_WORD,
    _clean,
    _load_intent_synonym_map,
    clear_cache,
    get_mappings_dir,
    get_operator_synonyms,
    load_synonym_map,
    match_intents,
)


def match_intents_from_text(text: str) -> list[Intent]:
    """Return Intents matched from free text using intent synonyms."""
    from .catalog_loader import (  # lazy import to avoid cycles
        get_capability_index,
        load_intents,
    )

    intents_by_id = load_intents()
    synonym_map = _load_intent_synonym_map()

    cleaned = _clean(text or "")
    if not cleaned:
        return []

    matches: list[str] = []
    for intent_id, phrases in synonym_map.items():
        for phrase in phrases:
            if phrase in cleaned:
                matches.append(intent_id)
                break

    # Fallback: if no synonyms matched, try matching tool ids/names (NiWrap, etc.)
    if not matches:
        idx = get_capability_index()
        stop = {
            "run",
            "please",
            "use",
            "this",
            "that",
            "the",
            "a",
            "an",
            "on",
            "in",
            "with",
        }
        tokens = {tok for tok in cleaned.split() if tok not in stop and len(tok) > 2}
        for tool_id, tool in idx.by_id.items():
            tid = str(tool_id).lower()
            parts = tid.split(".")
            suffix = ".".join(parts[-2:]) if len(parts) >= 2 else tid
            if any(tok in tid or tok in suffix for tok in tokens):
                if getattr(tool, "intents", None):
                    matches.extend(tool.intents)
                else:
                    matches.append("generic_container_op")
                break

    # Preserve order of discovery and deduplicate
    seen = set()
    ordered: list[Intent] = []
    for intent_id in matches:
        if intent_id in seen:
            continue
        seen.add(intent_id)
        intent = intents_by_id.get(intent_id)
        if intent:
            ordered.append(intent)
    return ordered


__all__ = [
    "RE_WORD",
    "get_mappings_dir",
    "load_synonym_map",
    "match_intents",
    "get_operator_synonyms",
    "clear_cache",
    "match_intents_from_text",
]
