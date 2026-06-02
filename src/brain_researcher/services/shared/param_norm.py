"""Shared MCP parameter normalization — the canonical *categorical-arg contract*.

Every categorical MCP tool parameter should:

  1. **Advertise** its allowed values in the schema (``enum_str`` / a ``Literal``),
     so schema-aware clients pick a valid value up front.
  2. **Coerce** synonyms server-side (``coerce_enum``), so lax / weak-prompting
     hosts that send ``"event"`` or ``"codex"`` still succeed.
  3. **Never hard-raise** on an unknown value — fall back to a safe default, or,
     for genuinely required args, return a *structured* error that LISTS the
     valid values (``resolve_enum_or_error``).

This closes the failure mode where a non-Claude host eats repeated
``invalid_arguments`` (observed with Codex) while staying discoverable for
strict clients. ``log_research_event`` established the pattern; this module
makes it reusable so the whole tool surface is consistent.

PEP 563 note: ``from __future__ import annotations`` is in effect across the MCP
package, so annotations are stringized. ``enum_str(...)`` returns an
``Annotated[str, Field(...)]`` whose ``json_schema_extra={"enum": ...}`` survives
stringized annotations (verified with ``mcp>=1.26`` FastMCP) and is advertised
WITHOUT being enforced server-side — so ``coerce_enum`` still runs on whatever
the client actually sent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from pydantic import Field

__all__ = ["enum_str", "coerce_enum", "as_str_list", "resolve_enum_or_error"]


def enum_str(values: Iterable[str], description: str) -> Any:
    """Return an ``Annotated[str]`` type that advertises ``values`` as a schema enum.

    Permissive by design: the enum is advertised (clients can discover the legal
    values) but NOT enforced at the FastMCP/Pydantic boundary, so the server-side
    ``coerce_enum`` can still normalize synonyms. Use as a parameter annotation::

        def tool(direction: enum_str(("out", "in", "both"), "...") = "both"): ...
    """

    return Annotated[
        str,
        Field(description=description, json_schema_extra={"enum": list(values)}),
    ]


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def coerce_enum(value: Any, aliases: Mapping[str, str], default: str) -> str:
    """Normalize a free-form value to a canonical enum value. Never raises.

    ``aliases`` maps lowercased/underscored synonyms -> canonical value and must
    include every canonical value mapped to itself. Unknown / empty input -> ``default``.
    """

    key = _key(value)
    if not key:
        return default
    return aliases.get(key, default)


def resolve_enum_or_error(
    value: Any,
    aliases: Mapping[str, str],
    *,
    field: str,
    default: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Coerce ``value`` to a canonical enum value, or return a structured error.

    For *required* categorical args where a wrong value must not silently default:
    returns ``(canonical, None)`` on success, else ``(None, error_dict)`` where the
    error lists the allowed values so a client recovers in one shot instead of
    trial-and-error. If ``default`` is given, unknown values coerce to it (no error).
    """

    key = _key(value)
    if key and key in aliases:
        return aliases[key], None
    if not key and default is not None:
        return default, None
    if default is not None:
        return default, None
    allowed = sorted(set(aliases.values()))
    return None, {
        "ok": False,
        "error": "invalid_arguments",
        "field": field,
        "message": f"{field} must be one of: {', '.join(allowed)}",
        "allowed": allowed,
        "received": value,
    }


def as_str_list(value: Any) -> list[str]:
    """Accept scalar-or-list and return a clean ``list[str]``. Never raises.

    - ``None``        -> ``[]``
    - ``"a, b\\nc"``  -> ``["a", "b", "c"]`` (comma / newline / semicolon separated)
    - ``"single"``    -> ``["single"]``
    - ``["a", "b"]``  -> ``["a", "b"]``

    Mirrors the forgiving ``species:["human"]`` vs ``species:"human"`` contract:
    a host may pass either a scalar or a list and both work.
    """

    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\n;]+", value)]
        return [p for p in parts if p]
    if isinstance(value, list | tuple | set):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []
