"""Compatibility alias for the legacy ``services.tools.tool_executor`` path.

The actual executor implementation lives in the higher ``agent`` layer, which
itself depends on this ``tools`` layer. Resolve the compatibility exports lazily
so importing this module does not introduce a static ``tools -> agent`` back-edge.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["ToolExecutor", "BudgetedToolExecutor"]

_EXPORTS = {
    "ToolExecutor": "brain_researcher.services.agent.tool_executor",
    "BudgetedToolExecutor": "brain_researcher.services.agent.tool_executor",
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(target)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *__all__])
