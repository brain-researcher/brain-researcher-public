#!/usr/bin/env python3
"""
Test cases for the reorganized Nilearn tools using real data from the dataset directory.

Dataset: OpenNeuro ds000114 - Test-retest reliability of fMRI motor, language, and spatial tasks
Tasks include: fingerfootlips (motor), covertverbgeneration, overtverbgeneration (language), etc.
"""

import json
import os
from pathlib import Path

# Base paths
DATASET_PATH = "/app/data"
OUTPUT_DIR = "/tmp/nilearn_test_outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Test cases for the reorganized Nilearn tools
test_cases = [
    {
        "id": "test_1_preprocessing",
        "description": "Extract and clean time series from motor task fMRI",
        "tool": "nifti_masker",
        "params": {
            "img": f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz",
            "mask_img": "compute",
            "standardize": True,
            "detrend": True,
            "high_pass": 0.01,
            "t_r": 2.5,
            "smoothing_fwhm": 6.0,
            "output_file": f"{OUTPUT_DIR}/motor_cleaned_signals.npy"
        },
        "expected": "Extract cleaned signals from motor task data"
    },

    {
        "id": "test_2_roi_extraction",
        "description": "Extract ROI signals using AAL atlas from language task",
        "tool": "roi_extraction",
        "params": {
            "img": f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-covertverbgeneration_bold.nii.gz",
            "atlas": "AAL",
            "extract_type": "mean",
            "standardize": True,
            "high_pass": 0.01,
            "t_r": 2.5,
            "output_file": f"{OUTPUT_DIR}/language_roi_signals.npy",
            "labels_file": f"{OUTPUT_DIR}/aal_labels.txt"
        },
        "expected": "Extract mean signals from AAL regions during language task"
    },

    {
        "id": "test_3_connectivity_matrix",
        "description": "Compute functional connectivity matrix from preprocessed signals",
        "tool": "connectivity_matrix",
        "params": {
            "timeseries": f"{OUTPUT_DIR}/language_roi_signals.npy",
            "kind": "correlation",
            "fisher_z": True,
            "vectorize": False,
            "output_file": f"{OUTPUT_DIR}/connectivity_matrix.npy"
        },
        "expected": "Generate correlation matrix with Fisher z-transform"
    },

    {
        "id": "test_4_seed_connectivity",
        "description": "Compute PCC seed-based connectivity for default mode network",
        "tool": "seed_based_fc",
        "params": {
            "img": f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-overtverbgeneration_bold.nii.gz",
            "seed_coords": [0, -52, 18],  # PCC coordinates
            "radius": 8.0,
            "standardize": True,
            "high_pass": 0.01,
            "t_r": 2.5,
            "smoothing_fwhm": 6.0,
            "output_file": f"{OUTPUT_DIR}/pcc_connectivity_map.nii.gz"
        },
        "expected": "Generate whole-brain connectivity map from PCC seed"
    },

    {
        "id": "test_5_glm_first_level",
        "description": "Run first-level GLM on motor task (fingerfootlips)",
        "tool": "glm_first_level",
        "params": {
            "img": f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz",
            "t_r": 2.5,
            "hrf_model": "spm",
            "drift_model": "cosine",
            "high_pass": 0.01,
            "mask_img": "compute",
            "smoothing_fwhm": 6.0,
            "standardize": True,
            "noise_model": "ar1",
            "output_dir": f"{OUTPUT_DIR}/glm_motor"
        },
        "expected": "Fit GLM model to motor task data"
    },

    {
        "id": "test_6_visualization",
        "description": "Visualize statistical map from connectivity analysis",
        "tool": "viz_stat_maps",
        "params": {
            "stat_map": f"{OUTPUT_DIR}/pcc_connectivity_map.nii.gz",
            "bg_img": "MNI152",
            "threshold": 2.3,
            "cmap": "cold_hot",
            "display_mode": "ortho",
            "cut_coords": [0, -52, 18],
            "title": "PCC Seed Connectivity",
            "output_file": f"{OUTPUT_DIR}/pcc_connectivity_plot.png"
        },
        "expected": "Create orthogonal slices visualization of connectivity map"
    },

    {
        "id": "test_7_mvpa_decoding",
        "description": "Decode motor vs language tasks using SVM",
        "tool": "decoding_classifier",
        "params": {
            "img": [
                f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz",
                f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-covertverbgeneration_bold.nii.gz"
            ],
            "labels": ["motor", "language"],
            "classifier": "svc",
            "cv_folds": 5,
            "standardize": True,
            "smoothing_fwhm": 8.0,
            "feature_selection": "anova",
            "n_features": 500,
            "output_dir": f"{OUTPUT_DIR}/mvpa_results"
        },
        "expected": "Classify motor vs language task patterns"
    },

    {
        "id": "test_8_surface_projection",
        "description": "Project activation map to cortical surface",
        "tool": "surface_projection",
        "params": {
            "volume_img": f"{OUTPUT_DIR}/pcc_connectivity_map.nii.gz",
            "surf_mesh": "fsaverage5",
            "hemi": "both",
            "kind": "line",
            "view": "lateral",
            "colorbar": True,
            "output_file": f"{OUTPUT_DIR}/surface_projection.npz"
        },
        "expected": "Project volumetric data to fsaverage5 surface"
    },

    {
        "id": "test_9_confound_cleaning",
        "description": "Comprehensive confound removal with CompCor",
        "tool": "clean_confounds",
        "params": {
            "img": f"{DATASET_PATH}/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-linebisection_bold.nii.gz",
            "confounds": f"{OUTPUT_DIR}/mock_confounds.tsv",  # Would need real confounds file
            "strategy": "compcor",
            "motion_params": True,
            "wm_csf": True,
            "compcor": "anat",
            "n_compcor": 5,
            "high_pass": 0.008,
            "t_r": 2.5,
            "output_file": f"{OUTPUT_DIR}/cleaned_bold.nii.gz"
        },
        "expected": "Remove motion and physiological confounds"
    },

    {
        "id": "test_10_group_analysis",
        "description": "Second-level group analysis across sessions",
        "tool": "glm_second_level",
        "params": {
            "contrast_maps": [
                f"{OUTPUT_DIR}/glm_motor/motor_activation.nii.gz",
                f"{OUTPUT_DIR}/glm_language/language_activation.nii.gz"
            ],
            "design_matrix": None,  # Simple one-sample t-test
            "contrast": "mean",
            "smoothing_fwhm": 8.0,
            "output_dir": f"{OUTPUT_DIR}/group_analysis"
        },
        "expected": "Perform group-level statistical analysis"
    }
]

