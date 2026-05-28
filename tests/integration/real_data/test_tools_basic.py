#!/usr/bin/env python3
"""
Basic test for Brain Researcher tools to verify functionality.
Tests core tools with minimal dependencies.
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Create output directory
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs" / "basic_test")
LOG_DIR = str(REPO_ROOT / "outputs" / "test_logs" / datetime.now().strftime("%Y%m%d_%H%M%S"))
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# Test results
test_results = {
    "timestamp": datetime.now().isoformat(),
    "tests": {},
    "summary": {}
}


def log_test(test_name: str, status: str, message: str, error: str = None):
    """Log test results."""
    test_results["tests"][test_name] = {
        "status": status,
        "message": message,
        "error": error,
        "timestamp": datetime.now().isoformat()
    }
    
    # Print to console
    icon = "✅" if status == "success" else "❌" if status == "error" else "⚠️"
    print(f"{icon} {test_name}: {message}")
    if error:
        print(f"   Error: {error[:200]}")
    
    # Write to log file
    log_file = os.path.join(LOG_DIR, "test_log.txt")
    with open(log_file, "a") as f:
        f.write(f"{datetime.now()} - {test_name} - {status} - {message}\n")
        if error:
            f.write(f"   Error: {error}\n")


def test_tool_registry():
    """Test tool registry discovery."""
    test_name = "Tool Registry"
    try:
        from brain_researcher.services.tools.tool_registry import ToolRegistry
        
        registry = ToolRegistry(auto_discover=True)
        tool_count = len(registry.tools)
        
        log_test(test_name, "success", f"Found {tool_count} tools")
        
        # List some tools
        tool_names = list(registry.tools.keys())[:10]
        print(f"   Sample tools: {', '.join(tool_names)}")
        
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to load registry", str(e))
        return False


def test_fsl_tools():
    """Test FSL tool imports and basic functionality."""
    test_name = "FSL Tools"
    try:
        # Import with correct names
        from brain_researcher.services.tools.fsl_bet_tool import FSLBETTool, FSLBETArgs
        from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTool, FSLFLIRTArgs
        from brain_researcher.services.tools.fsl_melodic_tool import FSLMELODICTool, FSLMELODICArgs
        
        # Create tool instances
        bet_tool = FSLBETTool()
        flirt_tool = FSLFLIRTTool()
        melodic_tool = FSLMELODICTool()
        
        log_test(test_name, "success", "FSL tools imported successfully")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import FSL tools", str(e))
        return False


def test_mne_tools():
    """Test MNE tool imports."""
    test_name = "MNE Tools"
    try:
        from brain_researcher.services.tools.mne_preprocessing_tool import MNEPreprocessingTool
        from brain_researcher.services.tools.mne_ica_tool import MNEICATool
        from brain_researcher.services.tools.mne_timefreq_tool import MNETimeFreqTool
        from brain_researcher.services.tools.mne_connectivity_tool import MNEConnectivityTool
        
        # Create tool instances
        preproc_tool = MNEPreprocessingTool()
        ica_tool = MNEICATool()
        
        log_test(test_name, "success", "MNE tools imported successfully")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import MNE tools", str(e))
        return False


def test_dl_tools():
    """Test Deep Learning tool imports."""
    test_name = "Deep Learning Tools"
    try:
        from brain_researcher.services.tools.dl_pytorch_tool import DLPyTorchTool
        from brain_researcher.services.tools.gnn_connectivity_tool import GNNConnectivityTool
        
        # Create tool instances
        dl_tool = DLPyTorchTool()
        gnn_tool = GNNConnectivityTool()
        
        log_test(test_name, "success", "DL tools imported successfully")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import DL tools", str(e))
        return False


def test_multimodal_tools():
    """Test Multimodal Integration tool imports."""
    test_name = "Multimodal Tools"
    try:
        from brain_researcher.services.tools.multimodal_integration_tool import MultimodalIntegrationTool
        
        # Create tool instance
        mm_tool = MultimodalIntegrationTool()
        
        log_test(test_name, "success", "Multimodal tools imported successfully")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import Multimodal tools", str(e))
        return False


def test_bids_tools():
    """Test BIDS tool imports."""
    test_name = "BIDS Tools"
    try:
        from brain_researcher.services.tools.bids_tools import BIDSTools
        
        # Create tool instance
        bids_tool = BIDSTools()
        
        # Check available methods
        tool_names = [tool.get_tool_name() for tool in bids_tool.tools]
        print(f"   BIDS tools available: {', '.join(tool_names)}")
        
        log_test(test_name, "success", f"BIDS tools imported ({len(tool_names)} tools)")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import BIDS tools", str(e))
        return False


def test_statistical_tools():
    """Test Statistical analysis tool imports."""
    test_name = "Statistical Tools"
    try:
        from brain_researcher.services.tools.statsmodels_glm_tool import StatsmodelsGLMTool
        from brain_researcher.services.tools.multiple_comparison_tool import MultipleComparisonTool
        
        # Create tool instances
        glm_tool = StatsmodelsGLMTool()
        mc_tool = MultipleComparisonTool()
        
        log_test(test_name, "success", "Statistical tools imported successfully")
        return True
        
    except Exception as e:
        log_test(test_name, "error", "Failed to import Statistical tools", str(e))
        return False


def test_dataset_availability():
    """Check if datasets are available."""
    test_name = "Dataset Availability"
    
    datasets = {
        "ds000114": "/app/data/openneuro/ds000114",
        "ds000117": "/app/data/openneuro/ds000117",
        "MNE Sample": "/app/data/mne/sample",
        "Sleep-EDF": "/app/data/sleep_edf"
    }
    
    available = []
    missing = []
    
    for name, path in datasets.items():
        if os.path.exists(path):
            available.append(name)
        else:
            missing.append(name)
    
    message = f"Available: {len(available)}/{len(datasets)}"
    if available:
        print(f"   ✅ Available: {', '.join(available)}")
    if missing:
        print(f"   ❌ Missing: {', '.join(missing)}")
    
    status = "success" if available else "error"
    log_test(test_name, status, message)
    
    return len(available) > 0


def test_simple_tool_execution():
    """Test simple tool execution without data dependencies."""
    test_name = "Tool Execution"
    
    try:
        from brain_researcher.services.tools.tool_registry import ToolRegistry
        
        registry = ToolRegistry(auto_discover=True)
        
        # Test tool search
        tools = registry.get_tools_for_task("GLM analysis", k=3)
        
        if tools:
            log_test(test_name, "success", f"Tool search working ({len(tools)} tools found)")
            return True
        else:
            log_test(test_name, "warning", "No tools found for search")
            return False
            
    except Exception as e:
        log_test(test_name, "error", "Failed to execute tool search", str(e))
        return False


def generate_summary():
    """Generate test summary."""
    total_tests = len(test_results["tests"])
    successful = sum(1 for t in test_results["tests"].values() if t["status"] == "success")
    failed = sum(1 for t in test_results["tests"].values() if t["status"] == "error")
    warnings = sum(1 for t in test_results["tests"].values() if t["status"] == "warning")
    
    test_results["summary"] = {
        "total": total_tests,
        "successful": successful,
        "failed": failed,
        "warnings": warnings,
        "success_rate": (successful / total_tests * 100) if total_tests > 0 else 0
    }
    
    # Save results
    result_file = os.path.join(LOG_DIR, "test_results.json")
    with open(result_file, "w") as f:
        json.dump(test_results, f, indent=2)
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {total_tests}")
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    print(f"⚠️  Warnings: {warnings}")
    print(f"Success Rate: {test_results['summary']['success_rate']:.1f}%")
    print(f"\nLogs saved to: {LOG_DIR}")
    
    return test_results["summary"]


def main():
    """Run basic tests."""
    print("\n" + "=" * 60)
    print("BRAIN RESEARCHER TOOLS - BASIC TEST SUITE")
    print("=" * 60)
    print(f"Timestamp: {datetime.now()}")
    print(f"Log directory: {LOG_DIR}\n")
    
    # Run tests
    test_tool_registry()
    test_fsl_tools()
    test_mne_tools()
    test_dl_tools()
    test_multimodal_tools()
    test_bids_tools()
    test_statistical_tools()
    test_dataset_availability()
    test_simple_tool_execution()
    
    # Generate summary
    summary = generate_summary()
    
    # Return appropriate exit code
    if summary["failed"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
