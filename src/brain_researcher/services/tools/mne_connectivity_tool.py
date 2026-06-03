"""
MNE Connectivity Analysis implementation for Brain Researcher.

Implements various connectivity measures including coherence, phase locking,
Granger causality, and mutual information for EEG/MEG data.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.params import (
    MNEConnectivityParameters,
    mne_connectivity_from_payload,
    run_mne_connectivity,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)

configure_mne_environment()


class ConnectivityMethod(str):
    """Connectivity methods."""

    COHERENCE = "coherence"
    COHERENCY = "coherency"
    IMCOH = "imcoh"  # Imaginary coherence
    PLV = "plv"  # Phase Locking Value
    PLI = "pli"  # Phase Lag Index
    WPLI = "wpli"  # Weighted Phase Lag Index
    PSI = "psi"  # Phase Slope Index
    GC = "gc"  # Granger Causality
    MI = "mi"  # Mutual Information
    COR = "cor"  # Correlation
    COV = "cov"  # Covariance
    AEC = "aec"  # Amplitude Envelope Correlation
    PAC = "pac"  # Phase-Amplitude Coupling


class MNEConnectivityArgs(BaseModel):
    """Arguments for MNE connectivity analysis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input data
    epochs_file: str | None = Field(
        default=None, description="Path to epochs file (.fif format)"
    )
    raw_file: str | None = Field(
        default=None, description="Path to raw data file (.fif format)"
    )
    time_series: str | None = Field(
        default=None, description="Path to time series data (numpy array)"
    )

    # Analysis parameters
    method: str | list[str] = Field(
        default="coherence",
        description="Connectivity method(s): coherence, plv, pli, wpli, gc, mi, etc.",
    )
    mode: str = Field(
        default="multitaper",
        description="Spectral estimation mode: multitaper, fourier, cwt_morlet",
    )

    # Frequency parameters
    fmin: float | list[float] = Field(
        default=1.0,
        description="Minimum frequency or list of minimum frequencies for bands",
    )
    fmax: float | list[float] = Field(
        default=40.0,
        description="Maximum frequency or list of maximum frequencies for bands",
    )
    fskip: int = Field(default=0, description="Frequency skip factor for decimation")
    faverage: bool = Field(
        default=False, description="Average connectivity across frequency bands"
    )
    n_cycles: float | list[float] = Field(
        default=7.0, description="Number of cycles for wavelet analysis"
    )

    # Time parameters
    tmin: float | None = Field(
        default=None, description="Start time for analysis window"
    )
    tmax: float | None = Field(default=None, description="End time for analysis window")

    # Channel selection
    picks: str | list[str] | None = Field(
        default=None,
        description="Channel selection: 'meg', 'eeg', or list of channel names",
    )
    indices: tuple[list[int], list[int]] | None = Field(
        default=None, description="Specific connections to compute (seeds, targets)"
    )

    # Statistical parameters
    n_surrogates: int = Field(
        default=0, description="Number of surrogates for significance testing"
    )
    p_value: float = Field(
        default=0.05, description="P-value threshold for significance"
    )

    # Granger causality specific
    gc_n_lags: int = Field(
        default=10, description="Number of lags for Granger causality"
    )

    # Output options
    output_dir: str = Field(description="Output directory for results")
    save_matrix: bool = Field(default=True, description="Save connectivity matrix")
    save_plots: bool = Field(
        default=True, description="Generate and save visualization plots"
    )
    return_generator: bool = Field(
        default=False, description="Return generator for memory efficiency"
    )


