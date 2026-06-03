"""Unified AFNI 3dClustSim tool.

This module provides AFNI 3dClustSim (cluster simulation) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.afni_clustsim_tool import AFNIClustSimTool
from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.result import ToolResult


class AFNIClustSimPipeline(NeuroTool):
    """Unified AFNI 3dClustSim cluster threshold estimation tool.

    Estimates cluster-size thresholds for multiple comparison correction using
    Monte Carlo simulations. Uses ACF (spatial autocorrelation function) for
    realistic smoothness estimation. Automatically falls back to lightweight
    analytical approximations when AFNI binaries are unavailable.

    Delegates to the existing AFNIClustSimTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize AFNI ClustSim tool."""
        self._tool = AFNIClustSimTool()

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
        """Run AFNI 3dClustSim cluster simulation.

        Args:
            **kwargs: Arguments matching AFNIClustSimArgs schema.

        Returns:
            ToolResult with cluster threshold estimation results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["AFNIClustSimPipeline"]
