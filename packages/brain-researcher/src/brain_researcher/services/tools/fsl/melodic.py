"""Unified FSL MELODIC tool.

This module provides FSL MELODIC (ICA) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_melodic_tool import FSLMELODICTool


class FSLMELODICPipeline(NeuroTool):
    """Unified FSL MELODIC ICA analysis tool.

    FSL MELODIC for Independent Component Analysis of fMRI data. Performs
    probabilistic ICA decomposition with automatic dimensionality estimation,
    component maps, and time courses. Useful for identifying resting-state
    networks and noise components.

    Delegates to the existing FSLMELODICTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL MELODIC tool."""
        self._tool = FSLMELODICTool()

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
        """Run FSL MELODIC ICA analysis.

        Args:
            **kwargs: Arguments matching FSLMELODICArgs schema.

        Returns:
            ToolResult with ICA analysis results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLMELODICPipeline"]
