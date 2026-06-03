"""
HCP Workbench (Connectome Workbench) implementation for Brain Researcher.

Implements wb_command interface for surface-based analysis, CIFTI processing,
and visualization of Human Connectome Project data.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class HCPWorkbenchCommand(BaseModel):
    """Base arguments for HCP Workbench commands."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: str = Field(
        description="Workbench command to execute (e.g., -cifti-smoothing, -volume-to-surface, etc.)"
    )
    input_file: str = Field(description="Primary input file (CIFTI, GIFTI, or NIfTI)")
    output_file: str = Field(description="Output file path")
    additional_args: dict[str, Any] | None = Field(
        default=None, description="Additional command-specific arguments"
    )


class CiftiSmoothingArgs(BaseModel):
    """Arguments for CIFTI smoothing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    cifti_in: str = Field(description="Input CIFTI file")
    surface_kernel_size: float = Field(description="Sigma for surface smoothing (mm)")
    volume_kernel_size: float = Field(description="Sigma for volume smoothing (mm)")
    direction: str = Field(
        default="COLUMN", description="Direction to smooth along (COLUMN or ROW)"
    )
    cifti_out: str = Field(description="Output smoothed CIFTI file")
    left_surface: str | None = Field(
        default=None, description="Left hemisphere surface file"
    )
    right_surface: str | None = Field(
        default=None, description="Right hemisphere surface file"
    )
    left_corrected_areas: str | None = Field(
        default=None, description="Left hemisphere vertex area correction file"
    )
    right_corrected_areas: str | None = Field(
        default=None, description="Right hemisphere vertex area correction file"
    )


class VolumeToSurfaceArgs(BaseModel):
    """Arguments for volume to surface mapping."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    volume_file: str = Field(description="Input volume file (NIfTI)")
    surface_file: str = Field(description="Surface file to map onto (GIFTI)")
    metric_out: str = Field(description="Output metric file (GIFTI)")
    method: str = Field(
        default="trilinear",
        description="Interpolation method (trilinear, enclosing, cubic)",
    )
    ribbon_constrained: bool = Field(
        default=False, description="Use ribbon-constrained mapping"
    )
    inner_surface: str | None = Field(
        default=None, description="Inner surface for ribbon mapping (white matter)"
    )
    outer_surface: str | None = Field(
        default=None, description="Outer surface for ribbon mapping (pial)"
    )
    volume_roi: str | None = Field(
        default=None, description="Volume ROI to constrain mapping"
    )


