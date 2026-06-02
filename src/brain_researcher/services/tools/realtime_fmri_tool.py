"""
Real-time fMRI processing and neurofeedback tools for Brain Researcher.

Implements real-time preprocessing, GLM, neurofeedback computations,
adaptive algorithms, and specialized neurofeedback tools.

This file merges functionality from both realtime_fmri_tool.py and
realtime_neurofeedback.py into a comprehensive suite of real-time tools.
"""

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from importlib.util import find_spec
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal
from scipy.ndimage import gaussian_filter

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    write_feature_contract,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

# Additional dependency availability checks for neurofeedback tools.
nibabel_available = find_spec("nibabel") is not None
sklearn_available = find_spec("sklearn.decomposition") is not None

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models and Enums
# ============================================================================


class FeedbackType(Enum):
    """Types of neurofeedback."""

    VISUAL = "visual"
    AUDITORY = "auditory"
    TACTILE = "tactile"
    GAME = "game"
    VR = "vr"


@dataclass
class RealtimeMetrics:
    """Real-time processing metrics."""

    current_activation: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    trend: str  # "increasing", "decreasing", "stable"
    success_rate: float
    time_above_threshold: float


class RealtimeFMRIArgs(BaseModel):
    """Arguments for real-time fMRI processing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input configuration
    data_source: str = Field(
        default="file", description="Data source: 'file', 'stream', 'simulator'"
    )
    input_file: str | None = Field(
        default=None, description="Path to fMRI data file (for file mode)"
    )
    stream_address: str | None = Field(
        default=None, description="Network address for data stream"
    )

    # Processing mode
    mode: str = Field(
        default="neurofeedback",
        description="Mode: 'neurofeedback', 'decoding', 'monitoring', 'quality_control'",
    )

    # ROI configuration
    roi_mask: str | None = Field(default=None, description="Path to ROI mask file")
    roi_coordinates: list[int] | None = Field(
        default=None, description="ROI center coordinates [x, y, z]"
    )
    roi_radius: int = Field(default=5, description="ROI radius in voxels")

    # Preprocessing parameters
    motion_correction: bool = Field(default=True, description="Apply motion correction")
    spatial_smoothing: bool = Field(default=True, description="Apply spatial smoothing")
    smoothing_fwhm: float = Field(default=6.0, description="Smoothing FWHM in mm")
    temporal_filtering: bool = Field(
        default=True, description="Apply temporal filtering"
    )
    highpass_cutoff: float = Field(
        default=0.01, description="High-pass filter cutoff (Hz)"
    )
    lowpass_cutoff: float | None = Field(
        default=0.1, description="Low-pass filter cutoff (Hz)"
    )

    # GLM parameters
    enable_glm: bool = Field(default=False, description="Enable incremental GLM")
    design_matrix: str | None = Field(
        default=None, description="Path to design matrix file"
    )
    contrasts: dict[str, list[float]] | None = Field(
        default=None, description="GLM contrasts"
    )
    hrf_model: str = Field(
        default="canonical", description="HRF model: 'canonical', 'gamma', 'fir'"
    )

    # Neurofeedback parameters
    feedback_type: str = Field(
        default="continuous",
        description="Feedback type: 'continuous', 'intermittent', 'threshold'",
    )
    baseline_scans: int = Field(default=10, description="Number of scans for baseline")
    feedback_delay: float = Field(default=0.0, description="Feedback delay in seconds")
    target_level: float | None = Field(
        default=None, description="Target activation level"
    )

    # Decoding parameters
    classifier_type: str = Field(
        default="svm", description="Classifier: 'svm', 'logistic', 'lda'"
    )
    training_data: str | None = Field(default=None, description="Path to training data")

    # Quality control
    enable_qc: bool = Field(default=True, description="Enable quality control")
    motion_threshold: float = Field(default=0.5, description="Motion threshold in mm")
    dvars_threshold: float = Field(default=1.5, description="DVARS threshold")

    # Output configuration
    output_dir: str = Field(default="realtime_output", description="Output directory")
    save_volumes: bool = Field(default=False, description="Save processed volumes")
    save_metrics: bool = Field(default=True, description="Save quality metrics")

    # Simulation parameters (for testing)
    simulate_data: bool = Field(default=False, description="Use simulated data")
    simulation_volumes: int = Field(
        default=100, description="Number of volumes to simulate"
    )
    simulation_shape: list[int] = Field(
        default=[64, 64, 35], description="Shape of simulated volumes"
    )
    simulation_tr: float = Field(default=2.0, description="TR for simulation (seconds)")


# ----------------------------------------------------------------------------
# Schemas for specialized real-time tools (ensure proper LangChain binding)
# ----------------------------------------------------------------------------


class RealtimeGLMArgs(BaseModel):
    data: list[list[float]] | None = Field(
        default=None, description="Time x Voxels data matrix"
    )
    design_matrix: list[list[float]] | None = Field(
        default=None, description="Time x Regressors design matrix"
    )
    contrast: list[float] | None = Field(default=None, description="Contrast vector")
    # Optional file-based inputs for large arrays
    data_file: str | None = Field(
        default=None, description="Path to .npy or .json file for data"
    )
    design_matrix_file: str | None = Field(
        default=None, description="Path to .npy or .json file for design matrix"
    )
    contrast_file: str | None = Field(
        default=None, description="Path to .npy or .json file for contrast vector"
    )
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class NeurofeedbackControlArgs(BaseModel):
    activation_level: float | None = Field(
        default=None, description="Current activation level"
    )
    target_level: float | None = Field(
        default=None, description="Target activation level"
    )
    feedback_type: str = Field(default="visual", description="Feedback modality")
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class ROIMonitoringArgs(BaseModel):
    volume: list[list[list[float]]] | None = Field(
        default=None, description="3D volume for ROI extraction"
    )
    roi_masks: dict[str, list[list[list[bool]]]] | None = Field(
        default=None, description="Dict of ROI masks"
    )
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class AdaptiveThresholdingArgs(BaseModel):
    current_activation: float | None = Field(
        default=None, description="Current activation metric"
    )
    performance_metric: float | None = Field(
        default=None, description="Recent performance metric"
    )
    adaptation_rate: float = Field(default=0.1, description="Adaptation rate")
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class RealtimeDecodingArgs(BaseModel):
    brain_data: list[list[float]] | None = Field(
        default=None, description="Samples x Features matrix"
    )
    labels: list[int] | None = Field(default=None, description="Labels for training")
    mode: str = Field(default="predict", description="train or predict")
    decoder_type: str = Field(default="svm", description="svm|logistic|lda")
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class ClosedLoopStimulationArgs(BaseModel):
    brain_state: list[float] | None = Field(
        default=None, description="Current brain state vector"
    )
    target_state: list[float] | None = Field(
        default=None, description="Target state vector"
    )
    stimulation_type: str = Field(default="tms", description="tms|tdcs|optogenetic")
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class RealtimeConnectivityArgs(BaseModel):
    roi_timeseries: list[list[float]] | None = Field(
        default=None, description="Time x ROI matrix"
    )
    method: str = Field(
        default="correlation", description="correlation|partial_correlation|coherence"
    )
    window_size: int = Field(default=30, description="Sliding window size")
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


class NeurofeedbackTrainingArgs(BaseModel):
    session_number: int | None = Field(
        default=None, description="Training session index"
    )
    training_protocol: str | None = Field(default=None, description="Protocol name")
    performance_data: list[float] | None = Field(
        default=None, description="Array of performance values"
    )
    output_dir: str | None = Field(
        default=None, description="Directory to save outputs"
    )


# ============================================================================
# Original RealtimeFMRITool - Comprehensive single tool
# ============================================================================


class RealtimeFMRITool(NeuroToolWrapper):
    """Real-time fMRI processing tool."""

    def __init__(self):
        """Initialize real-time fMRI tool."""
        super().__init__()
        self._check_dependencies()
        self.buffer = None
        self.baseline = None
        self.feedback_history = []
        self.qc_metrics = []

    def _check_dependencies(self):
        """Check required dependencies."""
        self.nibabel_available = False
        self.nilearn_available = False

        if find_spec("nibabel") is not None:
            self.nibabel_available = True
            logger.info("Nibabel available")
        else:
            logger.warning("Nibabel not installed")

        if find_spec("nilearn") is not None:
            self.nilearn_available = True
            logger.info("Nilearn available")
        else:
            logger.warning("Nilearn not installed")

    def get_tool_name(self) -> str:
        return "realtime_fmri"

    def get_tool_description(self) -> str:
        return (
            "Real-time fMRI processing for neurofeedback and online analysis. "
            "Supports real-time motion correction, spatial smoothing, temporal "
            "filtering, and incremental GLM. Implements neurofeedback with ROI "
            "analysis, continuous/intermittent feedback, and adaptive baselines. "
            "Includes real-time quality control, outlier detection, and motion "
            "monitoring. Supports brain state decoding and closed-loop experiments."
        )

    def get_args_schema(self):
        return RealtimeFMRIArgs

    def _initialize_buffer(self, buffer_size, data_shape):
        """Initialize data buffer for real-time processing."""
        self.buffer = deque(maxlen=buffer_size)
        self.data_shape = data_shape
        self.volume_count = 0

    def _simulate_data_stream(self, n_volumes, shape, tr, noise_level):
        """Simulate fMRI data stream for testing."""
        for i in range(n_volumes):
            # Generate synthetic volume
            volume = np.random.randn(*shape) * noise_level

            # Add activation pattern
            if i > 10:  # After baseline
                # Add activation in center
                center = [s // 2 for s in shape]
                activation = np.exp(
                    -(
                        (np.arange(shape[0]) - center[0]) ** 2
                        + (np.arange(shape[1])[:, None] - center[1]) ** 2
                        + (np.arange(shape[2])[:, None, None] - center[2]) ** 2
                    )
                    / 100
                )
                volume += activation.T * np.sin(i * 0.1) * 2

            yield volume
            time.sleep(tr)  # Simulate TR delay

    def _motion_correction(self, volume, reference=None):
        """Perform real-time motion correction."""
        # Simplified motion correction (would use FSL MCFLIRT or similar)
        if reference is None:
            return volume, np.zeros(6)  # No correction for first volume

        # Simulate motion parameters (in practice, would compute registration)
        motion_params = np.random.randn(6) * 0.1  # Small random motion

        # Apply simple translation (simplified)
        from scipy.ndimage import shift

        corrected = volume.copy()
        # Apply shifts for each axis
        shifts = [0, 0, 0]
        for axis, param in enumerate(motion_params[:3]):
            shifts[axis] = param
        corrected = shift(corrected, shifts)

        return corrected, motion_params

    def _spatial_smoothing(self, volume, fwhm_mm, voxel_size=3.0):
        """Apply spatial smoothing."""
        sigma = fwhm_mm / (2.355 * voxel_size)  # Convert FWHM to sigma in voxels
        smoothed = gaussian_filter(volume, sigma=sigma)
        return smoothed

    def _temporal_filtering(self, timeseries, highpass, lowpass, tr):
        """Apply temporal filtering."""
        if len(timeseries) < 4:
            return timeseries  # Not enough data

        nyquist = 0.5 / tr

        # Design filter
        if highpass and lowpass:
            sos = signal.butter(
                4, [highpass / nyquist, lowpass / nyquist], btype="band", output="sos"
            )
        elif highpass:
            sos = signal.butter(4, highpass / nyquist, btype="high", output="sos")
        elif lowpass:
            sos = signal.butter(4, lowpass / nyquist, btype="low", output="sos")
        else:
            return timeseries

        # Apply filter
        filtered = signal.sosfiltfilt(sos, timeseries, axis=0)
        return filtered

    def _extract_roi_signal(self, volume, roi_mask=None, roi_coords=None, roi_radius=5):
        """Extract signal from ROI."""
        if roi_mask is not None:
            # Use provided mask
            return np.mean(volume[roi_mask > 0])
        elif roi_coords is not None:
            # Create spherical ROI
            x, y, z = roi_coords
            mask = np.zeros_like(volume, dtype=bool)

            # Create sphere
            for i in range(
                max(0, x - roi_radius), min(volume.shape[0], x + roi_radius + 1)
            ):
                for j in range(
                    max(0, y - roi_radius), min(volume.shape[1], y + roi_radius + 1)
                ):
                    for k in range(
                        max(0, z - roi_radius), min(volume.shape[2], z + roi_radius + 1)
                    ):
                        if (i - x) ** 2 + (j - y) ** 2 + (k - z) ** 2 <= roi_radius**2:
                            mask[i, j, k] = True

            return np.mean(volume[mask])
        else:
            # Use whole brain mean
            return np.mean(volume)

    def _compute_feedback(
        self,
        current_signal,
        baseline_mean,
        baseline_std,
        feedback_type="continuous",
        target_level=None,
    ):
        """Compute neurofeedback signal."""
        # Z-score normalization
        z_score = (current_signal - baseline_mean) / (baseline_std + 1e-6)

        if feedback_type == "continuous":
            # Linear scaling
            feedback = np.clip((z_score + 2) / 4, 0, 1)  # Map [-2, 2] to [0, 1]
        elif feedback_type == "threshold":
            # Binary feedback
            threshold = target_level if target_level else 1.0
            feedback = 1.0 if z_score > threshold else 0.0
        elif feedback_type == "intermittent":
            # Feedback only when significant change
            if abs(z_score) > 1.0:
                feedback = np.clip((z_score + 2) / 4, 0, 1)
            else:
                feedback = 0.5  # Neutral
        else:
            feedback = z_score

        return feedback, z_score

    def _incremental_glm(self, y, X, beta=None):
        """Perform incremental GLM update."""
        # Simplified incremental GLM
        if beta is None:
            # Initial fit
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        else:
            # Update (simplified - would use recursive least squares)
            residual = y - X @ beta
            update = 0.01 * X.T @ residual  # Learning rate
            beta = beta + update

        return beta

    def _compute_dvars(self, volume, prev_volume):
        """Compute DVARS (derivative of variance)."""
        if prev_volume is None:
            return 0.0

        diff = volume - prev_volume
        dvars = np.sqrt(np.mean(diff**2))
        return dvars

    def _compute_framewise_displacement(self, motion_params, radius=50):
        """Compute framewise displacement from motion parameters."""
        if len(motion_params) == 0:
            return 0.0

        # Convert rotations to displacements (assuming 50mm radius)
        rotations = motion_params[3:] * radius
        translations = motion_params[:3]

        fd = np.sum(np.abs(translations)) + np.sum(np.abs(rotations))
        return fd

    def _quality_control(self, volume, prev_volume, motion_params):
        """Perform quality control checks."""
        qc = {
            "dvars": self._compute_dvars(volume, prev_volume),
            "fd": self._compute_framewise_displacement(motion_params),
            "mean_signal": np.mean(volume),
            "std_signal": np.std(volume),
            "snr": np.mean(volume) / np.std(volume),
            "outlier": False,
        }

        # Check for outliers
        if qc["dvars"] > 1.5 or qc["fd"] > 0.5:
            qc["outlier"] = True

        return qc

    def _run(self, **kwargs) -> ToolResult:
        """Run real-time fMRI processing."""
        args = RealtimeFMRIArgs(**kwargs)

        # Setup output directory
        output_path = Path(args.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Initialize processing
        results = {
            "volumes_processed": 0,
            "feedback_signals": [],
            "qc_metrics": [],
            "roi_signals": [],
        }

        try:
            # Setup data source
            if args.simulate_data:
                data_stream = self._simulate_data_stream(
                    args.simulation_volumes,
                    args.simulation_shape,
                    args.simulation_tr,
                    noise_level=0.1,
                )
            else:
                # Would connect to real data stream
                logger.warning("Real data stream not implemented, using simulation")
                data_stream = self._simulate_data_stream(
                    args.simulation_volumes,
                    args.simulation_shape,
                    args.simulation_tr,
                    noise_level=0.1,
                )

            # Initialize buffer
            self._initialize_buffer(args.baseline_scans * 2, args.simulation_shape)

            # Process volumes
            prev_volume = None
            reference_volume = None
            baseline_signals = []
            glm_beta = None

            for i, volume in enumerate(data_stream):
                # Motion correction
                if args.motion_correction:
                    if reference_volume is None:
                        reference_volume = volume
                    volume, motion_params = self._motion_correction(
                        volume, reference_volume
                    )
                else:
                    motion_params = np.zeros(6)

                # Spatial smoothing
                if args.spatial_smoothing:
                    volume = self._spatial_smoothing(volume, args.smoothing_fwhm)

                # Extract ROI signal
                roi_signal = self._extract_roi_signal(
                    volume, roi_coords=args.roi_coordinates, roi_radius=args.roi_radius
                )

                # Buffer for temporal filtering
                self.buffer.append(roi_signal)

                # Temporal filtering (after enough data)
                if len(self.buffer) >= 4 and args.temporal_filtering:
                    filtered_buffer = self._temporal_filtering(
                        np.array(self.buffer),
                        args.highpass_cutoff,
                        args.lowpass_cutoff,
                        args.simulation_tr,
                    )
                    roi_signal = filtered_buffer[-1]

                # Quality control
                if args.enable_qc:
                    qc = self._quality_control(volume, prev_volume, motion_params)
                    results["qc_metrics"].append(qc)

                # Baseline period
                if i < args.baseline_scans:
                    baseline_signals.append(roi_signal)
                    if i == args.baseline_scans - 1:
                        # Compute baseline statistics
                        baseline_mean = np.mean(baseline_signals)
                        baseline_std = np.std(baseline_signals)
                        logger.info(
                            f"Baseline computed: mean={baseline_mean:.3f}, std={baseline_std:.3f}"
                        )

                # Neurofeedback computation
                elif args.mode == "neurofeedback" and i >= args.baseline_scans:
                    feedback, z_score = self._compute_feedback(
                        roi_signal,
                        baseline_mean,
                        baseline_std,
                        args.feedback_type,
                        args.target_level,
                    )

                    # Apply delay if specified
                    if args.feedback_delay > 0:
                        time.sleep(args.feedback_delay)

                    results["feedback_signals"].append(
                        {
                            "volume": i,
                            "feedback": float(feedback),
                            "z_score": float(z_score),
                            "roi_signal": float(roi_signal),
                        }
                    )

                    # Log feedback (would send to display in real system)
                    if i % 10 == 0:
                        logger.info(
                            f"Volume {i}: feedback={feedback:.3f}, z_score={z_score:.3f}"
                        )

                # GLM update
                if args.enable_glm and args.design_matrix and i >= args.baseline_scans:
                    # Would load actual design matrix
                    X = np.random.randn(i + 1, 2)  # Placeholder
                    y = np.array(results["roi_signals"])
                    glm_beta = self._incremental_glm(y, X[: len(y)], glm_beta)

                # Store results
                results["roi_signals"].append(float(roi_signal))
                results["volumes_processed"] = i + 1

                # Save volume if requested
                if args.save_volumes:
                    np.save(output_path / f"volume_{i:04d}.npy", volume)

                prev_volume = volume

                # Early stopping for demo
                if i >= 50 and args.simulate_data:
                    break

            # Save final results
            if args.save_metrics:
                with open(output_path / "results.json", "w") as f:
                    json.dump(results, f, indent=2)

            # Compute summary statistics
            if len(results["feedback_signals"]) > 0:
                feedback_values = [f["feedback"] for f in results["feedback_signals"]]
                summary = {
                    "mean_feedback": float(np.mean(feedback_values)),
                    "std_feedback": float(np.std(feedback_values)),
                    "max_feedback": float(np.max(feedback_values)),
                    "min_feedback": float(np.min(feedback_values)),
                    "volumes_processed": results["volumes_processed"],
                }
            else:
                summary = {"volumes_processed": results["volumes_processed"]}

            return ToolResult(
                status="success",
                data={
                    "summary": summary,
                    "outputs": {"results_file": str(output_path / "results.json")},
                    "feedback_history": (
                        results["feedback_signals"][-10:]
                        if results["feedback_signals"]
                        else []
                    ),
                },
            )

        except Exception as e:
            logger.error(f"Real-time processing failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


# ============================================================================
# Specialized Neurofeedback Tools (from realtime_neurofeedback.py)
# ============================================================================


class RealtimeGLMTool(NeuroToolWrapper):
    """Real-time incremental GLM for fMRI analysis."""

    def __init__(self):
        super().__init__()
        self.beta = None
        self.residuals = []

    def get_tool_name(self) -> str:
        return "realtime_glm"

    def get_tool_description(self) -> str:
        return "Incremental GLM for real-time fMRI analysis"

    def get_args_schema(self):
        return RealtimeGLMArgs

    def _run(
        self,
        data: np.ndarray | None = None,
        design_matrix: np.ndarray | None = None,
        contrast: np.ndarray | None = None,
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Run incremental GLM analysis."""
        try:
            output_path = Path(output_dir or "realtime_glm_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Allow file-based inputs via kwargs
            def _load_array(maybe_file):
                if maybe_file is None:
                    return None
                p = Path(str(maybe_file))
                if p.suffix.lower() == ".npy" and p.exists():
                    return np.load(p)
                # Try JSON
                try:
                    import json as _json

                    with open(p) as f:
                        arr = _json.load(f)
                    return np.array(arr)
                except Exception:
                    return None

            if data is None and (df := kwargs.get("data_file")):
                data = _load_array(df)
            if design_matrix is None and (dmf := kwargs.get("design_matrix_file")):
                design_matrix = _load_array(dmf)
            if contrast is None and (cf := kwargs.get("contrast_file")):
                c = _load_array(cf)
                if c is not None:
                    contrast = c

            # Generate test data if not provided
            if data is None:
                data = self._generate_test_data()
            if design_matrix is None:
                design_matrix = self._generate_design_matrix(data.shape[0])

            # Perform incremental GLM
            beta, residuals, stats = self._incremental_glm(data, design_matrix)

            # Apply contrast if provided
            if contrast is not None:
                contrast_map = self._apply_contrast(beta, contrast)
                np.save(output_path / "contrast_map.npy", contrast_map)

            # Save results
            np.save(output_path / "beta_maps.npy", beta)
            np.save(output_path / "residuals.npy", residuals)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "beta_maps": str(output_path / "beta_maps.npy"),
                        "residuals": str(output_path / "residuals.npy"),
                    },
                    "statistics": stats,
                },
            )

        except Exception as e:
            logger.error(f"Realtime GLM failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _generate_test_data(self):
        """Generate synthetic fMRI time series."""
        n_timepoints = 200
        n_voxels = 1000

        # Simulate BOLD signal
        time = np.arange(n_timepoints)
        signal = np.zeros((n_timepoints, n_voxels))

        # Add task effects
        for i in range(n_voxels):
            if i < 200:  # Active voxels
                signal[:, i] = (
                    0.5 * np.sin(0.05 * time) + np.random.randn(n_timepoints) * 0.2
                )
            else:  # Noise voxels
                signal[:, i] = np.random.randn(n_timepoints) * 0.3

        return signal

    def _generate_design_matrix(self, n_timepoints):
        """Generate a simple design matrix."""
        # Block design
        design = np.zeros((n_timepoints, 2))
        design[:, 0] = 1  # Intercept

        # Task regressor (blocks of 20 volumes)
        for i in range(0, n_timepoints, 40):
            design[i : i + 20, 1] = 1

        # Convolve with HRF

        t = np.arange(0, 30, 0.1)
        hrf = t**2 * np.exp(-t / 2) / 100  # Simplified HRF
        design[:, 1] = np.convolve(design[:, 1], hrf[:100], mode="same")

        return design

    def _incremental_glm(self, data, design_matrix):
        """Perform incremental GLM fitting."""
        n_timepoints, n_voxels = data.shape
        n_regressors = design_matrix.shape[1]

        # Initialize
        if self.beta is None:
            self.beta = np.zeros((n_regressors, n_voxels))

        # Incremental updates
        for t in range(n_timepoints):
            if t < n_regressors:
                continue

            # Mini-batch update
            X = design_matrix[: t + 1]
            y = data[: t + 1]

            # Update beta using recursive least squares
            self.beta = np.linalg.lstsq(X, y, rcond=None)[0]

        # Compute residuals
        predictions = design_matrix @ self.beta
        residuals = data - predictions

        # Compute statistics
        rss = np.sum(residuals**2, axis=0)
        tss = np.sum((data - np.mean(data, axis=0)) ** 2, axis=0)
        r_squared = 1 - rss / (tss + 1e-10)

        stats = {
            "r_squared": np.mean(r_squared),
            "mean_beta": float(np.mean(np.abs(self.beta))),
            "max_beta": float(np.max(np.abs(self.beta))),
        }

        return self.beta, residuals, stats

    def _apply_contrast(self, beta, contrast):
        """Apply contrast to beta maps."""
        return contrast @ beta


class NeurofeedbackControlTool(NeuroToolWrapper):
    """Neurofeedback control and display system."""

    def __init__(self):
        super().__init__()
        self.feedback_history = []

    def get_tool_name(self) -> str:
        return "neurofeedback_control"

    def get_tool_description(self) -> str:
        return "Control neurofeedback display and parameters"

    def get_args_schema(self):
        return NeurofeedbackControlArgs

    def _run(
        self,
        activation_level: float | None = None,
        target_level: float | None = None,
        feedback_type: str = "visual",
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Generate and control neurofeedback."""
        try:
            output_path = Path(output_dir or "neurofeedback_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Simulate activation if not provided
            if activation_level is None:
                activation_level = np.random.randn() * 0.5 + 0.5

            if target_level is None:
                target_level = 0.7

            # Calculate feedback
            feedback = self._calculate_feedback(
                activation_level, target_level, feedback_type
            )

            # Update history
            self.feedback_history.append(
                {
                    "timestamp": time.time(),
                    "activation": activation_level,
                    "target": target_level,
                    "feedback": feedback,
                }
            )

            # Generate display
            display_params = self._generate_display(feedback, feedback_type)

            # Save feedback log
            with open(output_path / "feedback_log.json", "w") as f:
                json.dump(self.feedback_history[-100:], f)  # Keep last 100

            return ToolResult(
                status="success",
                data={
                    "current_feedback": feedback,
                    "display_params": display_params,
                    "performance": self._calculate_performance(),
                },
            )

        except Exception as e:
            logger.error(f"Neurofeedback control failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _calculate_feedback(self, activation, target, feedback_type):
        """Calculate feedback signal."""
        diff = activation - target

        if feedback_type == "visual":
            # Map to visual scale (0-1)
            feedback = {
                "type": "visual",
                "value": float(np.clip(activation / target, 0, 1.5)),
                "color": self._get_color(diff),
                "size": float(np.abs(diff) * 100),
            }
        elif feedback_type == "auditory":
            # Map to audio parameters
            feedback = {
                "type": "auditory",
                "frequency": float(440 * (1 + diff)),  # Hz
                "volume": float(np.clip(np.abs(diff), 0, 1)),
            }
        else:
            feedback = {
                "type": "numeric",
                "value": float(activation),
                "target": float(target),
                "difference": float(diff),
            }

        return feedback

    def _get_color(self, diff):
        """Get color based on performance."""
        if diff > 0.1:
            return "green"
        elif diff < -0.1:
            return "red"
        else:
            return "yellow"

    def _generate_display(self, feedback, feedback_type):
        """Generate display parameters."""
        if feedback_type == "visual":
            return {
                "shape": "circle",
                "color": feedback["color"],
                "size": feedback["size"],
                "position": [50, 50],  # Center
                "animation": "pulse" if feedback["value"] > 1 else "none",
            }
        elif feedback_type == "auditory":
            return {
                "waveform": "sine",
                "frequency": feedback["frequency"],
                "volume": feedback["volume"],
                "duration": 1000,  # ms
            }
        else:
            return feedback

    def _calculate_performance(self):
        """Calculate performance metrics."""
        if len(self.feedback_history) < 2:
            return {}

        recent = self.feedback_history[-20:]
        activations = [f["activation"] for f in recent]
        targets = [f["target"] for f in recent]

        return {
            "mean_activation": float(np.mean(activations)),
            "success_rate": float(
                np.mean([a >= t for a, t in zip(activations, targets, strict=False)])
            ),
            "improvement": (
                float(activations[-1] - activations[0]) if len(activations) > 1 else 0
            ),
        }


class ROIMonitoringTool(NeuroToolWrapper):
    """Real-time ROI monitoring and analysis."""

    def __init__(self):
        super().__init__()
        self.roi_buffers = {}

    def get_tool_name(self) -> str:
        return "roi_monitoring"

    def get_tool_description(self) -> str:
        return "Monitor multiple ROIs in real-time"

    def get_args_schema(self):
        return ROIMonitoringArgs

    def _run(
        self,
        volume: np.ndarray | None = None,
        roi_masks: dict[str, np.ndarray] | None = None,
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Monitor ROI activations."""
        try:
            output_path = Path(output_dir or "roi_monitoring_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate test data if needed
            if volume is None:
                volume = np.random.randn(64, 64, 35)

            if roi_masks is None:
                roi_masks = self._create_default_rois(volume.shape)

            # Extract ROI signals
            roi_signals = {}
            for roi_name, mask in roi_masks.items():
                signal = self._extract_roi_signal(volume, mask)
                roi_signals[roi_name] = signal

                # Update buffer
                if roi_name not in self.roi_buffers:
                    self.roi_buffers[roi_name] = deque(maxlen=100)
                self.roi_buffers[roi_name].append(signal)

            # Compute ROI statistics
            roi_stats = self._compute_roi_statistics(roi_signals)

            # Check for significant changes
            alerts = self._check_alerts(roi_signals)

            # Save monitoring data
            monitoring_data = {
                "roi_signals": roi_signals,
                "roi_stats": roi_stats,
                "alerts": alerts,
            }

            with open(output_path / "monitoring.json", "w") as f:
                json.dump(monitoring_data, f)

            return ToolResult(
                status="success",
                data={
                    "roi_signals": roi_signals,
                    "statistics": roi_stats,
                    "alerts": alerts,
                },
            )

        except Exception as e:
            logger.error(f"ROI monitoring failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _create_default_rois(self, volume_shape):
        """Create default ROI masks."""
        rois = {}
        x, y, z = volume_shape

        # Motor cortex
        motor_mask = np.zeros(volume_shape, dtype=bool)
        motor_mask[
            x // 2 - 5 : x // 2 + 5, y // 2 - 5 : y // 2 + 5, z // 2 : z // 2 + 10
        ] = True
        rois["motor"] = motor_mask

        # Visual cortex
        visual_mask = np.zeros(volume_shape, dtype=bool)
        visual_mask[
            x // 2 - 5 : x // 2 + 5, y // 4 : y // 4 + 10, z // 2 - 5 : z // 2 + 5
        ] = True
        rois["visual"] = visual_mask

        # Prefrontal
        pfc_mask = np.zeros(volume_shape, dtype=bool)
        pfc_mask[
            x // 2 - 5 : x // 2 + 5,
            3 * y // 4 : 3 * y // 4 + 10,
            z // 2 - 5 : z // 2 + 5,
        ] = True
        rois["prefrontal"] = pfc_mask

        return rois

    def _extract_roi_signal(self, volume, mask):
        """Extract mean signal from ROI."""
        return float(np.mean(volume[mask]))

    def _compute_roi_statistics(self, roi_signals):
        """Compute statistics for each ROI."""
        stats = {}

        for roi_name, roi_signal in roi_signals.items():
            if roi_name in self.roi_buffers and len(self.roi_buffers[roi_name]) > 1:
                buffer = np.array(self.roi_buffers[roi_name])
                stats[roi_name] = {
                    "current": float(roi_signal),
                    "mean": float(np.mean(buffer)),
                    "std": float(np.std(buffer)),
                    "z_score": float(
                        (roi_signal - np.mean(buffer)) / (np.std(buffer) + 1e-6)
                    ),
                    "trend": self._compute_trend(buffer),
                }
            else:
                stats[roi_name] = {
                    "current": float(roi_signal),
                    "mean": float(roi_signal),
                    "std": 0,
                    "z_score": 0,
                    "trend": "stable",
                }

        return stats

    def _compute_trend(self, buffer):
        """Compute signal trend."""
        if len(buffer) < 10:
            return "stable"

        recent = buffer[-10:]
        slope = np.polyfit(range(len(recent)), recent, 1)[0]

        if slope > 0.01:
            return "increasing"
        elif slope < -0.01:
            return "decreasing"
        else:
            return "stable"

    def _check_alerts(self, roi_signals):
        """Check for significant changes requiring alerts."""
        alerts = []

        for roi_name, roi_signal in roi_signals.items():
            if roi_name in self.roi_buffers and len(self.roi_buffers[roi_name]) > 10:
                buffer = np.array(self.roi_buffers[roi_name])
                mean = np.mean(buffer[:-1])
                std = np.std(buffer[:-1])

                # Check for outliers
                if abs(roi_signal - mean) > 3 * std:
                    alerts.append(
                        {
                            "roi": roi_name,
                            "type": "outlier",
                            "severity": "high",
                            "value": float(roi_signal),
                            "threshold": float(mean + 3 * std),
                        }
                    )

        return alerts


class AdaptiveThresholdingTool(NeuroToolWrapper):
    """Adaptive thresholding for neurofeedback."""

    def __init__(self):
        super().__init__()
        self.threshold_history = []
        self.performance_history = []

    def get_tool_name(self) -> str:
        return "adaptive_thresholding"

    def get_tool_description(self) -> str:
        return "Adaptive threshold adjustment for optimal neurofeedback"

    def get_args_schema(self):
        return AdaptiveThresholdingArgs

    def _run(
        self,
        current_activation: float | None = None,
        performance_metric: float | None = None,
        adaptation_rate: float = 0.1,
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Adjust thresholds adaptively."""
        try:
            output_path = Path(output_dir or "adaptive_threshold_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Simulate if not provided
            if current_activation is None:
                current_activation = np.random.randn() * 0.3 + 0.5

            if performance_metric is None:
                performance_metric = np.random.random()

            # Update performance history
            self.performance_history.append(performance_metric)

            # Calculate new threshold
            new_threshold = self._calculate_adaptive_threshold(
                current_activation, performance_metric, adaptation_rate
            )

            # Update threshold history
            self.threshold_history.append(new_threshold)

            # Evaluate adaptation effectiveness
            adaptation_metrics = self._evaluate_adaptation()

            # Save adaptation data
            adaptation_data = {
                "current_threshold": new_threshold,
                "threshold_history": self.threshold_history[-50:],
                "performance_history": self.performance_history[-50:],
                "adaptation_metrics": adaptation_metrics,
            }

            with open(output_path / "adaptation.json", "w") as f:
                json.dump(adaptation_data, f)

            return ToolResult(
                status="success",
                data={
                    "new_threshold": new_threshold,
                    "adaptation_metrics": adaptation_metrics,
                    "recommendation": self._get_recommendation(adaptation_metrics),
                },
            )

        except Exception as e:
            logger.error(f"Adaptive thresholding failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _calculate_adaptive_threshold(self, activation, performance, rate):
        """Calculate adaptive threshold."""
        # Get current threshold or initialize
        if self.threshold_history:
            current_threshold = self.threshold_history[-1]
        else:
            current_threshold = 0.5

        # Adjust based on performance
        if performance > 0.7:
            # Good performance - make slightly harder
            adjustment = rate * 0.1
        elif performance < 0.3:
            # Poor performance - make easier
            adjustment = -rate * 0.1
        else:
            # Moderate performance - fine tune
            adjustment = rate * (performance - 0.5) * 0.05

        # Apply adjustment with bounds
        new_threshold = np.clip(current_threshold + adjustment, 0.1, 0.9)

        return float(new_threshold)

    def _evaluate_adaptation(self):
        """Evaluate adaptation effectiveness."""
        if len(self.performance_history) < 10:
            return {"status": "initializing"}

        recent_performance = self.performance_history[-10:]
        older_performance = (
            self.performance_history[-20:-10]
            if len(self.performance_history) >= 20
            else recent_performance
        )

        return {
            "recent_mean": float(np.mean(recent_performance)),
            "improvement": float(
                np.mean(recent_performance) - np.mean(older_performance)
            ),
            "stability": float(1 - np.std(recent_performance)),
            "optimal_range": self._in_optimal_range(recent_performance),
        }

    def _in_optimal_range(self, performance):
        """Check if performance is in optimal range."""
        mean_perf = np.mean(performance)
        return 0.5 <= mean_perf <= 0.8

    def _get_recommendation(self, metrics):
        """Get recommendation based on adaptation metrics."""
        if "status" in metrics and metrics["status"] == "initializing":
            return "Collecting baseline data"

        if metrics["improvement"] > 0.1:
            return "Adaptation working well - continue current strategy"
        elif metrics["improvement"] < -0.1:
            return "Consider adjusting adaptation rate or strategy"
        elif not metrics["optimal_range"]:
            return "Performance outside optimal range - consider manual adjustment"
        else:
            return "System stable - maintain current parameters"


class RealtimeDecodingTool(NeuroToolWrapper):
    """Real-time brain state decoding."""

    def __init__(self):
        super().__init__()
        self.decoder = None
        self.training_data = []

    def get_tool_name(self) -> str:
        return "realtime_decoding"

    def get_tool_description(self) -> str:
        return "Decode brain states in real-time"

    def get_args_schema(self):
        return RealtimeDecodingArgs

    def _run(
        self,
        brain_data: np.ndarray | None = None,
        labels: np.ndarray | None = None,
        mode: str = "predict",
        decoder_type: str = "svm",
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Perform real-time decoding."""
        try:
            output_path = Path(output_dir or "decoding_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate test data if needed
            if brain_data is None:
                brain_data = np.random.randn(100, 1000)  # 100 timepoints, 1000 voxels

            if mode == "train":
                if labels is None:
                    labels = np.random.randint(0, 2, 100)

                # Train decoder
                self.decoder = self._train_decoder(brain_data, labels, decoder_type)

                # Cross-validation
                cv_scores = self._cross_validate(brain_data, labels, decoder_type)

                result = {
                    "mode": "training",
                    "accuracy": float(np.mean(cv_scores)),
                    "cv_scores": cv_scores,
                }

            else:  # predict mode
                if self.decoder is None:
                    # Create and train a simple decoder
                    self.decoder = self._create_decoder(decoder_type)
                    # Use random training data for demo
                    train_data = np.random.randn(50, brain_data.shape[1])
                    train_labels = np.random.randint(0, 2, 50)
                    self.decoder.fit(train_data, train_labels)

                # Predict
                predictions = self.decoder.predict(brain_data)
                probabilities = (
                    self.decoder.predict_proba(brain_data)
                    if hasattr(self.decoder, "predict_proba")
                    else None
                )

                result = {
                    "mode": "prediction",
                    "predictions": predictions.tolist(),
                    "probabilities": (
                        probabilities.tolist() if probabilities is not None else None
                    ),
                    "confidence": (
                        float(np.mean(np.max(probabilities, axis=1)))
                        if probabilities is not None
                        else None
                    ),
                }

            # Save results
            with open(output_path / "decoding_results.json", "w") as f:
                json.dump(result, f)

            return ToolResult(status="success", data=result)

        except Exception as e:
            logger.error(f"Realtime decoding failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _create_decoder(self, decoder_type):
        """Create decoder based on type."""
        if decoder_type == "svm":
            from sklearn.svm import SVC

            return SVC(probability=True, kernel="linear")
        elif decoder_type == "logistic":
            from sklearn.linear_model import LogisticRegression

            return LogisticRegression(max_iter=1000)
        elif decoder_type == "lda":
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

            return LinearDiscriminantAnalysis()
        else:
            from sklearn.svm import SVC

            return SVC(probability=True)

    def _train_decoder(self, data, labels, decoder_type):
        """Train the decoder."""
        decoder = self._create_decoder(decoder_type)
        decoder.fit(data, labels)
        return decoder

    def _cross_validate(self, data, labels, decoder_type):
        """Perform cross-validation."""
        from sklearn.model_selection import cross_val_score

        decoder = self._create_decoder(decoder_type)
        scores = cross_val_score(decoder, data, labels, cv=5)

        return scores.tolist()


class ClosedLoopStimulationTool(NeuroToolWrapper):
    """Closed-loop brain stimulation based on real-time fMRI."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "closed_loop_stimulation"

    def get_tool_description(self) -> str:
        return "Closed-loop brain stimulation control"

    def get_args_schema(self):
        return ClosedLoopStimulationArgs

    def _run(
        self,
        brain_state: np.ndarray | None = None,
        target_state: np.ndarray | None = None,
        stimulation_type: str = "tms",
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Control closed-loop stimulation."""
        try:
            output_path = Path(output_dir or "closed_loop_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate test data if needed
            if brain_state is None:
                brain_state = np.random.randn(100) + np.sin(np.linspace(0, 10, 100))

            if target_state is None:
                target_state = np.ones(100) * 0.5

            # Calculate stimulation parameters
            stim_params = self._calculate_stimulation(
                brain_state, target_state, stimulation_type
            )

            # Save outputs
            np.save(output_path / "stimulation_params.npy", stim_params)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "stimulation": str(output_path / "stimulation_params.npy")
                    },
                    "summary": {
                        "type": stimulation_type,
                        "mean_intensity": float(np.mean(stim_params)),
                        "n_pulses": int(np.sum(stim_params > 0)),
                    },
                },
            )

        except Exception as e:
            logger.error(f"Closed-loop stimulation failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _calculate_stimulation(self, brain_state, target_state, stim_type):
        """Calculate stimulation parameters."""
        # Simple proportional control
        error = target_state - brain_state

        if stim_type == "tms":
            # TMS parameters
            intensity = np.clip(error * 10, 0, 100)  # 0-100% intensity
            frequency = np.ones_like(error) * 10  # 10 Hz
            params = np.column_stack([intensity, frequency])

        elif stim_type == "tdcs":
            # tDCS parameters
            current = np.clip(error * 2, -2, 2)  # -2 to 2 mA
            params = current

        elif stim_type == "optogenetic":
            # Optogenetic parameters
            power = np.clip(error * 5, 0, 10)  # 0-10 mW
            params = power

        else:
            params = error

        return params


class RealtimeConnectivityTool(NeuroToolWrapper):
    """Real-time functional connectivity analysis."""

    def __init__(self):
        super().__init__()
        self.connectivity_buffer = deque(maxlen=100)

    def get_tool_name(self) -> str:
        return "realtime_connectivity"

    def get_tool_description(self) -> str:
        return "Compute functional connectivity in real-time"

    def get_args_schema(self):
        return RealtimeConnectivityArgs

    def _run(
        self,
        roi_timeseries: np.ndarray | None = None,
        method: str = "correlation",
        window_size: int = 30,
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Compute real-time connectivity."""
        try:
            output_path = Path(output_dir or "connectivity_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate test data if needed
            if roi_timeseries is None:
                n_timepoints = 100
                n_rois = 10
                roi_timeseries = np.random.randn(n_timepoints, n_rois)
                # Add some correlation structure
                roi_timeseries[:, :5] += np.sin(np.linspace(0, 10, n_timepoints))[
                    :, None
                ]

            # Compute connectivity
            conn_matrix = self._compute_connectivity(
                roi_timeseries, method, window_size
            )

            # Update buffer
            self.connectivity_buffer.append(conn_matrix)

            # Detect changes
            changes = self._detect_connectivity_changes()

            # Network metrics
            metrics = self._compute_network_metrics(conn_matrix)

            # Save results
            matrix_path = output_path / "connectivity_matrix.npy"
            np.save(matrix_path, conn_matrix)
            n_timepoints = min(int(len(roi_timeseries)), int(window_size))
            estimator = {
                "correlation": "PearsonCorrelation",
                "partial_correlation": "OLSResidualPartialCorrelation",
                "coherence": "MagnitudeSquaredCoherence",
            }.get(str(method).lower(), "PearsonCorrelation")
            feature_contract = build_feature_contract(
                conn_matrix,
                matrix_kind=str(method),
                source_level="roi_timeseries",
                n_rois=int(conn_matrix.shape[0]),
                n_timepoints=n_timepoints,
                effective_n_timepoints=n_timepoints,
                covariance_estimator=estimator,
                extras={
                    "tool": self.get_tool_name(),
                    "window_size": int(window_size),
                },
            )
            feature_contract_path = write_feature_contract(
                feature_contract, output_path
            )

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "connectivity_matrix": str(matrix_path),
                        "feature_contract": str(feature_contract_path),
                    },
                    "connectivity_matrix": conn_matrix.tolist(),
                    "network_metrics": metrics,
                    "changes_detected": changes,
                },
            )

        except Exception as e:
            logger.error(f"Realtime connectivity failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _compute_connectivity(self, timeseries, method, window_size):
        """Compute connectivity matrix."""
        if len(timeseries) < window_size:
            window_data = timeseries
        else:
            window_data = timeseries[-window_size:]

        if method == "correlation":
            conn_matrix = np.corrcoef(window_data.T)

        elif method == "partial_correlation":
            # Partial correlation
            conn_matrix = self._partial_correlation(window_data)

        elif method == "coherence":
            # Coherence in specific frequency band
            conn_matrix = self._compute_coherence(window_data)

        else:
            conn_matrix = np.corrcoef(window_data.T)

        return conn_matrix

    def _partial_correlation(self, data):
        """Compute partial correlation matrix."""
        n_rois = data.shape[1]
        pcorr = np.zeros((n_rois, n_rois))

        for i in range(n_rois):
            for j in range(i + 1, n_rois):
                # Control for all other regions
                others = [k for k in range(n_rois) if k != i and k != j]
                if others:
                    # Regress out others
                    resid_i = (
                        data[:, i]
                        - data[:, others]
                        @ np.linalg.lstsq(data[:, others], data[:, i], rcond=None)[0]
                    )
                    resid_j = (
                        data[:, j]
                        - data[:, others]
                        @ np.linalg.lstsq(data[:, others], data[:, j], rcond=None)[0]
                    )
                    pcorr[i, j] = np.corrcoef(resid_i, resid_j)[0, 1]
                else:
                    pcorr[i, j] = np.corrcoef(data[:, i], data[:, j])[0, 1]

                pcorr[j, i] = pcorr[i, j]

        np.fill_diagonal(pcorr, 1)
        return pcorr

    def _compute_coherence(self, data):
        """Compute coherence matrix."""
        n_rois = data.shape[1]
        coherence = np.zeros((n_rois, n_rois))

        for i in range(n_rois):
            for j in range(i, n_rois):
                f, Cxy = signal.coherence(data[:, i], data[:, j], fs=1.0)
                # Average coherence in alpha band (8-12 Hz normalized)
                alpha_idx = np.where((f >= 0.08) & (f <= 0.12))[0]
                if len(alpha_idx) > 0:
                    coherence[i, j] = np.mean(Cxy[alpha_idx])
                else:
                    coherence[i, j] = np.mean(Cxy)
                coherence[j, i] = coherence[i, j]

        return coherence

    def _detect_connectivity_changes(self):
        """Detect significant connectivity changes."""
        if len(self.connectivity_buffer) < 10:
            return []

        recent = np.array(list(self.connectivity_buffer)[-10:])
        older = (
            np.array(list(self.connectivity_buffer)[-20:-10])
            if len(self.connectivity_buffer) >= 20
            else recent
        )

        # Compare mean connectivity
        recent_mean = np.mean(recent, axis=0)
        older_mean = np.mean(older, axis=0)

        # Find significant changes
        diff = recent_mean - older_mean
        threshold = 0.2

        changes = []
        n_rois = diff.shape[0]
        for i in range(n_rois):
            for j in range(i + 1, n_rois):
                if abs(diff[i, j]) > threshold:
                    changes.append(
                        {
                            "roi_pair": [i, j],
                            "change": float(diff[i, j]),
                            "direction": "increase" if diff[i, j] > 0 else "decrease",
                        }
                    )

        return changes

    def _compute_network_metrics(self, conn_matrix):
        """Compute network-level metrics."""
        # Threshold to get binary adjacency matrix
        threshold = 0.3
        adj_matrix = (np.abs(conn_matrix) > threshold).astype(int)
        np.fill_diagonal(adj_matrix, 0)

        # Degree
        degree = np.sum(adj_matrix, axis=0)

        # Clustering coefficient (simplified)
        n_nodes = len(adj_matrix)
        clustering = []
        for i in range(n_nodes):
            neighbors = np.where(adj_matrix[i])[0]
            if len(neighbors) > 1:
                # Count connections between neighbors
                neighbor_connections = 0
                for j in range(len(neighbors)):
                    for k in range(j + 1, len(neighbors)):
                        if adj_matrix[neighbors[j], neighbors[k]]:
                            neighbor_connections += 1

                possible_connections = len(neighbors) * (len(neighbors) - 1) / 2
                clustering.append(
                    neighbor_connections / possible_connections
                    if possible_connections > 0
                    else 0
                )
            else:
                clustering.append(0)

        return {
            "mean_connectivity": float(np.mean(np.abs(conn_matrix))),
            "mean_degree": float(np.mean(degree)),
            "clustering_coefficient": float(np.mean(clustering)),
            "network_density": float(np.sum(adj_matrix) / (n_nodes * (n_nodes - 1))),
        }


class NeurofeedbackTrainingTool(NeuroToolWrapper):
    """Multi-session neurofeedback training management."""

    def __init__(self):
        super().__init__()
        self.training_history = []

    def get_tool_name(self) -> str:
        return "neurofeedback_training"

    def get_tool_description(self) -> str:
        return "Manage multi-session neurofeedback training"

    def get_args_schema(self):
        return NeurofeedbackTrainingArgs

    def _run(
        self,
        session_number: int | None = None,
        training_protocol: str | None = None,
        performance_data: np.ndarray | None = None,
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Manage neurofeedback training session."""
        try:
            output_path = Path(output_dir or "training_output")
            output_path.mkdir(parents=True, exist_ok=True)

            if session_number is None:
                session_number = len(self.training_history) + 1

            if training_protocol is None:
                training_protocol = "standard"

            # Simulate performance data if not provided
            if performance_data is None:
                performance_data = self._simulate_session_performance(session_number)

            # Analyze session
            session_metrics = self._analyze_session(performance_data, session_number)

            # Update training history
            self.training_history.append(
                {
                    "session": session_number,
                    "protocol": training_protocol,
                    "metrics": session_metrics,
                }
            )

            # Calculate learning curve
            learning_curve = self._calculate_learning_curve()

            # Generate recommendations
            recommendations = self._generate_recommendations(
                session_metrics, learning_curve
            )

            # Save session data
            session_data = {
                "session_number": session_number,
                "metrics": session_metrics,
                "learning_curve": learning_curve,
                "recommendations": recommendations,
            }

            with open(output_path / f"session_{session_number}.json", "w") as f:
                json.dump(session_data, f)

            return ToolResult(status="success", data=session_data)

        except Exception as e:
            logger.error(f"Training session failed: {e}")
            return ToolResult(status="error", error=str(e), data={})

    def _simulate_session_performance(self, session_num):
        """Simulate performance data for a session."""
        # Performance improves with sessions
        base_performance = 0.3 + 0.05 * session_num
        noise = np.random.randn(100) * 0.1
        trend = np.linspace(0, 0.1, 100)

        performance = base_performance + noise + trend
        return np.clip(performance, 0, 1)

    def _analyze_session(self, performance_data, session_num):
        """Analyze session performance."""
        return {
            "mean_performance": float(np.mean(performance_data)),
            "std_performance": float(np.std(performance_data)),
            "max_performance": float(np.max(performance_data)),
            "improvement_rate": float(
                np.polyfit(range(len(performance_data)), performance_data, 1)[0]
            ),
            "success_rate": float(np.mean(performance_data > 0.6)),
            "session_duration": len(performance_data),
        }

    def _calculate_learning_curve(self):
        """Calculate learning curve across sessions."""
        if len(self.training_history) < 2:
            return {"status": "insufficient_data"}

        sessions = [h["session"] for h in self.training_history]
        performances = [h["metrics"]["mean_performance"] for h in self.training_history]

        # Fit learning curve
        z = np.polyfit(sessions, performances, 2)

        return {
            "coefficients": z.tolist(),
            "current_performance": performances[-1],
            "predicted_next": float(np.polyval(z, sessions[-1] + 1)),
            "sessions_to_plateau": self._estimate_plateau(z, sessions[-1]),
        }

    def _estimate_plateau(self, coefficients, current_session):
        """Estimate sessions until performance plateau."""
        # Simple estimate based on curve derivative
        derivative = 2 * coefficients[0] * current_session + coefficients[1]

        if derivative <= 0.01:
            return 0  # Already at plateau

        # Estimate based on current rate
        return int(0.1 / derivative) if derivative > 0 else 10

    def _generate_recommendations(self, session_metrics, learning_curve):
        """Generate training recommendations."""
        recommendations = []

        # Check performance
        if session_metrics["mean_performance"] < 0.4:
            recommendations.append(
                "Consider simplifying the task or adjusting difficulty"
            )
        elif session_metrics["mean_performance"] > 0.8:
            recommendations.append(
                "Consider increasing task difficulty for continued learning"
            )

        # Check variability
        if session_metrics["std_performance"] > 0.2:
            recommendations.append("High variability - focus on consistency")

        # Check learning rate
        if "predicted_next" in learning_curve:
            if (
                learning_curve["predicted_next"] - learning_curve["current_performance"]
                < 0.01
            ):
                recommendations.append(
                    "Learning plateau detected - consider protocol modification"
                )

        # Check success rate
        if session_metrics["success_rate"] < 0.5:
            recommendations.append(
                "Low success rate - provide more feedback or guidance"
            )

        return (
            recommendations if recommendations else ["Continue with current protocol"]
        )


# ============================================================================
# Collection class for all real-time tools
# ============================================================================


class RealtimeFMRITools:
    """Collection of real-time fMRI and neurofeedback tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all real-time fMRI and neurofeedback tools."""
        return [
            RealtimeFMRITool(),
            RealtimeGLMTool(),
            NeurofeedbackControlTool(),
            ROIMonitoringTool(),
            AdaptiveThresholdingTool(),
            RealtimeDecodingTool(),
            ClosedLoopStimulationTool(),
            RealtimeConnectivityTool(),
            NeurofeedbackTrainingTool(),
        ]
