"""Agent wrapper for ASL perfusion fallback workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    ASLPerfusionParameters,
    asl_perfusion_from_payload,
    run_asl_perfusion,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ASLPerfusionArgs(BaseModel):
    """Arguments accepted by the fallback ASL pipeline."""

    model_config = ConfigDict(extra="ignore")

    asl_file: str = Field(description="ASL 4D series (tag/control pairs)")
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    m0_file: Optional[str] = Field(
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
    delays: Optional[list[float]] = Field(
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
    random_seed: Optional[int] = Field(default=42, description="Deterministic seed")


class ASLPerfusionTool(NeuroToolWrapper):
    """Delegates ASL perfusion logic to neurocore fallback."""

    def get_tool_name(self) -> str:
        return "asl_perfusion"

    def get_tool_description(self) -> str:
        return "Quantify CBF from ASL series via neurocore fallback implementation."

    def get_args_schema(self):
        return ASLPerfusionArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = ASLPerfusionArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "asl_perfusion")

            params: ASLPerfusionParameters = asl_perfusion_from_payload(payload)
            results = run_asl_perfusion(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("ASL perfusion failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class ASLPerfusionTools:
    """Registry helper for ASL tools."""

    @staticmethod
    def get_all_tools():
        return [ASLPerfusionTool()]


__all__ = ["ASLPerfusionTool", "ASLPerfusionArgs", "ASLPerfusionTools"]
