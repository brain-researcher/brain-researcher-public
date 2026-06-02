"""
MNE-Python ICA Artifact Removal implementation for Brain Researcher.

Implements MNE's Independent Component Analysis (ICA) for artifact removal
from EEG/MEG data, including automatic detection of eye blinks, muscle artifacts,
and cardiac components.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.params import (
    MNEICAParameters,
    mne_ica_from_payload,
    run_mne_ica,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

configure_mne_environment()

logger = logging.getLogger(__name__)


class ICAMethod(str):
    """ICA algorithm options."""

    FASTICA = "fastica"
    INFOMAX = "infomax"
    PICARD = "picard"
    EXTENDED_INFOMAX = "extended-infomax"


class ArtifactType(str):
    """Artifact types for automatic detection."""

    EOG = "eog"  # Eye blinks/movements
    ECG = "ecg"  # Cardiac artifacts
    MUSCLE = "muscle"  # Muscle artifacts
    REF = "ref"  # Reference channel artifacts


class MNEICAArgs(BaseModel):
    """Arguments for MNE ICA artifact removal."""

    raw_file: str = Field(
        description="Path to preprocessed raw data file (.fif format)"
    )
    output_dir: str = Field(description="Output directory for ICA results")

    # ICA parameters
    n_components: Optional[Union[int, float]] = Field(
        default=None,
        description="Number of components (int) or variance to explain (0-1 float). None=use all",
    )
    method: str = Field(
        default="fastica",
        description="ICA algorithm: fastica, infomax, picard, extended-infomax",
    )
    max_iter: Union[int, str] = Field(
        default="auto", description="Maximum iterations for ICA convergence"
    )
    random_state: Optional[int] = Field(
        default=42, description="Random seed for reproducibility"
    )

    # Filtering for ICA
    l_freq: Optional[float] = Field(
        default=1.0, description="High-pass filter before ICA (Hz). Recommended: 1.0"
    )
    h_freq: Optional[float] = Field(
        default=None,
        description="Low-pass filter before ICA (Hz). None for no low-pass",
    )

    # Artifact detection
    detect_artifacts: List[str] = Field(
        default=["eog", "ecg"],
        description="Artifact types to automatically detect: eog, ecg, muscle, ref",
    )
    eog_channels: Optional[List[str]] = Field(
        default=None,
        description="EOG channel names for correlation (auto-detect if None)",
    )
    ecg_channels: Optional[List[str]] = Field(
        default=None,
        description="ECG channel names for correlation (auto-detect if None)",
    )

    # Thresholds for automatic detection
    eog_threshold: float = Field(
        default=3.0, description="Z-score threshold for EOG artifact detection"
    )
    ecg_threshold: float = Field(
        default=3.0, description="Z-score threshold for ECG artifact detection"
    )
    muscle_threshold: float = Field(
        default=5.0, description="Z-score threshold for muscle artifact detection"
    )

    # Component selection
    exclude_components: Optional[List[int]] = Field(
        default=None, description="Manually specify component indices to exclude"
    )
    n_max_eog: int = Field(
        default=2, description="Maximum number of EOG components to remove"
    )
    n_max_ecg: int = Field(
        default=2, description="Maximum number of ECG components to remove"
    )

    # Visualization and reporting
    plot_components: bool = Field(default=True, description="Generate component plots")
    plot_sources: bool = Field(default=True, description="Plot ICA sources")
    plot_overlay: bool = Field(
        default=True, description="Plot before/after overlay comparison"
    )
    n_pca_components: Optional[int] = Field(
        default=None,
        description="Number of PCA components for dimension reduction before ICA",
    )

    # Advanced options
    fit_params: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional parameters for the ICA algorithm"
    )
    reject: Optional[Dict[str, float]] = Field(
        default=None, description="Rejection parameters for bad segments during fitting"
    )
    picks: Optional[List[str]] = Field(
        default=None, description="Channel types or names to include in ICA"
    )

    # Output options
    save_ica: bool = Field(default=True, description="Save ICA solution for later use")
    apply_ica: bool = Field(
        default=True, description="Apply ICA to remove artifacts from data"
    )
    overwrite: bool = Field(
        default=False, description="Overwrite existing output files"
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _MNE_ICA_SCHEMA = MNEICAArgs.model_json_schema()
except AttributeError:
    _MNE_ICA_SCHEMA = MNEICAArgs.schema()


TOOL_SPEC = ToolSpec(
    name="mne_ica",
    description="Run ICA artifact removal via MNE-Python shared core.",
    json_schema=_MNE_ICA_SCHEMA,
    required=_model_required(MNEICAArgs),
    defaults=_model_defaults(MNEICAArgs),
    category="mne",
)


class MNEICATool(NeuroToolWrapper):
    TOOL_SPEC = TOOL_SPEC
    """MNE-Python ICA artifact removal tool."""

    def __init__(self):
        """Initialize MNE ICA tool."""
        super().__init__()
        self._check_mne()

    def _check_mne(self):
        """Check MNE-Python availability."""
        try:
            import mne

            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(f"MNE-Python {self.mne_version} available")
        except ImportError:
            self.mne_available = False
            logger.warning("MNE-Python not installed")

    def get_tool_name(self) -> str:
        return "mne_ica"

    def get_tool_description(self) -> str:
        return (
            "MNE-Python ICA (Independent Component Analysis) for artifact removal "
            "from EEG/MEG data. Automatically detects and removes eye blinks, "
            "cardiac artifacts, muscle artifacts, and other noise sources. "
            "Supports multiple ICA algorithms and provides visualization of components."
        )

    def get_args_schema(self):
        return MNEICAArgs

    def _detect_eog_components(
        self, ica, raw, eog_channels=None, threshold=3.0, n_max=2
    ):
        """Detect EOG artifact components."""
        import mne

        # Find or create EOG channels
        if eog_channels is None:
            eog_inds = mne.pick_types(raw.info, eog=True, exclude=[])
            if len(eog_inds) == 0:
                # Try to find channels with EOG in the name
                eog_channels = [ch for ch in raw.ch_names if "EOG" in ch.upper()]

        if not eog_channels and len(eog_inds) == 0:
            logger.warning("No EOG channels found")
            return []

        # Use automatic detection
        eog_indices, scores = ica.find_bads_eog(
            raw, ch_name=eog_channels[0] if eog_channels else None, threshold=threshold
        )

        # Limit to n_max components
        if len(eog_indices) > n_max:
            # Sort by score and take top n_max
            sorted_indices = sorted(
                zip(eog_indices, scores[eog_indices]),
                key=lambda x: abs(x[1]),
                reverse=True,
            )
            eog_indices = [idx for idx, _ in sorted_indices[:n_max]]

        return eog_indices

    def _detect_ecg_components(
        self, ica, raw, ecg_channels=None, threshold=3.0, n_max=2
    ):
        """Detect ECG artifact components."""
        import mne

        # Find or create ECG channels
        if ecg_channels is None:
            ecg_inds = mne.pick_types(raw.info, ecg=True, exclude=[])
            if len(ecg_inds) == 0:
                # Try to find channels with ECG in the name
                ecg_channels = [ch for ch in raw.ch_names if "ECG" in ch.upper()]

        try:
            # Use automatic detection
            ecg_indices, scores = ica.find_bads_ecg(
                raw,
                ch_name=ecg_channels[0] if ecg_channels else None,
                threshold=threshold,
                method="correlation",
            )
        except Exception as e:
            logger.warning(f"Could not detect ECG components: {e}")
            return []

        # Limit to n_max components
        if len(ecg_indices) > n_max:
            sorted_indices = sorted(
                zip(ecg_indices, scores[ecg_indices]),
                key=lambda x: abs(x[1]),
                reverse=True,
            )
            ecg_indices = [idx for idx, _ in sorted_indices[:n_max]]

        return ecg_indices

    def _detect_muscle_components(self, ica, raw, threshold=5.0):
        """Detect muscle artifact components using frequency characteristics."""
        import mne

        muscle_indices = []

        # Get ICA sources
        sources = ica.get_sources(raw)
        data = sources.get_data()

        # Calculate power spectral density for each component
        for idx in range(ica.n_components_):
            # Simple high-frequency power check
            component_data = data[idx, :]

            # Calculate power in high frequency band (>30 Hz)
            from scipy import signal

            freqs, psd = signal.welch(component_data, raw.info["sfreq"], nperseg=1024)

            # Get power in muscle frequency range (30-100 Hz)
            muscle_freq_mask = (freqs >= 30) & (freqs <= 100)
            muscle_power = np.mean(psd[muscle_freq_mask])

            # Get power in lower frequencies (1-30 Hz)
            low_freq_mask = (freqs >= 1) & (freqs <= 30)
            low_power = np.mean(psd[low_freq_mask])

            # High ratio indicates muscle artifact
            if low_power > 0:
                power_ratio = muscle_power / low_power
                if power_ratio > threshold:
                    muscle_indices.append(idx)

        return muscle_indices

    def _generate_plots(self, ica, raw, exclude_indices, output_dir):
        """Generate ICA component plots."""
        import matplotlib
        import mne

        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt

        plot_files = {}

        try:
            # Plot ICA components
            if ica.n_components_ > 0:
                fig = ica.plot_components(picks=range(min(20, ica.n_components_)))
                if isinstance(fig, list):
                    for i, f in enumerate(fig):
                        comp_file = output_dir / f"ica_components_{i}.png"
                        f.savefig(comp_file)
                        plt.close(f)
                    plot_files["components"] = str(output_dir / "ica_components_0.png")
                else:
                    comp_file = output_dir / "ica_components.png"
                    fig.savefig(comp_file)
                    plt.close(fig)
                    plot_files["components"] = str(comp_file)

            # Plot ICA sources
            fig = ica.plot_sources(raw, show=False)
            sources_file = output_dir / "ica_sources.png"
            fig.savefig(sources_file)
            plt.close(fig)
            plot_files["sources"] = str(sources_file)

            # Plot properties of excluded components
            for idx in exclude_indices[:5]:  # Limit to first 5
                try:
                    fig = ica.plot_properties(raw, picks=[idx], show=False)
                    prop_file = output_dir / f"ica_properties_comp{idx}.png"
                    if isinstance(fig, list):
                        fig[0].savefig(prop_file)
                        plt.close(fig[0])
                    else:
                        fig.savefig(prop_file)
                        plt.close(fig)
                except:
                    pass

            # Plot overlay (before/after)
            if exclude_indices:
                fig = ica.plot_overlay(raw, exclude=exclude_indices, show=False)
                overlay_file = output_dir / "ica_overlay.png"
                fig.savefig(overlay_file)
                plt.close(fig)
                plot_files["overlay"] = str(overlay_file)

        except Exception as e:
            logger.warning(f"Could not generate all plots: {e}")

        return plot_files

    def _run(
        self,
        raw_file: str,
        output_dir: str,
        n_components: Optional[Union[int, float]] = None,
        method: str = "fastica",
        max_iter: Union[int, str] = "auto",
        random_state: Optional[int] = 42,
        l_freq: Optional[float] = 1.0,
        h_freq: Optional[float] = None,
        detect_artifacts: List[str] = ["eog", "ecg"],
        eog_channels: Optional[List[str]] = None,
        ecg_channels: Optional[List[str]] = None,
        eog_threshold: float = 3.0,
        ecg_threshold: float = 3.0,
        muscle_threshold: float = 5.0,
        exclude_components: Optional[List[int]] = None,
        n_max_eog: int = 2,
        n_max_ecg: int = 2,
        plot_components: bool = True,
        plot_sources: bool = True,
        plot_overlay: bool = True,
        n_pca_components: Optional[int] = None,
        fit_params: Optional[Dict[str, Any]] = None,
        reject: Optional[Dict[str, float]] = None,
        picks: Optional[List[str]] = None,
        save_ica: bool = True,
        apply_ica: bool = True,
        overwrite: bool = False,
        **kwargs,
    ) -> ToolResult:
        """Execute MNE ICA artifact removal."""
        try:
            if not self.mne_available:
                return ToolResult(
                    status="error", error="MNE-Python not available", data={}
                )

            payload = {
                "raw_file": raw_file,
                "output_dir": output_dir,
                "n_components": n_components,
                "method": method,
                "max_iter": max_iter,
                "random_state": random_state,
                "l_freq": l_freq,
                "h_freq": h_freq,
                "detect_artifacts": detect_artifacts,
                "eog_channels": eog_channels,
                "ecg_channels": ecg_channels,
                "eog_threshold": eog_threshold,
                "ecg_threshold": ecg_threshold,
                "muscle_threshold": muscle_threshold,
                "exclude_components": exclude_components or [],
                "n_max_eog": n_max_eog,
                "n_max_ecg": n_max_ecg,
                "plot_components": plot_components,
                "plot_sources": plot_sources,
                "plot_overlay": plot_overlay,
                "n_pca_components": n_pca_components,
                "fit_params": fit_params,
                "reject": reject,
                "picks": picks or [],
                "save_ica": save_ica,
                "apply_ica": apply_ica,
                "overwrite": overwrite,
            }

            params = mne_ica_from_payload(payload)
            results = run_mne_ica(params)

            return ToolResult(
                status="success",
                data={
                    **results,
                    "message": "ICA artifact removal completed successfully",
                },
            )

        except Exception as e:
            logger.error(f"ICA processing failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})

    def apply_saved_ica(
        self,
        raw_file: str,
        ica_file: str,
        output_file: str,
        exclude_additional: Optional[List[int]] = None,
    ) -> ToolResult:
        """Apply a previously saved ICA solution to new data."""
        try:
            if not self.mne_available:
                return ToolResult(
                    status="error", error="MNE-Python not available", data={}
                )

            import mne
            from mne.preprocessing import read_ica

            # Load data and ICA
            raw = mne.io.read_raw_fif(raw_file, preload=True)
            ica = read_ica(ica_file)

            # Add additional components to exclude if specified
            if exclude_additional:
                ica.exclude.extend(exclude_additional)
                ica.exclude = list(set(ica.exclude))

            # Apply ICA
            logger.info(
                f"Applying saved ICA with {len(ica.exclude)} excluded components"
            )
            ica.apply(raw)

            # Save cleaned data
            raw.save(output_file, overwrite=True)

            return ToolResult(
                status="success",
                data={
                    "output": output_file,
                    "excluded_components": ica.exclude,
                    "message": f"Applied saved ICA solution, removed {len(ica.exclude)} components",
                },
            )

        except Exception as e:
            return ToolResult(status="error", error=str(e), data={})


class MNEICATools:
    """Collection of MNE ICA tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all MNE ICA tools."""
        return [MNEICATool()]
