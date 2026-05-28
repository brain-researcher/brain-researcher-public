#!/usr/bin/env python3
"""
Test Python-based neuroimaging tools with actual data generation.
This tests tools that don't require FSL installation.
"""

import sys
import os
import tempfile
import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

import pytest
from sklearn.exceptions import ConvergenceWarning

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.core.utils import configure_mne_environment

OUTPUT_BASE = REPO_ROOT / "outputs" / "test_outputs"
OUTPUT_BASE.mkdir(exist_ok=True)


def test_mne_preprocessing():
    """Test MNE preprocessing with generated EEG-like data."""
    print("\n" + "="*60)
    print("TESTING: MNE Preprocessing")
    print("="*60)
    
    try:
        configure_mne_environment()
        from brain_researcher.services.tools.mne_preprocessing_tool import MNEPreprocessingTool
        import mne
        
        tool = MNEPreprocessingTool()
        
        # Create synthetic EEG data
        output_dir = OUTPUT_BASE / "mne_preprocessing_test"
        output_dir.mkdir(exist_ok=True)
        
        # Generate raw data
        print("Generating synthetic EEG data...")
        sfreq = 256  # Sampling frequency
        times = np.arange(0, 10, 1/sfreq)  # 10 seconds
        n_channels = 32
        
        # Create channel names (standard 10-20 system subset)
        ch_names = [f'EEG{i:03d}' for i in range(1, n_channels + 1)]
        ch_types = ['eeg'] * n_channels
        
        # Generate synthetic data with some artifacts
        np.random.seed(42)
        data = np.random.randn(n_channels, len(times)) * 1e-6  # Convert to volts
        
        # Add some artificial artifacts
        # Eye blink at 2 seconds
        data[0:4, int(2*sfreq):int(2.2*sfreq)] += 50e-6
        
        # Line noise at 50 Hz
        for i in range(n_channels):
            data[i] += 5e-6 * np.sin(2 * np.pi * 50 * times)
        
        # Create MNE Raw object
        info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
        raw = mne.io.RawArray(data, info)
        
        # Save raw data
        raw_file = output_dir / "synthetic_raw.fif"
        raw.save(raw_file, overwrite=True)
        
        print(f"Created synthetic data: {n_channels} channels, {len(times)/sfreq:.1f} seconds")
        
        # Run preprocessing
        result = tool._run(
            raw_file=str(raw_file),
            output_dir=str(output_dir),
            l_freq=1.0,
            h_freq=40.0,
            notch_freq=50.0,
            reference="average",
            detect_bad_channels=False,
            interpolate_bads=False,
            save_format="fif",
            overwrite=True
        )
        
        assert result.status == "success", f"Preprocessing failed: {result.error}"
        print("✅ Preprocessing successful!")
        print(f"   Filtered: 1-40 Hz")
        print(f"   Notch filter: 50 Hz")
        print(f"   Reference: average")
        if 'statistics' in result.data:
            stats = result.data['statistics']
            print(f"   Duration: {stats.get('duration', 0):.1f}s")
            print(f"   Channels: {stats.get('n_channels', 0)}")
            print(f"   Bad channels detected: {stats.get('n_bad_channels', 0)}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(str(e))


def test_mne_ica_with_data():
    """Test MNE ICA with preprocessed data."""
    print("\n" + "="*60)
    print("TESTING: MNE ICA with Data")
    print("="*60)
    
    try:
        configure_mne_environment()
        from brain_researcher.services.tools.mne_ica_tool import MNEICATool
        import mne
        
        tool = MNEICATool()
        
        # Use preprocessed data from previous test
        preprocessed_file = OUTPUT_BASE / "mne_preprocessing_test" / "preprocessed_raw.fif"
        
        if not preprocessed_file.exists():
            print("⚠️  No preprocessed data found, generating new data...")
            # Generate simple data
            output_dir = OUTPUT_BASE / "mne_ica_test"
            output_dir.mkdir(exist_ok=True)
            
            sfreq = 256
            times = np.arange(0, 10, 1/sfreq)
            n_channels = 32
            
            ch_names = [f'EEG{i:03d}' for i in range(1, n_channels + 1)]
            ch_types = ['eeg'] * n_channels
            
            np.random.seed(42)
            data = np.random.randn(n_channels, len(times)) * 1e-6
            
            # Add artifacts
            # EOG-like artifact
            eog_signal = 20e-6 * np.sin(2 * np.pi * 0.5 * times)  # 0.5 Hz blink rate
            data[0:2] += eog_signal
            
            # ECG-like artifact
            ecg_signal = 10e-6 * np.sin(2 * np.pi * 1.2 * times)  # ~72 bpm
            data[10:12] += ecg_signal
            
            info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
            raw = mne.io.RawArray(data, info)
            
            preprocessed_file = output_dir / "test_raw.fif"
            raw.save(preprocessed_file, overwrite=True)
        else:
            output_dir = OUTPUT_BASE / "mne_ica_test"
            output_dir.mkdir(exist_ok=True)
        
        print(f"Using data: {preprocessed_file}")
        
        # Run ICA
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            result = tool._run(
                raw_file=str(preprocessed_file),
                output_dir=str(output_dir),
                n_components=15,
                method="fastica",
                detect_artifacts=["eog", "ecg"],
                plot_components=False,  # Disable plotting for test
                plot_sources=False,
                plot_overlay=False,
                save_ica=True,
                apply_ica=True,
                overwrite=True
            )

        assert result.status == "success", f"ICA failed: {result.error}"
        print("✅ ICA successful!")
        if 'artifact_components' in result.data:
            artifacts = result.data['artifact_components']
            print(f"   Total components excluded: {artifacts.get('total_excluded', 0)}")
            print(f"   Component indices: {artifacts.get('indices', [])}")
            if 'by_type' in artifacts:
                for artifact_type, indices in artifacts['by_type'].items():
                    if indices:
                        print(f"   {artifact_type.upper()}: {indices}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(str(e))


def test_mne_timefreq_with_epochs():
    """Test MNE Time-Frequency with epoched data."""
    print("\n" + "="*60)
    print("TESTING: MNE Time-Frequency with Epochs")
    print("="*60)
    
    try:
        configure_mne_environment()
        from brain_researcher.services.tools.mne_timefreq_tool import MNETimeFreqTool
        import mne
        
        tool = MNETimeFreqTool()
        
        output_dir = OUTPUT_BASE / "mne_timefreq_test"
        output_dir.mkdir(exist_ok=True)
        
        # Create synthetic epoched data
        print("Creating synthetic epoched data...")
        sfreq = 256
        n_epochs = 50
        n_channels = 32
        n_times = int(1.5 * sfreq)  # 1.5 seconds per epoch
        
        ch_names = [f'EEG{i:03d}' for i in range(1, n_channels + 1)]
        ch_types = ['eeg'] * n_channels
        
        # Generate epochs with different frequency components
        np.random.seed(42)
        epochs_data = []
        
        for epoch in range(n_epochs):
            epoch_data = np.random.randn(n_channels, n_times) * 1e-6
            
            # Add frequency components
            times = np.arange(n_times) / sfreq
            
            # Alpha (8-12 Hz)
            for ch in range(5, 15):
                epoch_data[ch] += 5e-6 * np.sin(2 * np.pi * 10 * times)
            
            # Beta (13-30 Hz)
            for ch in range(15, 25):
                epoch_data[ch] += 3e-6 * np.sin(2 * np.pi * 20 * times)
            
            epochs_data.append(epoch_data)
        
        epochs_data = np.array(epochs_data)
        
        # Create MNE Epochs object
        info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
        
        # Create events (all the same type for simplicity)
        events = np.column_stack([
            np.arange(n_epochs) * n_times,  # Sample number
            np.zeros(n_epochs, dtype=int),   # Previous event
            np.ones(n_epochs, dtype=int)     # Event ID
        ])
        
        epochs = mne.EpochsArray(epochs_data, info, events=events, tmin=-0.2)
        
        # Save epochs
        epochs_file = output_dir / "test_epochs_epo.fif"
        epochs.save(epochs_file, overwrite=True)
        
        print(f"Created {n_epochs} epochs, {n_channels} channels")
        
        # Run time-frequency analysis with adjusted parameters for short epochs
        result = tool._run(
            epochs_file=str(epochs_file),
            output_dir=str(output_dir),
            method="morlet",
            freq_min=4.0,
            freq_max=30.0,
            n_freqs=10,  # Reduced for shorter epochs
            n_cycles=3.0,  # Reduced cycles for shorter wavelets
            compute_psd=True,
            compute_band_power=True,
            plot_tfr=False,  # Disable plotting for test
            plot_topomap=False,
            save_format="npz"
        )
        
        assert result.status == "success", f"Time-frequency analysis failed: {result.error}"
        print("✅ Time-frequency analysis successful!")
        if 'analysis_info' in result.data:
            info = result.data['analysis_info']
            print(f"   Method: {info.get('method', 'unknown')}")
            print(f"   Frequencies: {info.get('n_frequencies', 0)}")
            print(f"   Frequency range: {info.get('freq_range', [])} Hz")
        if 'band_power' in result.data and result.data['band_power']:
            print("   Band powers computed:")
            for band, power in result.data['band_power'].items():
                mean_power = power.get('mean', 0)
                print(f"     {band}: {mean_power:.2e}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(str(e))


def test_statsmodels_glm_voxelwise():
    """Test Statsmodels GLM with simulated voxel-wise data."""
    print("\n" + "="*60)
    print("TESTING: Statsmodels GLM Voxel-wise")
    print("="*60)
    
    try:
        from brain_researcher.services.tools.statsmodels_glm_tool import StatsmodelsGLMTool
        import nibabel as nib
        
        tool = StatsmodelsGLMTool()
        
        output_dir = OUTPUT_BASE / "statsmodels_glm_voxelwise"
        output_dir.mkdir(exist_ok=True)
        
        # Create synthetic 4D fMRI data
        print("Creating synthetic fMRI data...")
        nx, ny, nz = 10, 10, 10  # Small volume for testing
        n_timepoints = 100
        
        # Generate data
        np.random.seed(42)
        data_4d = np.random.randn(nx, ny, nz, n_timepoints)
        
        # Add signal to some voxels
        # Region 1: responds to condition A
        data_4d[3:6, 3:6, 3:6, :] += np.random.randn(n_timepoints) * 0.5
        
        # Create NIfTI image
        affine = np.eye(4)
        img_4d = nib.Nifti1Image(data_4d, affine)
        
        # Save 4D data
        data_file = output_dir / "fmri_data.nii.gz"
        nib.save(img_4d, data_file)
        
        # Create design matrix
        design = pd.DataFrame({
            'intercept': np.ones(n_timepoints),
            'condition_A': np.zeros(n_timepoints),
            'condition_B': np.zeros(n_timepoints),
            'motion': np.random.randn(n_timepoints) * 0.1
        })
        
        # Add block design
        design.loc[10:30, 'condition_A'] = 1
        design.loc[40:60, 'condition_B'] = 1
        design.loc[70:90, 'condition_A'] = 1
        
        design_file = output_dir / "design_matrix.csv"
        design.to_csv(design_file, index=False)
        
        print(f"Created 4D data: {nx}x{ny}x{nz} voxels, {n_timepoints} timepoints")
        
        # Create brain mask
        mask = np.ones((nx, ny, nz))
        mask_img = nib.Nifti1Image(mask, affine)
        mask_file = output_dir / "brain_mask.nii.gz"
        nib.save(mask_img, mask_file)
        
        # Run voxel-wise GLM
        result = tool._run(
            data_file=str(data_file),
            design_matrix=str(design_file),
            output_dir=str(output_dir),
            mask_file=str(mask_file),
            family="gaussian",
            voxel_wise=True,
            correction_method="fdr",
            save_stats_maps=True
        )
        
        assert result.status == "success", f"Voxel-wise GLM failed: {result.error}"
        print("✅ Voxel-wise GLM successful!")
        if 'outputs' in result.data and 'stat_maps' in result.data['outputs']:
            stat_maps = result.data['outputs']['stat_maps']
            print(f"   Generated {len(stat_maps)} statistical maps")
            for map_file in stat_maps[:3]:  # Show first 3
                print(f"     - {Path(map_file).name}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(str(e))


def main():
    """Run all Python tool tests."""
    print("\n" + "="*60)
    print("TESTING PYTHON-BASED NEUROIMAGING TOOLS")
    print("="*60)
    print(f"Output: {OUTPUT_BASE}")
    
    results = []
    
    # Run tests
    print("\n🧪 Testing Tools with Generated Data...")
    
    results.append(("MNE Preprocessing", test_mne_preprocessing()))
    results.append(("MNE ICA", test_mne_ica_with_data()))
    results.append(("MNE Time-Frequency", test_mne_timefreq_with_epochs()))
    results.append(("Statsmodels GLM Voxel-wise", test_statsmodels_glm_voxelwise()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name:30} {status}")
    
    print(f"\nTotal: {len(results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    # Save results
    test_results = {
        "timestamp": datetime.now().isoformat(),
        "test_type": "python_tools_with_data",
        "results": [
            {"name": name, "passed": result}
            for name, result in results
        ],
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed
        }
    }
    
    results_file = OUTPUT_BASE / f"python_tools_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
