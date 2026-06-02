"""Tool wrapper for a surrogate calibrated-perfusion bundle."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    CalibratedPerfusionSurrogateParameters,
    calibrated_perfusion_surrogate_from_payload,
    run_calibrated_perfusion_surrogate,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class CalibratedPerfusionSurrogateArgs(BaseModel):
    """Arguments accepted by the surrogate calibrated-perfusion tool."""

    model_config = ConfigDict(extra="ignore")

    asl_file: str = Field(description="ASL 4D series (tag/control pairs)")
    signal_file: str = Field(
        description="BOLD ROI/global signal TSV/CSV/parquet for CVR summarization"
    )
    output_dir: str | None = Field(default=None, description="Directory for outputs")

    m0_file: str | None = Field(
        default=None, description="Optional M0 calibration image"
    )
    asl_type: str = Field(default="pcasl", description="Acquisition type")
    labeling_duration: float = Field(default=1.8, description="Labeling duration (s)")
    post_labeling_delay: list[float] = Field(
        default_factory=lambda: [2.0], description="Post-labeling delays (s)"
    )
    multi_delay: bool = Field(
        default=False, description="Whether multiple PLDs were acquired"
    )
    delays: list[float] | None = Field(
        default=None, description="Explicit multi-delay list"
    )
    use_m0: bool = Field(default=True, description="Use M0 for calibration")
    m0_scale: float = Field(default=1.0, description="Scale factor applied to M0")
    cbf_units: str = Field(default="ml/100g/min", description="Units for CBF reporting")
    compute_snr: bool = Field(default=True, description="Compute SNR metric")
    compute_cnr: bool = Field(default=True, description="Compute CNR metric")
    temporal_snr: bool = Field(default=True, description="Compute temporal SNR")
    save_cbf: bool = Field(default=True, description="Persist CBF map")
    save_att: bool = Field(default=True, description="Persist ATT map when available")
    save_qc: bool = Field(default=True, description="Persist QC metrics")
    save_perfusion_weighted: bool = Field(
        default=True, description="Persist perfusion-weighted map"
    )
    visualize: bool = Field(
        default=True, description="Generate summary visualization assets"
    )
    random_seed: int | None = Field(default=42, description="Deterministic seed")

    signal_column: str | None = Field(
        default=None, description="Explicit signal column name"
    )
    time_column: str | None = Field(
        default=None, description="Explicit time column in seconds"
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


class CalibratedPerfusionSurrogateTool(NeuroToolWrapper):
    """Bundle ASL perfusion and CVR summaries without claiming CMRO2."""

    def get_tool_name(self) -> str:
        return "calibrated_perfusion_surrogate"

    def get_tool_description(self) -> str:
        return (
            "Run ASL perfusion and CVR breath-hold summaries side by side, then bundle "
            "the outputs into a surrogate calibrated-perfusion report. This does not "
            "estimate CMRO2 or OEF."
        )

    def get_args_schema(self):
        return CalibratedPerfusionSurrogateArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = CalibratedPerfusionSurrogateArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(
                    Path.cwd() / "calibrated_perfusion_surrogate"
                )

            params: CalibratedPerfusionSurrogateParameters = (
                calibrated_perfusion_surrogate_from_payload(payload)
            )
            result = run_calibrated_perfusion_surrogate(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("Surrogate calibrated-perfusion bundle failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class CalibratedPerfusionSurrogateTools:
    """Registry helper for surrogate calibrated-perfusion tools."""

    @staticmethod
    def get_all_tools():
        return [CalibratedPerfusionSurrogateTool()]


__all__ = [
    "CalibratedPerfusionSurrogateArgs",
    "CalibratedPerfusionSurrogateTool",
    "CalibratedPerfusionSurrogateTools",
]
