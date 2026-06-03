"""Cached loader for Studio deterministic scaffold registry config."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)

_REGISTRY_PATH = resolve_from_config("catalog", "studio_scaffold_registry.yaml")


def _normalize_defaults(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if key}


@lru_cache(maxsize=1)
def load_studio_scaffold_registry() -> dict[str, Any]:
    """Return normalized family bindings for Studio deterministic planning."""
    if not _REGISTRY_PATH.exists():
        return {"families": {}, "tool_to_family": {}}

    try:
        payload = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"families": {}, "tool_to_family": {}}

    raw_families = payload.get("families")
    if not isinstance(raw_families, dict):
        return {"families": {}, "tool_to_family": {}}

    families: dict[str, dict[str, Any]] = {}
    tool_to_family: dict[str, str] = {}

    for raw_family_name, raw_spec in raw_families.items():
        family_name = str(raw_family_name or "").strip()
        if not family_name or not isinstance(raw_spec, dict):
            continue

        raw_tools = raw_spec.get("tools") or []
        tools: list[str] = []
        if isinstance(raw_tools, list):
            for raw_tool in raw_tools:
                normalized = str(raw_tool or "").strip()
                if not normalized:
                    continue
                canonical = resolve_primary_runtime_tool_id(normalized) or normalized
                if canonical not in tools:
                    tools.append(canonical)
                tool_to_family[canonical] = family_name

        raw_preferences = raw_spec.get("derivative_preferences") or []
        derivative_preferences = [
            str(item).strip() for item in raw_preferences if str(item or "").strip()
        ]

        families[family_name] = {
            "tools": tools,
            "derivative_preferences": derivative_preferences,
            "defaults": _normalize_defaults(raw_spec.get("defaults")),
        }

    return {
        "families": families,
        "tool_to_family": tool_to_family,
    }


__all__ = ["load_studio_scaffold_registry"]