class MNEConnectivityTool(NeuroToolWrapper):
    """MNE connectivity analysis tool."""

    def __init__(self):
        """Initialize MNE connectivity tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.mne_available = False
        self.mne_connectivity_available = False

        try:
            import mne

            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(f"MNE-Python {self.mne_version} available")
        except ImportError:
            logger.warning("MNE-Python not installed")

        try:
            import mne_connectivity

            self.mne_connectivity_available = True
            logger.info("MNE-Connectivity available")
        except ImportError:
            logger.warning("MNE-Connectivity not installed - using fallback methods")

    def get_tool_name(self) -> str:
        return "mne_connectivity"

    def get_tool_description(self) -> str:
        return (
            "MNE connectivity analysis for EEG/MEG data. Computes various "
            "connectivity measures including coherence, phase locking value (PLV), "
            "phase lag index (PLI), weighted PLI, Granger causality, and mutual "
            "information. Supports both sensor and source space connectivity with "
            "statistical significance testing."
        )

    def get_args_schema(self):
        return MNEConnectivityArgs

    def _load_data(
        self,
        epochs_file: str | None = None,
        raw_file: str | None = None,
        time_series: str | None = None,
        tmin: float | None = None,
        tmax: float | None = None,
    ):
        """Load and prepare data for connectivity analysis."""
        import mne

        if epochs_file:
            epochs = mne.read_epochs(epochs_file)
            if tmin is not None or tmax is not None:
                epochs = epochs.copy().crop(tmin, tmax)
            return epochs, epochs.info

        elif raw_file:
            raw = mne.io.read_raw_fif(raw_file, preload=True)
            # Create epochs from raw
            events = mne.make_fixed_length_events(raw, duration=2.0)
            epochs = mne.Epochs(
                raw, events, tmin=0, tmax=2.0, baseline=None, preload=True
            )
            if tmin is not None or tmax is not None:
                epochs = epochs.copy().crop(tmin, tmax)
            return epochs, raw.info

        elif time_series:
            # Load numpy array
            data = np.load(time_series)
            return data, None

        else:
            raise ValueError("No input data provided")

    def _compute_connectivity_mne(
        self,
        data,
        method: str | list[str],
        mode: str,
        fmin: float | list[float],
        fmax: float | list[float],
        indices: tuple | None = None,
        **kwargs,
    ):
        """Compute connectivity using MNE-Connectivity."""
        import inspect

        import mne_connectivity

        # Ensure method is a list
        if isinstance(method, str):
            method = [method]

        # Map our method names to MNE names
        method_map = {
            "coherence": "coh",
            "coherency": "cohy",
            "imcoh": "imcoh",
            "plv": "plv",
            "pli": "pli",
            "wpli": "wpli",
            "psi": "psi",
            "gc": "gc",
            "mi": "mi",
        }

        mne_methods = [method_map.get(m, m) for m in method]

        # Compute connectivity
        if hasattr(mne_connectivity, "spectral_connectivity_epochs"):
            func = mne_connectivity.spectral_connectivity_epochs
            sig = inspect.signature(func)
            call_kwargs = {
                "data": data,
                "method": mne_methods,
                "mode": mode,
                "indices": indices,
                "fmin": fmin,
                "fmax": fmax,
                "fskip": kwargs.get("fskip", 0),
                "faverage": kwargs.get("faverage", False),
                "n_jobs": 1,
                "verbose": False,
            }
            if "n_cycles" in sig.parameters:
                call_kwargs["n_cycles"] = kwargs.get("n_cycles", 7.0)
            if "cwt_n_cycles" in sig.parameters:
                call_kwargs["cwt_n_cycles"] = kwargs.get("n_cycles", 7.0)
            con = func(**{k: v for k, v in call_kwargs.items() if k in sig.parameters})
        else:
            # Fallback for older versions
            from mne.connectivity import spectral_connectivity

            sig = inspect.signature(spectral_connectivity)
            call_kwargs = {
                "data": data,
                "method": mne_methods,
                "mode": mode,
                "indices": indices,
                "fmin": fmin,
                "fmax": fmax,
                "fskip": kwargs.get("fskip", 0),
                "faverage": kwargs.get("faverage", False),
                "n_jobs": 1,
                "verbose": False,
            }
            if "n_cycles" in sig.parameters:
                call_kwargs["n_cycles"] = kwargs.get("n_cycles", 7.0)
            con = spectral_connectivity(
                **{k: v for k, v in call_kwargs.items() if k in sig.parameters}
            )

        return con

    def _compute_phase_locking_value(self, data1, data2):
        """Compute Phase Locking Value between two signals."""
        # Hilbert transform to get instantaneous phase
        analytic1 = signal.hilbert(data1)
        analytic2 = signal.hilbert(data2)

        phase1 = np.angle(analytic1)
        phase2 = np.angle(analytic2)

        # Phase difference
        phase_diff = phase1 - phase2

        # PLV
        plv = np.abs(np.mean(np.exp(1j * phase_diff)))

        return plv

    def _compute_phase_lag_index(self, data1, data2):
        """Compute Phase Lag Index between two signals."""
        # Hilbert transform
        analytic1 = signal.hilbert(data1)
        analytic2 = signal.hilbert(data2)

        phase1 = np.angle(analytic1)
        phase2 = np.angle(analytic2)

        # Phase difference
        phase_diff = phase1 - phase2

        # PLI
        pli = np.abs(np.mean(np.sign(np.sin(phase_diff))))

        return pli

    def _compute_granger_causality(self, data, n_lags=10):
        """Compute pairwise Granger causality."""
        from statsmodels.tsa.stattools import grangercausalitytests

        n_channels = data.shape[0]
        gc_matrix = np.zeros((n_channels, n_channels))

        for i in range(n_channels):
            for j in range(n_channels):
                if i != j:
                    try:
                        # Prepare data for Granger test
                        test_data = np.column_stack([data[j], data[i]])

                        # Run Granger causality test
                        result = grangercausalitytests(
                            test_data, maxlag=n_lags, verbose=False
                        )

                        # Extract F-statistic from first lag
                        gc_matrix[i, j] = result[1][0][0]["ftest"][0]
                    except:
                        gc_matrix[i, j] = 0

        return gc_matrix

    def _compute_mutual_information(self, data1, data2, bins=10):
        """Compute mutual information between two signals."""
        # Discretize the data
        hist_2d, _, _ = np.histogram2d(data1, data2, bins=bins)

        # Convert to probabilities
        pxy = hist_2d / np.sum(hist_2d)
        px = np.sum(pxy, axis=1)
        py = np.sum(pxy, axis=0)

        # Mutual information
        px_py = px[:, None] * py[None, :]

        # Avoid log(0)
        mask = pxy > 0
        mi = np.sum(pxy[mask] * np.log(pxy[mask] / px_py[mask]))

        return mi

    def _compute_amplitude_envelope_correlation(self, data1, data2):
        """Compute amplitude envelope correlation."""
        # Get amplitude envelopes
        analytic1 = signal.hilbert(data1)
        analytic2 = signal.hilbert(data2)

        envelope1 = np.abs(analytic1)
        envelope2 = np.abs(analytic2)

        # Correlate envelopes
        aec = np.corrcoef(envelope1, envelope2)[0, 1]

        return aec

    def _compute_connectivity_fallback(self, data, method: str, **kwargs):
        """Fallback connectivity computation without MNE-Connectivity."""
        if isinstance(data, np.ndarray):
            n_channels = data.shape[0]
            data.shape[-1]
        else:
            # Assume epochs
            data_array = data.get_data()
            n_channels = data_array.shape[1]
            data_array.shape[2]
            # Average across epochs for simplicity
            data = np.mean(data_array, axis=0)

        # Initialize connectivity matrix
        con_matrix = np.zeros((n_channels, n_channels))

        # Compute pairwise connectivity
        for i in range(n_channels):
            for j in range(i + 1, n_channels):
                if method == "plv":
                    con_matrix[i, j] = self._compute_phase_locking_value(
                        data[i], data[j]
                    )
                elif method == "pli":
                    con_matrix[i, j] = self._compute_phase_lag_index(data[i], data[j])
                elif method == "mi":
                    con_matrix[i, j] = self._compute_mutual_information(
                        data[i], data[j]
                    )
                elif method == "aec":
                    con_matrix[i, j] = self._compute_amplitude_envelope_correlation(
                        data[i], data[j]
                    )
                elif method in ["cor", "correlation"]:
                    con_matrix[i, j] = np.corrcoef(data[i], data[j])[0, 1]

                # Make symmetric
                con_matrix[j, i] = con_matrix[i, j]

        if method == "gc":
            # Granger causality is directional
            con_matrix = self._compute_granger_causality(
                data, kwargs.get("gc_n_lags", 10)
            )

        return con_matrix

    def _test_significance(
        self,
        data,
        con_matrix,
        method: str,
        n_surrogates: int = 100,
        p_value: float = 0.05,
    ):
        """Test significance using surrogate data."""
        if n_surrogates == 0:
            return None

        n_channels = con_matrix.shape[0]
        surrogate_con = []

        for _ in range(n_surrogates):
            # Create surrogate by phase randomization
            surrogate = np.zeros_like(data)
            for ch in range(n_channels):
                # FFT
                fft = np.fft.fft(data[ch])
                # Randomize phase
                random_phase = np.exp(1j * np.random.uniform(0, 2 * np.pi, len(fft)))
                fft_surrogate = fft * random_phase
                # Inverse FFT
                surrogate[ch] = np.real(np.fft.ifft(fft_surrogate))

            # Compute connectivity for surrogate
            sur_con = self._compute_connectivity_fallback(surrogate, method)
            surrogate_con.append(sur_con)

        # Statistical threshold
        surrogate_con = np.array(surrogate_con)
        threshold = np.percentile(surrogate_con, (1 - p_value) * 100, axis=0)

        # Significant connections
        sig_con = con_matrix > threshold

        return sig_con, threshold

    def _plot_connectivity_matrix(
        self,
        con_matrix: np.ndarray,
        labels: list[str] | None = None,
        title: str = "Connectivity Matrix",
        output_file: str | None = None,
    ):
        """Plot connectivity matrix."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 8))

        im = ax.imshow(con_matrix, cmap="RdBu_r", aspect="auto")
        plt.colorbar(im, ax=ax)

        if labels:
            ax.set_xticks(range(len(labels)))
            ax.set_yticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=45, ha="right")
            ax.set_yticklabels(labels)

        ax.set_title(title)
        ax.set_xlabel("Channels")
        ax.set_ylabel("Channels")

        plt.tight_layout()

        if output_file:
            plt.savefig(output_file, dpi=150, bbox_inches="tight")
            plt.close()
        else:
            plt.show()

    def _plot_connectivity_circle(
        self,
        con_matrix: np.ndarray,
        labels: list[str],
        threshold: float = 0.5,
        output_file: str | None = None,
    ):
        """Plot connectivity as a circle plot."""
        try:
            from mne.viz import plot_connectivity_circle

            # Threshold connections
            con_thresh = con_matrix.copy()
            con_thresh[np.abs(con_thresh) < threshold] = 0

            fig = plot_connectivity_circle(
                con_thresh, labels, n_lines=None, title="Connectivity Circle"
            )

            if output_file:
                fig.savefig(output_file, dpi=150, bbox_inches="tight")
        except ImportError:
            logger.warning("Circle plot requires MNE visualization functions")

    def _run(
        self,
        epochs_file: str | None = None,
        raw_file: str | None = None,
        time_series: str | None = None,
        method: str | list[str] = "coherence",
        mode: str = "multitaper",
        fmin: float | list[float] = 1.0,
        fmax: float | list[float] = 40.0,
        fskip: int = 0,
        faverage: bool = False,
        n_cycles: float | np.ndarray = 7.0,
        tmin: float | None = None,
        tmax: float | None = None,
        picks: str | list[str] | None = None,
        indices: tuple[np.ndarray, np.ndarray] | None = None,
        n_surrogates: int = 0,
        p_value: float = 0.05,
        gc_n_lags: int = 10,
        output_dir: str = None,
        save_matrix: bool = True,
        save_plots: bool = True,
        return_generator: bool = False,
        verbose: bool = True,
        **kwargs,
    ) -> ToolResult:
        """Execute connectivity analysis."""
        try:
            if not self.mne_available:
                return ToolResult(
                    status="error", error="MNE-Python not available", data={}
                )

            if output_dir is None:
                output_dir = str(
                    Path(epochs_file or raw_file or time_series or ".").parent
                    / "connectivity"
                )

            payload: dict[str, Any] = {
                "epochs_file": epochs_file,
                "raw_file": raw_file,
                "time_series": time_series,
                "output_dir": output_dir,
                "method": method,
                "mode": mode,
                "fmin": fmin,
                "fmax": fmax,
                "fskip": fskip,
                "faverage": faverage,
                "n_cycles": n_cycles,
                "tmin": tmin,
                "tmax": tmax,
                "picks": picks,
                "indices": indices,
                "n_surrogates": n_surrogates,
                "p_value": p_value,
                "gc_n_lags": gc_n_lags,
                "save_matrix": save_matrix,
                "save_plots": save_plots,
                "return_generator": return_generator,
            }

            params: MNEConnectivityParameters = mne_connectivity_from_payload(payload)
            results = run_mne_connectivity(params)
            used_package = results.pop("used_mne_connectivity_package", None)

            if verbose and used_package is False:
                logger.info(
                    "mne-connectivity package not available; fallback implementation used."
                )

            return ToolResult(status="success", data=results)

        except Exception as e:
            logger.error(f"Connectivity analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class MNEConnectivityTools:
    """Collection of MNE connectivity tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all MNE connectivity tools."""
        return [MNEConnectivityTool()]
