"""Agent wrapper for the FOOOF spectral parameterisation tool."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    MNEFOOOFParameters,
    mne_fooof_from_payload,
    run_mne_fooof,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class FOOOFArgs(BaseModel):
    raw_file: Optional[str] = None
    epochs_file: Optional[str] = None
    psd_file: Optional[str] = None
    freq_range: tuple[float, float] = Field(default=(1.0, 40.0))
    peak_width_limits: tuple[float, float] = Field(default=(0.5, 12.0))
    max_n_peaks: int = 6
    min_peak_height: float = 0.0
    peak_threshold: float = 2.0
    aperiodic_mode: str = "fixed"
    picks: Optional[list[str]] = None
    group_mode: bool = False
    output_dir: str
    save_model: bool = True
    save_report: bool = True
    save_plots: bool = True


class MNEFOOOFTool(NeuroToolWrapper):
    """Thin wrapper delegating to neurocore FOOOF helpers."""

    def __init__(self) -> None:
        super().__init__()
        try:
            import fooof  # noqa: F401

            self.fooof_available = True
        except ImportError:
            self.fooof_available = False
            logger.warning(
                "FOOOF package not installed; using lightweight spectral parameterization"
            )

    def get_tool_name(self) -> str:
        return "mne_fooof"

    def get_tool_description(self) -> str:
        return "Parameterise power spectra into periodic/aperiodic components using FOOOF neurocore helpers."

    def get_args_schema(self):  # noqa: D401
        return FOOOFArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        args = FOOOFArgs(**kwargs)
        payload: Dict[str, Any] = args.model_dump()
        payload["output_dir"] = args.output_dir or str(Path.cwd() / "fooof_output")
        params: MNEFOOOFParameters = mne_fooof_from_payload(payload)
        result = run_mne_fooof(params)
        return ToolResult(status="success", data=result)


class MNEFOOOFTools:
    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [MNEFOOOFTool()]


__all__ = ["MNEFOOOFTool", "MNEFOOOFTools"]
