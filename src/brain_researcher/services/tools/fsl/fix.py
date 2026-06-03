"""Unified FSL FIX tools.

This module provides FSL FIX (ICA-based Xnoiseifier) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_fix_tool import (
    FSLFIXTool,
    FSLFIXMultiRunTool,
)


class FSLFIXPipeline(NeuroTool):
    """Unified FSL FIX artifact removal tool.

    FSL FIX (FMRIB's ICA-based Xnoiseifier) for automated ICA artifact
    classification and removal. Uses machine learning classifiers trained
    on hand-labeled components to identify and remove noise from fMRI data.

    Delegates to the existing FSLFIXTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FIX tool."""
        self._tool = FSLFIXTool()

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
        """Run FSL FIX artifact removal.

        Args:
            **kwargs: Arguments matching FSLFIXArgs schema.

        Returns:
            ToolResult with artifact removal results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class FSLFIXMultiRunPipeline(NeuroTool):
    """Unified FSL FIX multi-run artifact removal tool.

    FSL FIX in multi-run mode for processing multiple fMRI sessions together.
    Trains and applies artifact classifiers across multiple runs for more
    robust noise removal.

    Delegates to the existing FSLFIXMultiRunTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FIX multi-run tool."""
        self._tool = FSLFIXMultiRunTool()

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
        """Run FSL FIX multi-run artifact removal.

        Args:
            **kwargs: Arguments matching FSLFIXMultiRunArgs schema.

        Returns:
            ToolResult with multi-run artifact removal results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLFIXPipeline", "FSLFIXMultiRunPipeline"]
