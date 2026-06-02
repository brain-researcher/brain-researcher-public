"""Tool wrapper for preprocessing pupillometry traces."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    PupillometryPreprocessParameters,
    pupillometry_preprocess_from_payload,
    run_pupillometry_preprocess,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PupillometryPreprocessArgs(BaseModel):
    """Arguments accepted by the pupillometry preprocessing tool."""

    model_config = ConfigDict(extra="ignore")

    pupil_file: str = Field(
        description="Raw pupillometry TSV/CSV/parquet with a pupil diameter column"
    )
    output_dir: str | None = Field(
        default=None, description="Directory for preprocessing outputs"
    )
    sampling_rate_hz: float | None = Field(
        default=None,
        description="Sampling frequency in Hz when no time column is available",
    )
    delimiter: str | None = Field(
        default=None, description="Optional delimiter override"
    )
    time_column: str | None = Field(
        default=None, description="Explicit time column in seconds"
    )
    pupil_column: str | None = Field(
        default=None, description="Explicit pupil diameter column name"
    )
    min_pupil: float = Field(
        default=0.0,
        description="Values at or below this threshold are treated as blinks",
    )
    blink_derivative_threshold: float = Field(
        default=6.0,
        description="Robust-z threshold on the pupil derivative for blink detection",
    )
    blink_padding_s: float = Field(
        default=0.15, description="Seconds of padding around detected blinks"
    )
    low_pass_hz: float = Field(
        default=4.0, description="Low-pass cutoff for the cleaned pupil signal"
    )
    tonic_low_pass_hz: float = Field(
        default=0.2,
        description="Lower cutoff used to derive the tonic component from the cleaned signal",
    )
    peak_prominence_z: float = Field(
        default=1.0,
        description="Minimum phasic z-scored prominence for arousal peak events",
    )
    peak_distance_s: float = Field(
        default=1.0, description="Minimum spacing between arousal peaks in seconds"
    )
    standardize: bool = Field(
        default=True,
        description="Z-score cleaned, derivative, tonic, and phasic traces",
    )
    t_r: float | None = Field(
        default=None,
        description="Optional fMRI repetition time; with n_scans exports scan-aligned confounds",
    )
    n_scans: int | None = Field(
        default=None,
        description="Optional number of scans; with t_r exports scan-aligned confounds",
    )
    scan_start_s: float = Field(
        default=0.0, description="Start time offset for the first BOLD sample"
    )


class PupillometryPreprocessTool(NeuroToolWrapper):
    """Preprocess pupil traces into cleaned signals, events, and confounds."""

    def get_tool_name(self) -> str:
        return "pupillometry_preprocess"

    def get_tool_description(self) -> str:
        return (
            "Clean raw pupillometry traces, detect blinks and arousal peaks, "
            "and optionally export scan-aligned confounds for downstream GLM use."
        )

    def get_args_schema(self):
        return PupillometryPreprocessArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = PupillometryPreprocessArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "pupillometry_preprocess")
            params: PupillometryPreprocessParameters = (
                pupillometry_preprocess_from_payload(payload)
            )
            result = run_pupillometry_preprocess(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("Pupillometry preprocessing failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class PupillometryPreprocessTools:
    """Registry helper for pupillometry preprocessing tools."""

    @staticmethod
    def get_all_tools():
        return [PupillometryPreprocessTool()]


__all__ = [
    "PupillometryPreprocessArgs",
    "PupillometryPreprocessTool",
    "PupillometryPreprocessTools",
]
