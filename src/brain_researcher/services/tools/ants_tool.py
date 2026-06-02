"""ANTs registration wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.params import (
    ANTsRegistrationParameters,
    ants_registration_from_payload,
    run_ants_registration,
)
from brain_researcher.services.tools.qc_rendering import (
    render_registration_checkerboard_png,
)
from brain_researcher.services.tools.spec import (
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCRetryRule,
    ToolQCSpec,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ANTsRegistrationArgs(BaseModel):
    """Agent-facing schema for ANTs registration."""

    model_config = ConfigDict(extra="ignore")

    fixed_image: str = Field(description="Fixed/reference image")
    moving_image: str = Field(description="Moving/source image")
    output_prefix: str = Field(
        description="Output prefix for transforms and warped images"
    )
    transform_type: str = Field(
        default="SyN", description="Transform model (Rigid/Affine/SyN)"
    )
    metric: str = Field(default="MI", description="Similarity metric (MI, CC, etc.)")
    convergence: str = Field(
        default="[1000x500x250x100,1e-6,10]", description="Convergence schedule"
    )
    shrink_factors: str = Field(
        default="8x4x2x1", description="Multi-resolution shrink factors"
    )
    smoothing_sigmas: str = Field(
        default="3x2x1x0vox", description="Smoothing sigmas schedule"
    )
    interpolation: str = Field(default="Linear", description="Interpolation method")
    use_histogram_matching: bool = Field(
        default=True, description="Apply histogram matching"
    )
    dimension: int = Field(default=3, description="Image dimensionality")
    float_precision: bool = Field(default=False, description="Use float precision")
    verbose: bool = Field(default=True, description="Verbose output")
    num_threads: int = Field(default=1, description="Threads for execution")
    extra_args: Optional[List[str]] = Field(
        default=None, description="Additional antsRegistration arguments"
    )


QC_SPEC = ToolQCSpec(
    artifact_output_keys=["qc_png", "checkerboard"],
    checklist=[
        "Confirm the warped moving image aligns to the fixed image across all three views.",
        "Look for residual cortical, ventricular, or midline mismatch in the checkerboard.",
        "Reject obvious nonlinear distortions or persistent gross misregistration.",
    ],
    failure_modes=["misregistration", "output_missing", "uncertain"],
    render_contract=ToolQCRenderContract(
        kind="checkerboard",
        layout="tri_planar_montage",
        notes="Review the warped-vs-fixed checkerboard for residual mismatch after ANTs registration.",
    ),
    prechecks=ToolQCPrecheckConfig(
        required_outputs={
            "warped_image": "output_missing",
            "qc_png": "output_missing",
        }
    ),
    retry_rules=[
        ToolQCRetryRule(
            match_any_failure_modes=["misregistration"],
            min_attempt=0,
            max_attempt=0,
            param_updates={"metric": "CC", "use_histogram_matching": True},
            notes="Retry ANTs with a stronger local similarity metric when the checkerboard remains misaligned.",
        ),
    ],
)


class ANTsRegistrationTool(NeuroToolWrapper):
    """ANTs registration thin wrapper backed by NiWrap (ants.antsRegistration.run)."""

    QC_SPEC = QC_SPEC

    def get_tool_name(self) -> str:
        return "ants_registration"

    def get_tool_description(self) -> str:
        return "Perform ANTs image registration producing warped outputs and transforms. Delegates to NiWrap Boutiques definition ants.antsRegistration.run."

    def get_args_schema(self):
        return ANTsRegistrationArgs

    def _run(self, **kwargs) -> ToolResult:
        """Validate args then delegate to NiWrap executor."""
        try:
            args = ANTsRegistrationArgs(**kwargs)
        except Exception as e:  # pragma: no cover
            return ToolResult(status="error", error=str(e), data={})

        out_prefix = kwargs.get("output_prefix") or kwargs.get("output")
        if out_prefix:
            try:
                Path(out_prefix).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="ants.antsRegistration.run",
                parameters=kwargs,
            )
            self._attach_qc_png(args, data)
            return ToolResult(status="success", data=data)
        except Exception as e:
            return ToolResult(status="error", error=str(e), data={})

    def _attach_qc_png(
        self,
        args: ANTsRegistrationArgs,
        payload: Any,
    ) -> None:
        if not isinstance(payload, dict):
            return
        outputs = payload.get("outputs")
        if not isinstance(outputs, dict):
            return
        warped_image = outputs.get("warped_image")
        if not isinstance(warped_image, str):
            return
        if not Path(warped_image).exists() or not Path(args.fixed_image).exists():
            return
        try:
            qc_png = render_registration_checkerboard_png(
                args.fixed_image,
                warped_image,
                Path(warped_image).with_name(f"{Path(warped_image).stem}_qc.png"),
                title="ANTs Registration QC",
            )
            outputs["qc_png"] = qc_png
            outputs["checkerboard"] = qc_png
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to render ANTs QC PNG: %s", exc)


def get_all_tools() -> List[NeuroToolWrapper]:
    return [ANTsRegistrationTool()]


class ANTsTools:
    """Back-compat collection wrapper for registry imports."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return get_all_tools()


__all__ = ["ANTsRegistrationTool", "ANTsTools"]
