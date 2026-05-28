"""
Comprehensive test script for MEG/EEG neuroimaging tools.

This script tests various MEG and EEG analysis tools with real data from:
- ds000117: Face recognition MEG dataset
- MNE sample data: Auditory/visual MEG dataset
- Sleep-EDF: Sleep stage EEG dataset
"""

import json
import os
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytest

warnings.filterwarnings(
    "ignore",
    message=".*channels are marked as bad.*",
    category=UserWarning,
)

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import MEG/EEG tool implementations
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.mne_preprocessing_tool import (
    MNEPreprocessingTool, MNEPreprocessingArgs
)
from brain_researcher.services.tools.mne_ica_tool import (
    MNEICATool, MNEICAArgs
)
from brain_researcher.services.tools.mne_timefreq_tool import (
    MNETimeFreqTool, MNETimeFreqArgs
)
from brain_researcher.services.tools.mne_source_tool import (
    MNESourceLocalizationTool, MNESourceLocalizationArgs
)
from brain_researcher.services.tools.mne_connectivity_tool import (
    MNEConnectivityTool, MNEConnectivityArgs
)
from brain_researcher.services.tools.mne_fooof_tool import (
    MNEFOOOFTool, FOOOFArgs
)
from brain_researcher.services.tools.mne_autoreject_tool import (
    MNEAutorejectTool, AutorejectArgs
)
from brain_researcher.services.tools.temporal_decoding_tool import (
    TemporalDecodingTool, TemporalDecodingArgs
)
from brain_researcher.services.tools.searchlight_tool import (
    SearchlightTool, SearchlightArgs
)
from brain_researcher.services.tools.rsa_toolbox_tool import (
    RSAToolboxTool, RSAArgs
)
from brain_researcher.services.tools.eeg_preprocess_tool import EEGPreprocessTool
from brain_researcher.services.tools.epoch_events_tool import EpochEventsTool
from brain_researcher.services.tools.connectivity_measures_tool import ConnectivityMeasuresTool

# Dataset configurations
MEG_DATASET = "/app/data/openneuro/ds000117"
MNE_SAMPLE = "/app/data/mne/sample"
SLEEP_EDF = "/app/data/sleep_edf"
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs" / "meg_eeg")

# Create output directory
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

RUN_REAL_MEG_EEG = os.getenv("RUN_REAL_MEG_EEG") == "1"
REAL_DATA_ONLY = pytest.mark.skipif(
    not RUN_REAL_MEG_EEG,
    reason="real-data meg/eeg tool tests skipped (set RUN_REAL_MEG_EEG=1)",
)

# Performance tracking
performance_metrics = {
    "tool_timings": {},
    "memory_usage": {},
    "success_rate": {},
    "errors": [],
    "data_info": {}
}


def create_synthetic_eeg_data(output_dir: Path) -> tuple[str, str]:
    """Create synthetic EEG data + events for lightweight integration chains."""
    configure_mne_environment()
    import mne

    output_dir.mkdir(parents=True, exist_ok=True)
    sfreq = 200.0
    duration = 6.0
    n_channels = 32
    times = np.arange(0, duration, 1 / sfreq)
    data = np.random.randn(n_channels, times.size) * 1e-6
    for idx in range(n_channels):
        data[idx] += 0.5e-6 * np.sin(2 * np.pi * (8 + idx * 0.1) * times)

    montage = mne.channels.make_standard_montage("standard_1020")
    ch_names = montage.ch_names[:n_channels]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=["eeg"] * n_channels)
    raw = mne.io.RawArray(data, info, verbose=False)
    raw.set_montage(montage)
    raw.set_annotations(
        mne.Annotations(onset=[0.0], duration=[duration], description=["synthetic"])
    )

    raw_file = output_dir / "synthetic_raw.fif"
    raw.save(raw_file, overwrite=True, verbose=False)

    n_events = 10
    event_times = np.linspace(0.5, duration - 0.5, n_events)
    events = np.column_stack(
        [
            (event_times * sfreq).astype(int),
            np.zeros(n_events, dtype=int),
            np.ones(n_events, dtype=int),
        ]
    )
    events_file = output_dir / "synthetic_events.npy"
    np.save(events_file, events)

    return str(raw_file), str(events_file)