def create_test_script():
    """Generate a Python script to run these tests."""

    script = """#!/usr/bin/env python3
'''
Automated test script for Nilearn tools.
Run with: python run_nilearn_tests.py
'''

import sys
import json
import numpy as np
from pathlib import Path

# Import the tools
from brain_researcher.services.tools.tool_registry import ToolRegistry

def run_test(test_case):
    '''Execute a single test case.'''
    print(f"\\n{'='*60}")
    print(f"Running: {test_case['id']} - {test_case['description']}")
    print(f"Tool: {test_case['tool']}")
    print(f"{'='*60}")

    try:
        # Initialize registry
        registry = ToolRegistry()

        # Get the tool
        tool = registry.get_tool(test_case['tool'])
        if not tool:
            print(f"ERROR: Tool '{test_case['tool']}' not found!")
            return False

        # Execute the tool
        result = tool.invoke(**test_case['params'])

        print(f"SUCCESS: {test_case['expected']}")
        print(f"Result: {json.dumps(result, indent=2)}")
        return True

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def main():
    # Load test cases
    with open('test_cases.json', 'r') as f:
        test_cases = json.load(f)

    results = []
    for test in test_cases:
        success = run_test(test)
        results.append((test['id'], success))

    # Summary
    print(f"\\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_id, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {test_id}")

    print(f"\\nTotal: {passed}/{total} passed")

if __name__ == "__main__":
    main()
"""

    # Save test cases as JSON
    with open(f"{OUTPUT_DIR}/test_cases.json", "w") as f:
        json.dump(test_cases, f, indent=2)

    # Save test script
    with open(f"{OUTPUT_DIR}/run_nilearn_tests.py", "w") as f:
        f.write(script)

    print(f"Test cases saved to: {OUTPUT_DIR}/test_cases.json")
    print(f"Test script saved to: {OUTPUT_DIR}/run_nilearn_tests.py")

    return test_cases

if __name__ == "__main__":
    # Create and display test cases
    cases = create_test_script()

    print("\n" + "="*70)
    print("NILEARN TOOLS TEST CASES")
    print("="*70)

    for i, case in enumerate(cases, 1):
        print(f"\n{i}. {case['description']}")
        print(f"   Tool: {case['tool']}")
        print(f"   Expected: {case['expected']}")
        print(f"   Key params: {', '.join(list(case['params'].keys())[:3])}...")

    print("\n" + "="*70)
    print(f"Created {len(cases)} test cases using real data from:")
    print(f"  - Dataset: OpenNeuro ds000114")
    print(f"  - Tasks: motor (fingerfootlips), language (verbgeneration), spatial (linebisection)")
    print(f"  - Output dir: {OUTPUT_DIR}")
    print("="*70)
