"""Unified FSL BEDPOSTX tool.

This module provides FSL BEDPOSTX (Bayesian Diffusion Modeling) conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import NeuroTool, ExecutionMode
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.fsl_bedpostx_tool import FSLBEDPOSTXTool


class FSLBEDPOSTXPipeline(NeuroTool):
    """Unified FSL BEDPOSTX diffusion modeling tool.

    FSL BEDPOSTX (Bayesian Estimation of Diffusion Parameters Obtained using
    Sampling Techniques with Crossing Fibres) for advanced diffusion MRI analysis.
    Models multiple crossing fibers per voxel using MCMC sampling, enabling
    probabilistic tractography with crossing fiber resolution.

    Delegates to the existing FSLBEDPOSTXTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FSL BEDPOSTX tool."""
        self._tool = FSLBEDPOSTXTool()

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
        """Run FSL BEDPOSTX diffusion modeling.

        Args:
            **kwargs: Arguments matching FSLBEDPOSTXArgs schema.

        Returns:
            ToolResult with diffusion modeling results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["FSLBEDPOSTXPipeline"]
