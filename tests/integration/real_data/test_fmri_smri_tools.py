import pytest
pytest.skip("real-data fmri/smri tool tests skipped (requires deps)", allow_module_level=True)
#!/usr/bin/env python3
"""
Comprehensive test script for fMRI/sMRI neuroimaging tools using ds000114 dataset.

This script tests various fMRI and structural MRI analysis tools with real BIDS data.
Dataset: ds000114 (motor and language tasks, test-retest reliability)
"""

import json
import os
import pytest
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import tool implementations
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.tools.fsl_bet_tool import FSLBETTool, FSLBETArgs as BETArgs
from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTool, FSLFLIRTArgs as FLIRTArgs
from brain_researcher.services.tools.fsl_feat_tool import (
    FSLFEATTool, FSLFEATArgs as FEATGLMArgs, MotionCorrection, StatThreshold
)
from brain_researcher.services.tools.fsl_melodic_tool import (
    FSLMELODICTool, FSLMELODICArgs as MELODICArgs, ICADimensionality, ApproachType
)
from brain_researcher.services.tools.fsl_fix_tool import FSLFIXTool, FSLFIXArgs as FIXArgs
from brain_researcher.services.tools.fsl_palm_tool import FSLPALMTool, FSLPALMArgs as PALMArgs
from brain_researcher.services.tools.nilearn_tools import (
    NilearnTools, FirstLevelGLMArgs, SecondLevelGLMArgs, 
    ConnectivityArgs, MaskingArgs
)
from brain_researcher.services.tools.bids_tools import (
    BIDSTools, ValidateBIDSArgs, QueryBIDSLayoutArgs
)
from brain_researcher.services.tools.qc_tools import QCTools, MRIQCArgs
from brain_researcher.services.tools.statsmodels_glm_tool import (
    StatsmodelsGLMTool, GLMModelArgs, MixedModelArgs
)
from brain_researcher.services.tools.multiple_comparison_tool import (
    MultipleComparisonTool, FDRCorrectionArgs, PermutationTestArgs
)

# Dataset configuration
DATASET_ROOT = "/app/data/openneuro/ds000114"
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs" / "fmri_smri")
SUBJECTS = ["sub-01", "sub-02"]  # Test with 2 subjects
SESSIONS = ["ses-test", "ses-retest"]
TASKS = ["fingerfootlips", "linebisection", "covertverbgeneration"]

# Create output directory
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Performance tracking
performance_metrics = {
    "tool_timings": {},
    "memory_usage": {},
    "success_rate": {},
    "errors": []
}


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
                for key, value in list(result.data.items())[:3]:  # Show first 3 items
                    if key not in ["command", "stdout", "stderr"]:
                        print(f"  {key}: {str(value)[:100]}")
        
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
def test_fsl_bet():
    """Test FSL BET brain extraction tool."""
    print_section("FSL BET - Brain Extraction", 2)
    
    tool = FSLBETTool()
    anat_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/anat/{SUBJECTS[0]}_{SESSIONS[0]}_T1w.nii.gz"
    
    if not os.path.exists(anat_file):
        print(f"⚠️ Anatomical file not found: {anat_file}")
        return False
    
    args = BETArgs(
        input_file=anat_file,
        output_file=os.path.join(OUTPUT_DIR, "bet_brain.nii.gz"),
        fractional_intensity=0.5,
        gradient_threshold=0.0,
        brain_mask=True,
        skull_image=True,
        robust_estimation=True,
        center_of_gravity=None,
        reduce_bias=True
    )
    
    result = tool._run(**args.model_dump())
    return handle_result(result, "FSL BET")


@measure_performance
def test_fsl_flirt():
    """Test FSL FLIRT linear registration."""
    print_section("FSL FLIRT - Linear Registration", 2)
    
    tool = FSLFLIRTTool()
    
    # Register functional to anatomical
    func_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/func/{SUBJECTS[0]}_{SESSIONS[0]}_task-{TASKS[0]}_bold.nii.gz"
    anat_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/anat/{SUBJECTS[0]}_{SESSIONS[0]}_T1w.nii.gz"
    
    if not os.path.exists(func_file) or not os.path.exists(anat_file):
        print("⚠️ Required files not found")
        return False
    
    args = FLIRTArgs(
        input_file=func_file,
        reference_file=anat_file,
        output_file=os.path.join(OUTPUT_DIR, "flirt_registered.nii.gz"),
        output_matrix=os.path.join(OUTPUT_DIR, "flirt_matrix.mat"),
        dof=6,  # Rigid body for func to anat
        cost_function="corratio",
        search_range_x=[-90, 90],
        search_range_y=[-90, 90],
        search_range_z=[-90, 90],
        interp="trilinear"
    )
    
    result = tool._run(**args.model_dump())
    return handle_result(result, "FSL FLIRT")


