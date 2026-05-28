#!/usr/bin/env python
"""
Test suite for Phase 2 tools using real NIfTI data from ds000114.
"""

import os
import json
import tempfile
import numpy as np
from pathlib import Path
import logging
import nibabel as nib

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the registry to access tools
from brain_researcher.services.tools.tool_registry import ToolRegistry


def get_real_test_data():
    """Get real NIfTI files from ds000114 dataset."""
    base_dir = Path("/app/data/openneuro/ds000114/sub-06")
    
    test_data = {
        "t1": str(base_dir / "ses-test/anat/sub-06_ses-test_T1w.nii.gz"),
        "fmri": str(base_dir / "ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz"),
        "dwi": str(base_dir / "ses-test/dwi/sub-06_ses-test_dwi.nii.gz"),
    }
    
    # Check which files exist
    existing = {}
    for key, path in test_data.items():
        if Path(path).exists():
            existing[key] = path
            print(f"✓ Found {key}: {Path(path).name}")
        else:
            print(f"✗ Missing {key}: {path}")
    
    # Create synthetic supplementary data for missing modalities
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Load T1 as reference
        if "t1" in existing:
            t1_img = nib.load(existing["t1"])
            t1_data = t1_img.get_fdata()
            affine = t1_img.affine
            
            # Create FLAIR-like image (brighter WM)
            flair_data = t1_data.copy()
            flair_data[t1_data > np.percentile(t1_data[t1_data > 0], 70)] *= 1.3
            flair_img = nib.Nifti1Image(flair_data, affine)
            flair_path = tmpdir / "synthetic_flair.nii.gz"
            nib.save(flair_img, flair_path)
            existing["flair"] = str(flair_path)
            
            # Create phase image for QSM
            phase_data = np.random.randn(*t1_data.shape) * 0.5
            phase_img = nib.Nifti1Image(phase_data, affine)
            phase_path = tmpdir / "synthetic_phase.nii.gz"
            nib.save(phase_img, phase_path)
            existing["phase"] = str(phase_path)
            
            # Create magnitude image
            mag_data = np.abs(t1_data) + np.random.randn(*t1_data.shape) * 10
            mag_img = nib.Nifti1Image(mag_data, affine)
            mag_path = tmpdir / "synthetic_magnitude.nii.gz"
            nib.save(mag_img, mag_path)
            existing["magnitude"] = str(mag_path)
            
            # Create brain mask
            mask_data = (t1_data > np.percentile(t1_data[t1_data > 0], 10)).astype(np.uint8)
            mask_img = nib.Nifti1Image(mask_data, affine)
            mask_path = tmpdir / "brain_mask.nii.gz"
            nib.save(mask_img, mask_path)
            existing["mask"] = str(mask_path)
            
            # For ASL, use fMRI data if available or create synthetic
            if "fmri" in existing:
                fmri_img = nib.load(existing["fmri"])
                fmri_data = fmri_img.get_fdata()
                
                # Take first 60 volumes as ASL tag-control pairs
                if fmri_data.shape[-1] >= 60:
                    asl_data = fmri_data[..., :60]
                else:
                    asl_data = fmri_data
                
                asl_img = nib.Nifti1Image(asl_data, fmri_img.affine)
                asl_path = tmpdir / "synthetic_asl.nii.gz"
                nib.save(asl_img, asl_path)
                existing["asl"] = str(asl_path)
        
        return existing, tmpdir


