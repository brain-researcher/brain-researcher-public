"""Unified FSL FEAT tools.

This module provides FSL FEAT (FMRI Expert Analysis Tool) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_feat_tool import (
    FSLFEATTool,
    FSLFEATGroupTool,
)


class FSLFEATPipeline(NeuroTool):
    """Unified FSL FEAT GLM analysis tool.

    FSL FEAT for first-level GLM analysis of task fMRI data with statistical
    inference. Supports preprocessing, design matrix specification, contrast
    definitions, and multiple comparison correction.

    Delegates to the existing FSLFEATTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FEAT tool."""
        self._tool = FSLFEATTool()

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
        """Run FSL FEAT GLM analysis.

        Args:
            **kwargs: Arguments matching FEATGLMArgs schema.

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


class FSLFEATGroupPipeline(NeuroTool):
    """Unified FSL FEAT group analysis tool.

    FSL FEAT higher-level (group) analysis combining multiple first-level analyses.
    Uses FLAME mixed effects model for group inference across subjects.

    Delegates to the existing FSLFEATGroupTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FEAT group tool."""
        self._tool = FSLFEATGroupTool()

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
        """Run FSL FEAT group analysis.

        Args:
            **kwargs: Arguments matching FEATGroupArgs schema.

        Returns:
            ToolResult with group analysis results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLFEATPipeline", "FSLFEATGroupPipeline"]
