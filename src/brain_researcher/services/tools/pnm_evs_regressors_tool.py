"""Agent wrapper for FSL PNM EV physiological regressors."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    PnmEvsRegressorParameters,
    pnm_evs_regressors_from_payload,
    run_pnm_evs_regressors,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PnmEvsRegressorArgs(BaseModel):
    """Arguments accepted by the PNM EV wrapper."""

    model_config = ConfigDict(extra="ignore")

    func_file: str = Field(description="4D functional/EPI image used by pnm_evs")
    tr: float = Field(description="Repetition time in seconds")
    output_dir: str | None = Field(default=None, description="Output directory")
    output_prefix: str = Field(default="pnm", description="Output filename prefix")
    dry_run: bool = Field(
        default=False,
        description="If true, only write the command plan without executing pnm_evs",
    )

    cardiac_file: str | None = Field(
        default=None,
        description="Optional cardiac phase or value file accepted by pnm_evs",
    )
    respiratory_file: str | None = Field(
        default=None,
        description="Optional respiratory phase file accepted by pnm_evs",
    )
    rvt_file: str | None = Field(
        default=None,
        description="Optional RVT time/value file",
    )
    heartrate_file: str | None = Field(
        default=None,
        description="Optional heart-rate time/value file",
    )
    csf_mask_file: str | None = Field(
        default=None,
        description="Optional CSF mask image for CSF regressors",
    )
    cardiac_order: int = Field(default=2, description="Order of cardiac Fourier pairs")
    respiratory_order: int = Field(
        default=1,
        description="Order of respiratory Fourier pairs",
    )
    cardiac_multiplicative_order: int = Field(
        default=0,
        description="Order of multiplicative cardiac terms",
    )
    respiratory_multiplicative_order: int = Field(
        default=0,
        description="Order of multiplicative respiratory terms",
    )
    rvt_smooth: float | None = Field(
        default=None, description="Optional RVT smoothing window in seconds"
    )
    heartrate_smooth: float | None = Field(
        default=None,
        description="Optional heartrate smoothing window in seconds",
    )
    slice_direction: str | None = Field(
        default=None,
        description="Optional slice direction x/y/z for slice-aware EVs",
    )
    slice_order: str | None = Field(
        default=None,
        description="Optional slice order such as up/down/interleaved_up/interleaved_down",
    )
    slice_timing_file: str | None = Field(
        default=None,
        description="Optional external slice timing file passed to pnm_evs",
    )
    pnm_evs_bin: str | None = Field(
        default=None,
        description="Explicit pnm_evs binary path",
    )
    extra_args: list[str] = Field(
        default_factory=list,
        description="Extra command-line arguments passed through to pnm_evs",
    )


class PnmEvsRegressorsTool(NeuroToolWrapper):
    """Thin wrapper around FSL PNM EV generation."""

    def get_tool_name(self) -> str:
        return "pnm_evs_regressors"

    def get_tool_description(self) -> str:
        return (
            "Generate slice-aware physiological confound regressors using FSL pnm_evs. "
            "This is the repo-native path for PNM-style cardiac/respiratory EVs when "
            "phase, RVT, heartrate, and slice timing inputs are available."
        )

    def get_args_schema(self):
        return PnmEvsRegressorArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = PnmEvsRegressorArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "pnm_evs_regressors")
            params: PnmEvsRegressorParameters = pnm_evs_regressors_from_payload(payload)
            results = run_pnm_evs_regressors(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("pnm_evs_regressors failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class PnmEvsRegressorsTools:
    @staticmethod
    def get_all_tools():
        return [PnmEvsRegressorsTool()]


__all__ = [
    "PnmEvsRegressorArgs",
    "PnmEvsRegressorsTool",
    "PnmEvsRegressorsTools",
]
