"""Adapter to wrap StructuredTool as NeuroToolWrapper.

This module provides an adapter class that allows StructuredTool instances
(returned by UnifiedToolRegistry) to be used in contexts that expect
NeuroToolWrapper instances (like Agent ToolRegistry).

Example:
    from brain_researcher.services.tools import UnifiedToolRegistry
    from brain_researcher.services.tools.adapter import StructuredToolAdapter

    unified = UnifiedToolRegistry()
    for tool in unified.get_all_tools():
        wrapped = StructuredToolAdapter(tool)
        # Now `wrapped` can be used anywhere NeuroToolWrapper is expected
"""

import logging
from typing import Any, Type

try:
    from langchain_core.tools import StructuredTool
except ImportError:  # pragma: no cover
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        from langchain.tools import StructuredTool  # type: ignore

from pydantic import BaseModel, Field, create_model

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class StructuredToolAdapter(NeuroToolWrapper):
    """Adapts a LangChain StructuredTool to NeuroToolWrapper interface.

    This adapter enables tools from UnifiedToolRegistry (which returns
    StructuredTool instances) to be used in Agent ToolRegistry (which
    expects NeuroToolWrapper instances).

    The adapter:
    - Preserves the tool's name, description, and args_schema exactly
    - Delegates execution to the underlying StructuredTool.func
    - Returns the original StructuredTool when as_langchain_tool() is called
      (avoiding double-wrapping)

    Attributes:
        _tool: The wrapped StructuredTool instance
    """

    def __init__(self, tool: StructuredTool):
        """Initialize the adapter with a StructuredTool.

        Args:
            tool: The LangChain StructuredTool to wrap
        """
        super().__init__()
        self._tool = tool
        # StructuredTool executes locally in-process by default, but allow callers
        # (e.g., MCP wrappers) to override backend for timeout/budget enforcement.
        backend = getattr(tool, "execution_backend", None)
        if backend is None:
            md = getattr(tool, "metadata", None)
            if isinstance(md, dict):
                backend = md.get("execution_backend")
        if backend in {"python", "api", "container"}:
            self.execution_backend = backend
        else:
            self.execution_backend = "python"

    def get_tool_name(self) -> str:
        """Return the tool's name."""
        return self._tool.name

    def get_tool_description(self) -> str:
        """Return the tool's description."""
        return self._tool.description or ""

    def get_args_schema(self) -> Type[BaseModel]:
        """Return the tool's argument schema.

        Returns the original args_schema if available, otherwise creates
        a minimal empty schema.
        """
        if self._tool.args_schema is not None:
            return self._tool.args_schema
        # Fallback: create empty schema if none exists
        return create_model(f"{self._tool.name}Args")

    def _run(self, **kwargs) -> ToolResult:
        """Execute the tool and return a ToolResult.

        Args:
            **kwargs: Arguments to pass to the tool

        Returns:
            ToolResult with status, data, and optional error
        """
        try:
            # Call the underlying tool's function
            if self._tool.func is not None:
                result = self._tool.func(**kwargs)
            elif hasattr(self._tool, "invoke"):
                result = self._tool.invoke(kwargs)
            else:
                return ToolResult(
                    status="error",
                    error="Tool has no callable function",
                    metadata={"tool_name": self._tool.name},
                )

            # Handle different result types
            if isinstance(result, dict):
                # If result is already a dict, check if it's a ToolResult-like dict
                if "status" in result and result.get("status") in ("success", "error"):
                    return ToolResult(**result)
                return ToolResult(status="success", data=result)
            elif isinstance(result, ToolResult):
                return result
            else:
                # Wrap primitive results
                return ToolResult(status="success", data={"result": result})

        except Exception as e:
            logger.debug(f"Tool {self._tool.name} execution failed: {e}")
            return ToolResult(
                status="error",
                error=str(e),
                metadata={
                    "tool_name": self._tool.name,
                    "error_type": type(e).__name__,
                },
            )

    def as_langchain_tool(self) -> StructuredTool:
        """Return the underlying StructuredTool (no double-wrapping).

        Unlike NeuroToolWrapper.as_langchain_tool() which creates a new
        StructuredTool, this returns the original tool directly.
        """
        return self._tool


def wrap_structured_tools(tools: list[StructuredTool]) -> list[NeuroToolWrapper]:
    """Wrap a list of StructuredTools as NeuroToolWrapper instances.

    Args:
        tools: List of StructuredTool instances

    Returns:
        List of StructuredToolAdapter instances
    """
    wrapped: list[NeuroToolWrapper] = []
    for tool in tools:
        try:
            wrapped.append(StructuredToolAdapter(tool))
        except Exception as e:
            logger.warning(
                f"Failed to wrap tool {getattr(tool, 'name', 'unknown')}: {e}"
            )
    return wrapped


__all__ = ["StructuredToolAdapter", "wrap_structured_tools"]
