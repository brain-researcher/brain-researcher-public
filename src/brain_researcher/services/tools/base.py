"""Base class for unified neuroimaging tools.

This module provides the NeuroTool base class that all unified tools inherit from.
It supports both container-based and subprocess execution modes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

from brain_researcher.services.tools.result import ToolResult


class ExecutionMode(str, Enum):
    """Execution mode for tools."""

    CONTAINER = "container"  # Run via containerized execution (Docker/Apptainer)
    SUBPROCESS = "subprocess"  # Run via direct subprocess call


class NeuroTool(ABC):
    """Base class for all unified neuroimaging tools.

    This provides a consistent interface that can be:
    - Converted to LangChain StructuredTool for agent use
    - Called directly for CLI/programmatic use
    - Executed via containers or direct subprocess

    Attributes:
        execution_mode: How the tool should be executed (container or subprocess)
        name: Tool name (lowercase, underscore-separated)
        description: Human-readable description for LLM/users

    Example:
        >>> class MyTool(NeuroTool):
        ...     def get_name(self) -> str:
        ...         return "my_tool"
        ...
        ...     def get_description(self) -> str:
        ...         return "Does something useful"
        ...
        ...     def get_args_schema(self) -> type[BaseModel]:
        ...         return MyToolArgs
        ...
        ...     def run(self, **kwargs) -> ToolResult:
        ...         return ToolResult(status="success", data={"result": "done"})
        ...
        >>> tool = MyTool()
        >>> langchain_tool = tool.as_langchain_tool()
    """

    execution_mode: ExecutionMode = ExecutionMode.SUBPROCESS

    @abstractmethod
    def get_name(self) -> str:
        """Return the tool name (lowercase, underscore-separated).

        Returns:
            Tool name, e.g., "niwrap_search" or "fsl_bet"
        """
        ...

    @abstractmethod
    def get_description(self) -> str:
        """Return human-readable description for LLM/users.

        Returns:
            Description string explaining what the tool does
        """
        ...

    @abstractmethod
    def get_args_schema(self) -> type[BaseModel]:
        """Return the Pydantic model for input arguments.

        Returns:
            Pydantic BaseModel class defining the tool's input schema
        """
        ...

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Arguments matching the schema from get_args_schema()

        Returns:
            ToolResult with status, data, and optional error/metadata
        """
        ...

    def _run(self, **kwargs: Any) -> ToolResult:
        """Alias for run() to match NeuroToolWrapper interface.

        This exists for compatibility with existing agent tools that use _run().
        """
        return self.run(**kwargs)

    def get_tool_name(self) -> str:
        """Alias for get_name() to match NeuroToolWrapper interface."""
        return self.get_name()

    def get_tool_description(self) -> str:
        """Alias for get_description() to match NeuroToolWrapper interface."""
        return self.get_description()

    def as_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain StructuredTool for agent use.

        Returns:
            LangChain StructuredTool wrapping this tool's functionality
        """
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:  # pragma: no cover
            from langchain.tools import StructuredTool

        def _wrapper(**kwargs: Any) -> dict:
            """Wrapper that returns dict for LangChain compatibility."""
            result = self.run(**kwargs)
            if result.status == "error":
                return {"status": "error", "error": result.error, "data": result.data}
            return {
                "status": "success",
                "data": result.data,
                "metadata": result.metadata,
            }

        return StructuredTool(
            name=self.get_name(),
            description=self.get_description(),
            func=_wrapper,
            args_schema=self.get_args_schema(),
        )


__all__ = ["NeuroTool", "ExecutionMode"]
