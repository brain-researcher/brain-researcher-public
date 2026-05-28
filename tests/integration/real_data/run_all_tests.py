#!/usr/bin/env python3
"""
Master test runner for all Brain Researcher neuroimaging tools.

This script runs all test suites and generates a comprehensive report
of tool functionality across different data modalities.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Test script locations
TEST_SCRIPTS = {
    "fMRI/sMRI Tools": "test_fmri_smri_tools.py",
    "MEG/EEG Tools": "test_meg_eeg_tools.py", 
    "Deep Learning & GNN": "test_dl_gnn_tools.py",
    "Multimodal Integration": "test_multimodal_integration.py",
    "Original ds000114 Test": "test_real_data_ds000114.py"
}

# Output directory for consolidated reports
REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs")
REPORT_DIR = os.path.join(OUTPUT_DIR, "consolidated_reports")
Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)

# Results tracking
all_results = {}
execution_times = {}
test_status = {}


def print_header(title: str):
    """Print a formatted header."""
    width = 80
    print("\n" + "=" * width)
    print(f"{title:^{width}}")
    print("=" * width)


def print_section(title: str):
    """Print a section header."""
    print("\n" + "-" * 60)
    print(f" {title}")
    print("-" * 60)


def run_test_script(name: str, script: str) -> Dict[str, Any]:
    """Run a single test script and capture results."""
    print_section(f"Running: {name}")
    
    script_path = os.path.join(os.path.dirname(__file__), script)
    
    if not os.path.exists(script_path):
        print(f"⚠️  Script not found: {script_path}")
        return {"status": "not_found", "error": f"Script {script} not found"}
    
    start_time = time.time()
    
    try:
        # Run the test script
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout per test suite
        )
        
        elapsed_time = time.time() - start_time
        
        # Parse output for success/failure
        output = result.stdout
        error = result.stderr
        
        # Look for success indicators in output
        success_indicators = ["PASS", "SUCCESS", "✅", "passed"]
        failure_indicators = ["FAIL", "ERROR", "❌", "failed"]
        
        passed_count = sum(1 for indicator in success_indicators if indicator in output.upper())
        failed_count = sum(1 for indicator in failure_indicators if indicator in output.upper())
        
        # Extract test counts from output if available
        test_count = 0
        if "Total Tests:" in output:
            try:
                line = [l for l in output.split('\n') if "Total Tests:" in l][0]
                test_count = int(line.split("Total Tests:")[1].split()[0])
            except:
                pass
        
        status = "success" if result.returncode == 0 else "failure"
        
        return {
            "status": status,
            "return_code": result.returncode,
            "elapsed_time": elapsed_time,
            "test_count": test_count,
            "passed_indicators": passed_count,
            "failed_indicators": failed_count,
            "output_snippet": output[-500:] if len(output) > 500 else output,
            "error": error if error else None
        }
        
    except subprocess.TimeoutExpired:
        elapsed_time = time.time() - start_time
        print(f"⏱️  Timeout after {elapsed_time:.2f}s")
        return {
            "status": "timeout",
            "elapsed_time": elapsed_time,
            "error": "Test execution timed out after 10 minutes"
        }
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"❌ Error: {str(e)}")
        return {
            "status": "error",
            "elapsed_time": elapsed_time,
            "error": str(e)
        }


def collect_individual_reports() -> Dict[str, Any]:
    """Collect individual test reports from output directories."""
    reports = {}
    
    report_patterns = [
        ("fMRI/sMRI", "fmri_smri/test_report_fmri_smri.json"),
        ("MEG/EEG", "meg_eeg/test_report_meg_eeg.json"),
        ("DL/GNN", "dl_gnn/test_report_dl_gnn.json"),
        ("Multimodal", "multimodal/test_report_multimodal.json"),
        ("Original", "test_results.json")
    ]
    
    for name, path in report_patterns:
        full_path = os.path.join(OUTPUT_DIR, path)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r') as f:
                    reports[name] = json.load(f)
                print(f"  ✅ Loaded report: {name}")
            except Exception as e:
                print(f"  ⚠️  Failed to load {name}: {e}")
    
    return reports


def generate_consolidated_report():
    """Generate a comprehensive consolidated report."""
    print_header("GENERATING CONSOLIDATED REPORT")
    
    # Collect individual reports
    individual_reports = collect_individual_reports()
    
    # Create consolidated report
    report = {
        "test_date": datetime.now().isoformat(),
        "test_suites": list(TEST_SCRIPTS.keys()),
        "execution_summary": test_status,
        "execution_times": execution_times,
        "individual_reports": individual_reports,
        "datasets_used": {
            "fMRI/sMRI": "ds000114 (OpenNeuro)",
            "MEG": "ds000117 (OpenNeuro)",
            "EEG": "Sleep-EDF",
            "Sample": "MNE Sample Data"
        }
    }
    
    # Calculate overall statistics
    total_tests = len(test_status)
    successful = sum(1 for s in test_status.values() if s.get("status") == "success")
    failed = sum(1 for s in test_status.values() if s.get("status") == "failure")
    timeouts = sum(1 for s in test_status.values() if s.get("status") == "timeout")
    not_found = sum(1 for s in test_status.values() if s.get("status") == "not_found")
    
    report["overall_summary"] = {
        "total_test_suites": total_tests,
        "successful": successful,
        "failed": failed,
        "timeouts": timeouts,
        "not_found": not_found,
        "success_rate": (successful / total_tests * 100) if total_tests > 0 else 0,
        "total_execution_time": sum(execution_times.values())
    }
    
    # Tool coverage analysis
    tool_coverage = analyze_tool_coverage(individual_reports)
    report["tool_coverage"] = tool_coverage
    
    # Save JSON report
    json_file = os.path.join(REPORT_DIR, "consolidated_test_report.json")
    with open(json_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n📊 JSON report saved: {json_file}")
    
    # Generate markdown report
    generate_markdown_report(report)
    
    return report


def analyze_tool_coverage(reports: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze tool coverage across all tests."""
    coverage = {
        "tools_tested": set(),
        "by_category": {},
        "success_rates": {}
    }
    
    # Categories of tools
    categories = {
        "FSL Suite": ["BET", "FLIRT", "FNIRT", "FEAT", "MELODIC", "FIX", "PALM"],
        "MNE": ["Preprocessing", "ICA", "Time-Frequency", "Source", "Connectivity", "FOOOF", "Autoreject"],
        "Nilearn": ["GLM", "Connectivity", "Masking", "Decoding"],
        "Deep Learning": ["CNN3D", "LSTM", "VAE", "Transformer"],
        "GNN": ["Node Classification", "Graph Classification", "Link Prediction", "Community Detection"],
        "Multimodal": ["CCA", "PLS", "ICA Fusion", "NMF", "Tensor", "Graph Fusion"],
        "Statistical": ["Statsmodels", "Multiple Comparisons", "Permutation Tests"],
        "BIDS": ["Validation", "Query", "Metadata"],
        "QC": ["MRIQC", "Visual QC", "Autoreject"]
    }
    
    # Extract tested tools from reports
    for name, report in reports.items():
        if isinstance(report, dict):
            # Look for tool information in various places
            if "tool_categories" in report:
                for category, tools in report["tool_categories"].items():
                    if category not in coverage["by_category"]:
                        coverage["by_category"][category] = []
                    coverage["by_category"][category].extend(tools)
                    coverage["tools_tested"].update(tools)
            
            # Extract success rates
            if "summary" in report and "success_rate" in report["summary"]:
                coverage["success_rates"][name] = report["summary"]["success_rate"]
    
    # Convert set to list for JSON serialization
    coverage["tools_tested"] = list(coverage["tools_tested"])
    coverage["total_tools_tested"] = len(coverage["tools_tested"])
    
    # Calculate category coverage
    for category, expected_tools in categories.items():
        tested = [t for t in expected_tools if any(t in str(coverage["tools_tested"]) for t in expected_tools)]
        coverage["by_category"][category] = {
            "expected": len(expected_tools),
            "tested": len(tested),
            "coverage": len(tested) / len(expected_tools) * 100 if expected_tools else 0
        }
    
    return coverage


