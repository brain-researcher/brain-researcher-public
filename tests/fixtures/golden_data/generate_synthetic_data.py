#!/usr/bin/env python3
"""Generate synthetic neuroimaging data for golden tests.

This script creates small, reproducible NIfTI files for testing neuroimaging
tools without requiring large real datasets.
"""
import json
import numpy as np
import nibabel as nib
from pathlib import Path


def create_synthetic_t1w(output_path: Path, shape=(10, 10, 10), seed=42):
    """Create a synthetic T1-weighted anatomical image.

    Args:
        output_path: Where to save the NIfTI file
        shape: Volume dimensions (small for testing)
        seed: Random seed for reproducibility
    """
    np.random.seed(seed)

    # Create simple brain-like structure
    data = np.zeros(shape, dtype=np.float32)
    center = np.array(shape) // 2

    # Add a "brain" sphere in the center
    for i in range(shape[0]):
        for j in range(shape[1]):
            for k in range(shape[2]):
                dist = np.sqrt((i - center[0])**2 + (j - center[1])**2 + (k - center[2])**2)
                if dist < shape[0] / 3:
                    # Brain tissue with some noise
                    data[i, j, k] = 100 + np.random.randn() * 10

    # Create affine matrix (standard RAS orientation, 2mm isotropic)
    affine = np.eye(4)
    affine[0:3, 0:3] = np.diag([2.0, 2.0, 2.0])
    affine[0:3, 3] = -center * 2.0

    # Create NIfTI image
    img = nib.Nifti1Image(data, affine)
    img.header.set_xyzt_units('mm', 'sec')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, output_path)
    print(f"Created T1w image: {output_path} ({data.nbytes} bytes)")


def create_synthetic_bold(output_path: Path, shape=(10, 10, 10, 20), seed=43):
    """Create a synthetic BOLD fMRI time series.

    Args:
        output_path: Where to save the NIfTI file
        shape: Volume dimensions (x, y, z, time)
        seed: Random seed for reproducibility
    """
    np.random.seed(seed)

    # Create BOLD data with temporal structure
    data = np.zeros(shape, dtype=np.float32)
    center = np.array(shape[:3]) // 2

    for i in range(shape[0]):
        for j in range(shape[1]):
            for k in range(shape[2]):
                dist = np.sqrt((i - center[0])**2 + (j - center[1])**2 + (k - center[2])**2)
                if dist < shape[0] / 3:
                    # Add temporal signal (sine wave + noise)
                    baseline = 1000
                    signal_amplitude = 20
                    t = np.arange(shape[3])
                    signal = baseline + signal_amplitude * np.sin(2 * np.pi * t / 10)
                    noise = np.random.randn(shape[3]) * 5
                    data[i, j, k, :] = signal + noise

    # Create affine matrix
    affine = np.eye(4)
    affine[0:3, 0:3] = np.diag([2.0, 2.0, 2.0])
    affine[0:3, 3] = -center * 2.0

    # Create NIfTI image with TR
    img = nib.Nifti1Image(data, affine)
    img.header.set_xyzt_units('mm', 'sec')
    img.header['pixdim'][4] = 2.0  # TR = 2 seconds

    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, output_path)
    print(f"Created BOLD image: {output_path} ({data.nbytes} bytes)")


def create_synthetic_mask(output_path: Path, shape=(10, 10, 10), seed=44):
    """Create a synthetic binary brain mask.

    Args:
        output_path: Where to save the NIfTI file
        shape: Volume dimensions
        seed: Random seed for reproducibility
    """
    np.random.seed(seed)

    # Create binary mask
    data = np.zeros(shape, dtype=np.uint8)
    center = np.array(shape) // 2

    # Spherical mask
    for i in range(shape[0]):
        for j in range(shape[1]):
            for k in range(shape[2]):
                dist = np.sqrt((i - center[0])**2 + (j - center[1])**2 + (k - center[2])**2)
                if dist < shape[0] / 3:
                    data[i, j, k] = 1

    # Create affine matrix
    affine = np.eye(4)
    affine[0:3, 0:3] = np.diag([2.0, 2.0, 2.0])
    affine[0:3, 3] = -center * 2.0

    # Create NIfTI image
    img = nib.Nifti1Image(data, affine)
    img.header.set_xyzt_units('mm', 'sec')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, output_path)
    print(f"Created mask image: {output_path} ({data.nbytes} bytes)")


