"""Canonical runtime adapter for ToolRegistry compatibility.

This bridges StructuredTool-first registry loading to the legacy runtime
interface expected by agent code (``NeuroToolWrapper`` instances).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from brain_researcher.services.tools.adapter import wrap_structured_tools
from brain_researcher.services.tools.registry import UnifiedToolRegistry
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeReport:
    added: int
    collisions: int
    collision_ids: tuple[str, ...]


class CanonicalRuntimeAdapter:
    """Load runtime wrappers from canonical UnifiedToolRegistry surfaces."""

    def load_runtime_tools(self) -> list[NeuroToolWrapper]:
        registry = UnifiedToolRegistry()
        structured_tools = registry.get_all_tools()
        wrapped = wrap_structured_tools(structured_tools)
        logger.info(
            "CanonicalRuntimeAdapter loaded %d canonical runtime tools",
            len(wrapped),
        )
        return wrapped

    @staticmethod
    def merge_prefer_primary(
        primary: Iterable[NeuroToolWrapper],
        fallback: Iterable[NeuroToolWrapper],
    ) -> tuple[list[NeuroToolWrapper], MergeReport]:
        """Merge tool streams, keeping primary entries on name collisions."""

        merged: dict[str, NeuroToolWrapper] = {}
        collisions: list[str] = []

        for tool in primary:
            try:
                merged[tool.get_tool_name()] = tool
            except Exception:
                continue

        added = 0
        for tool in fallback:
            try:
                tool_id = tool.get_tool_name()
            except Exception:
                continue
            if tool_id in merged:
                collisions.append(tool_id)
                continue
            merged[tool_id] = tool
            added += 1

        return list(merged.values()), MergeReport(
            added=added,
            collisions=len(collisions),
            collision_ids=tuple(sorted(set(collisions))),
        )
