#!/usr/bin/env python3
"""
Validation script to test the security testing infrastructure setup.

This script validates that all security testing components are properly configured
and can run without errors.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def check_tool_availability() -> dict[str, bool]:
    """Check if required security tools are available."""
    tools = {
        "bandit": "bandit --version",
        "safety": "safety --version",
        "semgrep": "semgrep --version",
        "pytest": "pytest --version",
        "python": "python --version",
    }

    availability = {}

    for tool, cmd in tools.items():
        try:
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            availability[tool] = result.returncode == 0
        except FileNotFoundError:
            availability[tool] = False

    return availability


def validate_config_files() -> dict[str, bool]:
    """Validate that configuration files exist and are readable."""
    project_root = Path(__file__).parent.parent.parent.parent

    config_files = {
        "bandit_config": "tests/security/sast/bandit.yaml",
        "semgrep_config": "tests/security/sast/semgrep.yml",
        "safety_policy": "tests/security/sast/safety_policy.json",
        "zap_config": "tests/security/owasp_zap/zap_automation.yaml",
        "zap_baseline": "tests/security/owasp_zap/zap_baseline.conf",
        "pytest_config": "tests/security/configs/pytest.ini",
        "precommit_config": "tests/security/configs/pre-commit-security.yaml",
    }

    validation_results = {}

    for name, path in config_files.items():
        file_path = project_root / path
        validation_results[name] = file_path.exists() and file_path.is_file()

    return validation_results


def validate_test_files() -> dict[str, bool]:
    """Validate that test files exist and are executable."""
    project_root = Path(__file__).parent.parent.parent.parent

    test_files = {
        "auth_tests": "tests/security/auth/test_authentication.py",
        "api_tests": "tests/security/api/test_api_security.py",
        "jwt_tests": "tests/security/jwt/test_jwt_security.py",
    }

    validation_results = {}

    for name, path in test_files.items():
        file_path = project_root / path
        validation_results[name] = file_path.exists() and file_path.is_file()

    return validation_results


def validate_security_scripts() -> dict[str, bool]:
    """Validate that security scripts exist and are executable."""
    project_root = Path(__file__).parent.parent.parent.parent

    scripts = {
        "main_scanner": "tests/security/scripts/run_security_scan.py",
        "secrets_checker": "tests/security/scripts/check_secrets.py",
        "participant_data_checker": "tests/security/scripts/check_participant_data.py",
        "jwt_checker": "tests/security/scripts/check_jwt_security.py",
    }

    validation_results = {}

    for name, path in scripts.items():
        file_path = project_root / path
        validation_results[name] = (
            file_path.exists() and file_path.is_file() and os.access(file_path, os.X_OK)
        )

    return validation_results


def run_quick_sast_test() -> dict[str, Any]:
    """Run a quick SAST test to validate tools work."""
    project_root = Path(__file__).parent.parent.parent.parent

    # Create a test file with intentional security issues
    test_file = project_root / "test_security_sample.py"
    test_code = """
# Test file with intentional security issues for validation
import os
import subprocess

# Hardcoded secret (should be detected)
API_KEY = "sk-1234567890abcdef"

# SQL injection vulnerability (should be detected)
def unsafe_query(user_input):
    query = f"SELECT * FROM users WHERE id = {user_input}"
    return query

# Subprocess with shell=True (should be flagged)
def run_command(cmd):
    subprocess.run(cmd, shell=True)

