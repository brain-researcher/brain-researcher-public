"""Method-block normalization helpers for the GABRIEL pipeline.

This module contains pure helper functions that coerce and normalise the
structured "method block" dictionaries returned by the LLM extractor:
boolean blocks (preregistration, threshold correction, open data, ROI),
sample-size blocks, and supporting utilities (_coerce_bool,
_normalize_method_section, _normalize_method_status, ...).

All functions are private by convention (underscore-prefixed) and are
re-exported from ``gabriel_generator`` for backward compatibility.
"""

from __future__ import annotations

import re
from typing import Any


def _coerce_bool(value: Any, default: bool | None = False) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _normalize_method_section(value: Any) -> str:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    normalized = (_clean_text(value) or "").strip().lower()
    if normalized in {"abstract", "methods", "results", "discussion"}:
        return normalized
    return "unknown"


def _normalize_method_status(
    value: Any,
    *,
    allowed: set[str],
    default: str,
    aliases: dict[str, str] | None = None,
) -> str:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    normalized = (_clean_text(value) or "").strip().lower()
    if not normalized:
        return default
    alias_map = aliases or {}
    normalized = alias_map.get(normalized, normalized)
    if normalized in allowed:
        return normalized
    return default


def _normalize_method_evidence_fields(
    payload: dict[str, Any],
) -> tuple[str | None, str]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    evidence = (
        payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    )
    quote = _clean_text(payload.get("quote")) or _clean_text(evidence.get("quote"))
    section = _normalize_method_section(
        payload.get("section") or evidence.get("section")
    )
    return quote, section


def _normalize_method_boolean_block(
    value: Any,
    *,
    fallback: Any = None,
    registry: str | None = None,
    extra_field_name: str | None = None,
    extra_field_default: str | None = None,
) -> dict[str, Any]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _clean_text,  # lazy
    )

    payload = value if isinstance(value, dict) else {}
    quote, section = _normalize_method_evidence_fields(payload)
    raw_status = payload.get("status") if isinstance(value, dict) else value
    status = _normalize_method_status(
        raw_status,
        allowed={"yes", "no", "unknown"},
        default="unknown",
        aliases={
            "reported": "yes",
            "not_reported": "no",
            "clear": "yes",
            "unclear": "no",
            "true": "yes",
            "false": "no",
        },
    )
    if status == "unknown":
        fallback_bool = _coerce_bool(fallback, default=None)
        if fallback_bool is True:
            status = "yes"
        elif fallback_bool is False:
            status = "no"

    block: dict[str, Any] = {
        "status": status,
        "quote": quote,
        "section": section,
    }
    if registry is not None:
        block["registry"] = registry
    if extra_field_name:
        block[extra_field_name] = (
            _clean_text(payload.get(extra_field_name)) or extra_field_default
        )
    return block


def _normalize_method_sample_size_block(
    value: Any,
    *,
    publication: Any,  # PublicationSeed -- typed as Any to avoid circular import at module level
) -> dict[str, Any]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (  # lazy
        SAMPLE_SIZE_PATTERN,
        _coerce_int,
        _publication_blob,
    )

    payload = value if isinstance(value, dict) else {}
    quote, section = _normalize_method_evidence_fields(payload)
    raw_status = payload.get("status") if isinstance(value, dict) else None
    reported_n = _coerce_int(
        payload.get("reported_n") or payload.get("n") or payload.get("value")
    )
    if reported_n is None:
        reported_n = _sample_size_from_match(SAMPLE_SIZE_PATTERN.search(quote or ""))
    if reported_n is None and not payload and not isinstance(value, dict):
        reported_n = _sample_size_from_match(
            SAMPLE_SIZE_PATTERN.search(_publication_blob(publication))
        )
    status = _normalize_method_status(
        raw_status,
        allowed={"reported", "not_reported", "unknown"},
        default="unknown",
        aliases={
            "yes": "reported",
            "no": "not_reported",
            "true": "reported",
            "false": "not_reported",
        },
    )
    if status == "unknown" and reported_n is not None:
        status = "reported"
    return {
        "status": status,
        "reported_n": reported_n,
        "quote": quote,
        "section": section,
    }