def test_light_eeg_chain_source_localization(tmp_path: Path):
    """Lightweight EEG chain that stays warning-free and exercises core tools."""
    raw_file, events_file = create_synthetic_eeg_data(tmp_path / "light_chain")

    preprocess_tool = EEGPreprocessTool()
    preprocess_result = preprocess_tool._run(
        raw_eeg=raw_file,
        montage_def="standard_1020",
        highpass_hz=1.0,
        lowpass_hz=40.0,
        output_dir=str(tmp_path / "light_chain"),
        reference="average",
    )
    assert preprocess_result.status == "success"
    clean_eeg = preprocess_result.data["outputs"]["clean_eeg"]

    epoch_tool = EpochEventsTool()
    epoch_result = epoch_tool._run(
        clean_eeg=clean_eeg,
        events_file=events_file,
        tmin=-0.2,
        tmax=0.8,
        output_dir=str(tmp_path / "light_chain"),
    )
    assert epoch_result.status == "success"
    epochs_file = epoch_result.data["outputs"]["epochs"]

    conn_tool = ConnectivityMeasuresTool()
    conn_result = conn_tool._run(
        epochs=epochs_file,
        method="pli",
        fmin=8.0,
        fmax=13.0,
        output_dir=str(tmp_path / "light_chain"),
    )
    assert conn_result.status == "success"

    fooof_tool = MNEFOOOFTool()
    fooof_result = fooof_tool._run(
        raw_file=clean_eeg,
        freq_range=(1.0, 40.0),
        output_dir=str(tmp_path / "light_chain" / "fooof"),
        save_report=False,
        save_plots=False,
        save_model=True,
    )
    assert fooof_result.status == "success"

    source_tool = MNESourceLocalizationTool()
    source_result = source_tool._run(
        epochs_file=epochs_file,
        subjects_dir=str(tmp_path / "light_chain" / "subjects"),
        subject="fsaverage",
        output_dir=str(tmp_path / "light_chain" / "source"),
        save_inverse=True,
        save_stc=True,
    )
    assert source_result.status == "success"


def _make_epochs_file(raw_file: str, output_dir: Path) -> str:
    """Create epochs from a raw FIF/EDF file for downstream MEG/EEG tools."""
    configure_mne_environment()
    import mne

    output_dir.mkdir(parents=True, exist_ok=True)
    raw = mne.io.read_raw(raw_file, preload=True, verbose=False)
    events = mne.make_fixed_length_events(raw, duration=2.0, id=1)
    epochs = mne.Epochs(
        raw,
        events,
        tmin=0.0,
        tmax=1.0,
        baseline=None,
        preload=True,
        reject_by_annotation=False,
        verbose=False,
    )
    epochs_path = output_dir / f"{Path(raw_file).stem}_epo.fif"
    epochs.save(epochs_path, overwrite=True)
    return str(epochs_path)


def _make_subset_raw(raw_file: str, output_dir: Path, n_channels: int = 10, tmax: float = 30.0) -> str:
    """Create a smaller raw file to keep connectivity computations fast."""
    configure_mne_environment()
    import mne

    output_dir.mkdir(parents=True, exist_ok=True)
    raw = mne.io.read_raw(raw_file, preload=True, verbose=False)
    picks = mne.pick_types(raw.info, eeg=True, meg=True, exclude="bads")
    if picks.size == 0:
        picks = mne.pick_types(raw.info, meg=True, eeg=False, exclude="bads")
    picks = picks[:n_channels]
    raw = raw.copy().pick(picks)
    if raw.times.size > 1:
        raw.crop(tmin=0.0, tmax=min(tmax, raw.times[-1]), include_tmax=True)
    subset_path = output_dir / f"{Path(raw_file).stem}_subset_raw.fif"
    raw.save(subset_path, overwrite=True, verbose=False)
    return str(subset_path)


def print_section(title: str, level: int = 1):
    """Print a formatted section header."""
    if level == 1:
        print("\n" + "=" * 70)
        print(f" {title}")
        print("=" * 70)
    elif level == 2:
        print("\n" + "-" * 60)
        print(f" {title}")
        print("-" * 60)
    else:
        print(f"\n### {title}")


