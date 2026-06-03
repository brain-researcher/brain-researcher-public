"""Unified FSL PALM tool.

This module provides FSL PALM (Permutation Analysis of Linear Models) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.fsl_palm_tool import FSLPALMTool
from brain_researcher.services.tools.result import ToolResult


class FSLPALMPipeline(NeuroTool):
    """Unified FSL PALM permutation testing tool.

    FSL PALM for permutation-based statistical testing of complex general
    linear models. Supports exchangeability blocks, TFCE (Threshold-Free
    Cluster Enhancement), and various multiple comparison corrections
    including FWE and FDR.

    Delegates to the existing FSLPALMTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL PALM tool."""
        self._tool = FSLPALMTool()

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
        """Run FSL PALM permutation testing.

        Args:
            **kwargs: Arguments matching FSLPALMArgs schema.

        Returns:
            ToolResult with permutation testing results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLPALMPipeline"]
