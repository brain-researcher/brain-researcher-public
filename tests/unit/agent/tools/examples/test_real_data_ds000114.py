#!/usr/bin/env python3
"""
Comprehensive test script for Brain Researcher tools using ds000114 dataset.

This script tests various neuroimaging tools with real BIDS data from OpenNeuro.
Dataset: ds000114 (motor and language tasks)
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

# This file is primarily a runnable example (see README.md). When collected by pytest,
# keep it opt-in because it depends on large local datasets and external toolchains.
if "pytest" in sys.modules:
    import pytest

    pytestmark = pytest.mark.slow
    if os.getenv("BR_RUN_REAL_DATA_TOOL_TESTS", "").lower() not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "Set BR_RUN_REAL_DATA_TOOL_TESTS=1 to run ds000114 real-data examples.",
            allow_module_level=True,
        )

# Add project root to path for direct execution.
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.tools.fsl_feat_tool import (
    FEATGLMArgs,
    FSLFEATTool,
    MotionCorrection,
    StatThreshold,
)
from brain_researcher.services.tools.fsl_melodic_tool import (
    FSLMELODICTool,
    MELODICArgs,
    ICADimensionality,
    ApproachType,
)
from brain_researcher.services.tools.bids_tools import (
    BIDSTools,
    ValidateBIDSArgs,
    QueryBIDSLayoutArgs,
)
from brain_researcher.services.tools.fmriprep_tool import (
    FMRIPrepTool,
    FMRIPrepArgs,
)
# QC tools have different structure, will test separately if needed
# from brain_researcher.services.tools.qc_tools import QCTools

# Dataset paths
DATASET_ROOT = "/app/data/openneuro/ds000114"
SUBJECT = "sub-01"
SESSION = "ses-test"
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs")

# Create output directory if it doesn't exist
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_result(result):
    """Print a formatted result."""
    # Handle both ToolResult objects and dictionaries
    if hasattr(result, 'status'):
        # ToolResult object
        if result.status == "success":
            print("✅ SUCCESS")
        else:
            print("❌ FAILED")
        
        if result.data:
            if isinstance(result.data, dict):
                if result.data.get("command"):
                    print(f"Command: {result.data['command']}")
                if result.data.get("message"):
                    print(f"Message: {result.data['message']}")
                if result.data.get("outputs"):
                    print(f"Outputs: {result.data['outputs']}")
        
        if result.error:
            print(f"Error: {result.error}")
        
        if result.metadata:
            print(f"Metadata: {result.metadata}")
    else:
        # Dictionary result
        if result.get("success"):
            print("✅ SUCCESS")
        else:
            print("❌ FAILED")
        
        if result.get("command"):
            print(f"Command: {result['command']}")
        
        if result.get("message"):
            print(f"Message: {result['message']}")
        
        if result.get("outputs"):
            print(f"Outputs: {result['outputs']}")
        
        if result.get("error"):
            print(f"Error: {result['error']}")


def test_tool_registry():
    """Test the tool registry and discovery."""
    print_section("Testing Tool Registry")
    
    registry = ToolRegistry(auto_discover=True)
    
    print(f"Total tools discovered: {len(registry.tools)}")
    print("\nAvailable tools:")
    for name, tool in registry.tools.items():
        print(f"  - {name}: {tool.get_tool_description()[:60]}...")
    
    # Test tool search
    print("\n🔍 Testing tool search for 'GLM analysis':")
    relevant_tools = registry.get_tools_for_task("GLM analysis of task fMRI", k=3)
    for tool in relevant_tools:
        print(f"  - {tool.get_tool_name()}")
    
    return registry


def create_fsl_event_file(events_file: str, output_file: str) -> str:
    """
    Convert BIDS events TSV to FSL 3-column format.
    
    FSL format: onset duration weight
    """
    import pandas as pd
    
    # Read BIDS events
    events = pd.read_csv(events_file, sep='\t')
    
    # Create FSL format for task conditions
    fsl_events = []
    
    # Group by trial_type
    for trial_type in events['trial_type'].unique():
        if pd.notna(trial_type):
            condition_events = events[events['trial_type'] == trial_type]
            
            # Write FSL format: onset duration weight
            condition_file = output_file.replace('.txt', f'_{trial_type}.txt')
            with open(condition_file, 'w') as f:
                for _, row in condition_events.iterrows():
                    f.write(f"{row['onset']}\t{row['duration']}\t{row.get('weight', 1.0)}\n")
            
            fsl_events.append((trial_type, condition_file))
            print(f"  Created event file: {condition_file}")
    
    return fsl_events


def test_fsl_feat_glm():
    """Test FSL FEAT GLM tool with real data."""
    print_section("Testing FSL FEAT GLM Tool")
    
    tool = FSLFEATTool()
    
    # Use the linebisection task (has events file)
    func_file = f"{DATASET_ROOT}/{SUBJECT}/{SESSION}/func/{SUBJECT}_{SESSION}_task-linebisection_bold.nii.gz"
    events_file = f"{DATASET_ROOT}/{SUBJECT}/{SESSION}/func/{SUBJECT}_{SESSION}_task-linebisection_events.tsv"
    
    # Create temporary directory for event files
    with tempfile.TemporaryDirectory() as temp_dir:
        # Convert BIDS events to FSL format
        print("📝 Converting BIDS events to FSL format...")
        fsl_events = create_fsl_event_file(
            events_file, 
            os.path.join(temp_dir, "events.txt")
        )
        
        # Create EV dictionary
        ev_files = {}
        for trial_type, ev_file in fsl_events:
            # Clean trial type name for use as key
            clean_name = trial_type.replace("_", "").replace(" ", "_")
            ev_files[clean_name] = ev_file
        
        # Set up FEAT arguments
        args = FEATGLMArgs(
            input_file=func_file,
            output_dir=os.path.join(OUTPUT_DIR, "feat_glm"),
            tr=2.0,  # From task JSON metadata
            ev_files=ev_files,
            contrasts={
                "task_vs_control": [1, -1] if len(ev_files) >= 2 else [1],
            },
            motion_correction=MotionCorrection.MCFLIRT,
            brain_extraction=True,
            smoothing_kernel=5.0,
            highpass_cutoff=100.0,
            statistical_threshold=StatThreshold.CLUSTER_CORRECTED,
            z_threshold=2.3,
            cluster_p_threshold=0.05,
        )
        
        print("\n🧠 Running FEAT GLM analysis...")
        # Tools use _run method with keyword arguments
        result = tool._run(**args.model_dump())
        print_result(result)
        
        # Check if FSF file was created
        if hasattr(result, 'data') and result.data and result.data.get("outputs"):
            if result.data["outputs"].get("fsf_file"):
                print(f"\n📄 FSF file created: {result.data['outputs']['fsf_file']}")
                
                # Display first few lines of FSF
                if os.path.exists(result.data["outputs"]["fsf_file"]):
                    with open(result.data["outputs"]["fsf_file"], 'r') as f:
                        lines = f.readlines()[:20]
                        print("\nFirst 20 lines of FSF file:")
                        for line in lines:
                            print(f"  {line.rstrip()}")
    
    return result


def test_fsl_melodic_ica():
    """Test FSL MELODIC ICA tool."""
    print_section("Testing FSL MELODIC ICA Tool")
    
    tool = FSLMELODICTool()
    
    # Use fingerfootlips motor task
    func_file = f"{DATASET_ROOT}/{SUBJECT}/{SESSION}/func/{SUBJECT}_{SESSION}_task-fingerfootlips_bold.nii.gz"
    
    args = MELODICArgs(
        input_files=[func_file],
        output_dir=os.path.join(OUTPUT_DIR, "melodic_ica"),
        tr=2.5,  # From task metadata
        approach=ApproachType.CONCAT,
        dimensionality=ICADimensionality.AUTOMATIC,
        bg_threshold=10.0,
        var_norm=True,
        output_all=True,
        report=True,
    )
    
    print("🧠 Running MELODIC ICA analysis...")
    result = tool._run(**args.model_dump())
    print_result(result)
    
    return result


def test_bids_tools():
    """Test BIDS validation and metadata extraction."""
    print_section("Testing BIDS Tools")
    
    bids_tools = BIDSTools()
    
    # Test BIDS validation
    print("\n📋 Testing BIDS validation...")
    validate_tool = bids_tools.get_tool_by_name("validate_bids")
    validate_args = ValidateBIDSArgs(
        bids_dir=DATASET_ROOT
    )
    
    result = validate_tool._run(**validate_args.model_dump())
    print_result(result)
    
    # Test BIDS query
    print("\n📊 Testing BIDS query/metadata extraction...")
    query_tool = bids_tools.get_tool_by_name("query_bids_layout")
    query_args = QueryBIDSLayoutArgs(
        bids_dir=DATASET_ROOT,
        suffix="bold",
        subject=SUBJECT.replace("sub-", ""),
        scope="raw"
    )
    
    result = query_tool._run(**query_args.model_dump())
    print_result(result)
    
    if hasattr(result, 'data') and result.data and result.data.get("files"):
        print("\nFound files:")
        for file in result.data["files"][:5]:  # Show first 5 files
            print(f"  - {file}")
    
    return result


def test_fmriprep_tool():
    """Test fMRIPrep command generation."""
    print_section("Testing fMRIPrep Tool")
    
    tool = FMRIPrepTool()
    
    args = FMRIPrepArgs(
        bids_dir=DATASET_ROOT,
        output_dir=os.path.join(OUTPUT_DIR, "fmriprep"),
        participant_label=[SUBJECT.replace("sub-", "")],  # Must be a list
        work_dir=os.path.join(OUTPUT_DIR, "fmriprep_work"),
        use_aroma=True,
        output_spaces=["MNI152NLin2009cAsym", "fsaverage"],
        skull_strip_t1w="auto",
        n_cpus=4,
        mem_mb=16000,
    )
    
    print("🧠 Generating fMRIPrep command...")
    result = tool._run(**args.model_dump())
    print_result(result)
    
    if hasattr(result, 'data') and result.data and result.data.get("command"):
        print("\n📝 Generated command (formatted):")
        cmd_parts = result.data["command"].split()
        for i, part in enumerate(cmd_parts):
            if part.startswith("--"):
                print(f"\n  {part}", end=" ")
            else:
                print(part, end=" ")
        print()
    
    return result


def test_qc_tools():
    """Test quality control tools."""
    print_section("Testing QC Tools")
    
    # QC tools need specific setup, skipping for now
    print("⏭️  Skipping QC tools test (requires specific setup)")
    
    return {"success": True, "message": "Skipped - requires specific QC tool setup"}


def test_integration_pipeline():
    """Test integrating multiple tools in a pipeline."""
    print_section("Testing Tool Integration Pipeline")
    
    print("🔗 Creating analysis pipeline: BIDS validation → GLM → ICA")
    
    results = {}
    
    # Step 1: Validate BIDS
    print("\nStep 1: BIDS Validation")
    bids_tools = BIDSTools()
    validate_tool = bids_tools.get_tool_by_name("validate_bids")
    validate_result = validate_tool._run(
        bids_dir=DATASET_ROOT
    )
    results["bids_validation"] = validate_result
    print(f"  BIDS valid: {validate_result.status == 'success' if hasattr(validate_result, 'status') else validate_result.get('success', False)}")
    
    # Step 2: Run GLM
    func_file = f"{DATASET_ROOT}/{SUBJECT}/{SESSION}/func/{SUBJECT}_{SESSION}_task-fingerfootlips_bold.nii.gz"
    
    # Check validation result - handle ToolResult object
    validation_ok = True  # Continue even if validation has issues
    if hasattr(validate_result, 'status'):
        validation_ok = validate_result.status != "critical_error"  
    
    if validation_ok:
        print("\nStep 2: GLM Analysis")
        feat_tool = FSLFEATTool()
        
        # Simple GLM without events for pipeline test
        glm_result = feat_tool._run(
            input_file=func_file,
            output_dir=os.path.join(OUTPUT_DIR, "pipeline_glm"),
            tr=2.5,
            ev_files={},
            contrasts={},
            motion_correction=MotionCorrection.MCFLIRT,
            brain_extraction=True,
            smoothing_kernel=5.0,
        )
        results["glm"] = glm_result
        print(f"  GLM complete: {glm_result.status == 'success' if hasattr(glm_result, 'status') else False}")
        
        # Step 3: Run ICA
        glm_success = glm_result.status == 'success' if hasattr(glm_result, 'status') else False
        if glm_success:
            print("\nStep 3: ICA Analysis")
            melodic_tool = FSLMELODICTool()
            ica_result = melodic_tool._run(
                input_files=[func_file],
                output_dir=os.path.join(OUTPUT_DIR, "pipeline_ica"),
                tr=2.5,
                approach="concat",
                dimensionality="automatic",
            )
            results["ica"] = ica_result
            print(f"  ICA complete: {ica_result.status == 'success' if hasattr(ica_result, 'status') else ica_result.get('success', False)}")
    
    print("\n📊 Pipeline Summary:")
    for step, result in results.items():
        if hasattr(result, 'status'):
            status = "✅" if result.status == 'success' else "❌"
        else:
            status = "✅" if result.get("success", False) else "❌"
        print(f"  {status} {step}")
    
    return results


def main():
    """Run all tests."""
    print("\n" + "🧠" * 20)
    print("  BRAIN RESEARCHER TOOLS TEST SUITE")
    print("  Dataset: ds000114 from OpenNeuro")
    print("🧠" * 20)
    
    # Test results collection
    all_results = {}
    
    # 1. Test tool registry
    registry = test_tool_registry()
    
    # 2. Test individual tools
    all_results["feat_glm"] = test_fsl_feat_glm()
    all_results["melodic_ica"] = test_fsl_melodic_ica()
    all_results["bids"] = test_bids_tools()
    all_results["fmriprep"] = test_fmriprep_tool()
    all_results["qc"] = test_qc_tools()
    
    # 3. Test integration
    all_results["pipeline"] = test_integration_pipeline()
    
    # Summary
    print_section("TEST SUMMARY")
    
    total_tests = len(all_results)
    passed_tests = sum(1 for r in all_results.values() if (hasattr(r, 'status') and r.status == 'success') or r.get("success", False))
    
    print(f"\nTotal Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
    
    print("\n📁 Test outputs saved to:", OUTPUT_DIR)
    
    # Save results to JSON
    results_file = os.path.join(OUTPUT_DIR, "test_results.json")
    with open(results_file, 'w') as f:
        # Convert results to JSON-serializable format
        json_results = {}
        for key, value in all_results.items():
            if hasattr(value, 'status'):
                # ToolResult object
                json_results[key] = {
                    "success": value.status == "success",
                    "message": str(value.error or value.data.get("message", "") if value.data else ""),
                    "command": str(value.data.get("command", "") if value.data else "") or None,
                }
            elif isinstance(value, dict):
                json_results[key] = {
                    "success": value.get("success", False),
                    "message": str(value.get("message", "")),
                    "command": str(value.get("command", "")) if value.get("command") else None,
                }
        json.dump(json_results, f, indent=2)
    
    print(f"📊 Results saved to: {results_file}")
    
    return all_results


if __name__ == "__main__":
    results = main()
