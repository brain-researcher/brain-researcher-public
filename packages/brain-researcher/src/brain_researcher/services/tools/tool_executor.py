"""Shim module for planner imports.

Some planner paths import ``brain_researcher.services.tools.tool_executor``.
The actual implementation lives in ``services.agent.tool_executor``.
This shim re-exports the public executors to avoid ImportError/fallbacks.
"""

from brain_researcher.services.agent.tool_executor import (  # noqa: F401
    ToolExecutor,
    BudgetedToolExecutor,
)

__all__ = ["ToolExecutor", "BudgetedToolExecutor"]

