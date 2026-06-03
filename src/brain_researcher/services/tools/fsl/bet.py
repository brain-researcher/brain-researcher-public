"""Unified FSL BET tool.

This module provides FSL BET (Brain Extraction Tool) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_bet_tool import FSLBETTool


class FSLBETPipeline(NeuroTool):
    """Unified FSL BET brain extraction tool.

    FSL BET (Brain Extraction Tool) for skull stripping and brain extraction.
    Removes non-brain tissue from structural and functional MRI images.
    Supports robust center estimation, bias field correction, and 4D fMRI data.

    Delegates to the existing FSLBETTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL BET tool."""
        self._tool = FSLBETTool()

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
        """Run FSL BET brain extraction.

        Args:
            **kwargs: Arguments matching FSLBETArgs schema.

        Returns:
            ToolResult with brain extraction results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLBETPipeline"]