@measure_performance
def test_fsl_melodic():
    """Test FSL MELODIC ICA decomposition."""
    print_section("FSL MELODIC - ICA Analysis", 2)
    
    tool = FSLMELODICTool()
    
    # Use multiple runs for group ICA
    func_files = []
    for subj in SUBJECTS[:2]:
        for task in TASKS[:1]:  # Use one task to keep it manageable
            func_file = f"{DATASET_ROOT}/{subj}/{SESSIONS[0]}/func/{subj}_{SESSIONS[0]}_task-{task}_bold.nii.gz"
            if os.path.exists(func_file):
                func_files.append(func_file)
    
    if not func_files:
        print("⚠️ No functional files found")
        return False
    
    print(f"  Found {len(func_files)} functional files for group ICA")
    
    args = MELODICArgs(
        input_files=func_files,
        output_dir=os.path.join(OUTPUT_DIR, "melodic"),
        tr=2.5,
        approach=ApproachType.CONCAT,
        dimensionality=ICADimensionality.AUTOMATIC,
        bg_threshold=10.0,
        var_norm=True,
        output_all=True,
        report=True
    )
    
    result = tool._run(**args.model_dump())
    return handle_result(result, "FSL MELODIC")


@measure_performance
def test_nilearn_glm():
    """Test Nilearn GLM analysis."""
    print_section("Nilearn - First Level GLM", 2)
    
    tools = NilearnTools()
    glm_tool = tools.get_tool_by_name("first_level_glm")
    
    # Prepare data for one subject
    func_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/func/{SUBJECTS[0]}_{SESSIONS[0]}_task-{TASKS[0]}_bold.nii.gz"
    events_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/func/{SUBJECTS[0]}_{SESSIONS[0]}_task-{TASKS[0]}_events.tsv"
    
    if not os.path.exists(func_file):
        print("⚠️ Functional file not found")
        return False
    
    # Load events if available
    import pandas as pd
    events = None
    if os.path.exists(events_file):
        try:
            events = pd.read_csv(events_file, sep='\t')
            print(f"  Loaded events with {len(events)} entries")
        except Exception as e:
            print(f"  Warning: Could not load events: {e}")
    
    args = FirstLevelGLMArgs(
        bold_files=[func_file],
        tr=2.5,
        events=[events] if events is not None else None,
        mask_img=None,
        smoothing_fwhm=6.0,
        high_pass=0.01,
        noise_model="ar1",
        drift_model="cosine",
        hrf_model="spm",
        minimize_memory=False
    )
    
    result = glm_tool._run(**args.model_dump())
    return handle_result(result, "Nilearn First Level GLM")


@measure_performance
def test_nilearn_connectivity():
    """Test Nilearn connectivity analysis."""
    print_section("Nilearn - Connectivity Analysis", 2)
    
    tools = NilearnTools()
    conn_tool = tools.get_tool_by_name("connectivity_analysis")
    
    func_file = f"{DATASET_ROOT}/{SUBJECTS[0]}/{SESSIONS[0]}/func/{SUBJECTS[0]}_{SESSIONS[0]}_task-{TASKS[0]}_bold.nii.gz"
    
    if not os.path.exists(func_file):
        print("⚠️ Functional file not found")
        return False
    
    args = ConnectivityArgs(
        time_series_files=[func_file],
        atlas="schaefer_2018",
        n_parcels=100,
        measure="correlation",
        confounds=None,
        standardize=True,
        detrend=True,
        low_pass=0.1,
        high_pass=0.01,
        tr=2.5
    )
    
    result = conn_tool._run(**args.model_dump())
    return handle_result(result, "Nilearn Connectivity")


@measure_performance
def test_bids_validation():
    """Test BIDS dataset validation."""
    print_section("BIDS - Dataset Validation", 2)
    
    bids_tools = BIDSTools()
    validate_tool = bids_tools.get_tool_by_name("validate_bids")
    
    args = ValidateBIDSArgs(
        bids_dir=DATASET_ROOT,
        verbose=True
    )
    
    result = validate_tool._run(**args.model_dump())
    success = handle_result(result, "BIDS Validation")
    
    # Also test BIDS query
    print("\n  Testing BIDS query...")
    query_tool = bids_tools.get_tool_by_name("query_bids_layout")
    query_args = QueryBIDSLayoutArgs(
        bids_dir=DATASET_ROOT,
        suffix="bold",
        subject=SUBJECTS[0].replace("sub-", ""),
        task=TASKS[0],
        scope="raw"
    )
    
    query_result = query_tool._run(**query_args.model_dump())
    query_success = handle_result(query_result, "BIDS Query")
    
    return success and query_success