def measure_performance(func):
    """Decorator to measure function performance."""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            import psutil
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024  # MB
        except ImportError:
            mem_before = 0
        
        result = func(*args, **kwargs)
        
        elapsed_time = time.time() - start_time
        try:
            mem_after = process.memory_info().rss / 1024 / 1024  # MB
            mem_used = mem_after - mem_before
        except:
            mem_used = 0
        
        func_name = func.__name__
        performance_metrics["tool_timings"][func_name] = elapsed_time
        performance_metrics["memory_usage"][func_name] = mem_used
        
        print(f"⏱️  Time: {elapsed_time:.2f}s | 💾 Memory: {mem_used:.1f}MB")
        
        return result
    return wrapper


def handle_result(result, tool_name: str) -> bool:
    """Process and display tool result."""
    success = False
    
    if hasattr(result, 'status'):
        success = result.status == "success"
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {tool_name}: {result.status}")
        
        if result.data:
            if isinstance(result.data, dict):
                # Show key metrics
                for key in ["n_channels", "n_samples", "n_components", "n_epochs", 
                           "frequencies", "n_sources", "connectivity_shape"]:
                    if key in result.data:
                        print(f"  {key}: {result.data[key]}")
        
        if result.error:
            print(f"  ⚠️ Error: {result.error}")
            performance_metrics["errors"].append({
                "tool": tool_name,
                "error": str(result.error)
            })
    else:
        success = result.get("success", False)
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {tool_name}")
        
        if result.get("message"):
            print(f"  Message: {result['message'][:200]}")
    
    return success


