"""Unified fMRIPrep pipeline tools.

This module provides fMRIPrep tools conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.fmriprep_tool import (
    FMRIPrepQCTool,
    FMRIPrepTool,
)
from brain_researcher.services.tools.result import ToolResult


class FMRIPrepPipeline(NeuroTool):
    """Unified fMRIPrep preprocessing tool.

    This tool provides comprehensive fMRI preprocessing including motion
    correction, distortion correction, registration, and confound extraction.

    Delegates to the existing FMRIPrepTool implementation.
    """

    execution_mode = ExecutionMode.CONTAINER

    def __init__(self):
        """Initialize fMRIPrep pipeline tool."""
        self._tool = FMRIPrepTool()

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
        """Run fMRIPrep preprocessing.

        Args:
            **kwargs: Arguments matching FMRIPrepArgs schema.

        Returns:
            ToolResult with preprocessing results.
        """
        result = self._tool._run(**kwargs)
        # Convert from agent ToolResult to unified ToolResult
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class FMRIPrepQCPipeline(NeuroTool):
    """Unified fMRIPrep quality control tool.

    Extracts and analyzes quality control metrics from fMRIPrep outputs
    including motion parameters, registration quality, and preprocessing summaries.

    Delegates to the existing FMRIPrepQCTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize fMRIPrep QC tool."""
        self._tool = FMRIPrepQCTool()

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
        """Run fMRIPrep QC analysis.

        Args:
            **kwargs: Arguments matching FMRIPrepQCArgs schema.

        Returns:
            ToolResult with QC analysis results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FMRIPrepPipeline", "FMRIPrepQCPipeline"]
