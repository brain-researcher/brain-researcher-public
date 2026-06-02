"""
MNE-Python Time-Frequency Analysis implementation for Brain Researcher.

Implements time-frequency decomposition, spectral analysis, and connectivity
measures for EEG/MEG data using MNE-Python.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.params import (
    MNETimeFreqParameters,
    mne_timefreq_from_payload,
    run_mne_timefreq,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)

configure_mne_environment()


class TFRMethod(str):
    """Time-frequency analysis methods."""

    MORLET = "morlet"
    MULTITAPER = "multitaper"
    STOCKWELL = "stockwell"
    HILBERT = "hilbert"
    FILTER_BANK = "filter_bank"


class ConnectivityMethod(str):
    """Connectivity analysis methods."""

    COHERENCE = "coherence"
    COHERENCY = "coherency"
    PLV = "plv"  # Phase Locking Value
    PLI = "pli"  # Phase Lag Index
    WPLI = "wpli"  # Weighted Phase Lag Index
    SPECTRAL_CONNECTIVITY = "spectral_connectivity"
    ENVELOPE_CORRELATION = "envelope_correlation"


class BaselineMode(str):
    """Baseline correction modes."""

    MEAN = "mean"
    RATIO = "ratio"
    LOGRATIO = "logratio"
    PERCENT = "percent"
    ZSCORE = "zscore"
    ZLOGRATIO = "zlogratio"


class MNETimeFreqArgs(BaseModel):
    """Arguments for MNE time-frequency analysis."""

    # Input data
    epochs_file: str = Field(description="Path to epoched data file (.fif format)")
    output_dir: str = Field(description="Output directory for results")

    # Time-frequency parameters
    method: str = Field(
        default="morlet",
        description="TFR method: morlet, multitaper, stockwell, hilbert, filter_bank",
    )
    freqs: Optional[List[float]] = Field(
        default=None,
        description="Frequencies of interest (Hz). If None, uses log-spaced 1-40 Hz",
    )
    freq_min: Optional[float] = Field(
        default=1.0, description="Minimum frequency for automatic frequency selection"
    )
    freq_max: Optional[float] = Field(
        default=40.0, description="Maximum frequency for automatic frequency selection"
    )
    n_freqs: Optional[int] = Field(
        default=30, description="Number of frequencies for automatic selection"
    )

    # Morlet wavelet parameters
    n_cycles: Optional[Union[float, List[float]]] = Field(
        default=7.0,
        description="Number of cycles in Morlet wavelet. Can vary with frequency",
    )
    use_fft: bool = Field(default=True, description="Use FFT for convolution (faster)")

    # Multitaper parameters
    time_bandwidth: float = Field(
        default=4.0, description="Time-bandwidth product for multitaper"
    )
    n_tapers: Optional[int] = Field(
        default=None, description="Number of tapers (auto-computed if None)"
    )

    # Output type
    output: str = Field(
        default="power",
        description="Output type: power, phase, complex, itc (inter-trial coherence)",
    )
    average: bool = Field(default=True, description="Average over epochs")
    return_itc: bool = Field(
        default=True, description="Also compute inter-trial coherence"
    )

    # Baseline correction
    baseline: Optional[Tuple[float, float]] = Field(
        default=(None, 0), description="Baseline interval for correction (tmin, tmax)"
    )
    baseline_mode: str = Field(
        default="mean",
        description="Baseline mode: mean, ratio, logratio, percent, zscore, zlogratio",
    )

    # Power spectral density
    compute_psd: bool = Field(
        default=True, description="Compute power spectral density"
    )
    psd_method: str = Field(
        default="welch", description="PSD method: welch, multitaper, or periodogram"
    )

    # Connectivity analysis
    compute_connectivity: bool = Field(
        default=False, description="Compute connectivity measures"
    )
    connectivity_method: str = Field(
        default="coherence",
        description="Connectivity method: coherence, plv, pli, wpli, etc.",
    )
    connectivity_pairs: Optional[List[Tuple[str, str]]] = Field(
        default=None, description="Channel pairs for connectivity (None = all pairs)"
    )

    # Band power
    compute_band_power: bool = Field(
        default=True, description="Compute band power in standard bands"
    )
    bands: Optional[Dict[str, Tuple[float, float]]] = Field(
        default=None,
        description="Frequency bands (default: delta, theta, alpha, beta, gamma)",
    )

    # Visualization
    plot_tfr: bool = Field(default=True, description="Generate TFR plots")
    plot_topomap: bool = Field(default=True, description="Generate topographic maps")
    plot_joint: bool = Field(
        default=False, description="Generate joint plot (TFR + topomap)"
    )

    # Channel selection
    picks: Optional[List[str]] = Field(
        default=None, description="Channels to analyze (None = all channels)"
    )
    combine_channels: bool = Field(
        default=False, description="Combine channels by averaging"
    )

    # Statistical analysis
    compute_statistics: bool = Field(
        default=False, description="Compute statistical tests on TFR"
    )
    stat_threshold: float = Field(
        default=0.05, description="Statistical significance threshold"
    )

    # Export options
    save_format: str = Field(
        default="hdf5", description="Save format: hdf5, mat, or npz"
    )
    save_plots: bool = Field(default=True, description="Save generated plots")


class MNETimeFreqTool(NeuroToolWrapper):
    """MNE-Python time-frequency analysis tool."""

    def __init__(self):
        """Initialize MNE time-frequency tool."""
        super().__init__()
        self._check_mne()

    def _check_mne(self):
        """Check MNE-Python availability."""
        try:
            import mne
            from mne.time_frequency import tfr_morlet, tfr_multitaper

            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(
                f"MNE-Python {self.mne_version} available for time-frequency analysis"
            )
        except ImportError:
            self.mne_available = False
            logger.warning("MNE-Python not installed for time-frequency analysis")

    def get_tool_name(self) -> str:
        return "mne_timefreq"

    def get_tool_description(self) -> str:
        return (
            "MNE-Python time-frequency analysis for EEG/MEG data. Includes "
            "wavelet transforms (Morlet), multitaper spectral analysis, "
            "power spectral density, inter-trial coherence, and connectivity "
            "measures. Supports baseline correction and statistical analysis."
        )

    def get_args_schema(self):
        return MNETimeFreqArgs

    def _get_default_bands(self):
        """Get default frequency bands."""
        return {
            "delta": (0.5, 4),
            "theta": (4, 8),
            "alpha": (8, 13),
            "beta": (13, 30),
            "gamma": (30, 100),
        }

    def _compute_tfr(self, epochs, method, freqs, **kwargs):
        """Compute time-frequency representation."""
        import mne
        from mne.time_frequency import (
            tfr_array_morlet,
            tfr_array_multitaper,
            tfr_morlet,
            tfr_multitaper,
            tfr_stockwell,
        )

        if method == "morlet":
            n_cycles = kwargs.get("n_cycles", 7.0)
            use_fft = kwargs.get("use_fft", True)
            output = kwargs.get("output", "power")
            average = kwargs.get("average", True)
            return_itc = kwargs.get("return_itc", True)

            power, itc = tfr_morlet(
                epochs,
                freqs=freqs,
                n_cycles=n_cycles,
                use_fft=use_fft,
                output=output,
                average=average,
                return_itc=return_itc,
            )
            return power, itc

        elif method == "multitaper":
            time_bandwidth = kwargs.get("time_bandwidth", 4.0)
            n_tapers = kwargs.get("n_tapers", None)
            output = kwargs.get("output", "power")
            average = kwargs.get("average", True)
            return_itc = kwargs.get("return_itc", True)

            if n_tapers is None:
                n_tapers = int(2 * time_bandwidth - 1)

            power, itc = tfr_multitaper(
                epochs,
                freqs=freqs,
                n_cycles=time_bandwidth,
                time_bandwidth=time_bandwidth,
                n_tapers=n_tapers,
                use_fft=True,
                output=output,
                average=average,
                return_itc=return_itc,
            )
            return power, itc

        elif method == "stockwell":
            power = tfr_stockwell(epochs, fmin=freqs[0], fmax=freqs[-1])
            return power, None

        else:
            raise ValueError(f"Unknown TFR method: {method}")

    def _compute_psd(self, epochs, method="welch", **kwargs):
        """Compute power spectral density."""
        import mne

        if method == "welch":
            psd = epochs.compute_psd(method="welch", fmin=0.5, fmax=100)
        elif method == "multitaper":
            psd = epochs.compute_psd(method="multitaper", fmin=0.5, fmax=100)
        elif method == "periodogram":
            from mne.time_frequency import psd_array_periodogram

            data = epochs.get_data()
            freqs, psd_data = psd_array_periodogram(
                data, epochs.info["sfreq"], fmin=0.5, fmax=100
            )
            # Create PSD object
            from mne.time_frequency import EpochsSpectrum

            psd = EpochsSpectrum(
                epochs.info, psd_data, freqs, "epochs", method="periodogram"
            )
        else:
            raise ValueError(f"Unknown PSD method: {method}")

        return psd

    def _compute_band_power(self, epochs, bands=None):
        """Compute power in frequency bands."""
        if bands is None:
            bands = self._get_default_bands()

        band_powers = {}

        # Compute PSD
        psd = epochs.compute_psd(method="welch")

        # Extract band power for each band
        for band_name, (fmin, fmax) in bands.items():
            band_power = psd.get_data(fmin=fmin, fmax=fmax).mean(axis=-1)
            band_powers[band_name] = {
                "mean": float(np.mean(band_power)),
                "std": float(np.std(band_power)),
                "median": float(np.median(band_power)),
                "by_channel": band_power.mean(axis=0).tolist(),
            }

        return band_powers

    def _compute_connectivity(self, epochs, method="coherence", pairs=None, freqs=None):
        """Compute connectivity measures."""
        try:
            from mne_connectivity import spectral_connectivity_epochs
        except ImportError:
            logger.warning(
                "mne-connectivity not installed, skipping connectivity analysis"
            )
            return None

        if freqs is None:
            freqs = np.logspace(np.log10(1), np.log10(40), 30)

        # Map method names
        method_map = {
            "coherence": "coh",
            "coherency": "cohy",
            "plv": "plv",
            "pli": "pli",
            "wpli": "wpli",
            "spectral_connectivity": "coh",
        }

        mne_method = method_map.get(method, "coh")

        # Compute connectivity
        con = spectral_connectivity_epochs(
            epochs,
            method=mne_method,
            fmin=freqs[0],
            fmax=freqs[-1],
            faverage=True,
            verbose=False,
        )

        return con

    def _generate_plots(self, tfr_power, itc, epochs, output_dir, **kwargs):
        """Generate time-frequency plots."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plot_files = {}

        try:
            # TFR plot for selected channels
            if kwargs.get("plot_tfr", True) and tfr_power is not None:
                # Average over channels or plot first channel
                fig = tfr_power.plot(
                    picks=[0],
                    baseline=kwargs.get("baseline"),
                    mode=kwargs.get("baseline_mode", "mean"),
                    title="Time-Frequency Power",
                    show=False,
                )
                tfr_file = output_dir / "tfr_power.png"
                (
                    fig[0].savefig(tfr_file)
                    if isinstance(fig, list)
                    else fig.savefig(tfr_file)
                )
                plt.close("all")
                plot_files["tfr_power"] = str(tfr_file)

            # ITC plot
            if itc is not None and kwargs.get("return_itc", True):
                fig = itc.plot(
                    picks=[0],
                    baseline=kwargs.get("baseline"),
                    mode=kwargs.get("baseline_mode", "mean"),
                    title="Inter-Trial Coherence",
                    show=False,
                )
                itc_file = output_dir / "itc.png"
                (
                    fig[0].savefig(itc_file)
                    if isinstance(fig, list)
                    else fig.savefig(itc_file)
                )
                plt.close("all")
                plot_files["itc"] = str(itc_file)

            # Topographic maps at specific times/frequencies
            if kwargs.get("plot_topomap", True) and tfr_power is not None:
                # Plot topomap at alpha band peak
                alpha_freqs = (8, 13)
                times = [0.2, 0.4, 0.6]  # Example time points

                fig = tfr_power.plot_topomap(
                    tmin=times[0],
                    tmax=times[-1],
                    fmin=alpha_freqs[0],
                    fmax=alpha_freqs[1],
                    baseline=kwargs.get("baseline"),
                    mode=kwargs.get("baseline_mode", "mean"),
                    title="Alpha Power Topography",
                    show=False,
                )
                topo_file = output_dir / "topomap_alpha.png"
                fig.savefig(topo_file)
                plt.close()
                plot_files["topomap_alpha"] = str(topo_file)

            # Joint plot
            if kwargs.get("plot_joint", False) and tfr_power is not None:
                fig = tfr_power.plot_joint(
                    baseline=kwargs.get("baseline"),
                    mode=kwargs.get("baseline_mode", "mean"),
                    show=False,
                )
                joint_file = output_dir / "joint_plot.png"
                fig.savefig(joint_file)
                plt.close()
                plot_files["joint_plot"] = str(joint_file)

            # PSD plot
            if kwargs.get("compute_psd", True):
                psd = self._compute_psd(
                    epochs, method=kwargs.get("psd_method", "welch")
                )
                fig = psd.plot(average=True, show=False)
                psd_file = output_dir / "psd.png"
                fig.savefig(psd_file)
                plt.close()
                plot_files["psd"] = str(psd_file)

        except Exception as e:
            logger.warning(f"Could not generate all plots: {e}")

        return plot_files

    def _run(
        self,
        epochs_file: str,
        output_dir: str,
        method: str = "morlet",
        freqs: Optional[List[float]] = None,
        freq_min: Optional[float] = 1.0,
        freq_max: Optional[float] = 40.0,
        n_freqs: Optional[int] = 30,
        n_cycles: Optional[Union[float, List[float]]] = 7.0,
        use_fft: bool = True,
        time_bandwidth: float = 4.0,
        n_tapers: Optional[int] = None,
        output: str = "power",
        average: bool = True,
        return_itc: bool = True,
        baseline: Optional[Tuple[float, float]] = (None, 0),
        baseline_mode: str = "mean",
        compute_psd: bool = True,
        psd_method: str = "welch",
        compute_connectivity: bool = False,
        connectivity_method: str = "coherence",
        connectivity_pairs: Optional[List[Tuple[str, str]]] = None,
        compute_band_power: bool = True,
        bands: Optional[Dict[str, Tuple[float, float]]] = None,
        plot_tfr: bool = True,
        plot_topomap: bool = True,
        plot_joint: bool = False,
        picks: Optional[List[str]] = None,
        combine_channels: bool = False,
        compute_statistics: bool = False,
        stat_threshold: float = 0.05,
        save_format: str = "hdf5",
        save_plots: bool = True,
        **kwargs,
    ) -> ToolResult:
        """Execute MNE time-frequency analysis."""
        try:
            if not self.mne_available:
                return ToolResult(
                    status="error", error="MNE-Python not available", data={}
                )

            if output_dir is None:
                output_dir = str(Path(epochs_file).parent / "timefreq")

            payload: Dict[str, Any] = {
                "epochs_file": epochs_file,
                "output_dir": output_dir,
                "method": method,
                "freqs": freqs,
                "freq_min": freq_min,
                "freq_max": freq_max,
                "n_freqs": n_freqs,
                "n_cycles": n_cycles,
                "use_fft": use_fft,
                "average": average,
                "return_itc": return_itc,
                "baseline": baseline,
                "baseline_mode": baseline_mode,
                "compute_psd": compute_psd,
                "psd_method": psd_method,
                "save_plots": save_plots,
                "picks": picks,
                "time_bandwidth": time_bandwidth,
                "n_tapers": n_tapers,
                "save_format": save_format,
                "compute_connectivity": compute_connectivity,
                "connectivity_method": connectivity_method,
                "connectivity_pairs": connectivity_pairs,
                "compute_band_power": compute_band_power,
                "bands": bands,
                "compute_statistics": compute_statistics,
                "stat_threshold": stat_threshold,
            }

            params: MNETimeFreqParameters = mne_timefreq_from_payload(payload)
            results = run_mne_timefreq(params)
            used_package = results.pop("used_mne_timefreq_package", None)

            if used_package is False:
                logger.info(
                    "MNE time-frequency package unavailable; fallback routine executed."
                )

            return ToolResult(status="success", data=results)

        except Exception as e:
            logger.error(f"Time-frequency analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class MNETimeFreqTools:
    """Collection of MNE time-frequency tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all MNE time-frequency tools."""
        return [MNETimeFreqTool()]
