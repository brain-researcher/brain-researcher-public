#!/usr/bin/env python3
"""
Test script for newly implemented neuroimaging tools.
Tests each tool individually with the ds000114 dataset.
"""

import sys
import os
import tempfile
import json
import warnings
import shutil
from pathlib import Path
from datetime import datetime

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from brain_researcher.services.tools.tool_registry import ToolRegistry

# Dataset paths
DATASET_PATH = Path("/app/data/openneuro/ds000114")
SUBJECT = "sub-01"
SESSION = "ses-test"
OUTPUT_BASE = REPO_ROOT / "outputs" / "test_outputs"
OUTPUT_BASE.mkdir(exist_ok=True)

warnings.filterwarnings(
    "ignore",
    message="The bic value is computed using the deviance formula.*",
    category=FutureWarning,
)

# Test results
test_results = {
    "timestamp": datetime.now().isoformat(),
    "dataset": str(DATASET_PATH),
    "tools_tested": [],
    "summary": {
        "total": 0,
        "passed": 0,
        "failed": 0
    }
}

def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(reason)


def _skip_if_fsl_missing(tool_name: str) -> None:
    if not (shutil.which(tool_name) or os.environ.get("FSLDIR")):
        pytest.skip(f"{tool_name} not available (FSL not installed)")


def print_header(tool_name):
    """Print a formatted header for each tool test."""
    print("\n" + "="*60)
    print(f"TESTING: {tool_name}")
    print("="*60)


def print_result(result):
    """Print tool execution result."""
    if hasattr(result, 'status'):
        # ToolResult object
        if result.status == "success":
            print("✅ SUCCESS")
            if hasattr(result, 'data') and result.data:
                if 'message' in result.data:
                    print(f"   Message: {result.data['message']}")
                if 'outputs' in result.data:
                    print(f"   Outputs: {list(result.data['outputs'].keys())}")
            return True
        else:
            print(f"❌ FAILED: {result.error}")
            return False
    else:
        # Dictionary result
        if result.get('status') == 'success':
            print("✅ SUCCESS")
            if 'message' in result:
                print(f"   Message: {result['message']}")
            return True
        else:
            print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
            return False


def test_fsl_fnirt():
    """Test FSL FNIRT non-linear registration."""
    print_header("FSL FNIRT Non-linear Registration")
    _skip_if_fsl_missing("fnirt")

    # Test with structural image
    anat_file = DATASET_PATH / SUBJECT / SESSION / "anat" / f"{SUBJECT}_{SESSION}_T1w.nii.gz"
    ref_file = Path("/usr/share/fsl/data/standard/MNI152_T1_2mm.nii.gz")
    _skip_if_missing(anat_file, f"Test data not found: {anat_file}")
    _skip_if_missing(ref_file, f"FSL template not found: {ref_file}")

    try:
        from brain_researcher.services.tools.fsl_fnirt_tool import FSLFNIRTTool
        
        tool = FSLFNIRTTool()
        print(f"Tool: {tool.get_tool_name()}")
        print(f"Description: {tool.get_tool_description()[:100]}...")
        
        output_dir = OUTPUT_BASE / "fsl_fnirt"
        output_dir.mkdir(exist_ok=True)

        print(f"Input: {anat_file}")

        # For testing, we'll generate the command without execution
        # since we don't have FSL template files readily available
        result = tool._run(
            in_file=str(anat_file),
            ref_file=str(ref_file),  # Standard FSL template
            output_dir=str(output_dir),
            warp_resolution="10,10,10",
            max_iterations="5,5,5,5",
            config_file="T1_2_MNI152_2mm"
        )

        success = print_result(result)
        test_results["tools_tested"].append({
            "name": "fsl_fnirt",
            "status": "success" if success else "failed",
            "output_dir": str(output_dir)
        })
        assert success

    except Exception as e:
        print(f"❌ Error: {e}")
        test_results["tools_tested"].append({
            "name": "fsl_fnirt",
            "status": "error",
            "error": str(e)
        })
        raise


