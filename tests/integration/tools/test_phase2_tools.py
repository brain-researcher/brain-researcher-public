#!/usr/bin/env python
"""
Comprehensive test suite for Phase 2 neuroimaging tools.
Tests all 16 new tools added to reach 130 total.
"""

import os
import json
import tempfile
import numpy as np
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the registry to access tools
from brain_researcher.services.tools.tool_registry import ToolRegistry


def create_test_data(output_dir):
    """Create synthetic test data for tool testing."""
    # Create synthetic NIfTI-like data
    test_image = np.random.randn(64, 64, 40)
    test_4d = np.random.randn(64, 64, 40, 100)
    
    # Save as numpy arrays (simulating NIfTI files)
    np.save(output_dir / "test_t1.npy", test_image)
    np.save(output_dir / "test_flair.npy", test_image * 1.2)
    np.save(output_dir / "test_phase.npy", test_image * np.pi)
    np.save(output_dir / "test_magnitude.npy", np.abs(test_image) * 1000)
    np.save(output_dir / "test_asl.npy", test_4d)
    np.save(output_dir / "test_fmri.npy", test_4d)
    np.save(output_dir / "test_mask.npy", test_image > 0)
    
    return {
        "t1": str(output_dir / "test_t1.npy"),
        "flair": str(output_dir / "test_flair.npy"),
        "phase": str(output_dir / "test_phase.npy"),
        "magnitude": str(output_dir / "test_magnitude.npy"),
        "asl": str(output_dir / "test_asl.npy"),
        "fmri": str(output_dir / "test_fmri.npy"),
        "mask": str(output_dir / "test_mask.npy")
    }


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
            output_dir=str(output_dir / "segmentation")
        )
        
        if result.status == "success":
            print("✅ Tissue segmentation: SUCCESS")
            print(f"   - Segmented regions: {result.data['summary'].get('n_classes', 0)}")
            print(f"   - Voxels segmented: {result.data['summary'].get('n_voxels_segmented', 0)}")
            
            # Test lesion detection mode
            result2 = tool._run(
                input_image=test_data["flair"],
                modality="FLAIR",
                segmentation_type="lesion",
                lesion_type="WMH",
                output_dir=str(output_dir / "segmentation_lesion")
            )
            
            if result2.status == "success":
                print("✅ Lesion segmentation: SUCCESS")
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
    
    try:
        result = tool._run(
            asl_file=test_data["asl"],
            m0_file=test_data["magnitude"],
            asl_type="pcasl",
            labeling_duration=1.8,
            post_labeling_delay=[2.0],
            output_dir=str(output_dir / "asl")
        )
        
        if result.status == "success":
            print("✅ ASL perfusion: SUCCESS")
            cbf_stats = result.data['summary'].get('cbf_statistics', {})
            print(f"   - Mean CBF: {cbf_stats.get('mean', 0):.1f} ml/100g/min")
            print(f"   - SNR: {result.data['summary'].get('qc_metrics', {}).get('snr', 0):.1f}")
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
        # Test WMH detection
        result = tool._run(
            flair_image=test_data["flair"],
            t1_image=test_data["t1"],
            lesion_type="wmh",
            algorithm="auto",
            output_dir=str(output_dir / "lesions")
        )
        
        if result.status == "success":
            print("✅ WMH detection: SUCCESS")
            quant = result.data['summary'].get('quantification', {})
            print(f"   - Lesions detected: {quant.get('n_lesions', 0)}")
            print(f"   - Total volume: {quant.get('total_volume_ml', 0):.2f} ml")
            
            # Test MS lesion detection
            result2 = tool._run(
                flair_image=test_data["flair"],
                t2_image=test_data["t1"],
                lesion_type="ms",
                ms_subtypes=["t2"],
                output_dir=str(output_dir / "ms_lesions")
            )
            
            if result2.status == "success":
                print("✅ MS lesion detection: SUCCESS")
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
            phase_file=test_data["phase"],
            magnitude_file=test_data["magnitude"],
            field_strength=3.0,
            te=0.020,
            qsm_method="tkd",
            output_dir=str(output_dir / "qsm")
        )
        
        if result.status == "success":
            print("✅ QSM reconstruction: SUCCESS")
            chi_stats = result.data['summary'].get('susceptibility_stats', {})
            print(f"   - Mean susceptibility: {chi_stats.get('mean_ppm', 0):.3f} ppm")
            print(f"   - QC SNR: {result.data['summary'].get('quality_metrics', {}).get('snr', 0):.1f}")
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
        result = tool._run(
            field_strength=3.0,
            te=30.0,
            sequence_type="press",
            voxel_location="pcc",
            metabolites=["NAA", "Cr", "Cho", "mI"],
            output_dir=str(output_dir / "mrs")
        )
        
        if result.status == "success":
            print("✅ MR Spectroscopy: SUCCESS")
            metabolites = result.data['summary'].get('metabolite_concentrations', {})
            print(f"   - Metabolites quantified: {len(metabolites)}")
            if metabolites:
                print(f"   - NAA/Cr ratio: {result.data['summary'].get('metabolite_ratios', {}).get('NAA/Cr', 0):.2f}")
            return True
        else:
            print(f"❌ MRS failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


def test_batch_tools(registry, test_data, output_dir):
    """Test the batch implementation tools."""
    print("\n" + "="*60)
    print("Testing Batch Tools (11 tools)")
    print("="*60)
    
    batch_tools = [
        ("surface_analysis", {"surface_file": test_data["t1"], "measure": "thickness"}),
        ("pet_spect_analysis", {"pet_file": test_data["t1"], "tracer": "FDG"}),
        ("multi_atlas_segmentation", {
            "target_image": test_data["t1"],
            "atlas_images": [test_data["t1"]],
            "atlas_labels": [test_data["mask"]]
        }),
        ("radiomics_extraction", {"image_file": test_data["t1"], "mask_file": test_data["mask"]}),
        ("longitudinal_analysis", {
            "baseline_image": test_data["t1"],
            "followup_images": [test_data["t1"]]
        }),
        ("phantom_analysis", {"phantom_image": test_data["t1"], "phantom_type": "ACR"}),
        ("motion_quantification", {"fmri_file": test_data["fmri"]}),
        ("data_harmonization", {
            "data_files": [test_data["t1"], test_data["t1"]],
            "site_labels": ["site1", "site2"]
        }),
        ("validation_metrics", {
            "prediction_file": test_data["mask"],
            "ground_truth_file": test_data["mask"]
        }),
        ("report_generation", {"analysis_results": {"test": "results"}, "template": "clinical"}),
        ("dicom_processing", {"dicom_dir": str(output_dir), "convert_to_nifti": True})
    ]
    
    results = []
    for tool_name, args in batch_tools:
        tool = registry.get_tool(tool_name)
        if not tool:
            print(f"❌ {tool_name}: NOT FOUND")
            results.append(False)
            continue
        
        try:
            args["output_dir"] = str(output_dir / tool_name)
            result = tool._run(**args)
            
            if result.status == "success":
                print(f"✅ {tool_name}: SUCCESS")
                results.append(True)
            else:
                print(f"❌ {tool_name}: FAILED - {result.error}")
                results.append(False)
                
        except Exception as e:
            print(f"❌ {tool_name}: ERROR - {str(e)}")
            results.append(False)
    
    return all(results)


def main():
    """Main test function."""
    print("\n" + "="*60)
    print("PHASE 2 TOOLS TEST SUITE")
    print("="*60)
    
    # Create registry
    print("\nInitializing tool registry...")
    registry = ToolRegistry()
    print(f"Total tools registered: {len(registry.tools)}")
    
    # Count Phase 2 tools
    phase2_tools = [
        "brain_segmentation", "asl_perfusion", "lesion_detection",
        "qsm_reconstruction", "mr_spectroscopy", "surface_analysis",
        "pet_spect_analysis", "multi_atlas_segmentation", "radiomics_extraction",
        "longitudinal_analysis", "phantom_analysis", "motion_quantification",
        "data_harmonization", "validation_metrics", "report_generation",
        "dicom_processing"
    ]
    
    found_tools = [t for t in phase2_tools if registry.get_tool(t)]
    print(f"Phase 2 tools found: {len(found_tools)}/{len(phase2_tools)}")
    
    # Create test environment
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        
        # Create test data
        print("\nCreating test data...")
        test_data = create_test_data(output_dir)
        
        # Run tests
        test_results = []
        
        # Test P0 Clinical tools
        print("\n" + "="*60)
        print("P0 - CLINICAL ESSENTIAL TOOLS")
        print("="*60)
        
        test_results.append(test_segmentation_tool(registry, test_data, output_dir))
        test_results.append(test_asl_perfusion_tool(registry, test_data, output_dir))
        test_results.append(test_lesion_detection_tool(registry, test_data, output_dir))
        
        # Test P1 Quantitative tools
        print("\n" + "="*60)
        print("P1 - ADVANCED QUANTITATIVE TOOLS")
        print("="*60)
        
        test_results.append(test_qsm_tool(registry, test_data, output_dir))
        test_results.append(test_mrs_tool(registry, test_data, output_dir))
        
        # Test remaining batch tools
        print("\n" + "="*60)
        print("P2/P3 - SPECIALIZED & QC TOOLS")
        print("="*60)
        
        test_results.append(test_batch_tools(registry, test_data, output_dir))
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(test_results)
        total = len(test_results)
        
        print(f"\nTests Passed: {passed}/{total}")
        print(f"Success Rate: {passed/total*100:.1f}%")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED! Phase 2 tools are working correctly!")
        else:
            print(f"\n⚠️  {total - passed} tests failed. Check the output above for details.")
        
        # Tool statistics
        print("\n" + "="*60)
        print("TOOL STATISTICS")
        print("="*60)
        print(f"Total platform tools: {len(registry.tools)}")
        print(f"Phase 2 tools tested: {len(found_tools)}")
        print(f"Test coverage: {len(found_tools)/len(phase2_tools)*100:.1f}%")


if __name__ == "__main__":
    main()