def generate_markdown_report(report: Dict[str, Any]):
    """Generate a comprehensive markdown report."""
    md_content = f"""# Brain Researcher Tools - Comprehensive Test Report

## Executive Summary
- **Test Date**: {report['test_date']}
- **Total Test Suites**: {report['overall_summary']['total_test_suites']}
- **Successful**: {report['overall_summary']['successful']}
- **Failed**: {report['overall_summary']['failed']}
- **Success Rate**: {report['overall_summary']['success_rate']:.1f}%
- **Total Execution Time**: {report['overall_summary']['total_execution_time']:.2f} seconds

## Datasets Used
"""
    
    for name, dataset in report["datasets_used"].items():
        md_content += f"- **{name}**: {dataset}\n"
    
    md_content += "\n## Test Suite Results\n\n"
    
    for suite_name, status in test_status.items():
        icon = "✅" if status["status"] == "success" else "❌"
        md_content += f"### {icon} {suite_name}\n"
        md_content += f"- **Status**: {status['status']}\n"
        md_content += f"- **Execution Time**: {status.get('elapsed_time', 0):.2f}s\n"
        if status.get("test_count"):
            md_content += f"- **Tests Run**: {status['test_count']}\n"
        if status.get("error"):
            md_content += f"- **Error**: {status['error']}\n"
        md_content += "\n"
    
    # Tool coverage section
    if "tool_coverage" in report:
        md_content += "## Tool Coverage Analysis\n\n"
        md_content += f"- **Total Unique Tools Tested**: {report['tool_coverage'].get('total_tools_tested', 0)}\n\n"
        
        md_content += "### Coverage by Category\n\n"
        md_content += "| Category | Expected | Tested | Coverage |\n"
        md_content += "|----------|----------|--------|----------|\n"
        
        for category, info in report["tool_coverage"]["by_category"].items():
            if isinstance(info, dict):
                md_content += f"| {category} | {info['expected']} | {info['tested']} | {info['coverage']:.1f}% |\n"
    
    # Individual report summaries
    md_content += "\n## Individual Test Suite Summaries\n\n"
    
    for name, ind_report in report["individual_reports"].items():
        if isinstance(ind_report, dict) and "summary" in ind_report:
            summary = ind_report["summary"]
            md_content += f"### {name}\n"
            if "total_tests" in summary:
                md_content += f"- Tests: {summary['total_tests']}\n"
            if "successful_tests" in summary:
                md_content += f"- Passed: {summary['successful_tests']}\n"
            if "success_rate" in summary:
                md_content += f"- Success Rate: {summary['success_rate']:.1f}%\n"
            md_content += "\n"
    
    # Recommendations
    md_content += """## Recommendations

### High Priority Actions
1. **Install Missing Dependencies**: 
   - BIDS validator for dataset validation
   - PyTorch for deep learning models
   - FOOOF for spectral parameterization

2. **Fix Failing Tests**:
   - Review error logs in individual test reports
   - Update tool implementations with proper error handling
   
3. **Performance Optimization**:
   - Consider parallel execution for independent tests
   - Implement caching for preprocessed data
   
### Future Enhancements
1. Add continuous integration (CI) for automated testing
2. Implement performance benchmarking
3. Add real-time monitoring dashboard
4. Create tool-specific documentation

## Output Files
- Consolidated JSON Report: `consolidated_reports/consolidated_test_report.json`
- Individual Test Reports: Available in respective output directories
- Test Logs: Check individual test output directories

---
*Generated by Brain Researcher Test Suite*
"""
    
    md_file = os.path.join(REPORT_DIR, "consolidated_test_report.md")
    with open(md_file, 'w') as f:
        f.write(md_content)
    print(f"📝 Markdown report saved: {md_file}")


