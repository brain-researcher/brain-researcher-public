"""Shared read-only facade for tool-registry search.

BR-KG needs tool search results for evidence aggregation, but it should not
import the concrete ``services.tools`` registry directly. This module keeps the
contract small and structural, and lets the tools layer register the concrete
factory when it is imported.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class ToolRegistryTool(Protocol):
    """Minimal tool-wrapper contract consumed by BR-KG evidence adapters."""

    def get_tool_name(self) -> str: ...

    def get_tool_description(self) -> str: ...


@runtime_checkable
class ToolRegistryView(Protocol):
    """Read-only subset of the concrete tool registry used by BR-KG."""

    @property
    def tools(self) -> Mapping[str, ToolRegistryTool]: ...

    def get_tool(self, name: str) -> ToolRegistryTool | None: ...

    def get_tools_for_task(
        self,
        task_description: str,
        k: int = 5,
    ) -> list[ToolRegistryTool]: ...


ToolRegistryFactory = Callable[..., ToolRegistryView]

_default_tool_registry_factory: ToolRegistryFactory | None = None


def register_default_tool_registry(factory: ToolRegistryFactory) -> None:
    """Register the concrete tool-registry factory.

    Called by the tools layer. Idempotent by design because runtime entrypoints
    may import the tools layer more than once.
    """

    global _default_tool_registry_factory
    _default_tool_registry_factory = factory


def has_default_tool_registry() -> bool:
    """Whether a concrete tool-registry factory has been registered."""

    return _default_tool_registry_factory is not None


def _legacy_tool_registry_factory(
    *,
    auto_discover: bool,
    light_mode: bool,
) -> ToolRegistryView:
    """Load the historical concrete registry lazily for standalone BR-KG use."""

    module = importlib.import_module("brain_researcher.services.tools.tool_registry")
    registry_cls = module.ToolRegistry
    return registry_cls(auto_discover=auto_discover, light_mode=light_mode)


def get_default_tool_registry(
    *,
    auto_discover: bool = True,
    light_mode: bool = True,
) -> ToolRegistryView:
    """Build the default read-only tool-registry view.

    If the tools layer has not registered a factory yet, this preserves the
    previous lazy-loading behavior without a direct BR-KG import of
    ``services.tools``.
    """

    factory = _default_tool_registry_factory
    if factory is None:
        return _legacy_tool_registry_factory(
            auto_discover=auto_discover,
            light_mode=light_mode,
        )
    return factory(auto_discover=auto_discover, light_mode=light_mode)


__all__ = [
    "ToolRegistryTool",
    "ToolRegistryView",
    "ToolRegistryFactory",
    "register_default_tool_registry",
    "has_default_tool_registry",
    "get_default_tool_registry",
]