def create_bids_dataset(base_dir: Path):
    """Create a minimal BIDS-compliant dataset structure.

    Args:
        base_dir: Base directory for the BIDS dataset
    """
    bids_dir = base_dir / "bids_dataset"

    # Create dataset_description.json
    dataset_desc = {
        "Name": "Synthetic Golden Test Dataset",
        "BIDSVersion": "1.6.0",
        "Authors": ["Brain Researcher Test Suite"],
        "License": "CC0",
        "ReferencesAndLinks": [],
    }

    desc_path = bids_dir / "dataset_description.json"
    desc_path.parent.mkdir(parents=True, exist_ok=True)
    with open(desc_path, "w") as f:
        json.dump(dataset_desc, f, indent=2)
    print(f"Created dataset_description.json: {desc_path}")

    # Create participant
    sub_id = "sub-01"
    ses_id = "ses-01"

    # Anatomical data
    anat_dir = bids_dir / sub_id / ses_id / "anat"
    t1w_path = anat_dir / f"{sub_id}_{ses_id}_T1w.nii.gz"
    create_synthetic_t1w(t1w_path)

    # Functional data
    func_dir = bids_dir / sub_id / ses_id / "func"
    bold_path = func_dir / f"{sub_id}_{ses_id}_task-rest_bold.nii.gz"
    create_synthetic_bold(bold_path)

    # Mask
    mask_path = anat_dir / f"{sub_id}_{ses_id}_T1w_brain_mask.nii.gz"
    create_synthetic_mask(mask_path)

    print(f"\nBIDS dataset created at: {bids_dir}")
    return bids_dir


def create_standalone_test_files(base_dir: Path):
    """Create standalone test files (not BIDS) for specific tool tests.

    Args:
        base_dir: Base directory for test files
    """
    standalone_dir = base_dir / "standalone"

    # FSL BET test input
    fsl_dir = standalone_dir / "fsl"
    create_synthetic_t1w(fsl_dir / "brain_input.nii.gz", seed=100)

    # AFNI 3dTstat test input
    afni_dir = standalone_dir / "afni"
    create_synthetic_bold(afni_dir / "timeseries_input.nii.gz", seed=101)

    # ANTs registration test inputs
    ants_dir = standalone_dir / "ants"
    create_synthetic_t1w(ants_dir / "fixed_image.nii.gz", seed=102)
    create_synthetic_t1w(ants_dir / "moving_image.nii.gz", seed=103)

    # FreeSurfer mri_convert test input
    fs_dir = standalone_dir / "freesurfer"
    create_synthetic_t1w(fs_dir / "convert_input.nii.gz", seed=104)

    print(f"\nStandalone test files created at: {standalone_dir}")
    return standalone_dir


def main():
    """Generate all synthetic test data."""
    script_dir = Path(__file__).parent
    print(f"Generating synthetic neuroimaging data in: {script_dir}\n")

    # Create BIDS dataset
    bids_dir = create_bids_dataset(script_dir)

    # Create standalone test files
    standalone_dir = create_standalone_test_files(script_dir)

    # Print summary
    print("\n" + "="*60)
    print("Synthetic data generation complete!")
    print("="*60)
    print(f"BIDS dataset: {bids_dir}")
    print(f"Standalone files: {standalone_dir}")
    print("\nTotal disk usage (approximate):")

    total_size = 0
    for filepath in script_dir.rglob("*.nii.gz"):
        size = filepath.stat().st_size
        total_size += size
        print(f"  {filepath.relative_to(script_dir)}: {size/1024:.1f} KB")

    print(f"\nTotal: {total_size/1024:.1f} KB ({total_size/1024/1024:.2f} MB)")
    print("\nAll files use deterministic seeds for reproducibility.")


if __name__ == "__main__":
    main()
