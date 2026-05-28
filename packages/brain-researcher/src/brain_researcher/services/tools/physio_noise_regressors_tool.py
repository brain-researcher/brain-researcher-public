"""Tool wrapper for scan-aligned physiological nuisance regressors."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    PhysioNoiseRegressorParameters,
    physio_noise_regressors_from_payload,
    run_physio_noise_regressors,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PhysioNoiseRegressorArgs(BaseModel):
    """Arguments accepted by the physio confounds export tool."""

    model_config = ConfigDict(extra="ignore")

    physio_file: str = Field(
        description="Raw physio TSV/CSV with cardiac and/or respiratory traces"
    )
    output_dir: str | None = Field(
        default=None, description="Directory for confounds outputs"
    )
    sampling_rate_hz: float = Field(
        description="Sampling frequency of the physio trace in Hz"
    )
    t_r: float = Field(description="fMRI repetition time in seconds")
    n_scans: int = Field(
        description="Number of BOLD volumes to align regressors against"
    )
    scan_start_s: float = Field(
        default=0.0, description="Start time offset for the first BOLD sample"
    )
    delimiter: str | None = Field(
        default=None, description="Optional delimiter override"
    )
    cardiac_column: str | None = Field(
        default=None, description="Explicit cardiac/PPG/ECG column name"
    )
    respiratory_column: str | None = Field(
        default=None, description="Explicit respiratory column name"
    )
    cardiac_order: int = Field(
        default=3, description="Number of cardiac Fourier harmonics"
    )
    respiratory_order: int = Field(
        default=4, description="Number of respiratory Fourier harmonics"
    )
    interaction_order: int = Field(
        default=1, description="Number of cardiorespiratory interaction harmonics"
    )
    include_resampled_traces: bool = Field(
        default=True,
        description="Include z-scored scan-aligned raw traces and derivatives",
    )
    standardize: bool = Field(
        default=True,
        description="Standardize traces and derived regressors when applicable",
    )


class PhysioNoiseRegressorTool(NeuroToolWrapper):
    """Generate confounds TSVs from raw physiological traces."""

    def get_tool_name(self) -> str:
        return "physio_noise_regressors"

    def get_tool_description(self) -> str:
        return (
            "Generate scan-aligned cardiac and respiratory nuisance regressors "
            "from raw physiological traces for downstream GLM confound modeling."
        )

    def get_args_schema(self):
        return PhysioNoiseRegressorArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = PhysioNoiseRegressorArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "physio_noise_regressors")
            params: PhysioNoiseRegressorParameters = (
                physio_noise_regressors_from_payload(payload)
            )
            result = run_physio_noise_regressors(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("Physio regressor generation failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class PhysioNoiseRegressorTools:
    """Registry helper for physio regressor tools."""

    @staticmethod
    def get_all_tools():
        return [PhysioNoiseRegressorTool()]


__all__ = [
    "PhysioNoiseRegressorArgs",
    "PhysioNoiseRegressorTool",
    "PhysioNoiseRegressorTools",
]
