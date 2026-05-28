"""ToolSpec-exposed entrypoints for Grandmaster tools/workflows.

Why this exists:
- The agent runtime primarily executes tools via ToolRegistry (NeuroToolWrapper instances).
- Some integrations (MCP/tool_search/ToolSpec routing) rely on ToolSpec entries.

We keep explicit non-workflow exposure curated while resolving orchestration
workflow IDs from config so runtime/workflow routing stays in sync.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


_LEGACY_EXPOSED_GRANDMASTER_TOOL_IDS = [
    "compute_brain_age",
    "individual_parcellation",
    "visual_feature_decoder",
    "query_neuromaps",
    "visualize_interactive",
]


class _AnyArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


@lru_cache(maxsize=1)
def _resolve_exposed_grandmaster_tool_ids() -> tuple[str, ...]:
    """Return agent-visible Grandmaster IDs from the filtered exposed surface."""

    merged_ids = list(_LEGACY_EXPOSED_GRANDMASTER_TOOL_IDS)
    try:
        from brain_researcher.services.tools.catalog_loader import (
            load_exposed_tools,
        )

        for tool_id in load_exposed_tools():
            if tool_id and tool_id not in merged_ids:
                merged_ids.append(tool_id)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Failed to load exposed Grandmaster tool ids: %s", exc)

    return tuple(merged_ids)


EXPOSED_GRANDMASTER_TOOL_IDS = list(_resolve_exposed_grandmaster_tool_ids())


@lru_cache(maxsize=32)
def _runtime_tool_schema(tool_id: str) -> type[BaseModel]:
    try:
        registry = _runtime_registry()
        tool = registry.get_tool(tool_id)
        if tool is None:
            return _AnyArgs
        schema = tool.get_args_schema()
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema
    except Exception:
        return _AnyArgs
    return _AnyArgs


@lru_cache(maxsize=1)
def _runtime_registry():
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    return ToolRegistry.from_env(light_mode=True)


class GrandmasterExposedTool(NeuroToolWrapper):
    """Forward ToolSpec execution to the runtime ToolRegistry implementation."""

    def __init__(self, tool_id: str):
        super().__init__()
        self._tool_id = tool_id

    def get_tool_name(self) -> str:
        return self._tool_id

    def get_tool_description(self) -> str:
        return f"Grandmaster entrypoint: {self._tool_id}"

    def get_args_schema(self):
        return _runtime_tool_schema(self._tool_id)

    def _run(self, **kwargs) -> ToolResult:
        try:
            registry = _runtime_registry()
            tool = registry.get_tool(self._tool_id)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Grandmaster runtime tool not found: {self._tool_id}",
                    data={"tool_id": self._tool_id},
                )
            result = tool._run(**kwargs)
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                status = result.get("status", "success")
                if status == "success":
                    return ToolResult(status="success", data=result)
                return ToolResult(
                    status="error", error=result.get("error"), data=result
                )
            return ToolResult(status="success", data={"result": result})
        except Exception as exc:  # pragma: no cover
            logger.debug("Grandmaster exposed tool failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


def get_all_tools() -> list[NeuroToolWrapper]:
    return [
        GrandmasterExposedTool(tool_id)
        for tool_id in _resolve_exposed_grandmaster_tool_ids()
    ]


__all__ = ["GrandmasterExposedTool", "EXPOSED_GRANDMASTER_TOOL_IDS", "get_all_tools"]
