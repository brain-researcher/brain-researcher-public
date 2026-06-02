"""
MNE Autoreject implementation for Brain Researcher.

Automated rejection and repair of bad epochs/channels using cross-validation
to find optimal thresholds.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.params import (
    MNEAutorejectParameters,
    mne_autoreject_from_payload,
    run_mne_autoreject,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)

configure_mne_environment()


class AutorejectArgs(BaseModel):
    """Arguments for Autoreject analysis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input data
    epochs_file: str = Field(description="Path to epochs file (.fif format)")

    # Autoreject parameters
    n_interpolate: Optional[List[int]] = Field(
        default=None, description="Number of channels to interpolate (auto if None)"
    )
    consensus: Optional[List[float]] = Field(
        default=None, description="Consensus parameter values to try (auto if None)"
    )
    cv: int = Field(default=5, description="Number of cross-validation folds")
    thresh_method: str = Field(
        default="bayesian_optimization",
        description="Threshold selection method: 'bayesian_optimization' or 'random_search'",
    )
    n_jobs: int = Field(default=1, description="Number of parallel jobs")
    random_state: Optional[int] = Field(
        default=42, description="Random seed for reproducibility"
    )

    # Repair options
    mode: str = Field(
        default="repair",
        description="Mode: 'repair' (interpolate bad channels) or 'reject' (drop bad epochs)",
    )
    picks: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Channel selection: 'eeg', 'meg', or list of channel names",
    )

    # Local rejection
    use_local: bool = Field(
        default=True, description="Use local (channel-specific) rejection"
    )
    use_global: bool = Field(default=True, description="Use global rejection")

    # Output options
    output_dir: str = Field(description="Output directory for results")
    save_epochs: bool = Field(default=True, description="Save cleaned epochs")
    save_report: bool = Field(
        default=True, description="Generate and save rejection report"
    )
    save_plots: bool = Field(
        default=True, description="Generate and save diagnostic plots"
    )

    # Advanced options
    verbose: bool = Field(default=True, description="Verbose output")


class MNEAutorejectTool(NeuroToolWrapper):
    """MNE Autoreject automated QC tool."""

    def __init__(self):
        """Initialize MNE Autoreject tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.mne_available = False
        self.autoreject_available = False

        try:
            import mne

            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(f"MNE-Python {self.mne_version} available")
        except ImportError:
            logger.warning("MNE-Python not installed")

        try:
            import autoreject

            self.autoreject_available = True
            logger.info("Autoreject available")
        except ImportError:
            logger.warning("Autoreject not installed - using fallback implementation")

    def get_tool_name(self) -> str:
        return "mne_autoreject"

    def get_tool_description(self) -> str:
        return (
            "Autoreject automated quality control for EEG/MEG epochs. Uses "
            "cross-validation to find optimal rejection thresholds for each "
            "channel and epoch. Supports both local (channel-specific) and "
            "global rejection, automatic bad channel interpolation, and "
            "consensus-based repair strategies. Reduces manual QC time while "
            "maintaining data quality."
        )

    def get_args_schema(self):
        return AutorejectArgs

    def _run(
        self,
        epochs_file: str,
        n_interpolate: Optional[List[int]] = None,
        consensus: Optional[List[float]] = None,
        cv: int = 5,
        thresh_method: str = "bayesian_optimization",
        n_jobs: int = 1,
        random_state: Optional[int] = 42,
        mode: str = "repair",
        picks: Optional[Union[str, List[str]]] = None,
        use_local: bool = True,
        use_global: bool = True,
        output_dir: str = None,
        save_epochs: bool = True,
        save_report: bool = True,
        save_plots: bool = True,
        verbose: bool = True,
        **kwargs,
    ) -> ToolResult:
        """Execute Autoreject analysis."""
        try:
            if not self.mne_available:
                return ToolResult(
                    status="error", error="MNE-Python not available", data={}
                )
            if output_dir is None:
                output_dir = str(Path(epochs_file).parent / "autoreject")

            payload: Dict[str, Any] = {
                "epochs_file": epochs_file,
                "output_dir": output_dir,
                "n_interpolate": n_interpolate,
                "consensus": consensus,
                "cv": cv,
                "thresh_method": thresh_method,
                "n_jobs": n_jobs,
                "random_state": random_state,
                "mode": mode,
                "picks": picks,
                "use_local": use_local,
                "use_global": use_global,
                "save_epochs": save_epochs,
                "save_report": save_report,
                "save_plots": save_plots,
                "verbose": verbose,
            }

            params: MNEAutorejectParameters = mne_autoreject_from_payload(payload)
            results = run_mne_autoreject(params)
            used_autoreject = results.pop("used_autoreject_package", None)

            if verbose and used_autoreject is False:
                logger.info(
                    "Autoreject package not available; fallback routine executed."
                )

            return ToolResult(status="success", data=results)

        except Exception as e:
            logger.error(f"Autoreject analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class MNEAutorejectTools:
    """Collection of MNE Autoreject tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all MNE Autoreject tools."""
        return [MNEAutorejectTool()]
