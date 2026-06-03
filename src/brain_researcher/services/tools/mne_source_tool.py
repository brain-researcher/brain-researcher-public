"""Agent wrappers for MNE source localization workflows backed by neurocore."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.params import (
    MNEBeamformerParameters,
    MNEDipoleParameters,
    MNESourceInverseParameters,
    mne_beamformer_from_payload,
    mne_dipole_from_payload,
    mne_source_inverse_from_payload,
    run_mne_beamformer,
    run_mne_dipole,
    run_mne_source_inverse,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

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
    def _default_output(output_dir: str | None, fallback_name: str) -> str:
        if output_dir:
            return output_dir
        return str(Path.cwd() / fallback_name)


class MNESourceLocalizationArgs(BaseModel):
    raw_file: str | None = None
    epochs_file: str | None = None
    evoked_file: str | None = None
    subjects_dir: str
    subject: str
    forward_file: str | None = None
    bem_file: str | None = None
    trans_file: str | None = None
    spacing: str | None = "oct6"
    surface: str = "white"
    method: str = "dSPM"
    lambda2: float | None = None
    pick_ori: str | None = "normal"
    depth: float | None = 0.8
    noise_cov_file: str | None = None
    baseline: tuple[float | None, float | None] | None = (None, 0.0)
    output_dir: str
    save_stc: bool = True
    save_inverse: bool = True
    morphing: str | None = None


class MNEBeamformerArgs(BaseModel):
    raw_file: str | None = None
    epochs_file: str | None = None
    evoked_file: str | None = None
    subjects_dir: str
    subject: str
    forward_file: str | None = None
    trans_file: str | None = None
    data_cov_file: str | None = None
    noise_cov_file: str | None = None
    method: str = "lcmv"
    reg: float = 0.05
    weight_norm: str | None = "unit-noise-gain"
    freq_bands: list[tuple[float, float]] | None = None
    output_dir: str
    save_filters: bool = True
    save_stc: bool = True


class MNEDipoleArgs(BaseModel):
    evoked_file: str
    subjects_dir: str
    subject: str
    trans_file: str | None = None
    bem_file: str | None = None
    output_dir: str
    tmin: float | None = None
    tmax: float | None = None
    n_dipoles: int = 1
    min_dist: float = 5.0
    save_dipoles: bool = True


class MNESourceLocalizationTool(_BaseSourceTool):
    """Wrapper for inverse solutions."""

    def get_tool_name(self) -> str:
        return "mne_source_localization"

    def get_tool_description(self) -> str:
        return (
            "Run MNE inverse solution (MNE/dSPM/sLORETA) using shared neurocore logic."
        )

    def get_args_schema(self):  # noqa: D401
        return MNESourceLocalizationArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        if not self.mne_available:
            return ToolResult(
                status="error", error=self.mne_error or "MNE not available", data={}
            )
        args = MNESourceLocalizationArgs(**kwargs)
        payload: dict[str, Any] = args.model_dump()
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
            return ToolResult(
                status="error", error=self.mne_error or "MNE not available", data={}
            )
        args = MNEBeamformerArgs(**kwargs)
        payload: dict[str, Any] = args.model_dump()
        payload["output_dir"] = self._default_output(
            args.output_dir, "beamformer_output"
        )
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
            return ToolResult(
                status="error", error=self.mne_error or "MNE not available", data={}
            )
        args = MNEDipoleArgs(**kwargs)
        payload: dict[str, Any] = args.model_dump()
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
