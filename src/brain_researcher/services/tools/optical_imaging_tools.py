"""Optical imaging analysis tools for neuroscience research."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal, stats, ndimage
from scipy.optimize import curve_fit

from brain_researcher.core.package_resolver import PackageResolver
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class OpticalInput(BaseModel):
    """Input schema for optical imaging tools."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    imaging_data: Optional[np.ndarray] = Field(None, description="Optical imaging data (e.g., calcium imaging)")
    time_series: Optional[np.ndarray] = Field(None, description="Time series data")
    sampling_rate: Optional[float] = Field(None, description="Sampling rate in Hz")
    roi_masks: Optional[np.ndarray] = Field(None, description="ROI masks for analysis")
    wavelengths: Optional[List[float]] = Field(None, description="Wavelengths for spectral imaging")
    output_dir: Optional[str] = Field(None, description="Output directory for results")


class CalciumImagingAnalysisTool(NeuroToolWrapper):
    """Analyze calcium imaging data for neural activity."""

    def __init__(self):
        super().__init__()
        self.resolver = PackageResolver()

    def get_tool_name(self) -> str:
        return "calcium_imaging_analysis"

    def get_tool_description(self) -> str:
        return "Process and analyze calcium imaging data including spike detection and network dynamics"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        sampling_rate: float = 30.0,  # Hz
        roi_masks: Optional[np.ndarray] = None,
        spike_detection_method: str = "deconvolution",  # or "threshold"
        baseline_correction: bool = True,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze calcium imaging data."""
        try:
            output_path = Path(output_dir or "calcium_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data, rois = self._generate_synthetic_calcium_data()
            else:
                data = imaging_data
                rois = roi_masks if roi_masks is not None else self._auto_detect_rois(data)

            # Extract time series from ROIs
            time_series = self._extract_roi_time_series(data, rois)

            # Baseline correction
            if baseline_correction:
                time_series = self._correct_baseline(time_series)

            # Calculate ΔF/F
            df_f = self._calculate_df_f(time_series)

            # Detect spikes/events
            if spike_detection_method == "deconvolution":
                spikes = self._deconvolve_spikes(df_f, sampling_rate)
            else:
                spikes = self._threshold_detection(df_f)

            # Calculate activity metrics
            metrics = self._calculate_activity_metrics(df_f, spikes, sampling_rate)

            # Network analysis
            network = self._analyze_network_activity(df_f, spikes)

            # Detect events
            events = self._detect_population_events(spikes, sampling_rate)

            # Save results
            results = {
                'n_rois': len(rois),
                'sampling_rate': sampling_rate,
                'recording_duration': float(len(df_f[0]) / sampling_rate),
                'activity_metrics': metrics,
                'network_analysis': network,
                'population_events': events,
                'processing_parameters': {
                    'spike_detection': spike_detection_method,
                    'baseline_corrected': baseline_correction
                }
            }

            # Save processed data
            np.savez(
                output_path / "calcium_processed.npz",
                df_f=df_f,
                spikes=spikes,
                roi_masks=rois
            )

            with open(output_path / "calcium_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "calcium_processed.npz"),
                        "results": str(output_path / "calcium_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Calcium imaging analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_calcium_data(self) -> Tuple[np.ndarray, List[np.ndarray]]:
        """Generate synthetic calcium imaging data."""
        # Dimensions: x, y, time
        shape = (128, 128, 1000)
        data = np.random.randn(*shape) * 0.1

        # Add neurons with calcium transients
        n_neurons = 20
        rois = []

        for i in range(n_neurons):
            # Create circular ROI
            center = [np.random.randint(10, s-10) for s in shape[:2]]
            radius = np.random.randint(3, 7)

            y, x = np.ogrid[:shape[0], :shape[1]]
            mask = ((x - center[0])**2 + (y - center[1])**2) <= radius**2
            rois.append(mask)

            # Generate calcium transients
            n_spikes = np.random.randint(5, 20)
            spike_times = np.sort(np.random.randint(100, shape[2]-100, n_spikes))

            for spike_time in spike_times:
                # Calcium transient shape (exponential decay)
                duration = 50
                t = np.arange(duration)
                transient = 2 * np.exp(-t / 10)

                # Add to data
                end_time = min(spike_time + duration, shape[2])
                data[mask, spike_time:end_time] += transient[:end_time-spike_time]

        # Add noise
        data += np.random.randn(*shape) * 0.05

        return data, rois

    def _auto_detect_rois(self, data: np.ndarray) -> List[np.ndarray]:
        """Auto-detect ROIs from imaging data."""
        # Simplified ROI detection
        # In reality, would use more sophisticated methods

        # Use max projection and threshold
        max_proj = np.max(data, axis=2)

        # Threshold
        threshold = np.percentile(max_proj, 95)
        binary = max_proj > threshold

        # Find connected components
        from scipy.ndimage import label
        labeled, n_features = label(binary)

        rois = []
        for i in range(1, min(n_features + 1, 50)):  # Limit to 50 ROIs
            rois.append(labeled == i)

        return rois

    def _extract_roi_time_series(self, data: np.ndarray, rois: List[np.ndarray]) -> np.ndarray:
        """Extract time series from ROIs."""
        n_rois = len(rois)
        n_time = data.shape[2]
        time_series = np.zeros((n_rois, n_time))

        for i, roi in enumerate(rois):
            # Average signal within ROI
            time_series[i] = np.mean(data[roi], axis=0)

        return time_series

    def _correct_baseline(self, time_series: np.ndarray) -> np.ndarray:
        """Correct baseline drift."""
        corrected = np.zeros_like(time_series)

        for i in range(len(time_series)):
            # Estimate baseline using percentile filter
            from scipy.ndimage import percentile_filter
            baseline = percentile_filter(time_series[i], 20, size=300)
            corrected[i] = time_series[i] - baseline

        return corrected

    def _calculate_df_f(self, time_series: np.ndarray) -> np.ndarray:
        """Calculate ΔF/F."""
        df_f = np.zeros_like(time_series)

        for i in range(len(time_series)):
            # Baseline as lower percentile
            f0 = np.percentile(time_series[i], 10)
            df_f[i] = (time_series[i] - f0) / (f0 + 0.01)

        return df_f

    def _deconvolve_spikes(self, df_f: np.ndarray, sampling_rate: float) -> np.ndarray:
        """Deconvolve spikes from calcium signal."""
        # Simplified deconvolution
        spikes = np.zeros_like(df_f)

        for i in range(len(df_f)):
            # First derivative
            derivative = np.diff(df_f[i])
            derivative = np.concatenate([[0], derivative])

            # Threshold positive derivatives
            threshold = 3 * np.std(derivative[derivative < 0])  # Use negative for noise estimate
            spikes[i] = (derivative > threshold).astype(float)

            # Smooth spike train
            from scipy.ndimage import gaussian_filter1d
            spikes[i] = gaussian_filter1d(spikes[i], sigma=1)

        return spikes

    def _threshold_detection(self, df_f: np.ndarray) -> np.ndarray:
        """Simple threshold-based spike detection."""
        spikes = np.zeros_like(df_f)

        for i in range(len(df_f)):
            # Threshold at 2.5 standard deviations
            threshold = np.mean(df_f[i]) + 2.5 * np.std(df_f[i])
            spikes[i] = (df_f[i] > threshold).astype(float)

        return spikes

    def _calculate_activity_metrics(self, df_f: np.ndarray, spikes: np.ndarray,
                                   sampling_rate: float) -> Dict[str, Any]:
        """Calculate activity metrics."""
        metrics = {}

        # Per-neuron metrics
        firing_rates = np.sum(spikes, axis=1) / (len(spikes[0]) / sampling_rate)

        metrics['mean_firing_rate'] = float(np.mean(firing_rates))
        metrics['std_firing_rate'] = float(np.std(firing_rates))
        metrics['max_firing_rate'] = float(np.max(firing_rates))

        # Activity levels
        mean_df_f = np.mean(np.abs(df_f), axis=1)
        metrics['mean_activity'] = float(np.mean(mean_df_f))
        metrics['activity_variance'] = float(np.var(mean_df_f))

        # Burst analysis
        burst_counts = []
        for spike_train in spikes:
            # Detect bursts (consecutive spikes)
            diff = np.diff(np.where(spike_train > 0.5)[0])
            bursts = np.sum(diff == 1)
            burst_counts.append(bursts)

        metrics['mean_burst_count'] = float(np.mean(burst_counts))

        return metrics

    def _analyze_network_activity(self, df_f: np.ndarray, spikes: np.ndarray) -> Dict[str, Any]:
        """Analyze network-level activity."""
        # Correlation analysis
        correlation_matrix = np.corrcoef(df_f)

        # Remove diagonal
        np.fill_diagonal(correlation_matrix, 0)

        # Synchrony index
        mean_correlation = np.mean(np.abs(correlation_matrix))

        # Clustering coefficient (simplified)
        threshold = 0.3
        adjacency = (correlation_matrix > threshold).astype(int)

        clustering_coeffs = []
        for i in range(len(adjacency)):
            neighbors = np.where(adjacency[i])[0]
            if len(neighbors) > 1:
                # Count connections between neighbors
                subgraph = adjacency[np.ix_(neighbors, neighbors)]
                possible = len(neighbors) * (len(neighbors) - 1) / 2
                actual = np.sum(subgraph) / 2
                clustering_coeffs.append(actual / possible if possible > 0 else 0)
            else:
                clustering_coeffs.append(0)

        # Modularity (simplified community detection)
        n_communities = self._detect_communities(correlation_matrix)

        return {
            'mean_correlation': float(mean_correlation),
            'network_clustering': float(np.mean(clustering_coeffs)),
            'n_communities': int(n_communities),
            'synchrony_index': float(mean_correlation),
            'max_correlation': float(np.max(correlation_matrix))
        }

    def _detect_communities(self, correlation_matrix: np.ndarray) -> int:
        """Detect communities in correlation network."""
        # Simplified community detection using clustering
        from scipy.cluster.hierarchy import linkage, fcluster

        # Convert correlation to distance
        distance = 1 - np.abs(correlation_matrix)

        # Hierarchical clustering
        condensed = distance[np.triu_indices(len(distance), k=1)]
        Z = linkage(condensed, method='average')

        # Cut tree to get communities
        communities = fcluster(Z, t=0.7, criterion='distance')

        return len(np.unique(communities))

    def _detect_population_events(self, spikes: np.ndarray, sampling_rate: float) -> Dict[str, Any]:
        """Detect population-wide events."""
        # Sum activity across neurons
        population_activity = np.sum(spikes, axis=0)

        # Detect peaks
        threshold = np.mean(population_activity) + 2 * np.std(population_activity)

        from scipy.signal import find_peaks
        peaks, properties = find_peaks(population_activity, height=threshold, distance=int(sampling_rate))

        # Calculate event properties
        if len(peaks) > 0:
            event_rate = len(peaks) / (len(population_activity) / sampling_rate)
            mean_amplitude = np.mean(properties['peak_heights'])

            # Inter-event intervals
            if len(peaks) > 1:
                intervals = np.diff(peaks) / sampling_rate
                mean_interval = np.mean(intervals)
            else:
                mean_interval = 0
        else:
            event_rate = 0
            mean_amplitude = 0
            mean_interval = 0

        return {
            'n_events': len(peaks),
            'event_rate_hz': float(event_rate),
            'mean_amplitude': float(mean_amplitude),
            'mean_interval_s': float(mean_interval),
            'event_times': peaks.tolist() if len(peaks) > 0 else []
        }


class IntrinsicSignalImagingTool(NeuroToolWrapper):
    """Analyze intrinsic signal optical imaging data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "intrinsic_signal_imaging"

    def get_tool_description(self) -> str:
        return "Process intrinsic signal optical imaging for hemodynamic responses"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        wavelengths: Optional[List[float]] = None,
        stimulus_times: Optional[List[float]] = None,
        sampling_rate: float = 10.0,  # Hz
        analysis_type: str = "reflectance",  # or "oxygenation"
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze intrinsic signal imaging."""
        try:
            output_path = Path(output_dir or "intrinsic_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data, stim_times = self._generate_synthetic_intrinsic_data()
            else:
                data = imaging_data
                stim_times = stimulus_times if stimulus_times else []

            # Set wavelengths
            if wavelengths is None:
                wavelengths = [530, 610]  # Green and red light

            # Process based on analysis type
            if analysis_type == "oxygenation" and len(wavelengths) >= 2:
                results_data = self._analyze_oxygenation(data, wavelengths)
            else:
                results_data = self._analyze_reflectance(data)

            # Detect activated regions
            activation_map = self._detect_activation(results_data, stim_times, sampling_rate)

            # Calculate hemodynamic response
            hrf = self._calculate_hemodynamic_response(results_data, stim_times, sampling_rate)

            # Spatial analysis
            spatial_metrics = self._analyze_spatial_patterns(activation_map)

            # Temporal analysis
            temporal_metrics = self._analyze_temporal_dynamics(results_data, sampling_rate)

            results = {
                'analysis_type': analysis_type,
                'wavelengths': wavelengths,
                'sampling_rate': sampling_rate,
                'n_stimuli': len(stim_times),
                'hemodynamic_response': hrf,
                'spatial_metrics': spatial_metrics,
                'temporal_metrics': temporal_metrics,
                'activation_statistics': {
                    'activated_area': float(np.sum(activation_map > 0)),
                    'max_activation': float(np.max(activation_map)),
                    'mean_activation': float(np.mean(activation_map[activation_map > 0]))
                    if np.any(activation_map > 0) else 0
                }
            }

            # Save results
            np.savez(
                output_path / "intrinsic_processed.npz",
                processed_data=results_data,
                activation_map=activation_map
            )

            with open(output_path / "intrinsic_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "intrinsic_processed.npz"),
                        "results": str(output_path / "intrinsic_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Intrinsic signal imaging failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_intrinsic_data(self) -> Tuple[np.ndarray, List[float]]:
        """Generate synthetic intrinsic signal data."""
        # Dimensions: x, y, time, wavelength
        shape = (64, 64, 500, 2)
        data = np.ones(shape)

        # Add baseline fluctuations
        data += np.random.randn(*shape) * 0.001

        # Add stimulus responses
        stim_times = [100, 200, 300, 400]  # Frame numbers

        for stim_time in stim_times:
            # Create activation region
            center = [32 + np.random.randint(-10, 10), 32 + np.random.randint(-10, 10)]

            y, x = np.ogrid[:shape[0], :shape[1]]
            mask = ((x - center[0])**2 + (y - center[1])**2) <= 15**2

            # Hemodynamic response
            response_duration = 100
            t = np.arange(response_duration)

            # Different response for different wavelengths
            # 530nm (green) - sensitive to total hemoglobin
            hrf_530 = -0.02 * np.exp(-t / 20) * (1 - np.exp(-t / 5))

            # 610nm (red) - sensitive to deoxyhemoglobin
            hrf_610 = -0.015 * np.exp(-t / 25) * (1 - np.exp(-t / 7))

            end_time = min(stim_time + response_duration, shape[2])

            # Apply response
            for t_idx in range(stim_time, end_time):
                rel_t = t_idx - stim_time
                data[mask, t_idx, 0] *= (1 + hrf_530[rel_t])
                data[mask, t_idx, 1] *= (1 + hrf_610[rel_t])

        return data, stim_times

    def _analyze_reflectance(self, data: np.ndarray) -> np.ndarray:
        """Analyze reflectance changes."""
        # Calculate ΔR/R
        if len(data.shape) == 4:
            # Multiple wavelengths - use first
            data = data[:, :, :, 0]

        # Baseline as mean of first frames
        baseline = np.mean(data[:, :, :50], axis=2, keepdims=True)

        # Calculate relative change
        delta_r = (data - baseline) / (baseline + 0.0001)

        return delta_r

    def _analyze_oxygenation(self, data: np.ndarray, wavelengths: List[float]) -> np.ndarray:
        """Analyze oxygenation changes from multi-wavelength data."""
        # Simplified oxygenation calculation
        # In reality, would use modified Beer-Lambert law

        # Assume data has at least 2 wavelengths
        r_530 = data[:, :, :, 0]  # Green
        r_610 = data[:, :, :, 1]  # Red

        # Baseline
        baseline_530 = np.mean(r_530[:, :, :50], axis=2, keepdims=True)
        baseline_610 = np.mean(r_610[:, :, :50], axis=2, keepdims=True)

        # Optical density changes
        od_530 = -np.log(r_530 / (baseline_530 + 0.0001))
        od_610 = -np.log(r_610 / (baseline_610 + 0.0001))

        # Simplified HbO2 calculation
        # Coefficients would be wavelength-specific in reality
        hbo2 = 1.5 * od_530 - 0.5 * od_610

        return hbo2

    def _detect_activation(self, data: np.ndarray, stim_times: List[float],
                          sampling_rate: float) -> np.ndarray:
        """Detect activated regions."""
        if len(stim_times) == 0:
            # No stimuli - use variance
            activation_map = np.var(data, axis=2)
        else:
            # Average response to stimuli
            responses = []

            for stim_time in stim_times:
                stim_frame = int(stim_time)

                # Extract post-stimulus window
                window_duration = int(10 * sampling_rate)  # 10 seconds
                end_frame = min(stim_frame + window_duration, data.shape[2])

                # Baseline
                baseline = np.mean(data[:, :, max(0, stim_frame-50):stim_frame], axis=2)

                # Response
                response = np.mean(data[:, :, stim_frame:end_frame], axis=2)

                # Calculate change
                change = np.abs(response - baseline)
                responses.append(change)

            # Average across stimuli
            activation_map = np.mean(responses, axis=0)

        # Threshold
        threshold = np.mean(activation_map) + 2 * np.std(activation_map)
        activation_map[activation_map < threshold] = 0

        return activation_map

    def _calculate_hemodynamic_response(self, data: np.ndarray, stim_times: List[float],
                                       sampling_rate: float) -> Dict[str, Any]:
        """Calculate average hemodynamic response function."""
        if len(stim_times) == 0:
            return {'peak_time': 0, 'peak_amplitude': 0, 'duration': 0}

        # Extract and average responses
        window_duration = int(15 * sampling_rate)  # 15 seconds

        responses = []
        for stim_time in stim_times:
            stim_frame = int(stim_time)
            end_frame = min(stim_frame + window_duration, data.shape[2])

            # ROI as center region
            center_roi = data[24:40, 24:40, stim_frame:end_frame]

            # Average signal
            roi_signal = np.mean(center_roi, axis=(0, 1))

            # Baseline subtract
            baseline = np.mean(roi_signal[:int(sampling_rate)])
            roi_signal = roi_signal - baseline

            responses.append(roi_signal)

        # Average across trials
        min_len = min(len(r) for r in responses)
        responses = [r[:min_len] for r in responses]
        avg_response = np.mean(responses, axis=0)

        # Find peak
        peak_idx = np.argmin(avg_response)  # Negative for decreased reflectance
        peak_time = peak_idx / sampling_rate
        peak_amplitude = avg_response[peak_idx]

        # Duration (time to return to baseline)
        threshold = 0.1 * peak_amplitude
        above_threshold = np.where(avg_response < threshold)[0]
        if len(above_threshold) > 0:
            duration = (above_threshold[-1] - above_threshold[0]) / sampling_rate
        else:
            duration = 0

        return {
            'peak_time_s': float(peak_time),
            'peak_amplitude': float(peak_amplitude),
            'duration_s': float(duration),
            'response_curve': avg_response.tolist()
        }

    def _analyze_spatial_patterns(self, activation_map: np.ndarray) -> Dict[str, float]:
        """Analyze spatial patterns of activation."""
        # Find activated regions
        from scipy.ndimage import label

        binary = activation_map > 0
        labeled, n_features = label(binary)

        # Calculate metrics
        if n_features > 0:
            # Largest cluster
            cluster_sizes = [np.sum(labeled == i) for i in range(1, n_features + 1)]
            max_cluster = max(cluster_sizes) if cluster_sizes else 0

            # Center of mass
            from scipy.ndimage import center_of_mass
            com = center_of_mass(activation_map)

            # Spatial spread
            y, x = np.where(activation_map > 0)
            if len(y) > 0:
                spread = np.sqrt(np.var(y) + np.var(x))
            else:
                spread = 0
        else:
            max_cluster = 0
            com = (0, 0)
            spread = 0

        return {
            'n_clusters': int(n_features),
            'largest_cluster_size': int(max_cluster),
            'center_of_mass_x': float(com[1]) if n_features > 0 else 0,
            'center_of_mass_y': float(com[0]) if n_features > 0 else 0,
            'spatial_spread': float(spread)
        }

    def _analyze_temporal_dynamics(self, data: np.ndarray, sampling_rate: float) -> Dict[str, float]:
        """Analyze temporal dynamics."""
        # Global signal
        global_signal = np.mean(data, axis=(0, 1))

        # Frequency analysis
        from scipy.signal import welch
        frequencies, psd = welch(global_signal, fs=sampling_rate, nperseg=min(256, len(global_signal)))

        # Find dominant frequency
        dominant_freq_idx = np.argmax(psd[1:]) + 1  # Exclude DC
        dominant_freq = frequencies[dominant_freq_idx]

        # Calculate temporal SNR
        signal_power = np.var(global_signal)

        # Estimate noise from high frequencies
        high_freq_mask = frequencies > sampling_rate / 4
        if np.any(high_freq_mask):
            noise_power = np.mean(psd[high_freq_mask])
        else:
            noise_power = np.min(psd)

        snr = signal_power / (noise_power + 1e-10)

        return {
            'dominant_frequency_hz': float(dominant_freq),
            'temporal_snr': float(snr),
            'signal_variance': float(signal_power),
            'mean_signal': float(np.mean(global_signal))
        }


class VoltageImagingTool(NeuroToolWrapper):
    """Analyze voltage-sensitive dye imaging data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "voltage_imaging"

    def get_tool_description(self) -> str:
        return "Process voltage-sensitive dye imaging for membrane potential dynamics"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        sampling_rate: float = 1000.0,  # Hz (high for voltage imaging)
        bleaching_correction: bool = True,
        spike_detection: bool = True,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze voltage imaging data."""
        try:
            output_path = Path(output_dir or "voltage_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data = self._generate_synthetic_voltage_data()
            else:
                data = imaging_data

            # Bleaching correction
            if bleaching_correction:
                data = self._correct_bleaching(data)

            # Calculate ΔF/F
            df_f = self._calculate_df_f(data)

            # Detect action potentials if requested
            if spike_detection:
                spikes, spike_times = self._detect_action_potentials(df_f, sampling_rate)
            else:
                spikes = None
                spike_times = []

            # Analyze membrane dynamics
            dynamics = self._analyze_membrane_dynamics(df_f, sampling_rate)

            # Analyze propagation
            propagation = self._analyze_signal_propagation(df_f, sampling_rate)

            # Calculate statistics
            statistics = self._calculate_voltage_statistics(df_f, spikes, sampling_rate)

            results = {
                'sampling_rate': sampling_rate,
                'recording_duration': float(data.shape[2] / sampling_rate),
                'membrane_dynamics': dynamics,
                'propagation_analysis': propagation,
                'statistics': statistics,
                'n_action_potentials': len(spike_times) if spike_times else 0,
                'processing': {
                    'bleaching_corrected': bleaching_correction,
                    'spike_detection': spike_detection
                }
            }

            # Save processed data
            save_dict = {'df_f': df_f}
            if spikes is not None:
                save_dict['spikes'] = spikes
                save_dict['spike_times'] = spike_times

            np.savez(output_path / "voltage_processed.npz", **save_dict)

            with open(output_path / "voltage_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "voltage_processed.npz"),
                        "results": str(output_path / "voltage_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Voltage imaging analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_voltage_data(self) -> np.ndarray:
        """Generate synthetic voltage imaging data."""
        # High temporal resolution
        shape = (64, 64, 5000)  # 5 seconds at 1kHz

        # Baseline with noise
        data = np.ones(shape) + np.random.randn(*shape) * 0.01

        # Add action potentials
        n_spikes = 20
        spike_times = np.sort(np.random.randint(500, shape[2]-500, n_spikes))

        for spike_time in spike_times:
            # Spatial pattern (propagating wave)
            center = [32 + np.random.randint(-10, 10), 32 + np.random.randint(-10, 10)]

            # Action potential waveform
            ap_duration = 10  # ms
            t = np.arange(ap_duration)
            ap_waveform = 0.1 * np.exp(-t / 2) * np.sin(2 * np.pi * t / 5)

            # Apply with spatial propagation
            for dt in range(ap_duration):
                if spike_time + dt < shape[2]:
                    # Expanding wave
                    radius = 3 + dt * 2
                    y, x = np.ogrid[:shape[0], :shape[1]]
                    mask = ((x - center[0])**2 + (y - center[1])**2) <= radius**2
                    mask = mask & (((x - center[0])**2 + (y - center[1])**2) >= (radius-2)**2)

                    data[mask, spike_time + dt] *= (1 + ap_waveform[dt])

        # Add slow oscillations
        slow_freq = 0.01  # 10 Hz
        t = np.arange(shape[2])
        slow_osc = 0.02 * np.sin(2 * np.pi * slow_freq * t)
        data += slow_osc.reshape(1, 1, -1)

        # Add bleaching
        bleaching = np.exp(-t / 10000)
        data *= bleaching.reshape(1, 1, -1)

        return data

    def _correct_bleaching(self, data: np.ndarray) -> np.ndarray:
        """Correct for photobleaching."""
        corrected = np.zeros_like(data)

        # Fit exponential decay to each pixel
        t = np.arange(data.shape[2])

        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                signal = data[i, j, :]

                # Fit exponential
                def exp_func(x, a, b, c):
                    return a * np.exp(-x / b) + c

                try:
                    # Initial guess
                    p0 = [signal[0] - signal[-1], data.shape[2] / 2, signal[-1]]
                    popt, _ = curve_fit(exp_func, t, signal, p0=p0, maxfev=1000)

                    # Correct
                    bleaching_curve = exp_func(t, *popt) - popt[2]
                    corrected[i, j, :] = signal - bleaching_curve
                except:
                    # If fit fails, use simple linear correction
                    corrected[i, j, :] = signal - np.linspace(0, signal[-1] - signal[0], len(signal))

        return corrected

    def _calculate_df_f(self, data: np.ndarray) -> np.ndarray:
        """Calculate ΔF/F for voltage imaging."""
        # Use median as baseline (more robust for sparse spikes)
        baseline = np.median(data, axis=2, keepdims=True)
        df_f = (data - baseline) / (baseline + 0.001)
        return df_f

    def _detect_action_potentials(self, df_f: np.ndarray, sampling_rate: float) -> Tuple[np.ndarray, List]:
        """Detect action potentials in voltage imaging data."""
        # Spatial average for detection
        spatial_avg = np.mean(df_f, axis=(0, 1))

        # High-pass filter to enhance spikes
        from scipy.signal import butter, filtfilt
        b, a = butter(4, 100, fs=sampling_rate, btype='high')
        filtered = filtfilt(b, a, spatial_avg)

        # Detect peaks
        from scipy.signal import find_peaks
        threshold = 3 * np.std(filtered)
        peaks, properties = find_peaks(filtered, height=threshold, distance=int(sampling_rate * 0.002))

        # Create spike array
        spikes = np.zeros_like(df_f)
        for peak in peaks:
            # Find spatial extent of spike
            spike_frame = df_f[:, :, peak]
            spike_mask = spike_frame > np.percentile(spike_frame, 95)
            spikes[spike_mask, peak] = 1

        return spikes, peaks.tolist()

    def _analyze_membrane_dynamics(self, df_f: np.ndarray, sampling_rate: float) -> Dict[str, Any]:
        """Analyze membrane potential dynamics."""
        # Global signal
        global_signal = np.mean(df_f, axis=(0, 1))

        # Frequency analysis
        from scipy.signal import welch
        frequencies, psd = welch(global_signal, fs=sampling_rate, nperseg=min(1024, len(global_signal)))

        # Find peaks in spectrum
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(psd, height=np.mean(psd))

        if len(peaks) > 0:
            dominant_freqs = frequencies[peaks[:3]].tolist()  # Top 3 frequencies
        else:
            dominant_freqs = []

        # Phase analysis (simplified)
        from scipy.signal import hilbert
        analytic = hilbert(global_signal)
        phase = np.angle(analytic)

        # Phase coherence
        phase_coherence = np.abs(np.mean(np.exp(1j * phase)))

        return {
            'dominant_frequencies': dominant_freqs,
            'phase_coherence': float(phase_coherence),
            'mean_frequency': float(np.sum(frequencies * psd) / np.sum(psd)),
            'spectral_entropy': float(-np.sum(psd * np.log(psd + 1e-10)) / np.log(len(psd)))
        }

    def _analyze_signal_propagation(self, df_f: np.ndarray, sampling_rate: float) -> Dict[str, float]:
        """Analyze signal propagation patterns."""
        # Calculate propagation velocity (simplified)
        # Cross-correlation between adjacent pixels

        velocities = []

        for i in range(df_f.shape[0] - 1):
            for j in range(df_f.shape[1] - 1):
                # Horizontal propagation
                signal1 = df_f[i, j, :]
                signal2 = df_f[i, j + 1, :]

                # Cross-correlation
                correlation = np.correlate(signal1, signal2, mode='same')
                lag = np.argmax(correlation) - len(correlation) // 2

                # Convert to velocity (pixels/second)
                if lag != 0:
                    velocity = sampling_rate / abs(lag)
                    if velocity < 1000:  # Reasonable threshold
                        velocities.append(velocity)

        if velocities:
            mean_velocity = np.mean(velocities)
            std_velocity = np.std(velocities)
        else:
            mean_velocity = 0
            std_velocity = 0

        # Directionality analysis (simplified)
        # Calculate gradient
        dy, dx = np.gradient(np.mean(df_f, axis=2))

        # Predominant direction
        angle = np.arctan2(np.mean(dy), np.mean(dx))

        return {
            'mean_propagation_velocity': float(mean_velocity),
            'std_propagation_velocity': float(std_velocity),
            'predominant_direction_rad': float(angle),
            'anisotropy_index': float(np.std([np.std(dx), np.std(dy)]))
        }

    def _calculate_voltage_statistics(self, df_f: np.ndarray, spikes: Optional[np.ndarray],
                                     sampling_rate: float) -> Dict[str, float]:
        """Calculate voltage imaging statistics."""
        stats = {
            'mean_df_f': float(np.mean(np.abs(df_f))),
            'max_df_f': float(np.max(np.abs(df_f))),
            'signal_variance': float(np.var(df_f)),
            'spatial_correlation': float(np.mean(np.corrcoef(df_f.reshape(-1, df_f.shape[2]))))
        }

        if spikes is not None:
            spike_rate = np.sum(spikes) / (np.prod(spikes.shape[:2]) * spikes.shape[2] / sampling_rate)
            stats['spike_rate_hz'] = float(spike_rate)

        return stats


class TwoPhotonMicroscopyTool(NeuroToolWrapper):
    """Analyze two-photon microscopy data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "two_photon_microscopy"

    def get_tool_description(self) -> str:
        return "Process and analyze two-photon microscopy data for deep tissue imaging"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        z_stack: bool = False,
        motion_correction: bool = True,
        dendritic_analysis: bool = False,
        sampling_rate: float = 15.0,  # Hz
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze two-photon microscopy data."""
        try:
            output_path = Path(output_dir or "twophoton_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data = self._generate_synthetic_2p_data(z_stack)
            else:
                data = imaging_data

            # Motion correction
            if motion_correction and not z_stack:
                data, shifts = self._correct_motion(data)
            else:
                shifts = None

            # Process based on imaging type
            if z_stack:
                results_data = self._process_z_stack(data)
            else:
                results_data = self._process_time_series(data, sampling_rate)

            # Dendritic analysis if requested
            if dendritic_analysis:
                dendrite_results = self._analyze_dendrites(data)
            else:
                dendrite_results = {}

            # Morphological analysis
            morphology = self._analyze_morphology(data)

            # Signal quality assessment
            quality = self._assess_signal_quality(data)

            results = {
                'imaging_type': 'z_stack' if z_stack else 'time_series',
                'sampling_rate': sampling_rate if not z_stack else None,
                'motion_corrected': motion_correction and not z_stack,
                'morphology': morphology,
                'signal_quality': quality,
                'dendrite_analysis': dendrite_results,
                'processing_results': results_data
            }

            if shifts is not None:
                results['motion_shifts'] = {
                    'mean_x': float(np.mean(shifts[:, 0])),
                    'mean_y': float(np.mean(shifts[:, 1])),
                    'max_displacement': float(np.max(np.sqrt(shifts[:, 0]**2 + shifts[:, 1]**2)))
                }

            # Save results
            np.savez(
                output_path / "twophoton_processed.npz",
                processed_data=data if isinstance(data, np.ndarray) else results_data
            )

            with open(output_path / "twophoton_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "twophoton_processed.npz"),
                        "results": str(output_path / "twophoton_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Two-photon analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_2p_data(self, z_stack: bool) -> np.ndarray:
        """Generate synthetic two-photon data."""
        if z_stack:
            # 3D volume
            shape = (256, 256, 50)  # x, y, z
            data = np.random.poisson(10, shape).astype(float)

            # Add structures
            for _ in range(10):
                # Neurons
                center = [np.random.randint(20, s-20) for s in shape]
                radius = np.random.randint(5, 10)

                z, y, x = np.ogrid[:shape[2], :shape[0], :shape[1]]
                mask = ((x - center[1])**2 + (y - center[0])**2 +
                       (z - center[2])**2) <= radius**2
                data[mask[1:, :]] += 50

            # Add dendrites (lines)
            for _ in range(20):
                start = [np.random.randint(0, s) for s in shape]
                direction = np.random.randn(3)
                direction /= np.linalg.norm(direction)

                for t in range(50):
                    point = [int(start[i] + t * direction[i]) for i in range(3)]
                    if all(0 <= point[i] < shape[i] for i in range(3)):
                        data[point[0], point[1], point[2]] += 30
        else:
            # Time series
            shape = (256, 256, 500)
            data = np.random.poisson(10, shape).astype(float)

            # Add neurons with calcium transients
            for _ in range(15):
                center = [np.random.randint(20, s-20) for s in shape[:2]]
                radius = np.random.randint(5, 8)

                y, x = np.ogrid[:shape[0], :shape[1]]
                mask = ((x - center[0])**2 + (y - center[1])**2) <= radius**2

                # Base fluorescence
                data[mask] += 30

                # Add transients
                n_transients = np.random.randint(5, 15)
                for _ in range(n_transients):
                    t_start = np.random.randint(0, shape[2] - 50)
                    duration = 30
                    t = np.arange(duration)
                    transient = 20 * np.exp(-t / 10)

                    data[mask, t_start:t_start + duration] += transient

        return data

    def _correct_motion(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Correct for motion artifacts."""
        corrected = np.zeros_like(data)
        shifts = np.zeros((data.shape[2], 2))

        # Use first frame as reference
        reference = data[:, :, 0]
        corrected[:, :, 0] = reference

        for t in range(1, data.shape[2]):
            frame = data[:, :, t]

            # Cross-correlation for shift detection
            from scipy.signal import correlate2d
            correlation = correlate2d(reference, frame, mode='same')

            # Find peak
            peak = np.unravel_index(np.argmax(correlation), correlation.shape)
            shift = [peak[0] - data.shape[0] // 2, peak[1] - data.shape[1] // 2]

            # Apply shift
            from scipy.ndimage import shift as nd_shift
            corrected[:, :, t] = nd_shift(frame, [-shift[0], -shift[1]], order=1)

            shifts[t] = shift

        return corrected, shifts

    def _process_z_stack(self, data: np.ndarray) -> Dict[str, Any]:
        """Process z-stack data."""
        # Maximum intensity projection
        mip = np.max(data, axis=2)

        # 3D segmentation (simplified)
        from scipy.ndimage import label

        threshold = np.percentile(data, 95)
        binary = data > threshold
        labeled, n_features = label(binary)

        # Calculate properties
        volumes = []
        intensities = []

        for i in range(1, min(n_features + 1, 100)):
            mask = labeled == i
            volume = np.sum(mask)
            intensity = np.mean(data[mask])
            volumes.append(volume)
            intensities.append(intensity)

        return {
            'n_structures': int(n_features),
            'mean_volume': float(np.mean(volumes)) if volumes else 0,
            'mean_intensity': float(np.mean(intensities)) if intensities else 0,
            'max_projection_mean': float(np.mean(mip)),
            'depth_range': int(data.shape[2])
        }

    def _process_time_series(self, data: np.ndarray, sampling_rate: float) -> Dict[str, Any]:
        """Process time series data."""
        # Detect ROIs
        max_proj = np.max(data, axis=2)
        threshold = np.percentile(max_proj, 90)

        from scipy.ndimage import label
        binary = max_proj > threshold
        labeled, n_features = label(binary)

        # Extract time series
        time_series = []
        for i in range(1, min(n_features + 1, 50)):
            mask = labeled == i
            if np.sum(mask) > 10:  # Minimum size
                ts = np.mean(data[mask], axis=0)
                time_series.append(ts)

        if time_series:
            time_series = np.array(time_series)

            # Calculate correlations
            corr_matrix = np.corrcoef(time_series)
            np.fill_diagonal(corr_matrix, 0)

            results = {
                'n_rois': len(time_series),
                'mean_correlation': float(np.mean(np.abs(corr_matrix))),
                'mean_activity': float(np.mean(time_series)),
                'recording_duration': float(data.shape[2] / sampling_rate)
            }
        else:
            results = {
                'n_rois': 0,
                'mean_correlation': 0,
                'mean_activity': 0,
                'recording_duration': float(data.shape[2] / sampling_rate)
            }

        return results

    def _analyze_dendrites(self, data: np.ndarray) -> Dict[str, Any]:
        """Analyze dendritic structures."""
        # Simplified dendritic analysis
        # In reality, would use specialized algorithms

        # Use maximum projection for 2D analysis
        if len(data.shape) == 3 and data.shape[2] > 100:
            # Time series - use max projection
            proj = np.max(data, axis=2)
        elif len(data.shape) == 3:
            # Z-stack - use max projection
            proj = np.max(data, axis=2)
        else:
            proj = data

        # Detect linear structures (simplified)
        from scipy.ndimage import sobel

        # Edge detection
        edges_x = sobel(proj, axis=0)
        edges_y = sobel(proj, axis=1)
        edges = np.sqrt(edges_x**2 + edges_y**2)

        # Threshold
        threshold = np.percentile(edges, 95)
        dendrite_mask = edges > threshold

        # Skeleton analysis (simplified)
        from scipy.ndimage import binary_erosion
        skeleton = binary_erosion(dendrite_mask, iterations=1)

        # Calculate metrics
        total_length = np.sum(skeleton)

        # Branch points (simplified - pixels with >2 neighbors)
        from scipy.ndimage import convolve
        kernel = np.ones((3, 3))
        kernel[1, 1] = 0
        neighbor_count = convolve(skeleton.astype(int), kernel, mode='constant')
        branch_points = (neighbor_count > 2) & skeleton

        return {
            'total_dendritic_length': int(total_length),
            'n_branch_points': int(np.sum(branch_points)),
            'dendritic_density': float(total_length / np.prod(proj.shape)),
            'mean_dendrite_intensity': float(np.mean(proj[dendrite_mask]))
                if np.any(dendrite_mask) else 0
        }

    def _analyze_morphology(self, data: np.ndarray) -> Dict[str, float]:
        """Analyze morphological features."""
        # Use projection for analysis
        if len(data.shape) == 3:
            proj = np.max(data, axis=2 if data.shape[2] < 100 else 2)
        else:
            proj = data

        # Threshold
        threshold = np.percentile(proj, 80)
        binary = proj > threshold

        # Morphological measurements
        from scipy.ndimage import label, binary_fill_holes

        # Fill holes
        filled = binary_fill_holes(binary)

        # Label objects
        labeled, n_features = label(filled)

        # Calculate shape metrics
        if n_features > 0:
            # Circularity (simplified)
            areas = [np.sum(labeled == i) for i in range(1, min(n_features + 1, 20))]

            # Perimeter (simplified using edge detection)
            from scipy.ndimage import binary_erosion
            perimeters = []
            for i in range(1, min(n_features + 1, 20)):
                obj = labeled == i
                eroded = binary_erosion(obj)
                perimeter = np.sum(obj & ~eroded)
                perimeters.append(perimeter)

            if perimeters and areas:
                circularities = [4 * np.pi * a / (p**2 + 0.01)
                               for a, p in zip(areas, perimeters)]
                mean_circularity = np.mean(circularities)
            else:
                mean_circularity = 0

            mean_area = np.mean(areas) if areas else 0
        else:
            mean_area = 0
            mean_circularity = 0

        return {
            'n_objects': int(n_features),
            'mean_object_area': float(mean_area),
            'mean_circularity': float(mean_circularity),
            'tissue_coverage': float(np.sum(binary) / binary.size)
        }

    def _assess_signal_quality(self, data: np.ndarray) -> Dict[str, float]:
        """Assess signal quality metrics."""
        # Signal-to-noise ratio
        signal = np.mean(data[data > np.percentile(data, 75)])
        noise = np.std(data[data < np.percentile(data, 25)])
        snr = signal / (noise + 0.01)

        # Dynamic range
        dynamic_range = np.max(data) / (np.min(data[data > 0]) + 0.01)

        # Contrast
        contrast = np.std(data) / (np.mean(data) + 0.01)

        return {
            'snr': float(snr),
            'dynamic_range': float(dynamic_range),
            'contrast': float(contrast),
            'mean_intensity': float(np.mean(data)),
            'quality_score': float(snr * contrast)
        }


class OptogenecicsAnalysisTool(NeuroToolWrapper):
    """Analyze optogenetic stimulation and response data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "optogenetics_analysis"

    def get_tool_description(self) -> str:
        return "Analyze optogenetic stimulation experiments and neural responses"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        stimulation_times: Optional[List[float]] = None,
        stimulation_params: Optional[Dict] = None,
        sampling_rate: float = 30.0,
        response_window: float = 5.0,  # seconds
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze optogenetic data."""
        try:
            output_path = Path(output_dir or "optogenetics_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data, stim_times, stim_params = self._generate_synthetic_opto_data()
            else:
                data = imaging_data
                stim_times = stimulation_times if stimulation_times else []
                stim_params = stimulation_params if stimulation_params else {}

            # Process baseline
            df_f = self._calculate_df_f(data)

            # Analyze stimulation responses
            if stim_times:
                responses = self._analyze_stimulation_responses(
                    df_f, stim_times, sampling_rate, response_window
                )
            else:
                responses = {}

            # Analyze cell-type specific responses
            cell_types = self._classify_cell_responses(df_f, stim_times, sampling_rate)

            # Temporal dynamics
            dynamics = self._analyze_temporal_dynamics(df_f, stim_times, sampling_rate)

            # Spatial patterns
            spatial = self._analyze_spatial_patterns(df_f, stim_times, sampling_rate)

            results = {
                'n_stimulations': len(stim_times),
                'stimulation_parameters': stim_params,
                'sampling_rate': sampling_rate,
                'response_analysis': responses,
                'cell_type_responses': cell_types,
                'temporal_dynamics': dynamics,
                'spatial_patterns': spatial
            }

            # Save processed data
            np.savez(
                output_path / "optogenetics_processed.npz",
                df_f=df_f,
                stim_times=stim_times
            )

            with open(output_path / "optogenetics_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "optogenetics_processed.npz"),
                        "results": str(output_path / "optogenetics_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Optogenetics analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_opto_data(self) -> Tuple[np.ndarray, List, Dict]:
        """Generate synthetic optogenetic data."""
        shape = (128, 128, 1500)  # 50 seconds at 30 Hz
        data = np.ones(shape) + np.random.randn(*shape) * 0.05

        # Stimulation parameters
        stim_params = {
            'wavelength': 470,  # nm (blue light for ChR2)
            'power': 10,  # mW
            'pulse_duration': 10,  # ms
            'frequency': 20  # Hz
        }

        # Stimulation times (in frames)
        stim_times = [300, 600, 900, 1200]

        # Add different cell populations
        n_cells = 30

        for i in range(n_cells):
            # Cell location
            center = [np.random.randint(10, s-10) for s in shape[:2]]
            radius = np.random.randint(4, 8)

            y, x = np.ogrid[:shape[0], :shape[1]]
            mask = ((x - center[0])**2 + (y - center[1])**2) <= radius**2

            # Baseline fluorescence
            data[mask] *= 1.5

            # Cell type (excitatory vs inhibitory response)
            cell_type = 'excitatory' if i < n_cells * 0.7 else 'inhibitory'

            # Add responses to stimulation
            for stim_time in stim_times:
                response_duration = 150  # 5 seconds
                t = np.arange(response_duration)

                if cell_type == 'excitatory':
                    # Positive response
                    response = 0.3 * np.exp(-t / 30) * (1 - np.exp(-t / 5))
                    # Add some cells with delayed response
                    if i % 3 == 0:
                        delay = 15
                        response = np.concatenate([np.zeros(delay), response[:-delay]])
                else:
                    # Negative response (inhibition)
                    response = -0.2 * np.exp(-t / 40) * (1 - np.exp(-t / 10))

                end_time = min(stim_time + response_duration, shape[2])
                data[mask, stim_time:end_time] *= (1 + response[:end_time-stim_time])

        return data, stim_times, stim_params

    def _calculate_df_f(self, data: np.ndarray) -> np.ndarray:
        """Calculate ΔF/F."""
        # Baseline as 10th percentile
        baseline = np.percentile(data, 10, axis=2, keepdims=True)
        df_f = (data - baseline) / (baseline + 0.001)
        return df_f

    def _analyze_stimulation_responses(self, df_f: np.ndarray, stim_times: List,
                                      sampling_rate: float, response_window: float) -> Dict:
        """Analyze responses to optogenetic stimulation."""
        window_frames = int(response_window * sampling_rate)

        # Extract response windows
        responses = []
        for stim_time in stim_times:
            # Pre-stimulus baseline
            baseline_start = max(0, stim_time - window_frames)
            baseline = np.mean(df_f[:, :, baseline_start:stim_time], axis=2)

            # Post-stimulus response
            response_end = min(stim_time + window_frames, df_f.shape[2])
            response = df_f[:, :, stim_time:response_end]

            # Calculate metrics
            peak_response = np.max(np.mean(response, axis=(0, 1)))
            time_to_peak = np.argmax(np.mean(response, axis=(0, 1))) / sampling_rate

            # Spatial extent
            max_frame = np.argmax(np.mean(response, axis=(0, 1)))
            response_frame = response[:, :, max_frame]
            threshold = np.mean(baseline) + 2 * np.std(baseline)
            activated_area = np.sum(response_frame > threshold)

            responses.append({
                'peak_amplitude': float(peak_response),
                'time_to_peak': float(time_to_peak),
                'activated_area': int(activated_area),
                'baseline_mean': float(np.mean(baseline))
            })

        # Average across stimulations
        avg_response = {
            'mean_peak_amplitude': float(np.mean([r['peak_amplitude'] for r in responses])),
            'mean_time_to_peak': float(np.mean([r['time_to_peak'] for r in responses])),
            'mean_activated_area': float(np.mean([r['activated_area'] for r in responses])),
            'response_reliability': float(np.std([r['peak_amplitude'] for r in responses]) /
                                        (np.mean([r['peak_amplitude'] for r in responses]) + 0.01))
        }

        return avg_response

    def _classify_cell_responses(self, df_f: np.ndarray, stim_times: List,
                                sampling_rate: float) -> Dict:
        """Classify cells based on response type."""
        if not stim_times:
            return {'n_responsive': 0, 'n_excited': 0, 'n_inhibited': 0}

        # Detect ROIs
        max_proj = np.max(df_f, axis=2)
        threshold = np.percentile(max_proj, 90)

        from scipy.ndimage import label
        binary = max_proj > threshold
        labeled, n_features = label(binary)

        excited = 0
        inhibited = 0
        non_responsive = 0

        for i in range(1, min(n_features + 1, 100)):
            mask = labeled == i
            if np.sum(mask) < 10:
                continue

            # Extract time series
            ts = np.mean(df_f[mask], axis=0)

            # Calculate response
            responses = []
            for stim_time in stim_times:
                baseline = np.mean(ts[max(0, stim_time-30):stim_time])
                response = np.mean(ts[stim_time:min(stim_time+60, len(ts))])
                responses.append(response - baseline)

            mean_response = np.mean(responses)

            if mean_response > 0.1:
                excited += 1
            elif mean_response < -0.05:
                inhibited += 1
            else:
                non_responsive += 1

        total = excited + inhibited + non_responsive

        return {
            'n_responsive': int(excited + inhibited),
            'n_excited': int(excited),
            'n_inhibited': int(inhibited),
            'n_non_responsive': int(non_responsive),
            'excitation_ratio': float(excited / total) if total > 0 else 0,
            'inhibition_ratio': float(inhibited / total) if total > 0 else 0
        }

    def _analyze_temporal_dynamics(self, df_f: np.ndarray, stim_times: List,
                                  sampling_rate: float) -> Dict:
        """Analyze temporal dynamics of optogenetic responses."""
        if not stim_times:
            return {'onset_latency': 0, 'decay_time': 0}

        # Average spatial signal
        spatial_avg = np.mean(df_f, axis=(0, 1))

        # Analyze first stimulation
        stim_time = stim_times[0]

        # Onset latency
        baseline = np.mean(spatial_avg[max(0, stim_time-30):stim_time])
        threshold = baseline + 2 * np.std(spatial_avg[max(0, stim_time-30):stim_time])

        post_stim = spatial_avg[stim_time:min(stim_time+150, len(spatial_avg))]
        above_threshold = np.where(post_stim > threshold)[0]

        if len(above_threshold) > 0:
            onset_latency = above_threshold[0] / sampling_rate

            # Peak time
            peak_idx = np.argmax(post_stim)
            peak_time = peak_idx / sampling_rate

            # Decay time (to 50% of peak)
            peak_val = post_stim[peak_idx]
            half_peak = baseline + (peak_val - baseline) / 2

            decay_indices = np.where(post_stim[peak_idx:] < half_peak)[0]
            if len(decay_indices) > 0:
                decay_time = decay_indices[0] / sampling_rate
            else:
                decay_time = 0
        else:
            onset_latency = 0
            peak_time = 0
            decay_time = 0

        return {
            'onset_latency_s': float(onset_latency),
            'peak_time_s': float(peak_time),
            'decay_time_s': float(decay_time),
            'response_duration_s': float((peak_time + decay_time) if decay_time > 0 else 0)
        }

    def _analyze_spatial_patterns(self, df_f: np.ndarray, stim_times: List,
                                 sampling_rate: float) -> Dict:
        """Analyze spatial patterns of optogenetic activation."""
        if not stim_times:
            return {'spatial_spread': 0, 'propagation_velocity': 0}

        # Analyze response to first stimulation
        stim_time = stim_times[0]
        window = 60  # 2 seconds at 30 Hz

        response_window = df_f[:, :, stim_time:min(stim_time+window, df_f.shape[2])]

        # Calculate activation map
        baseline = np.mean(df_f[:, :, max(0, stim_time-30):stim_time], axis=2)
        max_response = np.max(response_window, axis=2)
        activation = max_response - baseline

        # Threshold
        threshold = np.mean(activation) + 2 * np.std(activation)
        activated = activation > threshold

        # Spatial spread
        if np.any(activated):
            y, x = np.where(activated)
            center_y, center_x = np.mean(y), np.mean(x)
            distances = np.sqrt((y - center_y)**2 + (x - center_x)**2)
            spatial_spread = np.mean(distances)

            # Propagation analysis (simplified)
            # Time to activation for each pixel
            time_to_activation = np.zeros(activation.shape)
            for i in range(response_window.shape[2]):
                newly_activated = (response_window[:, :, i] - baseline) > threshold
                time_to_activation[newly_activated & (time_to_activation == 0)] = i / sampling_rate

            # Calculate propagation velocity (simplified)
            if np.sum(time_to_activation > 0) > 10:
                # Gradient of activation times
                dy, dx = np.gradient(time_to_activation)
                velocity = 1 / np.sqrt(dy**2 + dx**2 + 0.01)
                propagation_velocity = np.median(velocity[activated])
            else:
                propagation_velocity = 0
        else:
            spatial_spread = 0
            propagation_velocity = 0

        return {
            'spatial_spread_pixels': float(spatial_spread),
            'propagation_velocity_pixels_per_s': float(propagation_velocity),
            'activated_fraction': float(np.sum(activated) / activated.size),
            'max_activation_strength': float(np.max(activation))
        }


class fNIRSAnalysisTool(NeuroToolWrapper):
    """Functional near-infrared spectroscopy (fNIRS) analysis."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "fnirs_analysis"

    def get_tool_description(self) -> str:
        return "Analyze fNIRS data for hemodynamic brain activity"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        time_series: Optional[np.ndarray] = None,
        wavelengths: Optional[List[float]] = None,
        sampling_rate: float = 10.0,
        channel_positions: Optional[np.ndarray] = None,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze fNIRS data."""
        try:
            output_path = Path(output_dir or "fnirs_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if time_series is None:
                data, positions = self._generate_synthetic_fnirs_data()
            else:
                data = time_series
                positions = channel_positions if channel_positions is not None else self._default_positions()

            # Set wavelengths
            if wavelengths is None:
                wavelengths = [760, 850]  # Common fNIRS wavelengths

            # Convert to hemoglobin concentrations
            hbo, hbr = self._modified_beer_lambert(data, wavelengths)

            # Motion artifact correction
            hbo_clean, hbr_clean = self._motion_artifact_correction(hbo, hbr, sampling_rate)

            # Calculate connectivity
            connectivity = self._calculate_connectivity(hbo_clean, sampling_rate)

            # Hemodynamic response analysis
            hrf = self._analyze_hrf(hbo_clean, sampling_rate)

            # Signal quality metrics
            quality = self._assess_signal_quality(hbo_clean, hbr_clean)

            results = {
                'n_channels': len(data) if len(data.shape) > 1 else 1,
                'sampling_rate': sampling_rate,
                'wavelengths': wavelengths,
                'hemoglobin_concentrations': {
                    'hbo_mean': float(np.mean(hbo_clean)),
                    'hbr_mean': float(np.mean(hbr_clean)),
                    'total_hb': float(np.mean(hbo_clean + hbr_clean))
                },
                'connectivity': connectivity,
                'hrf_analysis': hrf,
                'signal_quality': quality
            }

            # Save processed data
            np.savez(
                output_path / "fnirs_processed.npz",
                hbo=hbo_clean,
                hbr=hbr_clean,
                positions=positions
            )

            with open(output_path / "fnirs_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "processed_data": str(output_path / "fnirs_processed.npz"),
                        "results": str(output_path / "fnirs_results.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"fNIRS analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_fnirs_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Generate synthetic fNIRS data."""
        n_channels = 20
        n_timepoints = 3000  # 5 minutes at 10 Hz
        n_wavelengths = 2

        # Channel positions (simplified 2D layout)
        positions = np.random.rand(n_channels, 2) * 10

        # Generate data with hemodynamic responses
        data = np.zeros((n_channels, n_timepoints, n_wavelengths))

        # Add baseline
        for ch in range(n_channels):
            data[ch, :, 0] = 1.0 + np.random.randn(n_timepoints) * 0.01  # 760nm
            data[ch, :, 1] = 1.0 + np.random.randn(n_timepoints) * 0.01  # 850nm

        # Add hemodynamic responses
        n_events = 10
        event_times = np.sort(np.random.randint(200, n_timepoints-200, n_events))

        for event_time in event_times:
            # Random activation pattern
            activated_channels = np.random.choice(n_channels, size=n_channels//2, replace=False)

            # HRF
            t = np.arange(200)
            hrf = 0.05 * np.exp(-t/30) * (1 - np.exp(-t/6))

            for ch in activated_channels:
                # Different response for different wavelengths
                data[ch, event_time:event_time+200, 0] -= hrf * 1.2
                data[ch, event_time:event_time+200, 1] -= hrf * 0.8

        return data, positions

    def _default_positions(self) -> np.ndarray:
        """Generate default channel positions."""
        # 10-20 system approximation
        n_channels = 20
        positions = np.zeros((n_channels, 2))
        for i in range(n_channels):
            angle = 2 * np.pi * i / n_channels
            positions[i] = [5 * np.cos(angle), 5 * np.sin(angle)]
        return positions

    def _modified_beer_lambert(self, data: np.ndarray, wavelengths: List[float]) -> Tuple[np.ndarray, np.ndarray]:
        """Convert optical density to hemoglobin concentrations."""
        # Extinction coefficients (simplified)
        epsilon = {
            760: {'hbo': 1.486, 'hbr': 3.844},
            850: {'hbo': 2.526, 'hbr': 1.798}
        }

        # Ensure we have the right wavelengths
        if 760 not in wavelengths or 850 not in wavelengths:
            # Use default values
            wavelengths = [760, 850]

        # Optical density
        od = -np.log(data / np.mean(data[:, :100], axis=1, keepdims=True))

        # Solve for concentrations
        if len(od.shape) == 3 and od.shape[2] >= 2:
            od_760 = od[:, :, 0]
            od_850 = od[:, :, 1]
        else:
            od_760 = od_850 = od if len(od.shape) == 2 else od.reshape(-1, od.shape[-1])

        # Matrix inversion for each channel
        hbo = np.zeros_like(od_760)
        hbr = np.zeros_like(od_760)

        for ch in range(od_760.shape[0] if len(od_760.shape) > 1 else 1):
            if len(od_760.shape) > 1:
                y = np.stack([od_760[ch], od_850[ch]], axis=1)
            else:
                y = np.stack([od_760, od_850], axis=1)

            # Extinction matrix
            E = np.array([
                [epsilon[760]['hbo'], epsilon[760]['hbr']],
                [epsilon[850]['hbo'], epsilon[850]['hbr']]
            ])

            # Solve
            for t in range(y.shape[0]):
                try:
                    conc = np.linalg.solve(E, y[t])
                    if len(hbo.shape) > 1:
                        hbo[ch, t] = conc[0]
                        hbr[ch, t] = conc[1]
                    else:
                        hbo[t] = conc[0]
                        hbr[t] = conc[1]
                except:
                    pass

        return hbo, hbr

    def _motion_artifact_correction(self, hbo: np.ndarray, hbr: np.ndarray,
                                   sampling_rate: float) -> Tuple[np.ndarray, np.ndarray]:
        """Correct motion artifacts."""
        # Simple spline interpolation method
        hbo_clean = np.zeros_like(hbo)
        hbr_clean = np.zeros_like(hbr)

        for ch in range(hbo.shape[0] if len(hbo.shape) > 1 else 1):
            if len(hbo.shape) > 1:
                signal_hbo = hbo[ch]
                signal_hbr = hbr[ch]
            else:
                signal_hbo = hbo
                signal_hbr = hbr

            # Detect motion artifacts (high derivatives)
            diff_hbo = np.abs(np.diff(signal_hbo))
            threshold = 5 * np.median(diff_hbo)
            artifacts = np.where(diff_hbo > threshold)[0]

            # Interpolate
            if len(artifacts) > 0:
                clean_idx = np.setdiff1d(np.arange(len(signal_hbo)), artifacts)
                if len(clean_idx) > 2:
                    from scipy.interpolate import interp1d
                    f_hbo = interp1d(clean_idx, signal_hbo[clean_idx], kind='cubic',
                                    fill_value='extrapolate', bounds_error=False)
                    f_hbr = interp1d(clean_idx, signal_hbr[clean_idx], kind='cubic',
                                    fill_value='extrapolate', bounds_error=False)

                    if len(hbo_clean.shape) > 1:
                        hbo_clean[ch] = f_hbo(np.arange(len(signal_hbo)))
                        hbr_clean[ch] = f_hbr(np.arange(len(signal_hbr)))
                    else:
                        hbo_clean = f_hbo(np.arange(len(signal_hbo)))
                        hbr_clean = f_hbr(np.arange(len(signal_hbr)))
                else:
                    if len(hbo_clean.shape) > 1:
                        hbo_clean[ch] = signal_hbo
                        hbr_clean[ch] = signal_hbr
                    else:
                        hbo_clean = signal_hbo
                        hbr_clean = signal_hbr
            else:
                if len(hbo_clean.shape) > 1:
                    hbo_clean[ch] = signal_hbo
                    hbr_clean[ch] = signal_hbr
                else:
                    hbo_clean = signal_hbo
                    hbr_clean = signal_hbr

        return hbo_clean, hbr_clean

    def _calculate_connectivity(self, hbo: np.ndarray, sampling_rate: float) -> Dict[str, Any]:
        """Calculate functional connectivity."""
        if len(hbo.shape) == 1:
            return {'mean_connectivity': 0, 'clustering_coefficient': 0}

        # Correlation-based connectivity
        corr_matrix = np.corrcoef(hbo)
        np.fill_diagonal(corr_matrix, 0)

        # Graph metrics
        threshold = 0.3
        binary = (corr_matrix > threshold).astype(int)

        # Clustering coefficient
        clustering = []
        for i in range(len(binary)):
            neighbors = np.where(binary[i])[0]
            if len(neighbors) > 1:
                subgraph = binary[np.ix_(neighbors, neighbors)]
                n_edges = np.sum(subgraph) / 2
                n_possible = len(neighbors) * (len(neighbors) - 1) / 2
                clustering.append(n_edges / n_possible if n_possible > 0 else 0)

        return {
            'mean_connectivity': float(np.mean(np.abs(corr_matrix))),
            'clustering_coefficient': float(np.mean(clustering)) if clustering else 0,
            'max_correlation': float(np.max(np.abs(corr_matrix)))
        }

    def _analyze_hrf(self, hbo: np.ndarray, sampling_rate: float) -> Dict[str, float]:
        """Analyze hemodynamic response function."""
        # Average across channels
        if len(hbo.shape) > 1:
            signal = np.mean(hbo, axis=0)
        else:
            signal = hbo

        # Find peaks
        from scipy.signal import find_peaks
        peaks, properties = find_peaks(signal, height=np.std(signal), distance=int(sampling_rate*5))

        if len(peaks) > 0:
            # Average peak properties
            peak_amplitude = np.mean(properties['peak_heights'])

            # Time to peak (from detected events)
            if len(peaks) > 1:
                inter_peak_interval = np.mean(np.diff(peaks)) / sampling_rate
            else:
                inter_peak_interval = 0
        else:
            peak_amplitude = 0
            inter_peak_interval = 0

        return {
            'n_peaks': len(peaks),
            'mean_peak_amplitude': float(peak_amplitude),
            'inter_peak_interval_s': float(inter_peak_interval)
        }

    def _assess_signal_quality(self, hbo: np.ndarray, hbr: np.ndarray) -> Dict[str, float]:
        """Assess signal quality metrics."""
        # SNR
        signal_hbo = np.std(hbo)
        noise_hbo = np.median(np.abs(np.diff(hbo))) / 0.6745  # MAD estimator
        snr_hbo = signal_hbo / (noise_hbo + 1e-10)

        signal_hbr = np.std(hbr)
        noise_hbr = np.median(np.abs(np.diff(hbr))) / 0.6745
        snr_hbr = signal_hbr / (noise_hbr + 1e-10)

        # Correlation between HbO and HbR (should be negative for good signals)
        if len(hbo.shape) > 1:
            correlations = [np.corrcoef(hbo[i], hbr[i])[0, 1] for i in range(len(hbo))]
            mean_correlation = np.mean(correlations)
        else:
            mean_correlation = np.corrcoef(hbo, hbr)[0, 1]

        return {
            'snr_hbo': float(snr_hbo),
            'snr_hbr': float(snr_hbr),
            'hbo_hbr_correlation': float(mean_correlation),
            'signal_quality_index': float((snr_hbo + snr_hbr) / 2 * (1 - abs(mean_correlation)))
        }


class LightSheetMicroscopyTool(NeuroToolWrapper):
    """Light-sheet microscopy analysis for large-scale 3D imaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "light_sheet_microscopy"

    def get_tool_description(self) -> str:
        return "Analyze light-sheet microscopy data for whole-brain cellular imaging"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        voxel_size: Optional[Tuple[float, float, float]] = None,
        cell_detection: bool = True,
        vessel_segmentation: bool = False,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze light-sheet microscopy data."""
        try:
            output_path = Path(output_dir or "lightsheet_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data = self._generate_synthetic_lightsheet_data()
            else:
                data = imaging_data

            # Set voxel size
            if voxel_size is None:
                voxel_size = (1.0, 1.0, 5.0)  # μm (typical for light-sheet)

            # Cell detection
            if cell_detection:
                cells = self._detect_cells_3d(data)
            else:
                cells = []

            # Vessel segmentation
            if vessel_segmentation:
                vessels = self._segment_vessels(data)
            else:
                vessels = None

            # Tissue segmentation
            tissue_regions = self._segment_tissue_regions(data)

            # Calculate metrics
            metrics = self._calculate_volume_metrics(data, cells, vessels, voxel_size)

            # Spatial statistics
            spatial_stats = self._analyze_spatial_distribution(cells, data.shape, voxel_size)

            results = {
                'volume_shape': data.shape,
                'voxel_size_um': voxel_size,
                'n_cells_detected': len(cells),
                'tissue_regions': tissue_regions,
                'volume_metrics': metrics,
                'spatial_statistics': spatial_stats
            }

            if vessels is not None:
                results['vessel_analysis'] = {
                    'vessel_volume_fraction': float(np.sum(vessels) / vessels.size),
                    'mean_vessel_intensity': float(np.mean(data[vessels]))
                }

            # Save results
            save_dict = {'cell_positions': cells}
            if vessels is not None:
                save_dict['vessel_mask'] = vessels

            np.savez(output_path / "lightsheet_results.npz", **save_dict)

            with open(output_path / "lightsheet_analysis.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "results_data": str(output_path / "lightsheet_results.npz"),
                        "analysis": str(output_path / "lightsheet_analysis.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Light-sheet microscopy analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_lightsheet_data(self) -> np.ndarray:
        """Generate synthetic light-sheet data."""
        shape = (100, 100, 50)  # Smaller for efficiency
        data = np.random.poisson(5, shape).astype(float)

        # Add cells
        n_cells = 200
        for _ in range(n_cells):
            center = [np.random.randint(5, s-5) for s in shape]
            radius = np.random.randint(2, 4)

            z, y, x = np.ogrid[:shape[0], :shape[1], :shape[2]]
            mask = ((x - center[2])**2 + (y - center[1])**2 +
                   (z - center[0])**2) <= radius**2
            data[mask] += 50

        # Add vessels
        for _ in range(10):
            start = [np.random.randint(0, s) for s in shape]
            direction = np.random.randn(3)
            direction /= np.linalg.norm(direction)

            for t in range(100):
                point = [int(start[i] + t * direction[i]) for i in range(3)]
                if all(0 <= point[i] < shape[i] for i in range(3)):
                    # Vessel with varying diameter
                    radius = 1 + np.random.rand()
                    z, y, x = np.ogrid[:shape[0], :shape[1], :shape[2]]
                    mask = ((x - point[2])**2 + (y - point[1])**2 +
                           (z - point[0])**2) <= radius**2
                    data[mask] += 30

        # Smooth
        from scipy.ndimage import gaussian_filter
        data = gaussian_filter(data, sigma=0.5)

        return data

    def _detect_cells_3d(self, data: np.ndarray) -> List[Tuple[float, float, float]]:
        """Detect cells in 3D volume."""
        # LoG blob detection
        from scipy.ndimage import gaussian_laplace

        # Multi-scale detection
        scales = [2, 3, 4]
        blob_responses = []

        for scale in scales:
            response = -gaussian_laplace(data, sigma=scale)
            blob_responses.append(response)

        # Maximum across scales
        max_response = np.max(blob_responses, axis=0)

        # Find local maxima
        from scipy.ndimage import maximum_filter
        local_max = maximum_filter(max_response, size=5)
        peaks = (max_response == local_max) & (max_response > np.percentile(max_response, 98))

        # Get coordinates
        cells = list(zip(*np.where(peaks)))

        # Limit number
        if len(cells) > 500:
            indices = np.random.choice(len(cells), 500, replace=False)
            cells = [cells[i] for i in indices]

        return cells

    def _segment_vessels(self, data: np.ndarray) -> np.ndarray:
        """Segment blood vessels."""
        # Frangi vesselness filter (simplified)
        from scipy.ndimage import gaussian_filter

        # Calculate Hessian (second derivatives)
        sigma = 2
        smooth = gaussian_filter(data, sigma)

        # Gradients
        from scipy.ndimage import sobel
        gx = sobel(smooth, axis=0)
        gy = sobel(smooth, axis=1)
        gz = sobel(smooth, axis=2)

        # Second derivatives (simplified)
        gxx = sobel(gx, axis=0)
        gyy = sobel(gy, axis=1)
        gzz = sobel(gz, axis=2)

        # Vesselness measure (simplified)
        vesselness = np.abs(gxx) + np.abs(gyy) + np.abs(gzz)

        # Threshold
        threshold = np.percentile(vesselness, 95)
        vessels = vesselness > threshold

        # Morphological operations
        from scipy.ndimage import binary_closing
        vessels = binary_closing(vessels, iterations=2)

        return vessels

    def _segment_tissue_regions(self, data: np.ndarray) -> Dict[str, Any]:
        """Segment different tissue regions."""
        # Simple intensity-based segmentation
        thresholds = np.percentile(data[data > 0], [30, 60, 90])

        regions = {
            'background': np.sum(data <= thresholds[0]),
            'low_intensity': np.sum((data > thresholds[0]) & (data <= thresholds[1])),
            'medium_intensity': np.sum((data > thresholds[1]) & (data <= thresholds[2])),
            'high_intensity': np.sum(data > thresholds[2])
        }

        total = np.prod(data.shape)
        for key in regions:
            regions[key] = float(regions[key] / total)

        return regions

    def _calculate_volume_metrics(self, data: np.ndarray, cells: List,
                                 vessels: Optional[np.ndarray],
                                 voxel_size: Tuple) -> Dict[str, float]:
        """Calculate volume-based metrics."""
        voxel_volume = np.prod(voxel_size)
        total_volume = np.prod(data.shape) * voxel_volume

        # Cell density
        cell_density = len(cells) / total_volume if total_volume > 0 else 0

        # Tissue volume
        tissue_mask = data > np.percentile(data, 20)
        tissue_volume = np.sum(tissue_mask) * voxel_volume

        metrics = {
            'total_volume_um3': float(total_volume),
            'tissue_volume_um3': float(tissue_volume),
            'cell_density_per_mm3': float(cell_density * 1e9),  # Convert to mm³
            'tissue_fraction': float(tissue_volume / total_volume)
        }

        if vessels is not None:
            vessel_volume = np.sum(vessels) * voxel_volume
            metrics['vessel_volume_um3'] = float(vessel_volume)
            metrics['vessel_fraction'] = float(vessel_volume / tissue_volume) if tissue_volume > 0 else 0

        return metrics

    def _analyze_spatial_distribution(self, cells: List, volume_shape: Tuple,
                                     voxel_size: Tuple) -> Dict[str, float]:
        """Analyze spatial distribution of cells."""
        if len(cells) < 2:
            return {'clustering_index': 0, 'spatial_uniformity': 0}

        # Convert to physical coordinates
        cells_physical = np.array(cells) * np.array(voxel_size)

        # Nearest neighbor distances
        from scipy.spatial import distance_matrix

        # Limit for efficiency
        if len(cells_physical) > 100:
            indices = np.random.choice(len(cells_physical), 100, replace=False)
            cells_subset = cells_physical[indices]
        else:
            cells_subset = cells_physical

        dist_matrix = distance_matrix(cells_subset, cells_subset)
        np.fill_diagonal(dist_matrix, np.inf)

        nn_distances = np.min(dist_matrix, axis=1)

        # Clark-Evans index
        mean_nn = np.mean(nn_distances)
        volume = np.prod(volume_shape) * np.prod(voxel_size)
        density = len(cells) / volume
        expected_nn = 0.5 / (density ** (1/3)) if density > 0 else 0

        clark_evans = mean_nn / expected_nn if expected_nn > 0 else 1

        # Coefficient of variation
        cv = np.std(nn_distances) / mean_nn if mean_nn > 0 else 0

        return {
            'mean_nearest_neighbor_um': float(mean_nn),
            'clark_evans_index': float(clark_evans),
            'spatial_cv': float(cv),
            'clustering_index': float(1 / clark_evans) if clark_evans > 0 else 0
        }


class PhotoacousticImagingTool(NeuroToolWrapper):
    """Photoacoustic imaging analysis."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "photoacoustic_imaging"

    def get_tool_description(self) -> str:
        return "Analyze photoacoustic imaging data for deep tissue functional imaging"

    def get_args_schema(self):
        return OpticalInput

    def _run(
        self,
        imaging_data: Optional[np.ndarray] = None,
        wavelengths: Optional[List[float]] = None,
        sampling_rate: float = 50e6,  # 50 MHz typical for PA
        speed_of_sound: float = 1540.0,  # m/s in tissue
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Analyze photoacoustic imaging data."""
        try:
            output_path = Path(output_dir or "photoacoustic_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if imaging_data is None:
                data, wl = self._generate_synthetic_pa_data()
                wavelengths = wl
            else:
                data = imaging_data
                if wavelengths is None:
                    wavelengths = [532, 700, 800]  # Common PA wavelengths

            # Reconstruct images
            pa_images = self._reconstruct_pa_images(data, sampling_rate, speed_of_sound)

            # Spectroscopic unmixing
            components = self._spectroscopic_unmixing(pa_images, wavelengths)

            # Calculate oxygen saturation
            so2_map = self._calculate_oxygen_saturation(components)

            # Analyze vasculature
            vascular = self._analyze_vasculature(pa_images)

            # Signal quality
            quality = self._assess_pa_quality(pa_images)

            results = {
                'wavelengths': wavelengths,
                'sampling_rate': sampling_rate,
                'image_shape': pa_images.shape[:2] if len(pa_images.shape) > 2 else pa_images.shape,
                'spectroscopic_components': {
                    'hbo_fraction': float(np.mean(components.get('hbo', 0))),
                    'hbr_fraction': float(np.mean(components.get('hbr', 0)))
                },
                'oxygen_saturation': {
                    'mean_so2': float(np.mean(so2_map)),
                    'std_so2': float(np.std(so2_map))
                },
                'vascular_metrics': vascular,
                'signal_quality': quality
            }

            # Save results
            np.savez(
                output_path / "photoacoustic_results.npz",
                pa_images=pa_images,
                so2_map=so2_map
            )

            with open(output_path / "photoacoustic_analysis.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "pa_data": str(output_path / "photoacoustic_results.npz"),
                        "analysis": str(output_path / "photoacoustic_analysis.json")
                    }
                }
            )

        except Exception as e:
            logger.error(f"Photoacoustic imaging analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_pa_data(self) -> Tuple[np.ndarray, List[float]]:
        """Generate synthetic photoacoustic data."""
        # RF data dimensions: detectors x time x wavelengths
        n_detectors = 128
        n_samples = 2048
        wavelengths = [700, 800, 900]

        data = np.zeros((n_detectors, n_samples, len(wavelengths)))

        # Add PA signals (N-shaped pulses)
        n_sources = 20
        for _ in range(n_sources):
            # Source position
            depth = np.random.uniform(5, 50)  # mm
            lateral = np.random.uniform(-30, 30)  # mm

            for det in range(n_detectors):
                # Calculate time of flight
                det_pos = (det - n_detectors/2) * 0.5  # mm
                distance = np.sqrt((lateral - det_pos)**2 + depth**2)
                tof = int(distance / 1.54 * 50)  # samples (assuming 1.54 mm/μs and 50 MHz)

                if tof < n_samples - 10:
                    # N-shaped pulse
                    pulse = np.array([0, 1, 0, -1, 0])

                    for wl_idx in range(len(wavelengths)):
                        # Wavelength-dependent absorption
                        amplitude = np.random.uniform(0.5, 1.5) * (1 + 0.1 * wl_idx)
                        data[det, tof:tof+5, wl_idx] += amplitude * pulse

        # Add noise
        data += np.random.randn(*data.shape) * 0.1

        return data, wavelengths

    def _reconstruct_pa_images(self, data: np.ndarray, sampling_rate: float,
                              speed_of_sound: float) -> np.ndarray:
        """Reconstruct PA images using delay-and-sum beamforming."""
        if len(data.shape) == 3:
            n_detectors, n_samples, n_wavelengths = data.shape
        else:
            n_detectors, n_samples = data.shape
            n_wavelengths = 1
            data = data.reshape(n_detectors, n_samples, 1)

        # Image grid
        image_size = 128
        images = np.zeros((image_size, image_size, n_wavelengths))

        # Grid coordinates (mm)
        x = np.linspace(-30, 30, image_size)
        z = np.linspace(0, 60, image_size)

        # Detector positions
        det_x = np.linspace(-30, 30, n_detectors)

        # Delay-and-sum beamforming
        for wl in range(n_wavelengths):
            for i, xi in enumerate(x):
                for j, zj in enumerate(z):
                    pixel_value = 0

                    for det in range(n_detectors):
                        # Distance from pixel to detector
                        distance = np.sqrt((xi - det_x[det])**2 + zj**2)

                        # Time of flight (samples)
                        tof = int(distance / speed_of_sound * sampling_rate)

                        if tof < n_samples:
                            # Apply apodization
                            weight = 1 / (distance + 1)
                            pixel_value += data[det, tof, wl] * weight

                    images[j, i, wl] = pixel_value

        # Envelope detection
        from scipy.signal import hilbert
        for wl in range(n_wavelengths):
            images[:, :, wl] = np.abs(hilbert(images[:, :, wl], axis=0))

        return images

    def _spectroscopic_unmixing(self, pa_images: np.ndarray,
                               wavelengths: List[float]) -> Dict[str, np.ndarray]:
        """Unmix chromophores using spectroscopy."""
        # Simplified unmixing for HbO and HbR

        # Extinction coefficients (simplified, wavelength-dependent)
        extinction = {}
        for wl in wavelengths:
            # Approximate values
            if wl < 750:
                extinction[wl] = {'hbo': 0.5, 'hbr': 2.0}
            elif wl < 850:
                extinction[wl] = {'hbo': 1.0, 'hbr': 1.0}
            else:
                extinction[wl] = {'hbo': 2.0, 'hbr': 0.8}

        # Solve for concentrations
        if len(pa_images.shape) == 3 and pa_images.shape[2] >= 2:
            # Use first two wavelengths
            wl1, wl2 = wavelengths[0], wavelengths[1]

            # Build system of equations for each pixel
            hbo_map = np.zeros(pa_images.shape[:2])
            hbr_map = np.zeros(pa_images.shape[:2])

            for i in range(pa_images.shape[0]):
                for j in range(pa_images.shape[1]):
                    # PA signal = μa * Γ (Grüneisen parameter assumed constant)
                    signal = [pa_images[i, j, 0], pa_images[i, j, 1]]

                    # Extinction matrix
                    E = np.array([
                        [extinction[wl1]['hbo'], extinction[wl1]['hbr']],
                        [extinction[wl2]['hbo'], extinction[wl2]['hbr']]
                    ])

                    try:
                        conc = np.linalg.solve(E, signal)
                        hbo_map[i, j] = max(0, conc[0])
                        hbr_map[i, j] = max(0, conc[1])
                    except:
                        pass
        else:
            # Single wavelength - can't unmix
            hbo_map = pa_images if len(pa_images.shape) == 2 else pa_images[:, :, 0]
            hbr_map = np.zeros_like(hbo_map)

        return {'hbo': hbo_map, 'hbr': hbr_map}

    def _calculate_oxygen_saturation(self, components: Dict[str, np.ndarray]) -> np.ndarray:
        """Calculate oxygen saturation map."""
        hbo = components.get('hbo', np.zeros((128, 128)))
        hbr = components.get('hbr', np.zeros((128, 128)))

        total_hb = hbo + hbr
        so2 = np.zeros_like(hbo)

        mask = total_hb > 0
        so2[mask] = hbo[mask] / total_hb[mask]

        return so2

    def _analyze_vasculature(self, pa_images: np.ndarray) -> Dict[str, float]:
        """Analyze vascular structures."""
        # Use maximum intensity projection
        if len(pa_images.shape) == 3:
            mip = np.max(pa_images, axis=2)
        else:
            mip = pa_images

        # Vessel segmentation (threshold-based)
        threshold = np.percentile(mip, 90)
        vessels = mip > threshold

        # Morphological operations
        from scipy.ndimage import binary_closing, label
        vessels = binary_closing(vessels, iterations=2)

        # Label vessels
        labeled, n_vessels = label(vessels)

        # Calculate metrics
        vessel_density = np.sum(vessels) / vessels.size

        # Vessel diameter (simplified)
        from scipy.ndimage import distance_transform_edt
        if np.any(vessels):
            dist_transform = distance_transform_edt(vessels)
            mean_diameter = 2 * np.mean(dist_transform[vessels])
        else:
            mean_diameter = 0

        return {
            'vessel_density': float(vessel_density),
            'n_vessels': int(n_vessels),
            'mean_vessel_diameter_pixels': float(mean_diameter),
            'vascular_volume_fraction': float(vessel_density)
        }

    def _assess_pa_quality(self, pa_images: np.ndarray) -> Dict[str, float]:
        """Assess photoacoustic image quality."""
        if len(pa_images.shape) == 3:
            image = np.mean(pa_images, axis=2)
        else:
            image = pa_images

        # SNR
        signal = np.mean(image[image > np.percentile(image, 75)])
        noise = np.std(image[image < np.percentile(image, 25)])
        snr = signal / (noise + 1e-10)

        # Contrast
        high = np.percentile(image, 95)
        low = np.percentile(image, 5)
        contrast = (high - low) / (high + low + 1e-10)

        # Resolution (edge sharpness)
        from scipy.ndimage import sobel
        edges = np.sqrt(sobel(image, axis=0)**2 + sobel(image, axis=1)**2)
        sharpness = np.mean(edges)

        return {
            'snr': float(snr),
            'contrast': float(contrast),
            'edge_sharpness': float(sharpness),
            'quality_index': float(snr * contrast)
        }


class OpticalImagingTools:
    """Collection of optical imaging analysis tools."""

    def __init__(self):
        self.tools = [
            CalciumImagingAnalysisTool(),
            IntrinsicSignalImagingTool(),
            VoltageImagingTool(),
            TwoPhotonMicroscopyTool(),
            OptogenecicsAnalysisTool(),
            fNIRSAnalysisTool(),
            LightSheetMicroscopyTool(),
            PhotoacousticImagingTool()
        ]

    def get_all_tools(self) -> List[NeuroToolWrapper]:
        """Get all optical imaging tools."""
        return self.tools