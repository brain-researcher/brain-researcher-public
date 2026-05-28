"""Resolver helpers for runtime-canonical planner tool names.

The planner surface prefers runtime registry names (for example
``validate_bids`` or ``fsl_bet``). Legacy catalog/planner IDs such as
``python.validate_bids.run`` remain accepted only through narrow compatibility
helpers.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache

from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)

logger = logging.getLogger(__name__)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        out.append(item)
        seen.add(item)
    return out


def _resolve_python_runner_tool_name(tool_id: str) -> str | None:
    """Resolve a planner tool_id to the runtime registry tool name via python spec.

    This is best-effort and may fail if dependencies are missing or imports fail.
    """
    try:
        from brain_researcher.services.agent.planner.catalog_loader import (
            get_tool_by_id,
        )
    except Exception:
        return None

    try:
        cap = get_tool_by_id(tool_id)
    except Exception:
        cap = None

    if not cap or getattr(cap, "runtime_kind", None) != "python":
        return None

    runner = getattr(cap, "python", None)
    if not runner:
        return None

    module_name = getattr(runner, "module", None)
    symbol_name = getattr(runner, "function", None)
    entry_type = getattr(runner, "entry_type", None) or "function"

    if not module_name or not symbol_name:
        return None

    try:
        module = importlib.import_module(str(module_name))
        target = getattr(module, str(symbol_name), None)
        if target is None:
            return None

        if entry_type == "class":
            instance = target()
            get_tool_name = getattr(instance, "get_tool_name", None)
            if callable(get_tool_name):
                name = get_tool_name()
                return str(name) if name else None
            return None

        # entry_type == "function": no canonical runtime tool name to derive.
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to resolve python tool name for %s: %s", tool_id, exc)
        return None


@lru_cache(maxsize=4096)
def resolve_planner_tool_id_to_registry_tool_names(tool_id: str) -> list[str]:
    """Return candidate runtime registry tool names for a planner/runtime tool_id.

    The returned list is ordered by preference and contains no duplicates.
    The first entry is the canonical runtime name whenever one can be resolved.
    """
    if not tool_id:
        return []

    canonical = resolve_primary_runtime_tool_id(tool_id)
    if canonical:
        return [canonical]

    derived = _resolve_python_runner_tool_name(tool_id)
    if derived:
        return [derived]

    return [tool_id]


@lru_cache(maxsize=4096)
def resolve_registry_tool_name_to_planner_tool_ids(tool_name: str) -> list[str]:
    """Return the canonical runtime tool id for planner-facing use."""

    if not tool_name:
        return []
    canonical = resolve_primary_runtime_tool_id(tool_name) or str(tool_name).strip()
    return _dedupe_preserve_order([canonical])


__all__ = [
    "resolve_planner_tool_id_to_registry_tool_names",
    "resolve_registry_tool_name_to_planner_tool_ids",
]
