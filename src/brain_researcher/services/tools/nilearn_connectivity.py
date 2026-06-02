"""
Nilearn Connectivity Tools

This module provides tools for functional connectivity analysis.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    ConnectivityMatrixParameters,
    SeedBasedConnectivityParameters,
    connectivity_matrix_from_payload,
    run_connectivity_matrix,
    run_seed_based_connectivity,
    seed_connectivity_from_payload,
)
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.spec import ToolExample
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Connectivity Matrix Tool
# =============================================================================


class ConnectivityMatrixArgs(BaseModel):
    """Arguments for functional connectivity computation."""

    timeseries: Union[str, List[str]] = Field(
        description="Time series data or path to .npy file"
    )
    kind: str = Field(
        default="correlation",
        description="Type: 'correlation', 'partial correlation', 'tangent', 'covariance', 'precision'",
    )
    vectorize: bool = Field(default=False, description="Return vectorized matrix")
    discard_diagonal: bool = Field(default=False, description="Set diagonal to zero")
    fisher_z: bool = Field(
        default=True, description="Apply Fisher z-transform to correlations"
    )
    output_file: Optional[str] = Field(None, description="Save matrix to file")


class ConnectivityMatrixTool(NeuroToolWrapper):
    """Compute functional connectivity matrices."""

    name = "connectivity_matrix"
    description = "Compute functional connectivity using various methods (correlation, partial correlation, etc.)"
    category = "connectivity"

    ARG_SYNONYMS = {
        "kind": ["method", "correlation_type", "measure"],
        "vectorize": ["flatten", "upper_triangle"],
        "fisher_z": ["fisher_transform", "ztransform"],
    }

    EXAMPLES = [
        ToolExample(
            user_query="Calculate functional connectivity",
            params={
                "timeseries": "roi_signals.npy",
                "kind": "correlation",
                "vectorize": True,
                "fisher_z": True,
            },
            notes="Standard correlation with Fisher z",
        ),
        ToolExample(
            user_query="Compute partial correlations",
            params={
                "timeseries": "cleaned_signals.npy",
                "kind": "partial correlation",
                "discard_diagonal": True,
            },
            notes="Partial correlation removing diagonal",
        ),
    ]

    args_model = ConnectivityMatrixArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> Dict[str, Any]:
        out = self._invoke(**kwargs)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, dict):
            status = out.get("status", "success")
            data = {k: v for k, v in out.items() if k != "status"}
            return ToolResult(status=status, data=data)
        return ToolResult(status="success", data={"result": out})

    def _invoke(self, **kwargs) -> Dict[str, Any]:
        """Compute connectivity matrix."""
        args = ConnectivityMatrixArgs(**kwargs)
        payload = args.model_dump()
        params: ConnectivityMatrixParameters = connectivity_matrix_from_payload(payload)
        result = run_connectivity_matrix(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# 2. Seed-Based Connectivity Tool
# =============================================================================


class SeedBasedConnectivityArgs(BaseModel):
    """Arguments for seed-based connectivity analysis."""

    img: str = Field(description="Path to 4D fMRI image")
    seed_coords: Optional[List[float]] = Field(
        None, description="MNI coordinates [x, y, z] for seed"
    )
    seed_mask: Optional[str] = Field(None, description="Path to seed mask image")
    radius: float = Field(default=8.0, description="Radius for spherical seed in mm")
    mask_img: Optional[str] = Field(None, description="Brain mask for analysis")
    smoothing_fwhm: Optional[float] = Field(None, description="Smoothing kernel")
    standardize: bool = Field(default=True, description="Standardize signals")
    detrend: bool = Field(default=True, description="Detrend signals")
    low_pass: Optional[float] = Field(None, description="Low-pass filter")
    high_pass: Optional[float] = Field(None, description="High-pass filter")
    t_r: Optional[float] = Field(None, description="TR for filtering")
    confounds: Optional[str] = Field(None, description="Confounds file path")
    output_file: Optional[str] = Field(None, description="Save connectivity map")


class SeedBasedConnectivityTool(NeuroToolWrapper):
    """Compute seed-based functional connectivity maps."""

    name = "seed_based_fc"
    description = "Calculate whole-brain connectivity from seed regions using correlation analysis"
    category = "connectivity"

    ARG_SYNONYMS = {
        "seed_coords": ["coords", "seed", "mni_coords"],
        "seed_mask": ["seed_roi", "seed_region"],
        "radius": ["sphere_radius", "seed_radius"],
    }

    EXAMPLES = [
        ToolExample(
            user_query="Calculate PCC connectivity",
            params={
                "img": "rest_bold.nii.gz",
                "seed_coords": [0, -52, 18],
                "radius": 10,
                "standardize": True,
                "high_pass": 0.01,
                "t_r": 2.0,
            },
            notes="PCC seed connectivity for DMN",
        ),
        ToolExample(
            user_query="Seed connectivity from amygdala mask",
            params={
                "img": "preprocessed_bold.nii.gz",
                "seed_mask": "amygdala_mask.nii.gz",
                "confounds": "confounds.tsv",
                "smoothing_fwhm": 6.0,
            },
            notes="ROI-based seed connectivity",
        ),
    ]

    args_model = SeedBasedConnectivityArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> Dict[str, Any]:
        out = self._invoke(**kwargs)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, dict):
            status = out.get("status", "success")
            data = {k: v for k, v in out.items() if k != "status"}
            return ToolResult(status=status, data=data)
        return ToolResult(status="success", data={"result": out})

    def _invoke(self, **kwargs) -> Dict[str, Any]:
        """Compute seed-based connectivity."""
        args = SeedBasedConnectivityArgs(**kwargs)
        payload = args.model_dump()
        payload.setdefault(
            "output_dir",
            (
                str(Path(args.output_file).parent)
                if args.output_file
                else str(Path.cwd() / "seed_based_fc")
            ),
        )
        params: SeedBasedConnectivityParameters = seed_connectivity_from_payload(
            payload
        )
        result = run_seed_based_connectivity(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# Tool Registration
# =============================================================================


def register_connectivity_tools(registry):
    """Register all connectivity tools."""
    tools = [
        ConnectivityMatrixTool(),
        SeedBasedConnectivityTool(),
    ]

    for tool in tools:
        registry.register_tool(tool)
        logger.info(f"Registered connectivity tool: {tool.name}")

    return len(tools)
