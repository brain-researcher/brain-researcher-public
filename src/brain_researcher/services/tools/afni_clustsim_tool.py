"""
AFNI 3dClustSim wrapper.

Delegates Monte Carlo cluster-threshold estimation to the shared neurocore
implementation with deterministic fallbacks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.params import (
    AFNIClustSimParameters,
    afni_clustsim_from_payload,
    run_afni_clustsim,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class AFNIClustSimArgs(BaseModel):
    """Validated arguments exposed to the agent."""

    model_config = ConfigDict(extra="allow")

    input_file: Optional[str] = Field(
        default=None, description="Input dataset (residuals) for ACF estimation"
    )
    mask_file: Optional[str] = Field(
        default=None, description="Optional mask limiting simulation volume"
    )
    fwhm: Optional[Tuple[float, float, float]] = Field(
        default=None, description="Manual smoothness (x,y,z)"
    )
    pthr: List[float] = Field(
        default_factory=lambda: [0.01, 0.005, 0.001],
        description="Voxel-wise p-value thresholds",
    )
    athr: List[float] = Field(
        default_factory=lambda: [0.05, 0.01],
        description="Cluster-level alpha thresholds",
    )
    iter: int = Field(default=10000, description="Number of Monte Carlo iterations")
    seed: Optional[int] = Field(default=None, description="Random seed")
    sided: int = Field(
        default=2, description="Sidedness: 1=positive, 2=two-sided, 3=negative"
    )
    prefix: str = Field(default="ClustSim", description="Output prefix")
    acf: bool = Field(
        default=True, description="Use ACF smoothness estimation if possible"
    )
    fast: bool = Field(
        default=False, description="Use faster analytical approximations"
    )
    nodec: bool = Field(
        default=False, description="Disable deconvolution in estimation"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory for generated outputs"
    )


class AFNIClustSimTool(NeuroToolWrapper):
    """Agent-facing AFNI cluster simulation tool."""

    def get_tool_name(self) -> str:
        return "afni_3dClustSim"

    def get_tool_description(self) -> str:
        return (
            "Estimate cluster-size thresholds with AFNI 3dClustSim semantics. "
            "Automatically falls back to lightweight Monte Carlo approximations when AFNI binaries are unavailable."
        )

    def get_args_schema(self):
        return AFNIClustSimArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            AFNIClustSimArgs(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir") or kwargs.get("prefix")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="afni.3dClustSim.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            logger.exception("AFNI 3dClustSim failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


# ---------------------------------------------------------------------------
# NiWrap-backed AFNI tools (status=exact): 3dBlurInMask, 3dReHo
# ---------------------------------------------------------------------------


class AFNI3dBlurInMaskArgs(BaseModel):
    """Pass-through args for 3dBlurInMask; NiWrap schema is source of truth."""

    model_config = ConfigDict(extra="allow")


class AFNI3dBlurInMaskTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap afni.3dBlurInMask.run."""

    def get_tool_name(self) -> str:
        return "afni_3dBlurInMask"

    def get_tool_description(self) -> str:
        return "AFNI 3dBlurInMask smoothing within mask (NiWrap-backed)."

    def get_args_schema(self):
        return AFNI3dBlurInMaskArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            AFNI3dBlurInMaskArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="afni.3dBlurInMask.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


class AFNI3dReHoArgs(BaseModel):
    """Pass-through args for 3dReHo; NiWrap schema is source of truth."""

    model_config = ConfigDict(extra="allow")


class AFNI3dReHoTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap afni.3dReHo.run."""

    def get_tool_name(self) -> str:
        return "afni_3dReHo"

    def get_tool_description(self) -> str:
        return "AFNI 3dReHo regional homogeneity (NiWrap-backed)."

    def get_args_schema(self):
        return AFNI3dReHoArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            AFNI3dReHoArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="afni.3dReHo.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


class AFNI3dDeconvolveArgs(BaseModel):
    """Pass-through args for 3dDeconvolve; NiWrap schema is source of truth."""

    model_config = ConfigDict(extra="allow")


class AFNI3dDeconvolveTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap afni.3dDeconvolve.run."""

    def get_tool_name(self) -> str:
        return "afni_3dDeconvolve"

    def get_tool_description(self) -> str:
        return "AFNI 3dDeconvolve GLM/deconvolution analysis (NiWrap-backed)."

    def get_args_schema(self):
        return AFNI3dDeconvolveArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            AFNI3dDeconvolveArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="afni.3dDeconvolve.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


class AFNITools:
    """Discovery helper used by the registry."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [
            AFNIClustSimTool(),
            AFNI3dBlurInMaskTool(),
            AFNI3dReHoTool(),
            AFNI3dDeconvolveTool(),
        ]


__all__ = [
    "AFNIClustSimTool",
    "AFNI3dBlurInMaskTool",
    "AFNI3dReHoTool",
    "AFNI3dDeconvolveTool",
    "AFNITools",
]