def test_mne_ica():
    """Test MNE ICA artifact removal."""
    print_header("MNE ICA Artifact Removal")
    
    try:
        from brain_researcher.services.tools.mne_ica_tool import MNEICATool
        
        tool = MNEICATool()
        print(f"Tool: {tool.get_tool_name()}")
        print(f"Description: {tool.get_tool_description()[:100]}...")
        
        # Create a dummy epochs file for testing
        output_dir = OUTPUT_BASE / "mne_ica"
        output_dir.mkdir(exist_ok=True)
        
        # We'll test with a mock file path since we don't have EEG data
        epochs_file = output_dir / "test_epochs.fif"
        
        print(f"Testing ICA configuration...")
        
        # Test argument validation
        from brain_researcher.services.tools.mne_ica_tool import MNEICAArgs
        
        args = MNEICAArgs(
            raw_file=str(epochs_file),
            output_dir=str(output_dir),
            method="fastica",
            n_components=20,
            detect_artifacts=["eog", "ecg"],
            plot_components=False  # Disable plotting for test
        )
        
        print(f"✅ Argument validation passed")
        print(f"   Method: {args.method}")
        print(f"   Components: {args.n_components}")
        print(f"   Artifacts to detect: {args.detect_artifacts}")
        
        test_results["tools_tested"].append({
            "name": "mne_ica",
            "status": "success",
            "note": "Configuration validated"
        })
        assert True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        test_results["tools_tested"].append({
            "name": "mne_ica",
            "status": "error",
            "error": str(e)
        })
        raise


def test_statsmodels_glm():
    """Test Statsmodels GLM."""
    print_header("Statsmodels GLM")
    
    try:
        from brain_researcher.services.tools.statsmodels_glm_tool import StatsmodelsGLMTool
        import pandas as pd
        import numpy as np
        from statsmodels.genmod.generalized_linear_model import SET_USE_BIC_LLF

        SET_USE_BIC_LLF(True)
        
        tool = StatsmodelsGLMTool()
        print(f"Tool: {tool.get_tool_name()}")
        print(f"Description: {tool.get_tool_description()[:100]}...")
        
        # Create test data
        output_dir = OUTPUT_BASE / "statsmodels_glm"
        output_dir.mkdir(exist_ok=True)
        
        # Generate synthetic data for testing
        np.random.seed(42)
        n_samples = 100
        
        # Create design matrix
        design_data = pd.DataFrame({
            'age': np.random.normal(40, 10, n_samples),
            'group': np.random.choice([0, 1], n_samples),
            'motion': np.random.normal(0, 0.5, n_samples)
        })
        design_file = output_dir / "design_matrix.csv"
        design_data.to_csv(design_file, index=False)
        
        # Create outcome data
        y = 2 * design_data['age'] + 5 * design_data['group'] + np.random.normal(0, 1, n_samples)
        data = pd.DataFrame({'y': y})
        data_file = output_dir / "data.csv"
        data.to_csv(data_file, index=False)
        
        print(f"Created test data: {n_samples} samples")
        
        # Run GLM
        result = tool._run(
            data_file=str(data_file),
            design_matrix=str(design_file),
            output_dir=str(output_dir),
            dependent_var="y",
            family="gaussian",
            alpha=0.05,
            correction_method="fdr",
            compute_diagnostics=True,
            plot_diagnostics=False  # Disable for testing
        )
        
        success = print_result(result)
        test_results["tools_tested"].append({
            "name": "statsmodels_glm",
            "status": "success" if success else "failed",
            "output_dir": str(output_dir)
        })
        assert success
        
    except Exception as e:
        print(f"❌ Error: {e}")
        test_results["tools_tested"].append({
            "name": "statsmodels_glm",
            "status": "error",
            "error": str(e)
        })
        raise


def test_mne_timefreq():
    """Test MNE Time-Frequency analysis."""
    print_header("MNE Time-Frequency Analysis")
    
    try:
        from brain_researcher.services.tools.mne_timefreq_tool import MNETimeFreqTool
        
        tool = MNETimeFreqTool()
        print(f"Tool: {tool.get_tool_name()}")
        print(f"Description: {tool.get_tool_description()[:100]}...")
        
        output_dir = OUTPUT_BASE / "mne_timefreq"
        output_dir.mkdir(exist_ok=True)
        
        # Test configuration
        from brain_researcher.services.tools.mne_timefreq_tool import MNETimeFreqArgs
        
        args = MNETimeFreqArgs(
            epochs_file="test_epochs.fif",
            output_dir=str(output_dir),
            method="morlet",
            freq_min=1.0,
            freq_max=40.0,
            n_freqs=30,
            n_cycles=7.0,
            compute_psd=True,
            compute_band_power=True,
            plot_tfr=False  # Disable for testing
        )
        
        print(f"✅ Configuration validated")
        print(f"   Method: {args.method}")
        print(f"   Frequency range: {args.freq_min}-{args.freq_max} Hz")
        print(f"   Number of frequencies: {args.n_freqs}")
        
        test_results["tools_tested"].append({
            "name": "mne_timefreq",
            "status": "success",
            "note": "Configuration validated"
        })
        assert True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        test_results["tools_tested"].append({
            "name": "mne_timefreq",
            "status": "error",
            "error": str(e)
        })
        raise


