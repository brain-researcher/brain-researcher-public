"""Agent wrappers for MNE source localization workflows backed by neurocore."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    MNESourceInverseParameters,
    MNEBeamformerParameters,
    MNEDipoleParameters,
    mne_source_inverse_from_payload,
    mne_beamformer_from_payload,
    mne_dipole_from_payload,
    run_mne_source_inverse,
    run_mne_beamformer,
    run_mne_dipole,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.core.utils import configure_mne_environment

logger = logging.getLogger(__name__)

configure_mne_environment()


class _BaseSourceTool(NeuroToolWrapper):
    """Common helper for source localization wrappers."""

    def __init__(self) -> None:
        super().__init__()
        try:
            import mne  # noqa: F401

            self.mne_available = True
            self.mne_error = None
        except ImportError:
            self.mne_available = False
            self.mne_error = "MNE-Python not installed"
            logger.error(self.mne_error)

    @staticmethod
    def _default_output(output_dir: Optional[str], fallback_name: str) -> str:
        if output_dir:
            return output_dir
        return str(Path.cwd() / fallback_name)


class MNESourceLocalizationArgs(BaseModel):
    raw_file: Optional[str] = None
    epochs_file: Optional[str] = None
    evoked_file: Optional[str] = None
    subjects_dir: str
    subject: str
    forward_file: Optional[str] = None
    bem_file: Optional[str] = None
    trans_file: Optional[str] = None
    spacing: Optional[str] = "oct6"
    surface: str = "white"
    method: str = "dSPM"
    lambda2: Optional[float] = None
    pick_ori: Optional[str] = "normal"
    depth: Optional[float] = 0.8
    noise_cov_file: Optional[str] = None
    baseline: Optional[tuple[Optional[float], Optional[float]]] = (None, 0.0)
    output_dir: str
    save_stc: bool = True
    save_inverse: bool = True
    morphing: Optional[str] = None


class MNEBeamformerArgs(BaseModel):
    raw_file: Optional[str] = None
    epochs_file: Optional[str] = None
    evoked_file: Optional[str] = None
    subjects_dir: str
    subject: str
    forward_file: Optional[str] = None
    trans_file: Optional[str] = None
    data_cov_file: Optional[str] = None
    noise_cov_file: Optional[str] = None
    method: str = "lcmv"
    reg: float = 0.05
    weight_norm: Optional[str] = "unit-noise-gain"
    freq_bands: Optional[list[tuple[float, float]]] = None
    output_dir: str
    save_filters: bool = True
    save_stc: bool = True


class MNEDipoleArgs(BaseModel):
    evoked_file: str
    subjects_dir: str
    subject: str
    trans_file: Optional[str] = None
    bem_file: Optional[str] = None
    output_dir: str
    tmin: Optional[float] = None
    tmax: Optional[float] = None
    n_dipoles: int = 1
    min_dist: float = 5.0
    save_dipoles: bool = True


class MNESourceLocalizationTool(_BaseSourceTool):
    """Wrapper for inverse solutions."""

    def get_tool_name(self) -> str:
        return "mne_source_localization"

    def get_tool_description(self) -> str:
        return "Run MNE inverse solution (MNE/dSPM/sLORETA) using shared neurocore logic."

    def get_args_schema(self):  # noqa: D401
        return MNESourceLocalizationArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        if not self.mne_available:
            return ToolResult(status="error", error=self.mne_error or "MNE not available", data={})
        args = MNESourceLocalizationArgs(**kwargs)
        payload: Dict[str, Any] = args.model_dump()
        payload["output_dir"] = self._default_output(args.output_dir, "inverse_output")
        params: MNESourceInverseParameters = mne_source_inverse_from_payload(payload)
        result = run_mne_source_inverse(params)
        return ToolResult(status="success", data=result)


class MNEBeamformerTool(_BaseSourceTool):
    """Wrapper for beamformer workflows."""

    def get_tool_name(self) -> str:
        return "mne_beamformer"

    def get_tool_description(self) -> str:
        return "Run LCMV/DICS beamformer analysis using neurocore helpers."

    def get_args_schema(self):  # noqa: D401
        return MNEBeamformerArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        if not self.mne_available:
            return ToolResult(status="error", error=self.mne_error or "MNE not available", data={})
        args = MNEBeamformerArgs(**kwargs)
        payload: Dict[str, Any] = args.model_dump()
        payload["output_dir"] = self._default_output(args.output_dir, "beamformer_output")
        params: MNEBeamformerParameters = mne_beamformer_from_payload(payload)
        result = run_mne_beamformer(params)
        return ToolResult(status="success", data=result)


class MNEDipoleFittingTool(_BaseSourceTool):
    """Wrapper for dipole fitting."""

    def get_tool_name(self) -> str:
        return "mne_dipole"

    def get_tool_description(self) -> str:
        return "Run simple dipole fitting via neurocore helpers."

    def get_args_schema(self):  # noqa: D401
        return MNEDipoleArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        if not self.mne_available:
            return ToolResult(status="error", error=self.mne_error or "MNE not available", data={})
        args = MNEDipoleArgs(**kwargs)
        payload: Dict[str, Any] = args.model_dump()
        payload["output_dir"] = self._default_output(args.output_dir, "dipole_output")
        params: MNEDipoleParameters = mne_dipole_from_payload(payload)
        result = run_mne_dipole(params)
        return ToolResult(status="success", data=result)


class MNESourceTools:
    """Collection of source localization tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [
            MNESourceLocalizationTool(),
            MNEBeamformerTool(),
            MNEDipoleFittingTool(),
        ]


__all__ = [
    "MNESourceLocalizationTool",
    "MNEBeamformerTool",
    "MNEDipoleFittingTool",
    "MNESourceTools",
]
