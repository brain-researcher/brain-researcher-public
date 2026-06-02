"""Unified FSL FNIRT tool.

This module provides FSL FNIRT (Non-linear Image Registration Tool) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.fsl_fnirt_tool import FSLFNIRTTool
from brain_researcher.services.tools.result import ToolResult


class FSLFNIRTPipeline(NeuroTool):
    """Unified FSL FNIRT non-linear registration tool.

    FSL FNIRT (FMRIB's Non-linear Image Registration Tool) for high-precision
    non-linear registration of brain images to standard space. Typically used
    after FLIRT linear registration for refined alignment.

    Delegates to the existing FSLFNIRTTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FNIRT tool."""
        self._tool = FSLFNIRTTool()

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
        """Run FSL FNIRT non-linear registration.

        Args:
            **kwargs: Arguments matching FSLFNIRTArgs schema.

        Returns:
            ToolResult with non-linear registration results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLFNIRTPipeline"]
