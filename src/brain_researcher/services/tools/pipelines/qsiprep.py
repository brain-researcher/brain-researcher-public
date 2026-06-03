"""Unified QSIPrep pipeline tools.

This module provides QSIPrep tools conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.qsiprep_tool import (
    QSIPrepQCTool,
    QSIPrepReconTool,
    QSIPrepTool,
)
from brain_researcher.services.tools.result import ToolResult


class QSIPrepPipeline(NeuroTool):
    """Unified QSIPrep diffusion preprocessing tool.

    Provides comprehensive diffusion MRI preprocessing including denoising,
    distortion correction, head motion correction, and eddy current correction.
    Supports single-shell and multi-shell acquisitions.

    Delegates to the existing QSIPrepTool implementation.
    """

    execution_mode = ExecutionMode.CONTAINER

    def __init__(self):
        """Initialize QSIPrep pipeline tool."""
        self._tool = QSIPrepTool()

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
        """Run QSIPrep preprocessing.

        Args:
            **kwargs: Arguments matching QSIPrepArgs schema.

        Returns:
            ToolResult with preprocessing results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class QSIPrepReconPipeline(NeuroTool):
    """Unified QSIPrep reconstruction tool.

    Runs QSIPrep reconstruction workflows on preprocessed diffusion data.
    Supports various reconstruction methods including DTI, DKI, MAPMRI,
    NODDI, and tractography.

    Delegates to the existing QSIPrepReconTool implementation.
    """

    execution_mode = ExecutionMode.CONTAINER

    def __init__(self):
        """Initialize QSIPrep reconstruction tool."""
        self._tool = QSIPrepReconTool()

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
        """Run QSIPrep reconstruction.

        Args:
            **kwargs: Arguments matching QSIPrepReconArgs schema.

        Returns:
            ToolResult with reconstruction results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class QSIPrepQCPipeline(NeuroTool):
    """Unified QSIPrep quality control tool.

    Extracts and analyzes quality control metrics from QSIPrep outputs
    including motion parameters, SNR, CNR, and preprocessing quality measures.

    Delegates to the existing QSIPrepQCTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize QSIPrep QC tool."""
        self._tool = QSIPrepQCTool()

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
        """Run QSIPrep QC analysis.

        Args:
            **kwargs: Arguments matching QSIPrepQCArgs schema.

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


__all__ = ["QSIPrepPipeline", "QSIPrepReconPipeline", "QSIPrepQCPipeline"]
