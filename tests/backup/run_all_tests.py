#!/usr/bin/env python3
"""
Comprehensive Backup Test Runner

This script runs all backup and recovery tests including unit tests,
integration tests, performance tests, and failure scenario tests.
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


class BackupTestRunner:
    """Comprehensive test runner for backup system"""

    def __init__(self, test_root: Path, output_dir: Path):
        self.test_root = test_root
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.test_results = {
            "start_time": datetime.now().isoformat(),
            "test_suites": {},
            "summary": {},
            "end_time": None,
        }

    def run_all_tests(
        self, test_types: Optional[List[str]] = None, verbose: bool = False
    ) -> Dict:
        """Run all backup tests"""
        print("🔄 Starting Comprehensive Backup Test Suite")
        print("=" * 50)

        # Define test suites
        test_suites = {
            "validation": {
                "name": "Backup Validation Tests",
                "module": "test_backup_validation.py",
                "description": "Tests for backup creation, integrity, and validation",
            },
            "recovery": {
                "name": "Recovery Tests",
                "module": "recovery/",
                "description": "Tests for backup recovery procedures",
            },
            "performance": {
                "name": "Performance Tests",
                "module": "test_performance.py",
                "description": "Tests for backup and recovery performance",
            },
            "failure_scenarios": {
                "name": "Failure Scenario Tests",
                "module": "test_failure_scenarios.py",
                "description": "Tests for handling backup failures",
            },
            "monitoring": {
                "name": "Monitoring Tests",
                "module": "test_monitoring.py",
                "description": "Tests for backup monitoring and alerting",
            },
            "integration": {
                "name": "Integration Tests",
                "module": "scripts/test_backup_integration.sh",
                "description": "End-to-end integration tests",
            },
        }

        # Filter test suites if specified
        if test_types:
            test_suites = {k: v for k, v in test_suites.items() if k in test_types}

        # Run each test suite
        for suite_name, suite_info in test_suites.items():
            print(f"\n📋 Running {suite_info['name']}")
            print(f"   {suite_info['description']}")
            print("-" * 50)

            result = self._run_test_suite(suite_name, suite_info, verbose)
            self.test_results["test_suites"][suite_name] = result

            # Print immediate results
            self._print_suite_results(suite_name, result)

        # Generate summary
        self._generate_summary()

        # Save results
        self._save_results()

        print("\n" + "=" * 50)
        print("📊 Test Suite Complete")
        self._print_final_summary()

        return self.test_results

    def _run_test_suite(self, suite_name: str, suite_info: Dict, verbose: bool) -> Dict:
        """Run a single test suite"""
        start_time = time.time()

        result = {
            "name": suite_info["name"],
            "start_time": datetime.now().isoformat(),
            "status": "running",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_skipped": 0,
            "duration_seconds": 0,
            "output_file": None,
            "error_details": [],
        }

        try:
            if suite_info["module"].endswith(".sh"):
                # Shell script test
                result.update(self._run_shell_test(suite_name, suite_info, verbose))
            else:
                # Python pytest test
                result.update(self._run_pytest_test(suite_name, suite_info, verbose))

            result["status"] = "completed"

        except Exception as e:
            result["status"] = "error"
            result["error_details"].append(str(e))
            print(f"❌ Error running {suite_name}: {e}")

        result["duration_seconds"] = time.time() - start_time
        result["end_time"] = datetime.now().isoformat()

        return result

    def _run_pytest_test(
        self, suite_name: str, suite_info: Dict, verbose: bool
    ) -> Dict:
        """Run pytest-based tests"""
        module_path = self.test_root / suite_info["module"]
        output_file = self.output_dir / f"{suite_name}_results.xml"

        # Build pytest command
        pytest_cmd = [
            "python",
            "-m",
            "pytest",
            str(module_path),
            "--junitxml",
            str(output_file),
            "--tb=short",
            "-v" if verbose else "-q",
        ]

        # Add coverage if requested
        if os.getenv("BACKUP_TEST_COVERAGE"):
            pytest_cmd.extend(
                [
                    "--cov=backup",
                    "--cov-report=term-missing",
                    "--cov-report=xml:"
                    + str(self.output_dir / f"{suite_name}_coverage.xml"),
                ]
            )

        # Run pytest
        try:
            result = subprocess.run(
                pytest_cmd,
                cwd=self.test_root.parent,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
            )

            # Parse pytest output
            test_counts = self._parse_pytest_output(result.stdout, result.stderr)

            return {
                "tests_run": test_counts["run"],
                "tests_passed": test_counts["passed"],
                "tests_failed": test_counts["failed"],
                "tests_skipped": test_counts["skipped"],
                "output_file": str(output_file),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 1,
                "tests_skipped": 0,
                "error_details": ["Test suite timed out after 5 minutes"],
            }

    def _run_shell_test(self, suite_name: str, suite_info: Dict, verbose: bool) -> Dict:
        """Run shell script-based tests"""
        script_path = self.test_root / suite_info["module"]
        output_file = self.output_dir / f"{suite_name}_output.log"

        try:
            # Make script executable
            script_path.chmod(0o755)

            # Run shell script
            result = subprocess.run(
                [str(script_path)],
                cwd=script_path.parent,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes timeout for integration tests
                env={**os.environ, "TEST_OUTPUT_DIR": str(self.output_dir)},
            )

            # Save output
            with open(output_file, "w") as f:
                f.write(f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n")

            # Parse shell script results (look for specific patterns)
            test_counts = self._parse_shell_output(result.stdout, result.stderr)

            return {
                "tests_run": test_counts["run"],
                "tests_passed": test_counts["passed"],
                "tests_failed": test_counts["failed"],
                "tests_skipped": test_counts["skipped"],
                "output_file": str(output_file),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 1,
                "tests_skipped": 0,
                "error_details": ["Integration test timed out after 10 minutes"],
            }

    def _parse_pytest_output(self, stdout: str, stderr: str) -> Dict[str, int]:
        """Parse pytest output to extract test counts"""
        counts = {"run": 0, "passed": 0, "failed": 0, "skipped": 0}

        # Look for pytest summary line
        for line in stdout.split("\n"):
            if "failed" in line and "passed" in line:
                # Example: "2 failed, 8 passed, 1 skipped in 5.23s"
                parts = line.split()
                for i, part in enumerate(parts):
                    if part.isdigit() and i + 1 < len(parts):
                        count = int(part)
                        next_word = parts[i + 1]

                        if next_word.startswith("failed"):
                            counts["failed"] = count
                        elif next_word.startswith("passed"):
                            counts["passed"] = count
                        elif next_word.startswith("skipped"):
                            counts["skipped"] = count
                break

        counts["run"] = counts["passed"] + counts["failed"] + counts["skipped"]
        return counts

    def _parse_shell_output(self, stdout: str, stderr: str) -> Dict[str, int]:
        """Parse shell script output to extract test counts"""
        counts = {"run": 0, "passed": 0, "failed": 0, "skipped": 0}

        # Look for test result patterns
        passed_count = stdout.count("SUCCESS")
        failed_count = stdout.count("ERROR") + stderr.count("ERROR")

        # Look for specific result files mentioned in integration script
        if "backup_script_results.txt" in stdout:
            counts["run"] += 3  # postgres, br_kg, redis
        if "verification_results.txt" in stdout:
            counts["run"] += 3  # verification tests
        if "recovery_results.txt" in stdout:
            counts["run"] += 3  # recovery tests

        # Estimate passed/failed based on SUCCESS/ERROR counts
        if counts["run"] > 0:
            if failed_count == 0:
                counts["passed"] = counts["run"]
            else:
                counts["failed"] = min(failed_count, counts["run"])
                counts["passed"] = counts["run"] - counts["failed"]
        else:
            # Fallback: count based on output patterns
            counts["run"] = max(passed_count + failed_count, 1)
            counts["passed"] = passed_count
            counts["failed"] = failed_count

        return counts

    def _generate_summary(self):
        """Generate test summary statistics"""
        total_run = sum(
            suite["tests_run"] for suite in self.test_results["test_suites"].values()
        )
        total_passed = sum(
            suite["tests_passed"] for suite in self.test_results["test_suites"].values()
        )
        total_failed = sum(
            suite["tests_failed"] for suite in self.test_results["test_suites"].values()
        )
        total_skipped = sum(
            suite["tests_skipped"]
            for suite in self.test_results["test_suites"].values()
        )
        total_duration = sum(
            suite["duration_seconds"]
            for suite in self.test_results["test_suites"].values()
        )

        success_rate = (total_passed / total_run * 100) if total_run > 0 else 0

        suite_statuses = [
            suite["status"] for suite in self.test_results["test_suites"].values()
        ]
        overall_status = (
            "passed"
            if all(s == "completed" for s in suite_statuses) and total_failed == 0
            else "failed"
        )

        self.test_results["summary"] = {
            "total_suites": len(self.test_results["test_suites"]),
            "total_tests_run": total_run,
            "total_tests_passed": total_passed,
            "total_tests_failed": total_failed,
            "total_tests_skipped": total_skipped,
            "success_rate_percent": round(success_rate, 1),
            "total_duration_seconds": round(total_duration, 2),
            "overall_status": overall_status,
        }

        self.test_results["end_time"] = datetime.now().isoformat()

    def _save_results(self):
        """Save test results to JSON file"""
        results_file = self.output_dir / "backup_test_results.json"

        with open(results_file, "w") as f:
            json.dump(self.test_results, f, indent=2, default=str)

        print(f"\n💾 Test results saved to: {results_file}")

    def _print_suite_results(self, suite_name: str, result: Dict):
        """Print results for a single test suite"""
        status_icon = (
            "✅"
            if result["status"] == "completed" and result["tests_failed"] == 0
            else "❌"
        )

        print(f"{status_icon} {result['name']}")
        print(
            f"   Tests: {result['tests_run']} run, {result['tests_passed']} passed, {result['tests_failed']} failed"
        )
        print(f"   Duration: {result['duration_seconds']:.2f} seconds")

        if result["error_details"]:
            print(f"   ⚠️  Errors: {', '.join(result['error_details'])}")

    def _print_final_summary(self):
        """Print final test summary"""
        summary = self.test_results["summary"]

        print(f"📈 Overall Results:")
        print(f"   Total Test Suites: {summary['total_suites']}")
        print(f"   Total Tests: {summary['total_tests_run']}")
        print(
            f"   Passed: {summary['total_tests_passed']} ({summary['success_rate_percent']}%)"
        )
        print(f"   Failed: {summary['total_tests_failed']}")
        print(f"   Skipped: {summary['total_tests_skipped']}")
        print(f"   Duration: {summary['total_duration_seconds']:.2f} seconds")

        status_icon = "✅" if summary["overall_status"] == "passed" else "❌"
        print(f"\n{status_icon} Overall Status: {summary['overall_status'].upper()}")

        if summary["total_tests_failed"] > 0:
            print("\n⚠️  Some tests failed. Check individual test outputs for details.")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Run comprehensive backup system tests"
    )
    parser.add_argument(
        "--test-types",
        nargs="*",
        choices=[
            "validation",
            "recovery",
            "performance",
            "failure_scenarios",
            "monitoring",
            "integration",
        ],
        help="Specific test types to run (default: all)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--output-dir", "-o", type=Path, help="Output directory for test results"
    )
    parser.add_argument(
        "--coverage", action="store_true", help="Generate test coverage reports"
    )

    args = parser.parse_args()

    # Setup paths
    test_root = Path(__file__).parent
    output_dir = args.output_dir or (test_root / "test_results")

    # Set coverage environment variable
    if args.coverage:
        os.environ["BACKUP_TEST_COVERAGE"] = "1"

    # Create test runner and run tests
    runner = BackupTestRunner(test_root, output_dir)
    results = runner.run_all_tests(args.test_types, args.verbose)

    # Exit with appropriate code
    exit_code = 0 if results["summary"]["overall_status"] == "passed" else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