class SurfaceResampleArgs(BaseModel):
    """Arguments for surface resampling."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    surface_in: str = Field(description="Input surface file")
    current_sphere: str = Field(description="Current sphere registration")
    new_sphere: str = Field(description="Target sphere registration")
    method: str = Field(
        default="BARYCENTRIC",
        description="Resampling method (BARYCENTRIC or ADAP_BARY_AREA)",
    )
    surface_out: str = Field(description="Output resampled surface")
    area_surfs: bool = Field(default=False, description="Use area correction")
    current_area: str | None = Field(
        default=None, description="Current surface area file"
    )
    new_area: str | None = Field(default=None, description="New surface area file")


class HCPWorkbenchTool(NeuroToolWrapper):
    """HCP Workbench tool."""

    def __init__(self):
        """Initialize HCP Workbench tool."""
        super().__init__()
        self.workbench_dir = (
            "/cvmfs/neurodesk.ardc.edu.au/containers/connectomeworkbench_1.5.0_20220914"
        )
        self.wb_command = None
        self._check_workbench()

    def _check_workbench(self):
        """Check HCP Workbench availability."""
        if Path(self.workbench_dir).exists():
            self.wb_command = f"{self.workbench_dir}/wb_command"
            if not Path(self.wb_command).exists():
                # Try alternative location
                self.wb_command = f"{self.workbench_dir}/bin/wb_command"

        if not self.wb_command or not Path(self.wb_command).exists():
            logger.warning("HCP Workbench not found via Neurodesk, checking system")
            import shutil

            self.wb_command = shutil.which("wb_command")
            if not self.wb_command:
                logger.error("HCP Workbench not found")
        else:
            logger.info(f"HCP Workbench available at {self.wb_command}")

    def get_tool_name(self) -> str:
        return "hcp_workbench"

    def get_tool_description(self) -> str:
        return (
            "HCP Workbench (Connectome Workbench) for surface-based neuroimaging analysis. "
            "Supports CIFTI file processing, surface mapping, resampling, smoothing, "
            "parcellation, and visualization of Human Connectome Project data."
        )

    def get_args_schema(self):
        return HCPWorkbenchCommand

    def _run(
        self,
        command: str,
        input_file: str,
        output_file: str,
        additional_args: dict[str, Any] | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute generic HCP Workbench command."""
        try:
            if not self.wb_command:
                return ToolResult(
                    status="error", error="HCP Workbench not available", data={}
                )

            # Build command
            cmd = [self.wb_command, command, input_file, output_file]

            # Add additional arguments
            if additional_args:
                for key, value in additional_args.items():
                    if value is not None:
                        if isinstance(value, bool):
                            if value:
                                cmd.append(f"-{key}")
                        else:
                            cmd.extend([f"-{key}", str(value)])

            logger.info(f"Running HCP Workbench command: {' '.join(cmd)}")

            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(cmd),
                        "output_file": output_file,
                        "message": f"HCP Workbench {command} completed successfully",
                    },
                )
            else:
                return ToolResult(
                    status="error",
                    error=f"HCP Workbench command failed: {result.stderr}",
                    data={"command": " ".join(cmd)},
                )

        except Exception as e:
            logger.error(f"HCP Workbench failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class CiftiSmoothingTool(NeuroToolWrapper):
    """CIFTI smoothing tool using HCP Workbench."""

    def __init__(self):
        """Initialize CIFTI smoothing tool."""
        super().__init__()
        self.workbench = HCPWorkbenchTool()

    def get_tool_name(self) -> str:
        return "cifti_smoothing"

    def get_tool_description(self) -> str:
        return (
            "Smooth CIFTI files using HCP Workbench. Applies Gaussian smoothing "
            "to surface and volume components with specified kernel sizes."
        )

    def get_args_schema(self):
        return CiftiSmoothingArgs

    def _run(
        self,
        cifti_in: str,
        surface_kernel_size: float,
        volume_kernel_size: float,
        cifti_out: str,
        direction: str = "COLUMN",
        left_surface: str | None = None,
        right_surface: str | None = None,
        left_corrected_areas: str | None = None,
        right_corrected_areas: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute CIFTI smoothing."""
        try:
            if not self.workbench.wb_command:
                return ToolResult(
                    status="error", error="HCP Workbench not available", data={}
                )

            # Validate input
            if not Path(cifti_in).exists():
                return ToolResult(
                    status="error",
                    error=f"Input CIFTI file not found: {cifti_in}",
                    data={},
                )

            # Build command
            cmd = [
                self.workbench.wb_command,
                "-cifti-smoothing",
                cifti_in,
                str(surface_kernel_size),
                str(volume_kernel_size),
                direction,
                cifti_out,
            ]

            # Add optional surface files
            if left_surface:
                cmd.extend(["-left-surface", left_surface])
            if right_surface:
                cmd.extend(["-right-surface", right_surface])
            if left_corrected_areas:
                cmd.extend(["-left-corrected-areas", left_corrected_areas])
            if right_corrected_areas:
                cmd.extend(["-right-corrected-areas", right_corrected_areas])

            logger.info(f"Running CIFTI smoothing: {' '.join(cmd)}")

            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(cmd),
                        "output_file": cifti_out,
                        "surface_kernel": surface_kernel_size,
                        "volume_kernel": volume_kernel_size,
                        "message": "CIFTI smoothing completed successfully",
                    },
                )
            else:
                return ToolResult(
                    status="error",
                    error=f"CIFTI smoothing failed: {result.stderr}",
                    data={"command": " ".join(cmd)},
                )

        except Exception as e:
            logger.error(f"CIFTI smoothing failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class VolumeToSurfaceTool(NeuroToolWrapper):
    """Volume to surface mapping tool using HCP Workbench."""

    def __init__(self):
        """Initialize volume to surface tool."""
        super().__init__()
        self.workbench = HCPWorkbenchTool()

    def get_tool_name(self) -> str:
        return "volume_to_surface"

    def get_tool_description(self) -> str:
        return (
            "Map volumetric data to surface using HCP Workbench. "
            "Supports various interpolation methods and ribbon-constrained mapping."
        )

    def get_args_schema(self):
        return VolumeToSurfaceArgs

    def _run(
        self,
        volume_file: str,
        surface_file: str,
        metric_out: str,
        method: str = "trilinear",
        ribbon_constrained: bool = False,
        inner_surface: str | None = None,
        outer_surface: str | None = None,
        volume_roi: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute volume to surface mapping."""
        try:
            if not self.workbench.wb_command:
                return ToolResult(
                    status="error", error="HCP Workbench not available", data={}
                )

            # Validate inputs
            if not Path(volume_file).exists():
                return ToolResult(
                    status="error",
                    error=f"Volume file not found: {volume_file}",
                    data={},
                )

            if not Path(surface_file).exists():
                return ToolResult(
                    status="error",
                    error=f"Surface file not found: {surface_file}",
                    data={},
                )

            # Build command
            cmd = [
                self.workbench.wb_command,
                "-volume-to-surface-mapping",
                volume_file,
                surface_file,
                metric_out,
            ]

            if ribbon_constrained and inner_surface and outer_surface:
                cmd.extend(["-ribbon-constrained", inner_surface, outer_surface])
            else:
                cmd.extend([f"-{method}"])

            if volume_roi:
                cmd.extend(["-volume-roi", volume_roi])

            logger.info(f"Running volume to surface mapping: {' '.join(cmd)}")

            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(cmd),
                        "output_file": metric_out,
                        "method": (
                            "ribbon-constrained" if ribbon_constrained else method
                        ),
                        "message": "Volume to surface mapping completed successfully",
                    },
                )
            else:
                return ToolResult(
                    status="error",
                    error=f"Volume to surface mapping failed: {result.stderr}",
                    data={"command": " ".join(cmd)},
                )

        except Exception as e:
            logger.error(f"Volume to surface mapping failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class SurfaceResampleTool(NeuroToolWrapper):
    """Surface resampling tool using HCP Workbench."""

    def __init__(self):
        """Initialize surface resample tool."""
        super().__init__()
        self.workbench = HCPWorkbenchTool()

    def get_tool_name(self) -> str:
        return "surface_resample"

    def get_tool_description(self) -> str:
        return (
            "Resample surface data between different mesh resolutions using HCP Workbench. "
            "Supports barycentric and area-preserving methods."
        )

    def get_args_schema(self):
        return SurfaceResampleArgs

    def _run(
        self,
        surface_in: str,
        current_sphere: str,
        new_sphere: str,
        surface_out: str,
        method: str = "BARYCENTRIC",
        area_surfs: bool = False,
        current_area: str | None = None,
        new_area: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute surface resampling."""
        try:
            if not self.workbench.wb_command:
                return ToolResult(
                    status="error", error="HCP Workbench not available", data={}
                )

            # Validate inputs
            for f, name in [
                (surface_in, "surface"),
                (current_sphere, "current sphere"),
                (new_sphere, "new sphere"),
            ]:
                if not Path(f).exists():
                    return ToolResult(
                        status="error", error=f"{name} file not found: {f}", data={}
                    )

            # Build command
            cmd = [
                self.workbench.wb_command,
                "-surface-resample",
                surface_in,
                current_sphere,
                new_sphere,
                method,
                surface_out,
            ]

            if area_surfs and current_area and new_area:
                cmd.extend(["-area-surfs", current_area, new_area])

            logger.info(f"Running surface resampling: {' '.join(cmd)}")

            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(cmd),
                        "output_file": surface_out,
                        "method": method,
                        "message": "Surface resampling completed successfully",
                    },
                )
            else:
                return ToolResult(
                    status="error",
                    error=f"Surface resampling failed: {result.stderr}",
                    data={"command": " ".join(cmd)},
                )

        except Exception as e:
            logger.error(f"Surface resampling failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class HCPWorkbenchTools:
    """Collection of HCP Workbench tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all HCP Workbench tools."""
        return [
            HCPWorkbenchTool(),
            CiftiSmoothingTool(),
            VolumeToSurfaceTool(),
            SurfaceResampleTool(),
        ]