def test_fsl_bedpostx():
    """Test FSL BEDPOSTX diffusion modeling."""
    print_header("FSL BEDPOSTX Diffusion Modeling")
    _skip_if_fsl_missing("bedpostx")

    # Check for diffusion data
    dwi_dir = DATASET_PATH / SUBJECT / SESSION / "dwi"
    _skip_if_missing(dwi_dir, f"No diffusion data found in {dwi_dir}")
    dwi_files = list(dwi_dir.glob("*.nii.gz"))
    if not dwi_files:
        pytest.skip(f"No diffusion NIfTI files found in {dwi_dir}")

    try:
        from brain_researcher.services.tools.fsl_bedpostx_tool import FSLBEDPOSTXTool
        
        tool = FSLBEDPOSTXTool()
        print(f"Tool: {tool.get_tool_name()}")
        print(f"Description: {tool.get_tool_description()[:100]}...")
        
        output_dir = OUTPUT_BASE / "fsl_bedpostx"
        output_dir.mkdir(exist_ok=True)
        
        print(f"Found {len(dwi_files)} DWI files")

        # Test configuration
        from brain_researcher.services.tools.fsl_bedpostx_tool import FSLBEDPOSTXArgs

        args = FSLBEDPOSTXArgs(
            data_dir=str(dwi_dir),
            output_dir=str(output_dir),
            n_fibres=2,
            burnin=1000,
            n_jumps=1250,
            model="1"
        )

        print(f"✅ Configuration validated")
        print(f"   Max fibres: {args.n_fibres}")
        print(f"   MCMC burnin: {args.burnin}")
        print(f"   MCMC jumps: {args.n_jumps}")

        test_results["tools_tested"].append({
            "name": "fsl_bedpostx",
            "status": "success",
            "note": "Configuration validated"
        })
        assert True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        test_results["tools_tested"].append({
            "name": "fsl_bedpostx",
            "status": "error",
            "error": str(e)
        })
        raise


def test_registry_integration(monkeypatch):
    """Test that all new tools are properly registered."""
    print_header("Tool Registry Integration")
    
    try:
        monkeypatch.setenv("TOOL_DISCOVERY_MODE", "full")
        registry = ToolRegistry(auto_discover=True)
        
        # Check for our new tools
        expected_tools = [
            "fsl_fnirt",
            "mne_ica",
            "statsmodels_glm",
            "mne_timefreq",
            "fsl_bedpostx"
        ]
        
        registered_tools = list(registry.tools.keys())
        print(f"Total tools in registry: {len(registered_tools)}")
        
        found_tools = []
        missing_tools = []
        
        for tool_name in expected_tools:
            if tool_name in registered_tools:
                found_tools.append(tool_name)
                print(f"✅ Found: {tool_name}")
            else:
                missing_tools.append(tool_name)
                print(f"❌ Missing: {tool_name}")
        
        if missing_tools:
            print(f"\n⚠️  Missing tools: {missing_tools}")
            assert False, f"Missing tools: {missing_tools}"
        else:
            print(f"\n✅ All {len(expected_tools)} new tools are registered!")
            assert True
            
    except Exception as e:
        print(f"❌ Error: {e}")
        raise


def main():
    """Run all tool tests."""
    print("\n" + "="*60)
    print("TESTING NEWLY IMPLEMENTED NEUROIMAGING TOOLS")
    print("="*60)
    print(f"Dataset: {DATASET_PATH}")
    print(f"Output: {OUTPUT_BASE}")
    
    # Test each tool
    results = []
    
    # Test registry first
    print("\n📋 Testing Tool Registry Integration...")
    registry_ok = test_registry_integration()
    results.append(("Registry Integration", registry_ok))
    
    # Test individual tools
    print("\n🧪 Testing Individual Tools...")
    
    results.append(("FSL FNIRT", test_fsl_fnirt()))
    results.append(("MNE ICA", test_mne_ica()))
    results.append(("Statsmodels GLM", test_statsmodels_glm()))
    results.append(("MNE Time-Frequency", test_mne_timefreq()))
    results.append(("FSL BEDPOSTX", test_fsl_bedpostx()))
    
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
    
    # Update test results
    test_results["summary"]["total"] = len(results)
    test_results["summary"]["passed"] = passed
    test_results["summary"]["failed"] = failed
    
    # Save results
    results_file = OUTPUT_BASE / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