@measure_performance
def test_statsmodels_glm():
    """Test Statsmodels GLM and mixed models."""
    print_section("Statsmodels - Statistical Modeling", 2)
    
    tool = StatsmodelsGLMTool()
    
    # Create synthetic behavioral data for demonstration
    import numpy as np
    import pandas as pd
    
    n_subjects = 10
    n_conditions = 3
    
    # Simulate behavioral data
    data = []
    for subj in range(n_subjects):
        for cond in range(n_conditions):
            for trial in range(5):
                data.append({
                    'subject': f'sub-{subj:02d}',
                    'condition': f'cond_{cond}',
                    'rt': np.random.normal(500 + cond * 50, 50),
                    'accuracy': np.random.binomial(1, 0.7 + cond * 0.1),
                    'age': 20 + subj,
                    'trial': trial
                })
    
    df = pd.DataFrame(data)
    print(f"  Created synthetic data: {len(df)} observations")
    
    # Test linear model
    glm_args = GLMModelArgs(
        formula="rt ~ condition + age",
        data=df,
        family="gaussian"
    )
    
    result = tool._run(**glm_args.model_dump())
    glm_success = handle_result(result, "Linear Model")
    
    # Test mixed effects model
    print("\n  Testing mixed effects model...")
    mixed_args = MixedModelArgs(
        formula="rt ~ condition + age",
        data=df,
        groups="subject",
        re_formula="~1",
        method="REML"
    )
    
    mixed_result = tool._run(**mixed_args.model_dump())
    mixed_success = handle_result(mixed_result, "Mixed Model")
    
    return glm_success and mixed_success


@measure_performance
def test_multiple_comparisons():
    """Test multiple comparison correction."""
    print_section("Multiple Comparison Correction", 2)
    
    tool = MultipleComparisonTool()
    
    # Generate synthetic p-values
    import numpy as np
    np.random.seed(42)
    n_tests = 1000
    p_values = np.random.uniform(0, 1, n_tests)
    p_values[:50] = np.random.uniform(0, 0.01, 50)  # Add some significant values
    
    print(f"  Testing with {n_tests} p-values")
    
    # Test FDR correction
    fdr_args = FDRCorrectionArgs(
        pvalues=p_values.tolist(),
        alpha=0.05,
        method="fdr_bh"
    )
    
    result = tool._run(**fdr_args.model_dump())
    fdr_success = handle_result(result, "FDR Correction")
    
    if hasattr(result, 'data') and result.data:
        n_sig = sum(result.data.get("rejected", []))
        print(f"  Found {n_sig} significant tests after FDR correction")
    
    # Test permutation testing
    print("\n  Testing permutation test...")
    
    # Create two groups of data
    group1 = np.random.normal(0, 1, 30)
    group2 = np.random.normal(0.5, 1, 30)
    
    perm_args = PermutationTestArgs(
        data=[group1.tolist(), group2.tolist()],
        n_permutations=1000,
        test_statistic="mean_diff",
        random_state=42
    )
    
    perm_result = tool._run(**perm_args.model_dump())
    perm_success = handle_result(perm_result, "Permutation Test")
    
    return fdr_success and perm_success


@measure_performance
def test_qc_tools():
    """Test quality control tools."""
    print_section("Quality Control - MRIQC", 2)
    
    tool = QCTools()
    mriqc_tool = tool.get_tool_by_name("run_mriqc")
    
    args = MRIQCArgs(
        bids_dir=DATASET_ROOT,
        output_dir=os.path.join(OUTPUT_DIR, "mriqc"),
        participant_label=[SUBJECTS[0].replace("sub-", "")],
        modalities=["T1w", "bold"],
        n_procs=2,
        mem_gb=8.0,
        no_sub=True
    )
    
    result = mriqc_tool._run(**args.model_dump())
    return handle_result(result, "MRIQC")


def test_integration_pipeline():
    """Test integration of multiple tools in a pipeline."""
    print_section("Integration Pipeline Test", 1)
    
    print("Testing pipeline: BIDS → Brain Extraction → Registration → GLM → Connectivity")
    
    pipeline_results = {}
    
    # Step 1: BIDS Validation
    print_section("Step 1: BIDS Validation", 3)
    bids_success = test_bids_validation()
    pipeline_results["bids"] = bids_success
    
    # Step 2: Brain Extraction
    print_section("Step 2: Brain Extraction", 3)
    bet_success = test_fsl_bet()
    pipeline_results["bet"] = bet_success
    
    # Step 3: Registration
    print_section("Step 3: Registration", 3)
    flirt_success = test_fsl_flirt()
    pipeline_results["flirt"] = flirt_success
    
    # Step 4: GLM Analysis
    print_section("Step 4: GLM Analysis", 3)
    glm_success = test_nilearn_glm()
    pipeline_results["glm"] = glm_success
    
    # Step 5: Connectivity
    print_section("Step 5: Connectivity Analysis", 3)
    conn_success = test_nilearn_connectivity()
    pipeline_results["connectivity"] = conn_success
    
    # Summary
    print_section("Pipeline Summary", 2)
    total_steps = len(pipeline_results)
    successful_steps = sum(pipeline_results.values())
    
    for step, success in pipeline_results.items():
        status = "✅" if success else "❌"
        print(f"  {status} {step}")
    
    print(f"\nPipeline Success Rate: {successful_steps}/{total_steps} ({successful_steps/total_steps*100:.1f}%)")
    
    return pipeline_results


