#!/usr/bin/env python3
"""
Automated testing script for new neuroimaging tools.

This script provides comprehensive testing and validation for newly implemented
neuroimaging tools, including unit tests, integration tests, performance benchmarks,
and automatic status updates.

Usage:
    python test_new_tool.py --tool-name mne_preprocessing --category eeg
    python test_new_tool.py --tool-name fsl_bet --category mri --update-all
    python test_new_tool.py --list-pending
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tempfile
import shutil


class ToolTester:
    """Automated testing framework for neuroimaging tools."""
    
    def __init__(self, tool_name: str, category: str):
        """Initialize the tool tester.
        
        Args:
            tool_name: Name of the tool to test (e.g., 'mne_preprocessing')
            category: Tool category (e.g., 'eeg', 'mri', 'stats')
        """
        self.tool_name = tool_name
        self.category = category
        self.project_root = Path("/app/brain_researcher")
        self.test_data_path = Path("/app/data/openneuro/ds000114")
        self.results = {
            "tool": tool_name,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "environment": self._get_environment_info(),
            "tests": {},
            "metrics": {}
        }
    
    def _get_environment_info(self) -> Dict:
        """Get current environment information."""
        try:
            conda_env = os.environ.get('CONDA_DEFAULT_ENV', 'base')
            python_version = sys.version.split()[0]
            
            return {
                "conda_env": conda_env,
                "python_version": python_version,
                "platform": sys.platform,
                "test_data_available": self.test_data_path.exists()
            }
        except Exception as e:
            return {"error": str(e)}
    
    def check_package_installation(self) -> bool:
        """Check if required packages are installed."""
        print(f"\n🔍 Checking package dependencies for {self.tool_name}...")
        
        # Map tool categories to required packages
        package_requirements = {
            "eeg": ["mne", "autoreject", "fooof", "mne_bids"],
            "mri": ["nibabel", "nilearn", "nipype"],
            "stats": ["statsmodels", "sklearn", "scipy"],
            "connectivity": ["networkx", "bct", "nilearn"],
            "meta": ["nimare", "neurosynth"],
            "dl": ["torch", "monai"],
        }
        
        required_packages = package_requirements.get(self.category, [])
        missing_packages = []
        
        for package in required_packages:
            try:
                __import__(package.replace("-", "_"))
                print(f"  ✅ {package} installed")
            except ImportError:
                print(f"  ❌ {package} missing")
                missing_packages.append(package)
        
        if missing_packages:
            print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
            response = input("Attempt to install missing packages? (y/n): ")
            
            if response.lower() == 'y':
                for package in missing_packages:
                    self._install_package(package)
            else:
                return False
        
        return True
    
    def _install_package(self, package: str):
        """Attempt to install a missing package."""
        print(f"Installing {package}...")
        try:
            result = subprocess.run(
                ["pip", "install", package],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                print(f"  ✅ Successfully installed {package}")
                return True
            else:
                print(f"  ❌ Failed to install {package}: {result.stderr}")
                return False
        except Exception as e:
            print(f"  ❌ Error installing {package}: {e}")
            return False
    
    def create_test_file(self) -> bool:
        """Create a test file if it doesn't exist."""
        test_file = self.project_root / f"tests/unit/agent/tools/test_{self.tool_name}_tool.py"
        
        if test_file.exists():
            print(f"✅ Test file exists: {test_file}")
            return True
        
        print(f"📝 Creating test file: {test_file}")
        
        template = f'''"""Tests for {self.tool_name.replace('_', ' ').title()} tool."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from brain_researcher.services.tools.{self.category}_{self.tool_name} import {self.tool_name.title().replace('_', '')}Tool


class Test{self.tool_name.title().replace('_', '')}Tool:
    """Test suite for {self.tool_name.replace('_', ' ').title()} tool."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = {self.tool_name.title().replace('_', '')}Tool()
        self.temp_dir = tempfile.mkdtemp()
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "{self.tool_name}"
        assert self.tool.get_tool_description() is not None
    
    def test_args_schema(self):
        """Test argument schema validation."""
        schema = self.tool.get_args_schema()
        assert schema is not None
    
    def test_basic_execution(self):
        """Test basic tool execution."""
        # Add basic test implementation
        pass
    
    @pytest.mark.integration
    def test_with_real_data(self):
        """Test with real neuroimaging data."""
        test_file = "{self.test_data_path}/sub-01/ses-test/func/sub-01_ses-test_task-fingerfootlips_bold.nii.gz"
        
        if Path(test_file).exists():
            # Add real data test
            pass
        else:
            pytest.skip("Test data not available")
'''
        
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(template)
        print(f"  ✅ Test file created")
        return True
    
    def run_unit_tests(self) -> Dict:
        """Run unit tests for the tool."""
        print(f"\n🧪 Running unit tests for {self.tool_name}...")
        
        test_file = f"tests/unit/agent/tools/test_{self.tool_name}_tool.py"
        
        result = subprocess.run(
            ["pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=self.project_root
        )
        
        test_result = {
            "passed": result.returncode == 0,
            "output": result.stdout,
            "errors": result.stderr,
            "return_code": result.returncode
        }
        
        # Parse test results
        if "passed" in result.stdout:
            import re
            match = re.search(r'(\d+) passed', result.stdout)
            if match:
                test_result["n_passed"] = int(match.group(1))
        
        if test_result["passed"]:
            print(f"  ✅ Unit tests passed")
        else:
            print(f"  ❌ Unit tests failed")
            print(f"  Error: {result.stderr[:500]}")
        
        return test_result
    
    def run_integration_tests(self) -> Dict:
        """Run integration tests with real data."""
        print(f"\n🔗 Running integration tests for {self.tool_name}...")
        
        if not self.test_data_path.exists():
            print(f"  ⚠️  Test data not available at {self.test_data_path}")
            return {"passed": False, "reason": "Test data not available"}
        
        test_file = f"tests/unit/agent/tools/test_{self.tool_name}_tool.py"
        
        result = subprocess.run(
            ["pytest", test_file, "-v", "-m", "integration", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=self.project_root
        )
        
        test_result = {
            "passed": result.returncode == 0,
            "output": result.stdout,
            "errors": result.stderr,
            "return_code": result.returncode
        }
        
        if test_result["passed"]:
            print(f"  ✅ Integration tests passed")
        else:
            print(f"  ❌ Integration tests failed")
        
        return test_result
    
    def run_performance_benchmark(self) -> Dict:
        """Run performance benchmarks."""
        print(f"\n⚡ Running performance benchmark for {self.tool_name}...")
        
        # Create a simple benchmark script
        benchmark_script = f"""
import time
import tempfile
from brain_researcher.services.tools.{self.category}_{self.tool_name} import {self.tool_name.title().replace('_', '')}Tool

tool = {self.tool_name.title().replace('_', '')}Tool()

# Benchmark initialization
start = time.time()
tool = {self.tool_name.title().replace('_', '')}Tool()
init_time = time.time() - start

# Benchmark execution (with mock data)
start = time.time()
result = tool._run(
    input_file="test.nii.gz",
    output_dir=tempfile.mkdtemp()
)
exec_time = time.time() - start

print(f"Initialization: {{init_time:.3f}}s")
print(f"Execution: {{exec_time:.3f}}s")
"""
        
        # Write and run benchmark
        benchmark_file = self.project_root / f"benchmark_{self.tool_name}.py"
        benchmark_file.write_text(benchmark_script)
        
        try:
            result = subprocess.run(
                ["python", str(benchmark_file)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.project_root
            )
            
            perf_result = {
                "passed": result.returncode == 0,
                "output": result.stdout,
                "errors": result.stderr
            }
            
            # Parse timing information
            if "Initialization:" in result.stdout:
                import re
                init_match = re.search(r'Initialization: ([\d.]+)s', result.stdout)
                exec_match = re.search(r'Execution: ([\d.]+)s', result.stdout)
                
                if init_match and exec_match:
                    perf_result["init_time"] = float(init_match.group(1))
                    perf_result["exec_time"] = float(exec_match.group(1))
                    
                    # Check performance criteria
                    if perf_result["init_time"] < 5.0 and perf_result["exec_time"] < 120.0:
                        print(f"  ✅ Performance benchmark passed")
                        print(f"     Init: {perf_result['init_time']:.3f}s, Exec: {perf_result['exec_time']:.3f}s")
                    else:
                        print(f"  ⚠️  Performance below target")
                        perf_result["passed"] = False
            
        except subprocess.TimeoutExpired:
            perf_result = {
                "passed": False,
                "errors": "Benchmark timed out after 60 seconds"
            }
            print(f"  ❌ Performance benchmark timed out")
        finally:
            # Clean up
            if benchmark_file.exists():
                benchmark_file.unlink()
        
        return perf_result
    
    def check_registry_integration(self) -> bool:
        """Check if the tool is properly integrated in the registry."""
        print(f"\n📋 Checking registry integration for {self.tool_name}...")
        
        check_script = f"""
from brain_researcher.services.tools.tool_registry import ToolRegistry

registry = ToolRegistry(auto_discover=True)
tool = registry.get_tool("{self.tool_name}")

if tool:
    print("Tool found in registry")
    print(f"Name: {{tool.get_tool_name()}}")
    print(f"Description: {{tool.get_tool_description()[:100]}}...")
    exit(0)
else:
    print("Tool not found in registry")
    exit(1)
"""
        
        # Write and run check
        check_file = self.project_root / f"check_registry_{self.tool_name}.py"
        check_file.write_text(check_script)
        
        try:
            result = subprocess.run(
                ["python", str(check_file)],
                capture_output=True,
                text=True,
                cwd=self.project_root
            )
            
            if result.returncode == 0:
                print(f"  ✅ Tool found in registry")
                print(f"  {result.stdout.strip()}")
                return True
            else:
                print(f"  ❌ Tool not found in registry")
                return False
        finally:
            if check_file.exists():
                check_file.unlink()
    
    def update_status_document(self):
        """Update ISSUES_tools_implementation.md with test results."""
        print(f"\n📝 Updating status document for {self.tool_name}...")
        
        status_file = self.project_root / "docs/issues/ISSUES_tools_implementation.md"
        
        if not status_file.exists():
            print(f"  ❌ Status file not found: {status_file}")
            return
        
        content = status_file.read_text()
        
        # Determine overall status
        all_passed = (
            self.results["tests"].get("unit", {}).get("passed", False) and
            self.results["tests"].get("integration", {}).get("passed", False)
        )
        
        # Find and update the tool entry
        tool_id = self.tool_name.upper().replace("_", "-")
        
        if all_passed:
            # Update checkbox to completed
            content = content.replace(f"[ ] ", f"[x] ", 1)  # Update first unchecked box found
            print(f"  ✅ Marked {tool_id} as completed")
        else:
            print(f"  ⚠️  {tool_id} not fully passing - status unchanged")
        
        # Add test summary
        summary = f"\n<!-- Test Results for {tool_id} - {datetime.now().strftime('%Y-%m-%d')} -->\n"
        summary += f"<!-- Unit: {'✅' if self.results['tests'].get('unit', {}).get('passed') else '❌'} | "
        summary += f"Integration: {'✅' if self.results['tests'].get('integration', {}).get('passed') else '❌'} | "
        summary += f"Performance: {'✅' if self.results['tests'].get('performance', {}).get('passed') else '❌'} -->\n"
        
        # Save updated content
        status_file.write_text(content)
        print(f"  ✅ Status document updated")
    
    def update_coverage_matrix(self):
        """Update COVERAGE_MATRIX.md with implementation status."""
        print(f"\n📊 Updating coverage matrix for {self.tool_name}...")
        
        matrix_file = self.project_root / "docs/issues/COVERAGE_MATRIX.md"
        
        if not matrix_file.exists():
            print(f"  ❌ Coverage matrix not found: {matrix_file}")
            return
        
        content = matrix_file.read_text()
        
        # Update status from 📅 (planned) to ✅ (implemented) or 🚧 (in progress)
        all_passed = (
            self.results["tests"].get("unit", {}).get("passed", False) and
            self.results["tests"].get("integration", {}).get("passed", False)
        )
        
        if all_passed:
            # Replace planned with implemented
            content = content.replace("📅", "✅", 1)  # Update first occurrence
            print(f"  ✅ Updated status to implemented")
        else:
            # Replace planned with in progress
            content = content.replace("📅", "🚧", 1)  # Update first occurrence
            print(f"  🚧 Updated status to in progress")
        
        # Save updated content
        matrix_file.write_text(content)
        print(f"  ✅ Coverage matrix updated")
    
    def generate_report(self):
        """Generate a comprehensive test report."""
        report_path = self.project_root / f"test_reports/report_{self.tool_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print(f"\n📄 Test report saved: {report_path}")
        
        # Print summary
        print("\n" + "="*60)
        print(f"TEST SUMMARY: {self.tool_name}")
        print("="*60)
        print(f"Category: {self.category}")
        print(f"Timestamp: {self.results['timestamp']}")
        print(f"Environment: {self.results['environment']['conda_env']}")
        print("\nTest Results:")
        
        for test_type, test_results in self.results['tests'].items():
            if isinstance(test_results, dict):
                status = "✅ PASSED" if test_results.get('passed') else "❌ FAILED"
                print(f"  {test_type.replace('_', ' ').title()}: {status}")
                
                # Show additional metrics if available
                if "n_passed" in test_results:
                    print(f"    Tests passed: {test_results['n_passed']}")
                if "init_time" in test_results:
                    print(f"    Init time: {test_results['init_time']:.3f}s")
                if "exec_time" in test_results:
                    print(f"    Exec time: {test_results['exec_time']:.3f}s")
        
        print("="*60)
        
        # Overall status
        all_passed = all(
            test.get('passed', False) 
            for test in self.results['tests'].values() 
            if isinstance(test, dict)
        )
        
        if all_passed:
            print("🎉 ALL TESTS PASSED! Tool is ready for integration.")
        else:
            print("⚠️  Some tests failed. Please review and fix issues.")
    
    def run_all_tests(self, update_docs: bool = False):
        """Run all tests for the tool."""
        print(f"\n{'='*60}")
        print(f"TESTING TOOL: {self.tool_name}")
        print(f"{'='*60}")
        
        # Check package dependencies
        if not self.check_package_installation():
            print("⚠️  Missing dependencies. Please install required packages.")
            return
        
        # Create test file if needed
        self.create_test_file()
        
        # Run tests
        self.results["tests"]["unit"] = self.run_unit_tests()
        self.results["tests"]["integration"] = self.run_integration_tests()
        self.results["tests"]["performance"] = self.run_performance_benchmark()
        
        # Check registry integration
        self.results["metrics"]["registry_integrated"] = self.check_registry_integration()
        
        # Update documentation if requested
        if update_docs:
            self.update_status_document()
            self.update_coverage_matrix()
        
        # Generate report
        self.generate_report()
        
        # Return overall success status
        return all(
            test.get('passed', False) 
            for test in self.results['tests'].values() 
            if isinstance(test, dict)
        )


def list_pending_tools():
    """List all pending tools from ISSUES_tools_implementation.md."""
    issues_file = Path("/app/brain_researcher/docs/issues/ISSUES_tools_implementation.md")
    
    if not issues_file.exists():
        print("Issues file not found")
        return
    
    content = issues_file.read_text()
    lines = content.split('\n')
    
    print("\n📋 PENDING TOOLS TO IMPLEMENT:")
    print("="*60)
    
    current_category = ""
    pending_count = 0
    
    for line in lines:
        # Check for category headers
        if line.startswith("## ") and "[P" in line:
            current_category = line.replace("## ", "").strip()
        
        # Check for unchecked items
        if line.startswith("- [ ]"):
            if current_category:
                print(f"\n{current_category}")
                current_category = ""
            
            # Extract tool name
            tool_match = line.split(":")[0].replace("- [ ]", "").strip()
            print(f"  - {tool_match}")
            pending_count += 1
    
    print(f"\n{'='*60}")
    print(f"Total pending tools: {pending_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated testing for neuroimaging tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --tool-name mne_preprocessing --category eeg
  %(prog)s --tool-name fsl_bet --category mri --update-all
  %(prog)s --list-pending
        """
    )
    
    parser.add_argument("--tool-name", help="Name of the tool to test")
    parser.add_argument("--category", help="Tool category (eeg, mri, stats, etc.)")
    parser.add_argument("--update-status", action="store_true", 
                       help="Update status documents after testing")
    parser.add_argument("--update-registry", action="store_true",
                       help="Update tool registry after testing")
    parser.add_argument("--update-all", action="store_true",
                       help="Update all documentation after testing")
    parser.add_argument("--list-pending", action="store_true",
                       help="List all pending tools to implement")
    parser.add_argument("--skip-tests", action="store_true",
                       help="Skip running tests (only update docs)")
    
    args = parser.parse_args()
    
    # List pending tools if requested
    if args.list_pending:
        list_pending_tools()
        return
    
    # Validate required arguments
    if not args.tool_name or not args.category:
        print("Error: --tool-name and --category are required")
        parser.print_help()
        sys.exit(1)
    
    # Create tester instance
    tester = ToolTester(args.tool_name, args.category)
    
    # Run tests
    if not args.skip_tests:
        success = tester.run_all_tests(
            update_docs=args.update_all or args.update_status
        )
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
    else:
        # Just update documentation
        if args.update_all or args.update_status:
            tester.update_status_document()
            tester.update_coverage_matrix()
        
        print("✅ Documentation updated (tests skipped)")


if __name__ == "__main__":
    main()
