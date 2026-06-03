"""Unified FreeSurfer tools.

This module provides FreeSurfer tools conforming to the NeuroTool interface.
It delegates to the existing agent tool implementation to avoid duplication.
"""

from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.freesurfer_tool import (
    FreeSurferParcellationTool,
    FreeSurferQCTool,
    FreeSurferReconAllTool,
    FreeSurferVolumetricTool,
)
from brain_researcher.services.tools.result import ToolResult


class FreeSurferReconAllPipeline(NeuroTool):
    """Unified FreeSurfer recon-all surface reconstruction tool.

    FreeSurfer recon-all pipeline for cortical surface reconstruction.
    Performs skull stripping, white/gray matter segmentation, surface
    reconstruction, and cortical parcellation. Supports hippocampal
    subfields, brainstem structures, and thalamic nuclei segmentation.

    Delegates to the existing FreeSurferReconAllTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FreeSurfer recon-all tool."""
        self._tool = FreeSurferReconAllTool()

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
        """Run FreeSurfer recon-all pipeline.

        Args:
            **kwargs: Arguments matching FreeSurferReconAllArgs schema.

        Returns:
            ToolResult with surface reconstruction results.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class FreeSurferParcellationPipeline(NeuroTool):
    """Unified FreeSurfer cortical parcellation tool.

    Extracts cortical parcellation data from FreeSurfer recon-all output.
    Supports multiple atlases (Desikan-Killiany, Destrieux, DKT) and
    various surface measures (thickness, area, volume, curvature).

    Delegates to the existing FreeSurferParcellationTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FreeSurfer parcellation tool."""
        self._tool = FreeSurferParcellationTool()

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
        """Run FreeSurfer parcellation extraction.

        Args:
            **kwargs: Arguments matching FreeSurferParcellationArgs schema.

        Returns:
            ToolResult with parcellation data.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class FreeSurferVolumetricPipeline(NeuroTool):
    """Unified FreeSurfer volumetric analysis tool.

    Extracts volumetric measurements from FreeSurfer aseg and wmparc
    segmentations. Provides volumes for subcortical structures,
    ventricles, white matter parcels, and intracranial volume.

    Delegates to the existing FreeSurferVolumetricTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FreeSurfer volumetric tool."""
        self._tool = FreeSurferVolumetricTool()

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
        """Run FreeSurfer volumetric analysis.

        Args:
            **kwargs: Arguments matching FreeSurferVolumetricArgs schema.

        Returns:
            ToolResult with volumetric measurements.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


class FreeSurferQCPipeline(NeuroTool):
    """Unified FreeSurfer quality control tool.

    Extracts quality control metrics from FreeSurfer recon-all output.
    Includes surface quality metrics, Euler numbers, and visual QC
    snapshots for manual inspection of segmentation quality.

    Delegates to the existing FreeSurferQCTool implementation.
    """

    execution_mode = ExecutionMode.SUBPROCESS

    def __init__(self):
        """Initialize FreeSurfer QC tool."""
        self._tool = FreeSurferQCTool()

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
        """Run FreeSurfer quality control analysis.

        Args:
            **kwargs: Arguments matching FreeSurferQCArgs schema.

        Returns:
            ToolResult with QC metrics and visualizations.
        """
        result = self._tool._run(**kwargs)
        return ToolResult(
            status=result.status,
            data=result.data,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = [
    "FreeSurferReconAllPipeline",
    "FreeSurferParcellationPipeline",
    "FreeSurferVolumetricPipeline",
    "FreeSurferQCPipeline",
]
