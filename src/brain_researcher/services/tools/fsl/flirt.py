"""Unified FSL FLIRT tool.

This module provides FSL FLIRT (Linear Image Registration Tool) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTool


class FSLFLIRTPipeline(NeuroTool):
    """Unified FSL FLIRT linear registration tool.

    FSL FLIRT for linear (affine) image registration. Performs rigid body (6 DOF),
    global rescale (7 DOF), traditional (9 DOF), or full affine (12 DOF) registration.
    Supports multi-modal registration with various cost functions.

    Delegates to the existing FSLFLIRTTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL FLIRT tool."""
        self._tool = FSLFLIRTTool()

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
        """Run FSL FLIRT linear registration.

        Args:
            **kwargs: Arguments matching FSLFLIRTArgs schema.

        Returns:
            ToolResult with registration results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLFLIRTPipeline"]