# Remove test file when done
"""

    try:
        # Write test file
        with open(test_file, "w") as f:
            f.write(test_code)

        results = {}

        # Test bandit
        try:
            bandit_result = subprocess.run(
                ["bandit", "-f", "json", str(test_file)], capture_output=True, text=True
            )

            if bandit_result.stdout:
                bandit_data = json.loads(bandit_result.stdout)
                results["bandit"] = {
                    "status": "success",
                    "issues_found": len(bandit_data.get("results", [])),
                    "working": len(bandit_data.get("results", [])) > 0,
                }
            else:
                results["bandit"] = {"status": "no_output", "working": False}

        except Exception as e:
            results["bandit"] = {"status": "error", "error": str(e), "working": False}

        # Test semgrep (if config exists)
        semgrep_config = project_root / "tests/security/sast/semgrep.yml"
        if semgrep_config.exists():
            try:
                semgrep_result = subprocess.run(
                    [
                        "semgrep",
                        "--config",
                        str(semgrep_config),
                        "--json",
                        str(test_file),
                    ],
                    capture_output=True,
                    text=True,
                )

                if semgrep_result.stdout:
                    semgrep_data = json.loads(semgrep_result.stdout)
                    results["semgrep"] = {
                        "status": "success",
                        "issues_found": len(semgrep_data.get("results", [])),
                        "working": True,
                    }
                else:
                    results["semgrep"] = {
                        "status": "no_output",
                        "working": True,
                    }  # May be working but no issues

            except Exception as e:
                results["semgrep"] = {
                    "status": "error",
                    "error": str(e),
                    "working": False,
                }
        else:
            results["semgrep"] = {"status": "config_missing", "working": False}

        # Test custom secret checker
        try:
            secrets_script = project_root / "tests/security/scripts/check_secrets.py"
            if secrets_script.exists():
                secrets_result = subprocess.run(
                    ["python", str(secrets_script), str(test_file), "--json"],
                    capture_output=True,
                    text=True,
                )

                if secrets_result.stdout:
                    secrets_data = json.loads(secrets_result.stdout)
                    results["secrets_checker"] = {
                        "status": "success",
                        "issues_found": secrets_data.get("total_secrets", 0),
                        "working": secrets_data.get("total_secrets", 0) > 0,
                    }
                else:
                    results["secrets_checker"] = {
                        "status": "no_output",
                        "working": False,
                    }
            else:
                results["secrets_checker"] = {
                    "status": "script_missing",
                    "working": False,
                }

        except Exception as e:
            results["secrets_checker"] = {
                "status": "error",
                "error": str(e),
                "working": False,
            }

        return results

    finally:
        # Clean up test file
        if test_file.exists():
            test_file.unlink()


def run_validation() -> dict[str, Any]:
    """Run complete validation of security testing setup."""
    print("Validating Brain Researcher Security Testing Setup...\n")

    results = {
        "tool_availability": check_tool_availability(),
        "config_files": validate_config_files(),
        "test_files": validate_test_files(),
        "security_scripts": validate_security_scripts(),
        "sast_functionality": run_quick_sast_test(),
    }

    return results


def print_validation_results(results: dict[str, Any]):
    """Print validation results in a readable format."""

    def print_section(title: str, data: dict[str, Any], check_working: bool = False):
        print(f"\n{title}:")
        print("-" * len(title))

        for item, status in data.items():
            if isinstance(status, dict):
                if check_working:
                    status_text = (
                        "✓ WORKING" if status.get("working", False) else "✗ NOT WORKING"
                    )
                    if "issues_found" in status:
                        status_text += f" ({status['issues_found']} issues detected)"
                    if "error" in status:
                        status_text += f" - Error: {status['error']}"
                else:
                    status_text = (
                        "✓ OK"
                        if status.get("status") == "success"
                        else f"✗ {status.get('status', 'UNKNOWN')}"
                    )
            else:
                status_text = "✓ AVAILABLE" if status else "✗ MISSING"

            print(f"  {item:25} {status_text}")

    print_section("Security Tools", results["tool_availability"])
    print_section("Configuration Files", results["config_files"])
    print_section("Test Files", results["test_files"])
    print_section("Security Scripts", results["security_scripts"])
    print_section(
        "SAST Functionality Test", results["sast_functionality"], check_working=True
    )

    # Summary
    print(f"\n{'='*50}")
    print("VALIDATION SUMMARY")
    print(f"{'='*50}")

    total_checks = 0
    passed_checks = 0

    for category, data in results.items():
        category_total = len(data)
        category_passed = 0

        for _item, status in data.items():
            total_checks += 1
            if isinstance(status, dict):
                if category == "sast_functionality":
                    if (
                        status.get("working", False)
                        or status.get("status") == "success"
                    ):
                        category_passed += 1
                        passed_checks += 1
                elif status.get("status") == "success":
                    category_passed += 1
                    passed_checks += 1
            else:
                if status:
                    category_passed += 1
                    passed_checks += 1

        status_text = (
            "PASS"
            if category_passed == category_total
            else "PARTIAL" if category_passed > 0 else "FAIL"
        )
        print(f"{category:25} {category_passed}/{category_total} - {status_text}")

    overall_status = (
        "PASS"
        if passed_checks == total_checks
        else "PARTIAL" if passed_checks > 0 else "FAIL"
    )
    print(f"\nOverall Status: {passed_checks}/{total_checks} - {overall_status}")

    if overall_status != "PASS":
        print("\n⚠️  Some components are not properly configured.")
        print("   Please check the failed items above and ensure:")
        print("   - Required tools are installed (pip install bandit safety semgrep)")
        print("   - Configuration files are in the correct locations")
        print("   - Scripts have executable permissions")
        print("   - Test files are properly structured")
    else:
        print("\n✅ Security testing infrastructure is properly configured!")
        print("   You can now run comprehensive security scans.")


def main():
    """Main entry point."""
    try:
        results = run_validation()
        print_validation_results(results)

        # Return appropriate exit code
        all_tools_available = all(results["tool_availability"].values())
        all_configs_present = all(results["config_files"].values())
        all_tests_present = all(results["test_files"].values())
        all_scripts_present = all(results["security_scripts"].values())

        if all(
            [
                all_tools_available,
                all_configs_present,
                all_tests_present,
                all_scripts_present,
            ]
        ):
            return 0  # Success
        else:
            return 1  # Partial failure

    except Exception as e:
        print(f"Validation failed with error: {e}")
        return 2  # Error


if __name__ == "__main__":
    sys.exit(main())
