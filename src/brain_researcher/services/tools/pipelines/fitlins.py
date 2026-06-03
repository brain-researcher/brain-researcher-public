"""Unified FitLins pipeline tools.

This module provides FitLins tools conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.fitlins_tool import (
    FitLinsTool,
)
from brain_researcher.services.tools.result import ToolResult


class FitLinsPipeline(NeuroTool):
    """Unified FitLins BIDS GLM analysis tool.

    FitLins (Fitting Linear Models to BIDS Datasets) provides standardized
    GLM analyses. It automatically handles BIDS dataset structure, integrates
    with fMRIPrep outputs, and produces BIDS-derivative compliant results.

    Supports hierarchical models from run to group level with automatic
    contrast generation and multiple estimator backends.

    Delegates to the existing FitLinsTool implementation.
    """

    execution_mode = ExecutionMode.CONTAINER

    def __init__(self):
        """Initialize FitLins pipeline tool."""
        self._tool = FitLinsTool()

    def get_name(self) -> str:
        """Get tool name."""
        return self._tool.get_tool_name()

    def get_description(self) -> str:
        """Get tool description."""
        return self._tool.get_tool_description()

    def get_args_schema(self) -> type[BaseModel]:
        """Get arguments schema."""
        return self._tool.get_args_schema()

    def run(self, **kwargs: Any) -> ToolResult:
        """Run FitLins BIDS GLM analysis.

        Args:
            **kwargs: Arguments matching FitLinsArgs schema.

        Returns:
            ToolResult with GLM analysis results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FitLinsPipeline"]
