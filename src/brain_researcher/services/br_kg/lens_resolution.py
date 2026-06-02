"""Lens-type + disease-entity resolution helpers for the BR-KG lens API.

Carved out of ``br_kg/app.py``: the small helpers that resolve which lens a
request/entity belongs to (normalising lens aliases, looking up a lens's seed
labels / scheme filter, inferring a lens from an entity id) and that match /
expand disease entities against the disease-alias map. They own no module
state; the shared config dicts (``LENS_REGISTRY`` / ``LENS_ALIASES``) and disease
helpers (``_get_disease_alias_map`` / ``_normalize_acronym`` /
``_normalize_entity_label``) stay in ``app.py`` and are imported back lazily
inside the consuming functions, so the dependency flows one-way:
``app -> lens_resolution``.

``app.py`` re-exports every name below so existing ``app.<name>`` references and
route handlers keep resolving.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify


def _disease_entity_matches_query(entity_id: str, label: str, query: str) -> bool:
    from brain_researcher.services.br_kg.app import (
        _get_disease_alias_map,
        _normalize_acronym,
        _normalize_entity_label,
    )

    q_text = _normalize_entity_label(query, "disease")
    q_acronym = _normalize_acronym(query)
    if not q_text and not q_acronym:
        return True

    alias_entry = _get_disease_alias_map().get(entity_id, {})
    alias_terms = [*alias_entry.get("aliases", [])]
    acronym_terms = {token for token in alias_entry.get("acronyms", []) if token}

    # Fallback so search remains usable for nodes without explicit alias map entries.
    if not alias_terms:
        fallback = _normalize_entity_label(label, "disease")
        if fallback:
            alias_terms.append(fallback)

    label_norm = _normalize_entity_label(label, "disease")
    id_norm = _normalize_entity_label(entity_id, "disease")
    text_haystacks = [label_norm, id_norm, *alias_terms]

    if q_text:
        for haystack in text_haystacks:
            if haystack and q_text in haystack:
                return True

    if q_acronym:
        if q_acronym in acronym_terms:
            return True
        for term in alias_terms:
            if _normalize_acronym(term) == q_acronym:
                return True

    return False


def _disease_entity_query_mode(query: str) -> str:
    return "fast" if not str(query or "").strip() else "ranked"


def _disease_alias_candidate_ids(query: str) -> list[str]:
    from brain_researcher.services.br_kg.app import (
        _get_disease_alias_map,
        _normalize_acronym,
        _normalize_entity_label,
    )

    q_text = _normalize_entity_label(query, "disease")
    q_acronym = _normalize_acronym(query)
    if not q_text and not q_acronym:
        return []

    matches: list[str] = []
    for entity_id, alias_entry in _get_disease_alias_map().items():
        alias_terms = [
            str(value or "").strip().lower()
            for value in alias_entry.get("aliases", [])
            if str(value or "").strip()
        ]
        acronym_terms = {
            _normalize_acronym(value)
            for value in alias_entry.get("acronyms", [])
            if str(value or "").strip()
        }

        matched = False
        if q_text and any(q_text in alias for alias in alias_terms):
            matched = True
        if not matched and q_acronym:
            if q_acronym in acronym_terms:
                matched = True
            elif any(_normalize_acronym(alias) == q_acronym for alias in alias_terms):
                matched = True

        if matched:
            token = str(entity_id or "").strip()
            if token and token not in matches:
                matches.append(token)

    return matches


def _lens_not_found_response(lens: str):
    return jsonify({"error": f"unknown lens '{lens}'"}), 404


def _lens_disabled_response():
    return jsonify({"error": "lens endpoints disabled"}), 404


def _normalize_lens(lens: str) -> str:
    from brain_researcher.services.br_kg.app import LENS_ALIASES

    normalized = (lens or "").strip().lower()
    return LENS_ALIASES.get(normalized, normalized)


def _lens_seed_labels(lens: str) -> list[str]:
    from brain_researcher.services.br_kg.app import LENS_REGISTRY

    return list(LENS_REGISTRY[lens]["seed_labels"])


def _lens_scheme_filter(lens: str) -> str | None:
    from brain_researcher.services.br_kg.app import LENS_REGISTRY

    return LENS_REGISTRY[lens].get("scheme_filter")


def _infer_lens_for_entity(entity_id: str, requested_lens: str | None = None) -> str:
    from brain_researcher.services.br_kg.app import LENS_REGISTRY

    if requested_lens:
        normalized = _normalize_lens(requested_lens)
        if normalized in LENS_REGISTRY:
            return normalized
    token = (entity_id or "").strip()
    lowered = token.lower()
    if token.startswith("ONVOC_"):
        return "onvoc"
    if lowered.startswith("population:") or lowered.startswith("cohort:"):
        return "population"
    if lowered.startswith("disease:"):
        return "disease"
    if lowered.startswith("task:") or lowered.startswith("neurostore_task:"):
        return "task"
    if lowered.startswith("tf_paradigm:") or lowered.startswith("tf_"):
        return "task"
    return "task"


def _empty_paths_payload(
    entity_id: str, lens: str, warning: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity": {"id": entity_id, "lens": lens},
        "counts": {"paths": 0},
        "paths": [],
        "next_cursor": None,
    }
    if warning:
        payload["warnings"] = [warning]
    return payload