def generate_report():
    """Generate comprehensive test report."""
    print_section("Generating Test Report", 1)
    
    report = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": "ds000114",
        "dataset_path": DATASET_ROOT,
        "output_directory": OUTPUT_DIR,
        "subjects_tested": SUBJECTS,
        "performance_metrics": performance_metrics,
        "tool_categories": {
            "FSL Suite": ["BET", "FLIRT", "MELODIC", "FEAT", "FIX", "PALM"],
            "Nilearn": ["First Level GLM", "Second Level GLM", "Connectivity", "Masking"],
            "Statistical": ["Statsmodels GLM", "Mixed Models", "FDR", "Permutation"],
            "BIDS": ["Validation", "Query", "Metadata"],
            "QC": ["MRIQC", "Visual QC"]
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
        "errors_count": len(performance_metrics["errors"])
    }
    
    # Save JSON report
    report_file = os.path.join(OUTPUT_DIR, "test_report_fmri_smri.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"📊 Report saved to: {report_file}")
    
    # Generate markdown report
    md_report = f"""# fMRI/sMRI Tools Test Report

## Test Summary
- **Date**: {report['test_date']}
- **Dataset**: {report['dataset']}
- **Subjects**: {', '.join(report['subjects_tested'])}

## Performance Metrics
- **Total Tests**: {report['summary']['total_tests']}
- **Successful**: {report['summary']['successful_tests']}
- **Success Rate**: {report['summary']['success_rate']:.1f}%
- **Total Time**: {report['summary']['total_time']:.2f} seconds
- **Total Memory**: {report['summary']['total_memory']:.1f} MB

## Tool Timings
"""
    
    for tool, timing in sorted(performance_metrics["tool_timings"].items()):
        md_report += f"- {tool}: {timing:.2f}s\n"
    
    if performance_metrics["errors"]:
        md_report += "\n## Errors Encountered\n"
        for error in performance_metrics["errors"]:
            md_report += f"- **{error['tool']}**: {error['error']}\n"
    
    md_file = os.path.join(OUTPUT_DIR, "test_report_fmri_smri.md")
    with open(md_file, 'w') as f:
        f.write(md_report)
    
    print(f"📝 Markdown report saved to: {md_file}")
    
    return report


def main():
    """Run comprehensive fMRI/sMRI tool tests."""
    print("\n" + "🧠" * 25)
    print("  fMRI/sMRI NEUROIMAGING TOOLS TEST SUITE")
    print("  Dataset: ds000114 from OpenNeuro")
    print("🧠" * 25)
    
    # Initialize registry
    print_section("Initializing Tool Registry")
    registry = ToolRegistry(auto_discover=True)
    print(f"Total tools available: {len(registry.tools)}")
    
    # Track results
    all_results = {}
    
    # Run individual tool tests
    print_section("Individual Tool Tests", 1)
    
    # FSL Suite
    print_section("FSL Suite Tools", 2)
    all_results["fsl_bet"] = test_fsl_bet()
    all_results["fsl_flirt"] = test_fsl_flirt()
    all_results["fsl_melodic"] = test_fsl_melodic()
    
    # Nilearn
    print_section("Nilearn Analysis Tools", 2)
    all_results["nilearn_glm"] = test_nilearn_glm()
    all_results["nilearn_connectivity"] = test_nilearn_connectivity()
    
    # BIDS
    all_results["bids"] = test_bids_validation()
    
    # Statistical
    print_section("Statistical Analysis Tools", 2)
    all_results["statsmodels"] = test_statsmodels_glm()
    all_results["multiple_comparisons"] = test_multiple_comparisons()
    
    # QC
    all_results["qc"] = test_qc_tools()
    
    # Update success rates
    performance_metrics["success_rate"] = all_results
    
    # Run integration pipeline
    pipeline_results = test_integration_pipeline()
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
    print(f"  - test_report_fmri_smri.json")
    print(f"  - test_report_fmri_smri.md")
    
    return all_results


if __name__ == "__main__":
    try:
        results = main()
        sys.exit(0 if all(results.values()) else 1)
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        traceback.print_exc()
        sys.exit(1)
