"""Tool wrapper for ROI-level HRF estimation and refit."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    HRFEstimateAndRefitParameters,
    hrf_estimate_and_refit_from_payload,
    run_hrf_estimate_and_refit,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class HRFEstimateAndRefitArgs(BaseModel):
    """Arguments for HRF estimation from FIR and subsequent refitting."""

    model_config = ConfigDict(extra="ignore")

    img: str = Field(description="Path to a 4D BOLD image")
    events: str | None = Field(
        default=None, description="Task events TSV/CSV; defaults to a single block"
    )
    output_dir: str | None = Field(default=None, description="Output directory")
    t_r: float | None = Field(
        default=None, description="Repetition time in seconds (auto-detect if absent)"
    )
    roi_mask: str | None = Field(
        default=None,
        description="Optional ROI mask used to estimate a mean time series",
    )
    mask_img: str | None = Field(
        default=None,
        description="Optional fallback mask if roi_mask is not provided",
    )
    confounds: str | None = Field(
        default=None,
        description="Optional confounds TSV/CSV appended to all design matrices",
    )
    fir_delays: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5],
        description="FIR delay bins in scans for the estimation pass",
    )
    drift_model: str = Field(default="cosine", description="Drift model")
    high_pass: float = Field(default=0.01, description="High-pass cutoff in Hz")
    smoothing_fwhm: float | None = Field(
        default=None, description="Optional spatial smoothing before ROI extraction"
    )
    standardize: bool = Field(
        default=True, description="Standardize the extracted ROI signal"
    )
    comparison_hrf_model: str | None = Field(
        default="canonical",
        description="Optional comparison model such as canonical, glover, fir, or flobs",
    )
    flobs_basis_file: str | None = Field(
        default=None,
        description="Optional FLOBS basis file used when comparison_hrf_model='flobs'",
    )
    flobs_dt: float = Field(
        default=0.05,
        description="Sampling step in seconds for FLOBS basis convolution",
    )


class HRFEstimateAndRefitTool(NeuroToolWrapper):
    """Estimate FIR HRFs and refit using the learned kernel."""

    def get_tool_name(self) -> str:
        return "hrf_estimate_and_refit"

    def get_tool_description(self) -> str:
        return (
            "Estimate ROI-level HRF shapes from a FIR design and compare canonical "
            "versus refit models, with optional FLOBS comparison."
        )

    def get_args_schema(self):
        return HRFEstimateAndRefitArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = HRFEstimateAndRefitArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "hrf_estimate_and_refit")
            params: HRFEstimateAndRefitParameters = hrf_estimate_and_refit_from_payload(
                payload
            )
            result = run_hrf_estimate_and_refit(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("HRF estimate and refit failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class HRFEstimateAndRefitTools:
    """Registry helper for HRF estimation tools."""

    @staticmethod
    def get_all_tools():
        return [HRFEstimateAndRefitTool()]


__all__ = [
    "HRFEstimateAndRefitArgs",
    "HRFEstimateAndRefitTool",
    "HRFEstimateAndRefitTools",
]