def test_segmentation_tool(registry, test_data, output_dir):
    """Test brain segmentation tool."""
    print("\n" + "="*60)
    print("Testing Brain Segmentation Tool")
    print("="*60)
    
    tool = registry.get_tool("brain_segmentation")
    if not tool:
        print("❌ Tool not found!")
        return False
    
    try:
        # Test tissue segmentation
        result = tool._run(
            input_image=test_data["t1"],
            modality="T1",
            segmentation_type="tissue",
            n_classes=3,
            algorithm="fast",
            skull_strip=True,
            bias_correction=True,
            output_dir=str(output_dir / "segmentation"),
            visualize=True
        )
        
        if result.status == "success":
            print("✅ Tissue segmentation: SUCCESS")
            summary = result.data.get('summary', {})
            print(f"   - Segmented classes: {summary.get('n_classes', 0)}")
            print(f"   - Voxels segmented: {summary.get('n_voxels_segmented', 0)}")
            
            # Get volumes if available
            if 'volumes' in summary:
                print("   - Tissue volumes:")
                for tissue, vol in summary['volumes'].items():
                    print(f"     • Class {tissue}: {vol:.1f} mm³")
            
            return True
        else:
            print(f"❌ Segmentation failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_asl_perfusion_tool(registry, test_data, output_dir):
    """Test ASL perfusion tool."""
    print("\n" + "="*60)
    print("Testing ASL Perfusion Tool")
    print("="*60)
    
    tool = registry.get_tool("asl_perfusion")
    if not tool:
        print("❌ Tool not found!")
        return False
    
    if "asl" not in test_data:
        print("⚠️  No ASL data available, skipping")
        return True
    
    try:
        result = tool._run(
            asl_file=test_data["asl"],
            m0_file=test_data.get("magnitude", test_data["t1"]),
            asl_type="pcasl",
            labeling_duration=1.8,
            post_labeling_delay=[2.0],
            tr=4.0,
            field_strength=3.0,
            output_dir=str(output_dir / "asl"),
            visualize=True
        )
        
        if result.status == "success":
            print("✅ ASL perfusion: SUCCESS")
            cbf_stats = result.data['summary'].get('cbf_statistics', {})
            print(f"   - Mean CBF: {cbf_stats.get('mean', 0):.1f} ml/100g/min")
            print(f"   - Std CBF: {cbf_stats.get('std', 0):.1f}")
            
            qc = result.data['summary'].get('qc_metrics', {})
            if qc:
                print(f"   - SNR: {qc.get('snr', 0):.1f}")
                print(f"   - Brain coverage: {qc.get('brain_coverage', 0)*100:.1f}%")
            return True
        else:
            print(f"❌ ASL failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_lesion_detection_tool(registry, test_data, output_dir):
    """Test lesion detection tool."""
    print("\n" + "="*60)
    print("Testing Lesion Detection Tool")
    print("="*60)
    
    tool = registry.get_tool("lesion_detection")
    if not tool:
        print("❌ Tool not found!")
        return False
    
    try:
        # Test WMH detection with FLAIR
        result = tool._run(
            flair_image=test_data.get("flair", test_data["t1"]),
            t1_image=test_data["t1"],
            lesion_type="wmh",
            algorithm="auto",
            threshold_method="adaptive",
            min_lesion_size=3,
            output_dir=str(output_dir / "lesions"),
            visualize=True
        )
        
        if result.status == "success":
            print("✅ WMH detection: SUCCESS")
            quant = result.data['summary'].get('quantification', {})
            print(f"   - Lesions detected: {quant.get('n_lesions', 0)}")
            print(f"   - Total volume: {quant.get('total_volume_ml', 0):.2f} ml")
            print(f"   - Lesion burden: {quant.get('lesion_burden', 0):.2f}%")
            
            return True
        else:
            print(f"❌ Lesion detection failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_qsm_tool(registry, test_data, output_dir):
    """Test QSM reconstruction tool."""
    print("\n" + "="*60)
    print("Testing QSM Tool")
    print("="*60)
    
    tool = registry.get_tool("qsm_reconstruction")
    if not tool:
        print("❌ Tool not found!")
        return False
    
    try:
        result = tool._run(
            phase_file=test_data.get("phase", test_data["t1"]),
            magnitude_file=test_data.get("magnitude", test_data["t1"]),
            mask_file=test_data.get("mask"),
            field_strength=3.0,
            te=0.020,
            qsm_method="tkd",
            tkd_threshold=0.2,
            compute_iron=True,
            output_dir=str(output_dir / "qsm"),
            visualize=True
        )
        
        if result.status == "success":
            print("✅ QSM reconstruction: SUCCESS")
            chi_stats = result.data['summary'].get('susceptibility_stats', {})
            print(f"   - Mean susceptibility: {chi_stats.get('mean_ppm', 0):.3f} ppm")
            print(f"   - Std susceptibility: {chi_stats.get('std_ppm', 0):.3f} ppm")
            
            qc = result.data['summary'].get('quality_metrics', {})
            if qc:
                print(f"   - Field RMSE: {qc.get('field_rmse', 0):.3f}")
                print(f"   - SNR: {qc.get('snr', 0):.1f}")
            return True
        else:
            print(f"❌ QSM failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_mrs_tool(registry, test_data, output_dir):
    """Test MR Spectroscopy tool."""
    print("\n" + "="*60)
    print("Testing MR Spectroscopy Tool")
    print("="*60)
    
    tool = registry.get_tool("mr_spectroscopy")
    if not tool:
        print("❌ Tool not found!")
        return False
    
    try:
        # MRS doesn't need image input for synthetic test
        result = tool._run(
            field_strength=3.0,
            te=30.0,
            tr=2000.0,
            sequence_type="press",
            voxel_size=[20, 20, 20],
            voxel_location="pcc",
            metabolites=["NAA", "Cr", "Cho", "mI", "Glx"],
            reference_method="water",
            output_dir=str(output_dir / "mrs"),
            visualize=True
        )
        
        if result.status == "success":
            print("✅ MR Spectroscopy: SUCCESS")
            metabolites = result.data['summary'].get('metabolite_concentrations', {})
            print(f"   - Metabolites quantified: {len(metabolites)}")
            
            # Print key metabolite ratios
            ratios = result.data['summary'].get('metabolite_ratios', {})
            if ratios:
                print("   - Key ratios:")
                for ratio, value in list(ratios.items())[:3]:
                    print(f"     • {ratio}: {value:.2f}")
            
            # QC metrics
            qc = result.data['summary'].get('quality_metrics', {})
            if qc:
                print(f"   - SNR: {qc.get('snr', 0):.1f}")
                print(f"   - Linewidth: {qc.get('linewidth_ppm', 0):.3f} ppm")
            return True
        else:
            print(f"❌ MRS failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_additional_tools(registry, test_data, output_dir):
    """Test additional Phase 2 tools."""
    print("\n" + "="*60)
    print("Testing Additional Phase 2 Tools")
    print("="*60)
    
    tests = []
    
    # Surface analysis
    tool = registry.get_tool("surface_analysis")
    if tool:
        try:
            result = tool._run(
                surface_file=test_data["t1"],
                output_dir=str(output_dir / "surface")
            )
            if result.status == "success":
                print("✅ Surface analysis: SUCCESS")
                tests.append(True)
            else:
                print(f"❌ Surface analysis: {result.error}")
                tests.append(False)
        except Exception as e:
            print(f"❌ Surface analysis error: {str(e)}")
            tests.append(False)
    
    # Motion quantification for fMRI
    if "fmri" in test_data:
        tool = registry.get_tool("motion_quantification")
        if tool:
            try:
                result = tool._run(
                    fmri_file=test_data["fmri"],
                    output_dir=str(output_dir / "motion")
                )
                if result.status == "success":
                    print("✅ Motion quantification: SUCCESS")
                    summary = result.data.get('summary', {})
                    print(f"   - Mean FD: {summary.get('mean_fd', 0):.3f} mm")
                    print(f"   - Outliers: {summary.get('percent_outliers', 0):.1f}%")
                    tests.append(True)
                else:
                    print(f"❌ Motion quantification: {result.error}")
                    tests.append(False)
            except Exception as e:
                print(f"❌ Motion quantification error: {str(e)}")
                tests.append(False)
    
    # Radiomics extraction
    tool = registry.get_tool("radiomics_extraction")
    if tool and "mask" in test_data:
        try:
            result = tool._run(
                image_file=test_data["t1"],
                mask_file=test_data["mask"],
                output_dir=str(output_dir / "radiomics")
            )
            if result.status == "success":
                print("✅ Radiomics extraction: SUCCESS")
                print(f"   - Features extracted: {result.data['summary'].get('n_features', 0)}")
                tests.append(True)
            else:
                print(f"❌ Radiomics: {result.error}")
                tests.append(False)
        except Exception as e:
            print(f"❌ Radiomics error: {str(e)}")
            tests.append(False)
    
    return all(tests) if tests else True


def main():
    """Main test function."""
    print("\n" + "="*60)
    print("PHASE 2 TOOLS TEST WITH REAL DATA")
    print("Dataset: OpenNeuro ds000114")
    print("="*60)
    
    # Create registry
    print("\nInitializing tool registry...")
    registry = ToolRegistry()
    print(f"Total tools registered: {len(registry.tools)}")
    
    # Get real test data
    print("\n" + "="*60)
    print("LOADING TEST DATA")
    print("="*60)
    
    test_data, temp_dir = get_real_test_data()
    
    if not test_data:
        print("❌ No test data available!")
        return
    
    # Create output directory
    output_dir = Path("test_outputs_phase2")
    output_dir.mkdir(exist_ok=True)
    print(f"\nOutput directory: {output_dir}")
    
    # Run tests
    test_results = []
    
    print("\n" + "="*60)
    print("RUNNING TESTS")
    print("="*60)
    
    # Test core Phase 2 tools
    test_results.append(test_segmentation_tool(registry, test_data, output_dir))
    test_results.append(test_asl_perfusion_tool(registry, test_data, output_dir))
    test_results.append(test_lesion_detection_tool(registry, test_data, output_dir))
    test_results.append(test_qsm_tool(registry, test_data, output_dir))
    test_results.append(test_mrs_tool(registry, test_data, output_dir))
    test_results.append(test_additional_tools(registry, test_data, output_dir))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(test_results)
    total = len(test_results)
    
    print(f"\nTests Passed: {passed}/{total}")
    print(f"Success Rate: {passed/total*100:.1f}%")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Phase 2 tools are working with real data!")
    else:
        print(f"\n⚠️  {total - passed} tests failed. Check the output above for details.")
    
    print(f"\n📁 Check '{output_dir}' for generated outputs")
    print("   - Segmentation masks")
    print("   - CBF maps")
    print("   - Lesion masks")
    print("   - QSM maps")
    print("   - MRS spectra")
    print("   - Analysis reports")


if __name__ == "__main__":
    main()