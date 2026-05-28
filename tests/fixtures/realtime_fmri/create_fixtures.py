#!/usr/bin/env python
"""Create test fixtures for real-time fMRI tools."""

import numpy as np
import json
from pathlib import Path

# Create fixture directory
fixture_dir = Path("tests/fixtures/realtime_fmri")
fixture_dir.mkdir(parents=True, exist_ok=True)

print("Creating test fixtures for real-time fMRI tools...")

# Generate realistic fMRI test data
n_timepoints = 200
n_voxels = 100

# Create time series data with some structure
np.random.seed(42)  # For reproducibility
data = np.random.randn(n_timepoints, n_voxels) * 0.5

# Add task-related signal to subset of voxels
task_voxels = 20
task_signal = np.sin(np.linspace(0, 4*np.pi, n_timepoints))
for i in range(task_voxels):
    data[:, i] += task_signal * (0.5 + 0.1 * np.random.randn())

# Create block design matrix
design = np.zeros((n_timepoints, 3))
design[:, 0] = 1  # intercept

# Task blocks (20 volumes on, 20 off)
for i in range(0, n_timepoints, 40):
    if i + 20 < n_timepoints:
        design[i:i+20, 1] = 1

# Add motion regressor
design[:, 2] = np.cumsum(np.random.randn(n_timepoints) * 0.01)

# Create contrasts
contrasts = {
    "task_vs_rest": [0, 1, 0],
    "main_effect": [0, 1, 0],
    "deactivation": [0, -1, 0]
}

# Save as JSON files
print(f"Saving JSON files to {fixture_dir}/")
with open(fixture_dir / "test_data.json", "w") as f:
    json.dump(data.tolist(), f)
    print("  ✓ test_data.json")

with open(fixture_dir / "test_design.json", "w") as f:
    json.dump(design.tolist(), f)
    print("  ✓ test_design.json")

with open(fixture_dir / "test_contrasts.json", "w") as f:
    json.dump(contrasts, f, indent=2)
    print("  ✓ test_contrasts.json")

# Save as NumPy files
print(f"Saving NumPy files to {fixture_dir}/")
np.save(fixture_dir / "test_data.npy", data)
print("  ✓ test_data.npy")

np.save(fixture_dir / "test_design.npy", design)
print("  ✓ test_design.npy")

np.save(fixture_dir / "test_contrast.npy", np.array(contrasts["task_vs_rest"]))
print("  ✓ test_contrast.npy")

# Create 3D volume for ROI monitoring
volume_shape = (64, 64, 35)
test_volume = np.random.randn(*volume_shape) * 0.5

# Create ROI masks
roi_masks = {}

# Motor cortex ROI (central region)
motor_mask = np.zeros(volume_shape, dtype=bool)
motor_mask[28:36, 28:36, 15:25] = True
roi_masks["motor"] = motor_mask

# Visual cortex ROI (posterior region)
visual_mask = np.zeros(volume_shape, dtype=bool)
visual_mask[28:36, 10:20, 15:25] = True
roi_masks["visual"] = visual_mask

# Prefrontal ROI (anterior region)
pfc_mask = np.zeros(volume_shape, dtype=bool)
pfc_mask[28:36, 44:54, 15:25] = True
roi_masks["prefrontal"] = pfc_mask

# Save ROI data
np.save(fixture_dir / "test_volume.npy", test_volume)
print("  ✓ test_volume.npy")

np.savez(fixture_dir / "roi_masks.npz", **roi_masks)
print("  ✓ roi_masks.npz")

# Create ROI timeseries for connectivity analysis
n_rois = 10
roi_timeseries = np.random.randn(n_timepoints, n_rois) * 0.3

# Add correlation structure between some ROIs
# ROIs 0-4 are correlated
common_signal = np.sin(np.linspace(0, 6*np.pi, n_timepoints))
for i in range(5):
    roi_timeseries[:, i] += common_signal * (0.5 + 0.1 * i)

# ROIs 5-7 are anti-correlated with 0-4
for i in range(5, 8):
    roi_timeseries[:, i] -= common_signal * 0.3

np.save(fixture_dir / "roi_timeseries.npy", roi_timeseries)
print("  ✓ roi_timeseries.npy")

# Create sample request JSON files for testing
glm_request = {
    "query": "run realtime GLM analysis with my test data",
    "params": {
        "data_file": str(fixture_dir / "test_data.npy"),
        "design_matrix_file": str(fixture_dir / "test_design.npy"),
        "contrast_file": str(fixture_dir / "test_contrast.npy"),
        "output_dir": str(fixture_dir / "outputs" / "glm")
    }
}

with open(fixture_dir / "glm_request.json", "w") as f:
    json.dump(glm_request, f, indent=2)
    print("  ✓ glm_request.json")

feedback_request = {
    "query": "control neurofeedback display",
    "params": {
        "activation_level": 0.7,
        "target_level": 0.5,
        "feedback_type": "visual",
        "output_dir": str(fixture_dir / "outputs" / "feedback")
    }
}

with open(fixture_dir / "feedback_request.json", "w") as f:
    json.dump(feedback_request, f, indent=2)
    print("  ✓ feedback_request.json")

connectivity_request = {
    "query": "compute real-time connectivity from ROI timeseries",
    "params": {
        "roi_timeseries": roi_timeseries[:50].tolist(),  # First 50 timepoints
        "method": "correlation",
        "window_size": 30,
        "output_dir": str(fixture_dir / "outputs" / "connectivity")
    }
}

with open(fixture_dir / "connectivity_request.json", "w") as f:
    json.dump(connectivity_request, f, indent=2)
    print("  ✓ connectivity_request.json")

print(f"\n✅ Created {12} test fixture files in {fixture_dir.absolute()}")
print("\nTest data summary:")
print(f"  - fMRI data: {n_timepoints} timepoints × {n_voxels} voxels")
print(f"  - Design matrix: {design.shape}")
print(f"  - Volume shape: {volume_shape}")
print(f"  - ROI timeseries: {n_timepoints} timepoints × {n_rois} ROIs")
print(f"  - ROI masks: {len(roi_masks)} regions")