@measure_performance
def _run_mne_preprocessing():
    """Test MNE preprocessing on MEG data."""
    print_section("MNE Preprocessing - MEG Data", 2)
    
    tool = MNEPreprocessingTool()
    
    # Find MEG file
    meg_file = None
    if os.path.exists(MEG_DATASET):
        # Look for first available MEG file
        for root, dirs, files in os.walk(MEG_DATASET):
            for file in files:
                if file.endswith('.fif'):
                    meg_file = os.path.join(root, file)
                    break
            if meg_file:
                break
    
    # Fallback to MNE sample data
    if not meg_file or not os.path.exists(meg_file):
        meg_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"
    
    if not os.path.exists(meg_file):
        print(f"⚠️ MEG file not found: {meg_file}")
        return False
    
    print(f"  Using MEG file: {os.path.basename(meg_file)}")
    
    args = MNEPreprocessingArgs(
        raw_file=meg_file,
        output_dir=os.path.join(OUTPUT_DIR, "preprocessed_meg"),
        l_freq=1.0,
        h_freq=40.0,
        detect_bad_channels=False,
        interpolate_bads=False,
        reject={"mag": 4e-12, "grad": 4000e-13},
        flat=None,
        bad_channels=[],
        reference="average",
    )
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = tool._run(**args.model_dump())
    success = handle_result(result, "MNE Preprocessing")
    
    # Store data info
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["preprocessing"] = {
            "file": meg_file,
            "n_channels": result.data.get("n_channels"),
            "duration": result.data.get("duration"),
            "sampling_rate": result.data.get("sfreq")
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_preprocessing():
    assert _run_mne_preprocessing()


@measure_performance
def _run_mne_ica():
    """Test MNE ICA decomposition."""
    print_section("MNE ICA - Component Analysis", 2)
    
    tool = MNEICATool()
    
    # Use MNE sample data
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"

    if not os.path.exists(raw_file):
        print(f"⚠️ Raw file not found: {raw_file}")
        return False

    args = MNEICAArgs(
        raw_file=raw_file,
        output_dir=os.path.join(OUTPUT_DIR, "ica"),
        n_components=25,
        method="fastica",
        random_state=42,
        max_iter=200,
        fit_params=None,
        reject={"mag": 4e-12, "grad": 4000e-13},
        plot_components=False,
        plot_sources=False,
        plot_overlay=False,
        overwrite=True,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "MNE ICA")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["ica"] = {
            "n_components": result.data.get("n_components"),
            "method": "fastica",
            "explained_variance": result.data.get("explained_variance")
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_ica():
    assert _run_mne_ica()


@measure_performance
def _run_mne_timefreq():
    """Test MNE time-frequency analysis."""
    print_section("MNE Time-Frequency - Spectral Analysis", 2)
    
    tool = MNETimeFreqTool()
    
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"
    
    if not os.path.exists(raw_file):
        print(f"⚠️ Raw file not found: {raw_file}")
        return False

    epochs_file = _make_epochs_file(raw_file, Path(OUTPUT_DIR) / "timefreq_epochs")
    
    # Define frequency bands
    freqs = np.logspace(np.log10(4), np.log10(40), 20)
    
    args = MNETimeFreqArgs(
        epochs_file=epochs_file,
        output_dir=os.path.join(OUTPUT_DIR, "timefreq"),
        method="multitaper",
        freqs=freqs.tolist(),
        n_cycles=(freqs / 2).tolist(),  # Adaptive cycles
        time_bandwidth=4.0,
        average=True,
        return_itc=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "MNE Time-Frequency")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["timefreq"] = {
            "method": "multitaper",
            "n_frequencies": len(freqs),
            "freq_range": [freqs.min(), freqs.max()]
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_timefreq():
    assert _run_mne_timefreq()


@measure_performance
def _run_mne_source_localization():
    """Test MNE source localization."""
    print_section("MNE Source Localization", 2)
    
    tool = MNESourceLocalizationTool()
    
    # Use MNE sample data with pre-computed forward solution
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"
    fwd_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis-meg-oct-6-fwd.fif"
    
    if not os.path.exists(raw_file) or not os.path.exists(fwd_file):
        print("⚠️ Required files not found for source localization")
        return False
    
    args = MNESourceLocalizationArgs(
        raw_file=raw_file,
        subjects_dir=f"{MNE_SAMPLE}/subjects",
        subject="sample",
        output_dir=os.path.join(OUTPUT_DIR, "source_localization"),
        forward_file=fwd_file,
        method="dSPM",
        pick_ori="normal",
        depth=0.8,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "MNE Source Localization")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["source"] = {
            "method": "dSPM",
            "n_sources": result.data.get("n_sources"),
            "lambda2": result.data.get("lambda2")
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_source_localization():
    assert _run_mne_source_localization()


@measure_performance
def _run_mne_connectivity():
    """Test MNE connectivity analysis."""
    print_section("MNE Connectivity Analysis", 2)
    
    tool = MNEConnectivityTool()
    
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"
    
    if not os.path.exists(raw_file):
        print(f"⚠️ Raw file not found: {raw_file}")
        return False
    
    subset_raw = _make_subset_raw(raw_file, Path(OUTPUT_DIR) / "connectivity_subset")

    args = MNEConnectivityArgs(
        raw_file=subset_raw,
        output_dir=os.path.join(OUTPUT_DIR, "connectivity"),
        method="coherence",
        mode="multitaper",
        fmin=[8, 13],  # Alpha and beta bands
        fmax=[13, 30],
        faverage=True,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "MNE Connectivity")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["connectivity"] = {
            "method": "coherence",
            "freq_bands": ["alpha", "beta"],
            "connectivity_shape": result.data.get("connectivity_shape")
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_connectivity():
    assert _run_mne_connectivity()


@measure_performance
def _run_mne_fooof():
    """Test FOOOF spectral parameterization."""
    print_section("FOOOF - Spectral Parameterization", 2)
    
    tool = MNEFOOOFTool()
    
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"
    
    if not os.path.exists(raw_file):
        print(f"⚠️ Raw file not found: {raw_file}")
        return False
    
    args = FOOOFArgs(
        raw_file=raw_file,
        output_dir=os.path.join(OUTPUT_DIR, "fooof"),
        freq_range=(2.0, 40.0),
        peak_width_limits=(0.5, 12.0),
        max_n_peaks=8,
        min_peak_height=0.0,
        peak_threshold=2.0,
        aperiodic_mode="fixed",
        save_report=False,
        save_plots=False,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "FOOOF")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["fooof"] = {
            "freq_range": [2, 40],
            "aperiodic_params": result.data.get("aperiodic_params"),
            "n_peaks": result.data.get("n_peaks", 0)
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_fooof():
    assert _run_mne_fooof()


@measure_performance
def _run_mne_autoreject():
    """Test Autoreject for automated artifact rejection."""
    print_section("Autoreject - Automated QC", 2)
    
    tool = MNEAutorejectTool()
    
    raw_file = f"{MNE_SAMPLE}/MEG/sample/sample_audvis_raw.fif"

    if not os.path.exists(raw_file):
        print(f"⚠️ Raw file not found: {raw_file}")
        return False

    epochs_file = _make_epochs_file(raw_file, Path(OUTPUT_DIR) / "autoreject_epochs")

    args = AutorejectArgs(
        epochs_file=epochs_file,
        output_dir=os.path.join(OUTPUT_DIR, "autoreject"),
        n_interpolate=[1, 4, 8],
        consensus=[0.1, 0.3, 0.5],
        cv=5,
        thresh_method="bayesian_optimization",
        n_jobs=2,
        random_state=42,
        verbose=True,
        save_plots=False,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Autoreject")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["autoreject"] = {
            "n_bad_channels": result.data.get("n_bad_channels", 0),
            "n_interpolated": result.data.get("n_interpolated", 0),
            "rejection_threshold": result.data.get("threshold")
        }
    
    return success


@REAL_DATA_ONLY
def test_mne_autoreject():
    assert _run_mne_autoreject()


@measure_performance
def _run_sleep_eeg_analysis():
    """Test sleep EEG analysis tools."""
    print_section("Sleep EEG Analysis", 2)
    
    # Find sleep EDF file
    sleep_file = None
    if os.path.exists(SLEEP_EDF):
        for root, dirs, files in os.walk(SLEEP_EDF):
            for file in files:
                if file.endswith('.edf') and 'PSG' in file:
                    sleep_file = os.path.join(root, file)
                    break
            if sleep_file:
                break
    
    if not sleep_file or not os.path.exists(sleep_file):
        print("⚠️ Sleep EDF file not found")
        return False
    
    print(f"  Using sleep file: {os.path.basename(sleep_file)}")
    
    # Test preprocessing on sleep data
    tool = MNEPreprocessingTool()
    
    args = MNEPreprocessingArgs(
        raw_file=sleep_file,
        output_dir=os.path.join(OUTPUT_DIR, "preprocessed_sleep"),
        l_freq=0.5,
        h_freq=35.0,
        detect_bad_channels=False,
        interpolate_bads=False,
        reject=None,  # Sleep data has different scales
        flat=None,
        bad_channels=[],
        reference="average",
        baseline=None
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Sleep EEG Preprocessing")
    
    # Store sleep data info
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["sleep"] = {
            "file": sleep_file,
            "n_channels": result.data.get("n_channels"),
            "duration": result.data.get("duration"),
            "sampling_rate": result.data.get("sfreq")
        }
    
    return success


@REAL_DATA_ONLY
def test_sleep_eeg_analysis():
    assert _run_sleep_eeg_analysis()


@measure_performance
def _run_temporal_decoding():
    """Test temporal decoding on MEG data."""
    print_section("Temporal Decoding - MEG Classification", 2)
    
    tool = TemporalDecodingTool()
    
    output_dir = Path(OUTPUT_DIR) / "temporal_decoding"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create synthetic data/labels for demonstration
    n_samples = 200
    n_features = 20
    rng = np.random.default_rng(42)
    data = rng.normal(size=(n_samples, n_features))
    labels = rng.integers(0, 2, size=n_samples)

    data_file = output_dir / "temporal_data.npy"
    labels_file = output_dir / "temporal_labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    args = TemporalDecodingArgs(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(output_dir),
        classifier="lda",
        cv_folds=5,
        random_state=42,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Temporal Decoding")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["decoding"] = {
            "classifier": "lda",
            "mean_accuracy": result.data.get("summary", {}).get("mean_accuracy"),
            "n_windows": result.data.get("summary", {}).get("n_windows"),
        }
    
    return success


@REAL_DATA_ONLY
def test_temporal_decoding():
    assert _run_temporal_decoding()


@measure_performance
def _run_rsa_analysis():
    """Test RSA (Representational Similarity Analysis)."""
    print_section("RSA - Pattern Analysis", 2)
    
    tool = RSAToolboxTool()
    
    # Create synthetic neural data for demonstration
    n_conditions = 10
    n_voxels = 100
    n_timepoints = 50
    
    # Generate patterns with structure
    np.random.seed(42)
    patterns = []
    for i in range(n_conditions):
        # Create patterns with systematic differences
        base_pattern = np.random.randn(n_voxels)
        noise = np.random.randn(n_voxels) * 0.5
        patterns.append(base_pattern + i * 0.1 + noise)
    
    patterns = np.array(patterns)
    
    output_dir = Path(OUTPUT_DIR) / "rsa"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_file = output_dir / "patterns.npy"
    np.save(data_file, patterns)

    args = RSAArgs(
        data_file=str(data_file),
        analysis_type="pattern",
        distance_metric="correlation",
        n_conditions=n_conditions,
        n_permutations=100,
        output_dir=str(output_dir),
        plot_rdm=False,
        plot_mds=False,
        plot_dendogram=False,
        save_rdm=True,
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "RSA Analysis")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["data_info"]["rsa"] = {
            "n_conditions": n_conditions,
            "n_voxels": n_voxels,
            "metric": "correlation",
            "rdm_shape": result.data.get("rdm_shape")
        }
    
    return success


@REAL_DATA_ONLY
def test_rsa_analysis():
    assert _run_rsa_analysis()


@REAL_DATA_ONLY
def test_meg_eeg_pipeline():
    """Test complete MEG/EEG analysis pipeline."""
    print_section("MEG/EEG Analysis Pipeline", 1)
    
    print("Pipeline: Preprocessing → ICA → Time-Frequency → Connectivity → FOOOF")
    
    pipeline_results = {}
    
    # Step 1: Preprocessing
    print_section("Step 1: Preprocessing", 3)
    preproc_success = _run_mne_preprocessing()
    pipeline_results["preprocessing"] = preproc_success
    
    # Step 2: ICA
    print_section("Step 2: ICA Decomposition", 3)
    ica_success = _run_mne_ica()
    pipeline_results["ica"] = ica_success
    
    # Step 3: Time-Frequency
    print_section("Step 3: Time-Frequency Analysis", 3)
    tf_success = _run_mne_timefreq()
    pipeline_results["timefreq"] = tf_success
    
    # Step 4: Connectivity
    print_section("Step 4: Connectivity Analysis", 3)
    conn_success = _run_mne_connectivity()
    pipeline_results["connectivity"] = conn_success
    
    # Step 5: FOOOF
    print_section("Step 5: Spectral Parameterization", 3)
    fooof_success = _run_mne_fooof()
    pipeline_results["fooof"] = fooof_success
    
    # Summary
    print_section("Pipeline Summary", 2)
    total_steps = len(pipeline_results)
    successful_steps = sum(pipeline_results.values())
    
    for step, success in pipeline_results.items():
        status = "✅" if success else "❌"
        print(f"  {status} {step}")
    
    print(f"\nPipeline Success Rate: {successful_steps}/{total_steps} ({successful_steps/total_steps*100:.1f}%)")
    
    assert all(pipeline_results.values())


def generate_report():
    """Generate comprehensive test report."""
    print_section("Generating Test Report", 1)
    
    report = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "datasets": {
            "MEG": "ds000117 (Face Recognition)",
            "MNE_Sample": "Auditory/Visual MEG",
            "Sleep_EDF": "Sleep Stage EEG"
        },
        "output_directory": OUTPUT_DIR,
        "performance_metrics": performance_metrics,
        "tool_categories": {
            "MNE Core": ["Preprocessing", "ICA", "Time-Frequency", "Source", "Connectivity"],
            "Advanced MNE": ["FOOOF", "Autoreject", "Temporal Decoding"],
            "Pattern Analysis": ["RSA", "Searchlight"],
            "Sleep Analysis": ["Sleep EEG Processing"]
        }
    }
    
    # Calculate overall statistics
    total_tests = len(performance_metrics["tool_timings"])
    successful_tests = sum(1 for tool in performance_metrics.get("success_rate", {}).values() if tool)
    
    report["summary"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "success_rate": successful_tests / total_tests * 100 if total_tests > 0 else 0,
        "total_time": sum(performance_metrics["tool_timings"].values()),
        "total_memory": sum(performance_metrics["memory_usage"].values()),
        "errors_count": len(performance_metrics["errors"]),
        "data_info": performance_metrics["data_info"]
    }
    
    # Save JSON report
    report_file = os.path.join(OUTPUT_DIR, "test_report_meg_eeg.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"📊 Report saved to: {report_file}")
    
    # Generate markdown report
    md_report = f"""# MEG/EEG Tools Test Report

## Test Summary
- **Date**: {report['test_date']}
- **Datasets**: 
  - MEG: {report['datasets']['MEG']}
  - MNE Sample: {report['datasets']['MNE_Sample']}
  - Sleep EDF: {report['datasets']['Sleep_EDF']}

## Performance Metrics
- **Total Tests**: {report['summary']['total_tests']}
- **Successful**: {report['summary']['successful_tests']}
- **Success Rate**: {report['summary']['success_rate']:.1f}%
- **Total Time**: {report['summary']['total_time']:.2f} seconds
- **Total Memory**: {report['summary']['total_memory']:.1f} MB

## Data Processing Summary
"""
    
    for tool, info in performance_metrics["data_info"].items():
        md_report += f"\n### {tool.title()}\n"
        for key, value in info.items():
            if isinstance(value, str) and '/' in value:
                value = os.path.basename(value)
            md_report += f"- {key}: {value}\n"
    
    md_report += "\n## Tool Timings\n"
    for tool, timing in sorted(performance_metrics["tool_timings"].items()):
        md_report += f"- {tool}: {timing:.2f}s\n"
    
    if performance_metrics["errors"]:
        md_report += "\n## Errors Encountered\n"
        for error in performance_metrics["errors"]:
            md_report += f"- **{error['tool']}**: {error['error']}\n"
    
    md_file = os.path.join(OUTPUT_DIR, "test_report_meg_eeg.md")
    with open(md_file, 'w') as f:
        f.write(md_report)
    
    print(f"📝 Markdown report saved to: {md_file}")
    
    return report


def main():
    """Run comprehensive MEG/EEG tool tests."""
    print("\n" + "🧠" * 25)
    print("  MEG/EEG NEUROIMAGING TOOLS TEST SUITE")
    print("  Datasets: ds000117, MNE Sample, Sleep-EDF")
    print("🧠" * 25)
    
    # Initialize registry
    print_section("Initializing Tool Registry")
    registry = ToolRegistry(auto_discover=True)
    print(f"Total tools available: {len(registry.tools)}")
    
    # Track results
    all_results = {}
    
    # Run individual tool tests
    print_section("Individual Tool Tests", 1)
    
    # MNE Core Tools
    print_section("MNE Core Processing Tools", 2)
    all_results["mne_preprocessing"] = test_mne_preprocessing()
    all_results["mne_ica"] = test_mne_ica()
    all_results["mne_timefreq"] = test_mne_timefreq()
    all_results["mne_source"] = test_mne_source_localization()
    all_results["mne_connectivity"] = test_mne_connectivity()
    
    # Advanced MNE Tools
    print_section("Advanced MNE Analysis Tools", 2)
    all_results["mne_fooof"] = test_mne_fooof()
    all_results["mne_autoreject"] = test_mne_autoreject()
    all_results["temporal_decoding"] = test_temporal_decoding()
    
    # Pattern Analysis
    print_section("Pattern Analysis Tools", 2)
    all_results["rsa"] = test_rsa_analysis()
    
    # Sleep Analysis
    print_section("Sleep EEG Analysis", 2)
    all_results["sleep_eeg"] = test_sleep_eeg_analysis()
    
    # Update success rates
    performance_metrics["success_rate"] = all_results
    
    # Run integration pipeline
    pipeline_results = test_meg_eeg_pipeline()
    all_results["pipeline"] = all(pipeline_results.values())
    
    # Generate report
    report = generate_report()
    
    # Final summary
    print_section("FINAL TEST SUMMARY", 1)
    
    total = len(all_results)
    passed = sum(all_results.values())
    
    print(f"\n📊 Overall Results:")
    print(f"  Total Tests: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {total - passed}")
    print(f"  Success Rate: {passed/total*100:.1f}%")
    
    print(f"\n📁 Output Directory: {OUTPUT_DIR}")
    print(f"📊 Reports Generated:")
    print(f"  - test_report_meg_eeg.json")
    print(f"  - test_report_meg_eeg.md")
    
    return all_results


if __name__ == "__main__":
    try:
        results = main()
        sys.exit(0 if all(results.values()) else 1)
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        traceback.print_exc()
        sys.exit(1)