def _normalize_method_roi_block(value: Any, *, fallback: Any = None) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    quote, section = _normalize_method_evidence_fields(payload)
    raw_status = payload.get("status") if isinstance(value, dict) else value
    status = _normalize_method_status(
        raw_status,
        allowed={"clear", "unclear", "unknown"},
        default="unknown",
        aliases={
            "yes": "clear",
            "no": "unclear",
            "true": "clear",
            "false": "unclear",
        },
    )
    if status == "unknown":
        fallback_bool = _coerce_bool(fallback, default=None)
        if fallback_bool is True:
            status = "clear"
        elif fallback_bool is False:
            status = "unclear"
    return {
        "status": status,
        "quote": quote,
        "section": section,
    }


def _normalize_method_open_block(value: Any, *, fallback: Any = None) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    quote, section = _normalize_method_evidence_fields(payload)
    raw_status = payload.get("status") if isinstance(value, dict) else value
    status = _normalize_method_status(
        raw_status,
        allowed={"yes", "no", "unknown"},
        default="unknown",
        aliases={"true": "yes", "false": "no"},
    )
    if status == "unknown":
        fallback_bool = _coerce_bool(fallback, default=None)
        if fallback_bool is True:
            status = "yes"
        elif fallback_bool is False:
            status = "no"

    artifact = _normalize_method_status(
        payload.get("artifact"),
        allowed={"data", "code", "both", "unspecified", "unknown"},
        default="unspecified" if status == "yes" else "unknown",
    )
    return {
        "status": status,
        "artifact": artifact,
        "quote": quote,
        "section": section,
    }


def _method_block_status(block: Any, *, default: str = "unknown") -> str:
    if isinstance(block, dict):
        return str(block.get("status") or default)
    return default


def _first_matching_sentence(
    publication: Any,  # PublicationSeed -- typed as Any to avoid circular import at module level
    pattern: re.Pattern[str],
) -> tuple[str | None, str]:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _sentence_candidates,  # lazy
    )

    best_quote: str | None = None
    best_section = "unknown"
    best_score = -1.0
    section_bonus = {"methods": 0.5, "results": 0.4, "abstract": 0.3, "discussion": 0.2}
    for section, sentence in _sentence_candidates(publication):
        if not pattern.search(sentence):
            continue
        score = section_bonus.get(section, 0.0)
        if score > best_score:
            best_quote = sentence
            best_section = section if section in section_bonus else "unknown"
            best_score = score
    return best_quote, best_section


def _sample_size_from_match(match: re.Match[str] | None) -> int | None:
    from brain_researcher.services.br_kg.etl.gabriel_generator import (
        _coerce_int,  # lazy
    )

    if match is None:
        return None
    for group in match.groups():
        if group:
            return _coerce_int(group)
    return None


def _infer_threshold_correction_type(text: str | None) -> str | None:
    lowered = (text or "").lower()
    if "fwe" in lowered or "family-wise" in lowered:
        return "fwe"
    if "fdr" in lowered or "false discovery rate" in lowered:
        return "fdr"
    if "bonferroni" in lowered:
        return "bonferroni"
    if "holm" in lowered:
        return "holm"
    if "hoc" in lowered or "hochberg" in lowered:
        return "hochberg"
    if "svc" in lowered or "small-volume correction" in lowered:
        return "svc"
    if "corrected" in lowered or "multiple comparison" in lowered:
        return "corrected"
    return None


def _infer_open_artifact(text: str | None) -> str:
    lowered = (text or "").lower()
    has_data = any(
        token in lowered
        for token in {"open data", "data available", "openneuro", "neurovault"}
    )
    has_code = any(
        token in lowered
        for token in {"open code", "code available", "source code", "github", "gitlab"}
    )
    if has_data and has_code:
        return "both"
    if has_data:
        return "data"
    if has_code:
        return "code"
    return "unspecified" if lowered else "unknown"
