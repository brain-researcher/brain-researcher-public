"""
Nilearn GLM Tools

This module provides tools for first and second-level General Linear Model (GLM)
analysis using Nilearn, with full parameter schemas, examples, and metadata for
proper LLM function calling.
"""

from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
from pathlib import Path
import logging
from brain_researcher.services.tools.result import ToolResult

from brain_researcher.services.tools.params import (
    GLMFirstLevelParameters,
    GLMSecondLevelParameters,
    glm_first_level_from_payload,
    glm_second_level_from_payload,
    run_glm_first_level,
    run_glm_second_level,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper
from brain_researcher.services.tools.spec import ToolExample

logger = logging.getLogger(__name__)


# =============================================================================
# 1. GLM First Level Tool
# =============================================================================


class GLMFirstLevelArgs(BaseModel):
    """Arguments for first-level GLM analysis."""

    img: str = Field(description="Path to 4D BOLD fMRI image (nifti format)")
    events: Optional[str] = Field(
        None, description="Path to events.tsv file or 'auto' to detect from BIDS"
    )
    t_r: Optional[float] = Field(
        None, description="Repetition time in seconds (auto-detect if not provided)"
    )
    hrf_model: str = Field(
        default="spm",
        description="HRF model: 'spm', 'spm + derivative', 'glover', 'fir', or 'flobs' (also accepts aliases 'canonical' and 'derivs')",
    )
    fir_delays: Optional[List[int]] = Field(
        None,
        description="Optional FIR delay bins (in scans) used when hrf_model='fir'",
    )
    flobs_basis_file: Optional[str] = Field(
        None,
        description="Optional path to an FSL FLOBS basis file when hrf_model='flobs'",
    )
    flobs_dt: float = Field(
        default=0.05,
        description="Sampling step in seconds for FLOBS basis convolution",
    )
    drift_model: str = Field(
        default="cosine", description="Drift model: 'polynomial', 'cosine', None"
    )
    high_pass: float = Field(default=0.01, description="High-pass filter cutoff in Hz")
    mask_img: Optional[str] = Field(
        None, description="Path to brain mask or 'compute' to generate"
    )
    smoothing_fwhm: Optional[float] = Field(
        None, description="Smoothing kernel size in mm"
    )
    standardize: bool = Field(default=True, description="Standardize the data")
    noise_model: str = Field(default="ar1", description="Noise model: 'ar1', 'ols'")
    n_jobs: int = Field(default=-1, description="Number of parallel jobs")
    contrasts: Optional[Dict[str, List[float]]] = Field(
        None, description="Contrast definitions"
    )
    confounds: Optional[str] = Field(
        None, description="Optional confounds TSV/CSV to include during GLM fitting"
    )
    output_dir: Optional[str] = Field(None, description="Directory to save results")


class GLMFirstLevelTool(NeuroToolWrapper):
    """First-level GLM analysis using Nilearn."""

    name = "glm_first_level"
    description = "Perform first-level GLM analysis on task fMRI data with automatic BIDS integration"
    category = "glm"

    # Synonym mappings for this tool
    ARG_SYNONYMS = {
        "t_r": ["TR", "repetition_time", "tr"],
        "hrf_model": ["hrf", "hemodynamic_model", "basis"],
        "high_pass": ["hp_filter", "highpass", "hp"],
        "mask_img": ["mask", "brain_mask", "mask_file"],
        "smoothing_fwhm": ["fwhm", "smooth", "kernel_size"],
        "standardize": ["zscore", "normalize", "z_score"],
        "n_jobs": ["n_cpus", "n_cores", "parallel"],
    }

    # Examples for LLM understanding
    EXAMPLES = [
        ToolExample(
            user_query="Run GLM on my task fMRI data",
            params={
                "img": "sub-01_task-nback_bold.nii.gz",
                "events": "auto",
                "t_r": 2.0,
                "hrf_model": "spm",
                "contrasts": {"2back-0back": [0, -1, 1]},
            },
            notes="Basic task GLM with automatic event detection",
        ),
        ToolExample(
            user_query="Analyze motor task with FIR basis functions",
            params={
                "img": "sub-01_task-motor_bold.nii.gz",
                "events": "sub-01_task-motor_events.tsv",
                "t_r": "auto",
                "hrf_model": "fir",
                "fir_delays": [0, 2, 4, 6, 8, 10],
                "smoothing_fwhm": 6.0,
            },
            notes="FIR model for HRF estimation with smoothing",
        ),
        ToolExample(
            user_query="Process resting state data with confound regression",
            params={
                "img": "sub-01_task-rest_bold.nii.gz",
                "events": None,
                "t_r": 2.5,
                "confounds": "auto",
                "high_pass": 0.008,
                "standardize": True,
            },
            notes="Resting state preprocessing with filtering",
        ),
    ]

    # Safety constraints
    SAFETY = ["max_memory=8GB", "temp_dir=/scratch", "n_jobs<=4"]

    args_model = GLMFirstLevelArgs

    def get_tool_name(self):
        return self.name

    def get_tool_description(self):
        return self.description

    def get_args_schema(self):
        return self.args_model

    def _run(self, **kwargs):
        out = self._invoke(**kwargs)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, dict):
            status = out.get("status", "success")
            data = {k: v for k, v in out.items() if k != "status"}
            return ToolResult(status=status, data=data)
        return ToolResult(status="success", data={"result": out})

    def _invoke(self, **kwargs) -> Dict[str, Any]:
        """Execute first-level GLM analysis."""
        args = GLMFirstLevelArgs(**kwargs)
        payload = args.model_dump()
        payload["output_dir"] = payload.get("output_dir") or str(
            Path.cwd() / "glm_first_level"
        )
        params: GLMFirstLevelParameters = glm_first_level_from_payload(payload)
        result = run_glm_first_level(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# 2. Second Level GLM Tool
# =============================================================================


class SecondLevelGLMArgs(BaseModel):
    """Arguments for second-level (group) GLM analysis."""

    contrast_maps: List[str] = Field(description="List of first-level contrast maps")
    design_matrix: Optional[Union[str, Dict]] = Field(
        None, description="Design matrix or path to CSV"
    )
    contrast: Optional[Union[str, List[float]]] = Field(
        None, description="Second-level contrast"
    )
    mask_img: Optional[str] = Field(None, description="Group mask image")
    smoothing_fwhm: Optional[float] = Field(None, description="Smoothing kernel")
    model_type: str = Field(default="ols", description="Model type: 'ols' or 'mixedlm'")
    output_dir: Optional[str] = Field(None, description="Output directory")


class SecondLevelGLMTool(NeuroToolWrapper):
    """Second-level group analysis."""

    name = "glm_second_level"
    description = "Perform group-level GLM analysis on first-level contrasts"
    category = "glm"

    EXAMPLES = [
        ToolExample(
            user_query="Run group analysis on contrast maps",
            params={
                "contrast_maps": [
                    "sub-01_2back-0back.nii.gz",
                    "sub-02_2back-0back.nii.gz",
                ],
                "contrast": "mean",
                "smoothing_fwhm": 8.0,
            },
            notes="Simple one-sample t-test",
        )
    ]

    args_model = SecondLevelGLMArgs

    def get_tool_name(self):
        return self.name

    def get_tool_description(self):
        return self.description

    def get_args_schema(self):
        return self.args_model

    def _run(self, **kwargs):
        out = self._invoke(**kwargs)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, dict):
            status = out.get("status", "success")
            data = {k: v for k, v in out.items() if k != "status"}
            return ToolResult(status=status, data=data)
        return ToolResult(status="success", data={"result": out})

    def _invoke(self, **kwargs) -> Dict[str, Any]:
        """Run second-level analysis."""
        args = SecondLevelGLMArgs(**kwargs)
        payload = args.model_dump()
        payload["output_dir"] = payload.get("output_dir") or str(
            Path.cwd() / "glm_second_level"
        )
        params: GLMSecondLevelParameters = glm_second_level_from_payload(payload)
        result = run_glm_second_level(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# Tool Registration
# =============================================================================


def register_glm_tools(registry):
    """Register all GLM tools."""
    tools = [GLMFirstLevelTool(), SecondLevelGLMTool()]

    for tool in tools:
        registry.register_tool(tool)
        logger.info(f"Registered GLM tool: {tool.name}")

    return len(tools)
