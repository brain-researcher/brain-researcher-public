"""Unified ANTs registration tool.

This module provides ANTs registration conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.ants_tool import ANTsRegistrationTool
from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.result import ToolResult


class ANTsRegistrationPipeline(NeuroTool):
    """Unified ANTs image registration tool.

    ANTs (Advanced Normalization Tools) for deformable image registration.
    Supports rigid, affine, and non-linear (SyN) transformations with
    multiple similarity metrics (MI, CC, etc.). Produces forward and
    inverse warps along with the warped output image.

    Falls back to deterministic placeholders when native binaries are unavailable.

    Delegates to the existing ANTsRegistrationTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize ANTs registration tool."""
        self._tool = ANTsRegistrationTool()

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
        """Run ANTs image registration.

        Args:
            **kwargs: Arguments matching ANTsRegistrationArgs schema.

        Returns:
            ToolResult with registration results including transforms.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["ANTsRegistrationPipeline"]
