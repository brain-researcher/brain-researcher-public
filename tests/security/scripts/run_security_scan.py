#!/usr/bin/env python3
"""
Comprehensive security testing script for Brain Researcher platform.

Runs all security tests including:
- SAST (Static Application Security Testing)
- DAST (Dynamic Application Security Testing)
- Authentication tests
- API security tests
- JWT security tests
- Dependency vulnerability scanning
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class SecurityScanner:
    """Main security testing orchestrator."""

    def __init__(self, project_root: str, output_dir: str = "security_reports"):
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self.output_dir / "security_scan.log"),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Results storage
        self.results = {
            "scan_start": datetime.now().isoformat(),
            "sast_results": {},
            "dast_results": {},
            "dependency_results": {},
            "auth_test_results": {},
            "api_test_results": {},
            "jwt_test_results": {},
            "summary": {},
        }

    def run_sast_scan(self) -> dict[str, Any]:
        """Run Static Application Security Testing."""
        self.logger.info("Starting SAST scan...")
        sast_results = {}

        # Run Bandit scan
        sast_results["bandit"] = self.run_bandit_scan()

        # Run Semgrep scan
        sast_results["semgrep"] = self.run_semgrep_scan()

        # Run custom security checks
        sast_results["custom_checks"] = self.run_custom_security_checks()

        self.results["sast_results"] = sast_results
        return sast_results

    def run_bandit_scan(self) -> dict[str, Any]:
        """Run Bandit security scanner."""
        self.logger.info("Running Bandit scan...")

        try:
            # Install bandit if not available
            subprocess.run(
                ["pip", "install", "bandit[toml]"], check=False, capture_output=True
            )

            bandit_config = self.project_root / "tests/security/sast/bandit.yaml"
            output_file = self.output_dir / "bandit_report.json"

            cmd = [
                "bandit",
                "-r",
                str(self.project_root / "brain_researcher"),
                "-f",
                "json",
                "-o",
                str(output_file),
                "--config",
                str(bandit_config) if bandit_config.exists() else "",
                "--skip",
                "B101,B601",  # Skip assert_used and shell=True for scientific tools
                "--exclude",
                "tests,external,node_modules,__pycache__",
            ]

            # Remove empty config parameter
            cmd = [arg for arg in cmd if arg]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if output_file.exists():
                with open(output_file) as f:
                    bandit_data = json.load(f)

                return {
                    "status": "completed",
                    "high_severity_count": len(
                        [
                            issue
                            for issue in bandit_data.get("results", [])
                            if issue.get("issue_severity") == "HIGH"
                        ]
                    ),
                    "medium_severity_count": len(
                        [
                            issue
                            for issue in bandit_data.get("results", [])
                            if issue.get("issue_severity") == "MEDIUM"
                        ]
                    ),
                    "total_issues": len(bandit_data.get("results", [])),
                    "report_file": str(output_file),
                }
            else:
                return {
                    "status": "failed",
                    "error": result.stderr,
                    "stdout": result.stdout,
                }

        except Exception as e:
            self.logger.error(f"Bandit scan failed: {e}")
            return {"status": "error", "error": str(e)}

    def run_semgrep_scan(self) -> dict[str, Any]:
        """Run Semgrep security scanner."""
        self.logger.info("Running Semgrep scan...")

        try:
            # Install semgrep if not available
            subprocess.run(
                ["pip", "install", "semgrep"], check=False, capture_output=True
            )

            semgrep_config = self.project_root / "tests/security/sast/semgrep.yml"
            output_file = self.output_dir / "semgrep_report.json"

            cmd = [
                "semgrep",
                "--config",
                str(semgrep_config) if semgrep_config.exists() else "auto",
                "--json",
                "--output",
                str(output_file),
                str(self.project_root / "brain_researcher"),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if output_file.exists():
                with open(output_file) as f:
                    semgrep_data = json.load(f)

                results = semgrep_data.get("results", [])

                return {
                    "status": "completed",
                    "error_count": len(
                        [
                            r
                            for r in results
                            if r.get("extra", {}).get("severity") == "ERROR"
                        ]
                    ),
                    "warning_count": len(
                        [
                            r
                            for r in results
                            if r.get("extra", {}).get("severity") == "WARNING"
                        ]
                    ),
                    "total_findings": len(results),
                    "report_file": str(output_file),
                }
            else:
                return {
                    "status": "failed",
                    "error": result.stderr,
                    "stdout": result.stdout,
                }

        except Exception as e:
            self.logger.error(f"Semgrep scan failed: {e}")
            return {"status": "error", "error": str(e)}

    def run_dependency_scan(self) -> dict[str, Any]:
        """Run dependency vulnerability scanning."""
        self.logger.info("Running dependency vulnerability scan...")

        try:
            # Install safety if not available
            subprocess.run(
                ["pip", "install", "safety"], check=False, capture_output=True
            )

            output_file = self.output_dir / "safety_report.json"

            cmd = ["safety", "check", "--json", "--output", str(output_file)]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if output_file.exists():
                with open(output_file) as f:
                    safety_data = json.load(f)

                vulnerabilities = safety_data if isinstance(safety_data, list) else []

                return {
                    "status": "completed",
                    "vulnerability_count": len(vulnerabilities),
                    "high_severity_count": len(
                        [v for v in vulnerabilities if "high" in str(v).lower()]
                    ),
                    "report_file": str(output_file),
                    "vulnerabilities": vulnerabilities[:10],  # First 10 for summary
                }
            else:
                # Safety might exit with non-zero on vulnerabilities
                if (
                    result.returncode != 0
                    and "No known security vulnerabilities found" in result.stdout
                ):
                    return {
                        "status": "completed",
                        "vulnerability_count": 0,
                        "message": "No vulnerabilities found",
                    }
                else:
                    return {
                        "status": "warning",
                        "message": result.stdout,
                        "error": result.stderr,
                    }

        except Exception as e:
            self.logger.error(f"Dependency scan failed: {e}")
            return {"status": "error", "error": str(e)}

    def run_custom_security_checks(self) -> dict[str, Any]:
        """Run custom neuroimaging-specific security checks."""
        self.logger.info("Running custom security checks...")

        issues = []

        # Check for hardcoded secrets
        secret_patterns = [
            ("API Key", r'api[_-]?key["\s]*[:=]["\s]*[a-zA-Z0-9]{20,}'),
            ("Password", r'password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']'),
            ("Secret Key", r'secret[_-]?key["\s]*[:=]["\s]*["\'][^"\']{16,}["\']'),
            ("Database URL", r"postgresql://[^:]+:[^@]+@"),
            ("JWT Secret", r'jwt[_-]?secret["\s]*[:=]["\s]*["\'][^"\']+["\']'),
        ]

        python_files = list(self.project_root.glob("brain_researcher/**/*.py"))

        for py_file in python_files:
            try:
                with open(py_file, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for pattern_name, pattern in secret_patterns:
                    import re

                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        # Skip test files and example configs
                        if (
                            "test" in str(py_file).lower()
                            or "example" in str(py_file).lower()
                        ):
                            continue

                        issues.append(
                            {
                                "type": f"Potential {pattern_name}",
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": content[: match.start()].count("\n") + 1,
                                "severity": (
                                    "HIGH"
                                    if pattern_name in ["API Key", "Password"]
                                    else "MEDIUM"
                                ),
                            }
                        )
            except Exception:
                continue

        # Check for participant data exposure patterns
        participant_patterns = [
            r'participant[_-]?id["\s]*[:=]',
            r'subject[_-]?id["\s]*[:=]',
            r"medical[_-]?record",
            r"patient[_-]?data",
        ]

        for py_file in python_files:
            try:
                with open(py_file, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for pattern in participant_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        issues.append(
                            {
                                "type": "Potential Participant Data Handling",
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": content[: match.start()].count("\n") + 1,
                                "severity": "MEDIUM",
                                "note": "Review for proper anonymization",
                            }
                        )
            except Exception:
                continue

        return {
            "status": "completed",
            "issues_found": len(issues),
            "high_severity": len([i for i in issues if i["severity"] == "HIGH"]),
            "medium_severity": len([i for i in issues if i["severity"] == "MEDIUM"]),
            "issues": issues,
        }

    def run_pytest_security_tests(self) -> dict[str, Any]:
        """Run pytest-based security tests."""
        self.logger.info("Running pytest security tests...")

        test_categories = {
            "authentication": "tests/security/auth/test_authentication.py",
            "api_security": "tests/security/api/test_api_security.py",
            "jwt_security": "tests/security/jwt/test_jwt_security.py",
        }

        test_results = {}

        for category, test_file in test_categories.items():
            self.logger.info(f"Running {category} tests...")

            test_path = self.project_root / test_file
            if not test_path.exists():
                test_results[category] = {
                    "status": "skipped",
                    "reason": "Test file not found",
                }
                continue

            output_file = self.output_dir / f"pytest_{category}_report.json"

            cmd = [
                "python",
                "-m",
                "pytest",
                str(test_path),
                "--tb=short",
                "--json-report",
                f"--json-report-file={output_file}",
                "-v",
            ]

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=str(self.project_root)
                )

                if output_file.exists():
                    with open(output_file) as f:
                        pytest_data = json.load(f)

                    test_results[category] = {
                        "status": "completed",
                        "total_tests": pytest_data.get("summary", {}).get("total", 0),
                        "passed": pytest_data.get("summary", {}).get("passed", 0),
                        "failed": pytest_data.get("summary", {}).get("failed", 0),
                        "skipped": pytest_data.get("summary", {}).get("skipped", 0),
                        "report_file": str(output_file),
                    }
                else:
                    test_results[category] = {
                        "status": "failed",
                        "error": result.stderr,
                        "stdout": result.stdout,
                    }

            except Exception as e:
                test_results[category] = {"status": "error", "error": str(e)}

        return test_results

    def run_owasp_zap_scan(self) -> dict[str, Any]:
        """Run OWASP ZAP security scan."""
        self.logger.info("Running OWASP ZAP scan...")

        try:
            # Check if ZAP is available
            zap_result = subprocess.run(["which", "zap.sh"], capture_output=True)
            if zap_result.returncode != 0:
                return {"status": "skipped", "reason": "OWASP ZAP not installed"}

            # Start ZAP in daemon mode
            zap_config = (
                self.project_root / "tests/security/owasp_zap/zap_automation.yaml"
            )
            output_dir = self.output_dir / "zap_reports"
            output_dir.mkdir(exist_ok=True)

            if zap_config.exists():
                cmd = ["zap.sh", "-cmd", "-autorun", str(zap_config)]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=1800
                )  # 30 min timeout

                return {
                    "status": "completed",
                    "exit_code": result.returncode,
                    "reports_dir": str(output_dir),
                }
            else:
                # Fallback to basic baseline scan
                cmd = [
                    "zap-baseline.py",
                    "-t",
                    "http://localhost:8080",
                    "-J",
                    str(output_dir / "zap_baseline_report.json"),
                    "-r",
                    str(output_dir / "zap_baseline_report.html"),
                ]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=900
                )  # 15 min timeout

                return {
                    "status": "completed",
                    "exit_code": result.returncode,
                    "report_file": str(output_dir / "zap_baseline_report.json"),
                }

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "ZAP scan timed out"}
        except Exception as e:
            self.logger.error(f"ZAP scan failed: {e}")
            return {"status": "error", "error": str(e)}

    def generate_summary_report(self) -> dict[str, Any]:
        """Generate comprehensive security summary report."""
        self.logger.info("Generating security summary report...")

        summary = {
            "scan_completed": datetime.now().isoformat(),
            "total_scan_duration": str(
                datetime.now() - datetime.fromisoformat(self.results["scan_start"])
            ),
            "findings_summary": {},
            "recommendations": [],
            "risk_level": "LOW",
        }

        # Aggregate findings
        total_high_issues = 0
        total_medium_issues = 0
        total_low_issues = 0

        # SAST findings
        sast = self.results.get("sast_results", {})
        if sast.get("bandit", {}).get("status") == "completed":
            total_high_issues += sast["bandit"].get("high_severity_count", 0)
            total_medium_issues += sast["bandit"].get("medium_severity_count", 0)

        if sast.get("semgrep", {}).get("status") == "completed":
            total_high_issues += sast["semgrep"].get("error_count", 0)
            total_medium_issues += sast["semgrep"].get("warning_count", 0)

        if sast.get("custom_checks", {}).get("status") == "completed":
            total_high_issues += sast["custom_checks"].get("high_severity", 0)
            total_medium_issues += sast["custom_checks"].get("medium_severity", 0)

        # Dependency findings
        deps = self.results.get("dependency_results", {})
        if deps.get("status") == "completed":
            total_high_issues += deps.get("high_severity_count", 0)
            total_medium_issues += deps.get("vulnerability_count", 0) - deps.get(
                "high_severity_count", 0
            )

        summary["findings_summary"] = {
            "high_severity": total_high_issues,
            "medium_severity": total_medium_issues,
            "low_severity": total_low_issues,
        }

        # Determine risk level
        if total_high_issues > 0:
            summary["risk_level"] = "HIGH"
        elif total_medium_issues > 5:
            summary["risk_level"] = "MEDIUM"
        else:
            summary["risk_level"] = "LOW"

        # Generate recommendations
        recommendations = []

        if total_high_issues > 0:
            recommendations.append(
                "URGENT: Address high-severity security findings immediately"
            )

        if deps.get("vulnerability_count", 0) > 0:
            recommendations.append(
                "Update vulnerable dependencies to latest secure versions"
            )

        if sast.get("custom_checks", {}).get("issues_found", 0) > 0:
            recommendations.append(
                "Review participant data handling for proper anonymization"
            )

        recommendations.extend(
            [
                "Implement comprehensive authentication and authorization",
                "Enable HTTPS for all production services",
                "Configure proper security headers (CSP, HSTS, etc.)",
                "Implement rate limiting on all API endpoints",
                "Set up security monitoring and logging",
                "Regular security testing in CI/CD pipeline",
            ]
        )

        summary["recommendations"] = recommendations

        # Save summary report
        summary_file = self.output_dir / "security_summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        self.results["summary"] = summary
        return summary

    def run_full_scan(self) -> dict[str, Any]:
        """Run complete security assessment."""
        self.logger.info("Starting comprehensive security scan...")

        try:
            # Run all security tests
            self.results["sast_results"] = self.run_sast_scan()
            self.results["dependency_results"] = self.run_dependency_scan()

            # Run dynamic tests
            pytest_results = self.run_pytest_security_tests()
            self.results.update(pytest_results)

            # Run OWASP ZAP if available
            self.results["dast_results"] = self.run_owasp_zap_scan()

            # Generate summary
            self.results["summary"] = self.generate_summary_report()

            # Save complete results
            results_file = self.output_dir / "complete_security_results.json"
            with open(results_file, "w") as f:
                json.dump(self.results, f, indent=2, default=str)

            self.logger.info(
                f"Security scan completed. Results saved to {self.output_dir}"
            )
            return self.results

        except Exception as e:
            self.logger.error(f"Security scan failed: {e}")
            return {"status": "error", "error": str(e)}


def main():
    """Main entry point for security scanning."""
    parser = argparse.ArgumentParser(description="Brain Researcher Security Scanner")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument(
        "--output-dir", default="security_reports", help="Output directory for reports"
    )
    parser.add_argument(
        "--scan-type",
        choices=["sast", "dast", "deps", "all"],
        default="all",
        help="Type of security scan to run",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scanner = SecurityScanner(args.project_root, args.output_dir)

    if args.scan_type == "sast":
        results = scanner.run_sast_scan()
    elif args.scan_type == "dast":
        results = scanner.run_owasp_zap_scan()
    elif args.scan_type == "deps":
        results = scanner.run_dependency_scan()
    else:
        results = scanner.run_full_scan()

    # Print summary
    if "summary" in results:
        summary = results["summary"]
        print("\n=== Security Scan Summary ===")
        print(f"Risk Level: {summary.get('risk_level', 'UNKNOWN')}")
        print(
            f"High Severity Issues: {summary.get('findings_summary', {}).get('high_severity', 0)}"
        )
        print(
            f"Medium Severity Issues: {summary.get('findings_summary', {}).get('medium_severity', 0)}"
        )
        print(f"Reports saved to: {scanner.output_dir}")

        if summary.get("recommendations"):
            print("\nTop Recommendations:")
            for rec in summary["recommendations"][:3]:
                print(f"- {rec}")

    # Exit with appropriate code
    if results.get("summary", {}).get("risk_level") == "HIGH":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
