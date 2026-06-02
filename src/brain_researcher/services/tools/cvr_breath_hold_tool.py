"""Tool wrapper for lightweight CVR breath-hold analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    CVRBreathHoldParameters,
    cvr_breath_hold_from_payload,
    run_cvr_breath_hold,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class CVRBreathHoldArgs(BaseModel):
    """Arguments accepted by the CVR breath-hold tool."""

    model_config = ConfigDict(extra="ignore")

    signal_file: str = Field(
        description="BOLD ROI/global signal TSV/CSV/parquet with one numeric signal column"
    )
    signal_column: str | None = Field(
        default=None, description="Explicit signal column name"
    )
    time_column: str | None = Field(
        default=None, description="Explicit time column in seconds"
    )
    output_dir: str | None = Field(
        default=None, description="Directory for CVR outputs"
    )
    delimiter: str | None = Field(
        default=None, description="Optional delimiter override"
    )
    events_file: str | None = Field(
        default=None, description="Optional breath-hold events TSV/CSV/parquet"
    )
    event_onset_column: str = Field(
        default="onset", description="Event onset column name"
    )
    event_duration_column: str = Field(
        default="duration", description="Event duration column name"
    )
    event_type_column: str | None = Field(
        default=None, description="Optional event type/label column"
    )
    breath_hold_label: str = Field(
        default="breath_hold",
        description="Case-insensitive label used to select breath-hold rows",
    )
    breath_hold_onsets: list[float] | None = Field(
        default=None, description="Inline breath-hold onset times in seconds"
    )
    breath_hold_durations: list[float] | None = Field(
        default=None, description="Inline breath-hold durations in seconds"
    )
    t_r: float | None = Field(
        default=None,
        description="Repetition time in seconds when the signal is scan-aligned",
    )
    n_scans: int | None = Field(
        default=None,
        description="Optional expected number of scans when the signal is scan-aligned",
    )
    scan_start_s: float = Field(
        default=0.0, description="Start offset for the first scan or time sample"
    )
    lag_min_s: float = Field(default=0.0, description="Minimum lag to scan in seconds")
    lag_max_s: float = Field(default=20.0, description="Maximum lag to scan in seconds")
    lag_step_s: float = Field(
        default=0.5, description="Step size for lag scan in seconds"
    )
    baseline_window_s: float = Field(
        default=10.0, description="Pre-event baseline window in seconds"
    )
    standardize: bool = Field(
        default=True, description="Standardize the detrended signal and lag regressors"
    )
    detrend: bool = Field(
        default=True, description="Remove a linear trend before lag fitting"
    )


class CVRBreathHoldTool(NeuroToolWrapper):
    """Estimate a lightweight CVR lag and amplitude summary."""

    def get_tool_name(self) -> str:
        return "cvr_breath_hold"

    def get_tool_description(self) -> str:
        return (
            "Estimate a simple CVR response lag and amplitude summary from a BOLD "
            "ROI/global signal and a breath-hold schedule."
        )

    def get_args_schema(self):
        return CVRBreathHoldArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = CVRBreathHoldArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "cvr_breath_hold")
            params: CVRBreathHoldParameters = cvr_breath_hold_from_payload(payload)
            result = run_cvr_breath_hold(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("CVR breath-hold analysis failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class CVRBreathHoldTools:
    """Registry helper for CVR tools."""

    @staticmethod
    def get_all_tools():
        return [CVRBreathHoldTool()]


__all__ = [
    "CVRBreathHoldArgs",
    "CVRBreathHoldTool",
    "CVRBreathHoldTools",
]
