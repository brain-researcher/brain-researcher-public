"""Request query-param parsing + optional-value coercion for the BR-KG API.

Carved out of ``br_kg/app.py``: small pure helpers that parse boolean /
task-scope / source-mode / evidence-path query parameters off the Flask
request and coerce optional float / bool values. They own no module state and
call nothing else in ``app.py`` (their only external touchpoint is the Flask
``request`` proxy), so the dependency is strictly one-way: ``app -> request_params``.

``app.py`` re-exports every name below so existing ``app.<name>`` references and
route handlers keep resolving.
"""

from __future__ import annotations

from typing import Any

from flask import request


def _parse_bool_query_param(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("must be a boolean")


def _parse_task_scope_query_param(raw: str | None, *, default: str = "aliases") -> str:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"aliases", "neighbors", "all"}:
        return text
    raise ValueError("must be one of: aliases, neighbors, all")


def _parse_source_mode_query_param(
    raw: str | None,
    *,
    default: str = "graph_plus_live",
) -> str:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"graph_only", "graph_plus_live"}:
        return text
    raise ValueError("must be one of: graph_only, graph_plus_live")


def _parse_evidence_paths_query_params() -> tuple[int, float, bool, bool]:
    limit = int(request.args.get("limit", 50))
    limit = max(1, min(limit, 200))
    confidence_min_raw = request.args.get("confidence_min", "0")
    try:
        confidence_min = float(confidence_min_raw)
    except (TypeError, ValueError):
        raise ValueError("confidence_min must be a float between 0 and 1") from None
    if confidence_min < 0 or confidence_min > 1:
        raise ValueError("confidence_min must be between 0 and 1")
    try:
        verified_only = _parse_bool_query_param(
            request.args.get("verified_only"),
            default=False,
        )
    except ValueError:
        raise ValueError("verified_only must be a boolean") from None
    try:
        include_mediated = _parse_bool_query_param(
            request.args.get("include_mediated"),
            default=True,
        )
    except ValueError:
        raise ValueError("include_mediated must be a boolean") from None
    return limit, confidence_min, verified_only, include_mediated


def _coerce_float_optional(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _coerce_bool_optional(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None