def main():
    """Run all test suites and generate consolidated report."""
    print_header("BRAIN RESEARCHER COMPREHENSIVE TEST SUITE")
    print(f"\nStarting at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Output directory: {OUTPUT_DIR}")
    
    total_start = time.time()
    
    # Run each test suite
    for name, script in TEST_SCRIPTS.items():
        result = run_test_script(name, script)
        test_status[name] = result
        execution_times[name] = result.get("elapsed_time", 0)
        
        # Print immediate feedback
        if result["status"] == "success":
            print(f"  ✅ Completed in {result['elapsed_time']:.2f}s")
        elif result["status"] == "not_found":
            print(f"  ⏭️  Skipped - script not found")
        elif result["status"] == "timeout":
            print(f"  ⏱️  Timed out after {result['elapsed_time']:.2f}s")
        else:
            print(f"  ❌ Failed with code {result.get('return_code', 'N/A')}")
    
    total_elapsed = time.time() - total_start
    
    # Generate consolidated report
    report = generate_consolidated_report()
    
    # Print final summary
    print_header("TEST SUITE COMPLETE")
    
    print(f"\n📊 Overall Statistics:")
    print(f"  Total Test Suites: {report['overall_summary']['total_test_suites']}")
    print(f"  Successful: {report['overall_summary']['successful']}")
    print(f"  Failed: {report['overall_summary']['failed']}")
    print(f"  Timeouts: {report['overall_summary']['timeouts']}")
    print(f"  Not Found: {report['overall_summary']['not_found']}")
    print(f"  Success Rate: {report['overall_summary']['success_rate']:.1f}%")
    print(f"  Total Time: {total_elapsed:.2f} seconds")
    
    print(f"\n📁 Reports saved to: {REPORT_DIR}")
    print("  - consolidated_test_report.json")
    print("  - consolidated_test_report.md")
    
    # Exit with appropriate code
    if report['overall_summary']['failed'] > 0:
        print("\n⚠️  Some tests failed. Check individual reports for details.")
        sys.exit(1)
    else:
        print("\n✅ All test suites completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
