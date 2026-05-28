"""
Supervisor role - Orchestrates testing and analysis, generates reports.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .static_analyst import StaticAnalyst
from .tester import Tester


@dataclass
class QualityGate:
    """Quality gate criteria."""

    name: str
    passed: bool
    reason: str
    metric: float | None = None
    threshold: float | None = None


class Supervisor:
    """
    Supervisor - Orchestrates the entire testing and analysis process.

    Responsibilities:
    - Coordinate Tester and StaticAnalyst
    - Apply quality gates
    - Generate comprehensive reports
    - Make deployment decisions
    - Track quality metrics over time
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.console = Console()
        self.tester = Tester(project_root)
        self.analyst = StaticAnalyst(project_root)
        self.reports_dir = self.project_root / "quality_reports"
        self.reports_dir.mkdir(exist_ok=True)

        # Load configuration
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load supervisor configuration."""
        config_path = self.project_root / ".quality.yml"

        default_config = {
            "quality_gates": {
                "test_coverage": 80.0,
                "test_pass_rate": 95.0,
                "max_complexity": 15,
                "max_errors": 0,
                "max_security_issues": 0,
            },
            "enabled_tools": [
                "unit_tests",
                "integration_tests",
                "ruff",
                "mypy",
                "security",
                "complexity",
                "formatting",
            ],
        }

        if config_path.exists():
            with open(config_path) as f:
                user_config = yaml.safe_load(f)
                default_config.update(user_config)

        return default_config

    def run_full_assessment(self) -> dict[str, Any]:
        """Run complete quality assessment."""
        self.console.print(
            Panel.fit(
                "[bold cyan]Starting Quality Assessment[/bold cyan]\n"
                f"Project: {self.project_root.name}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                title="Supervisor",
                border_style="cyan",
            )
        )

        assessment = {
            "timestamp": datetime.now().isoformat(),
            "project": str(self.project_root),
            "test_results": {},
            "analysis_results": {},
            "quality_gates": [],
            "recommendation": None,
        }

        # Run tests
        if "unit_tests" in self.config["enabled_tools"]:
            self.console.print("\n[bold]═══ Testing Phase ═══[/bold]\n")
            test_suites = []

            # Unit tests
            unit_suite = self.tester.run_unit_tests(coverage_enabled=True)
            test_suites.append(unit_suite)

            # Integration tests
            if "integration_tests" in self.config["enabled_tools"]:
                integration_suite = self.tester.run_integration_tests()
                test_suites.append(integration_suite)

            # CLI tests
            cli_suite = self.tester.run_cli_tests()
            test_suites.append(cli_suite)

            # Generate test report
            test_report = self.tester.generate_report(test_suites)
            assessment["test_results"] = test_report

        # Run static analysis
        self.console.print("\n[bold]═══ Analysis Phase ═══[/bold]\n")
        analysis_results = []

        if "ruff" in self.config["enabled_tools"]:
            analysis_results.append(self.analyst.run_ruff())

        if "mypy" in self.config["enabled_tools"]:
            analysis_results.append(self.analyst.run_mypy())

        if "security" in self.config["enabled_tools"]:
            analysis_results.append(self.analyst.run_security_scan())

        if "complexity" in self.config["enabled_tools"]:
            analysis_results.append(self.analyst.analyze_complexity())

        if "formatting" in self.config["enabled_tools"]:
            analysis_results.append(self.analyst.check_formatting())

        # Generate analysis report
        analysis_report = self.analyst.generate_report(analysis_results)
        assessment["analysis_results"] = analysis_report

        # Apply quality gates
        self.console.print("\n[bold]═══ Quality Gates ═══[/bold]\n")
        quality_gates = self._apply_quality_gates(assessment)
        assessment["quality_gates"] = [
            {
                "name": gate.name,
                "passed": gate.passed,
                "reason": gate.reason,
                "metric": gate.metric,
                "threshold": gate.threshold,
            }
            for gate in quality_gates
        ]

        # Make recommendation
        assessment["recommendation"] = self._make_recommendation(quality_gates)

        # Generate final report
        self._generate_final_report(assessment, quality_gates)

        return assessment

    def _apply_quality_gates(self, assessment: dict[str, Any]) -> list[QualityGate]:
        """Apply quality gates to assessment results."""
        gates = []
        thresholds = self.config["quality_gates"]

        # Test coverage gate
        if assessment.get("test_results"):
            coverage_data = None
            for suite in assessment["test_results"].get("suites", []):
                if suite.get("coverage"):
                    coverage_data = suite["coverage"]
                    break

            if coverage_data:
                coverage_percent = coverage_data.get("percent", 0)
                gates.append(
                    QualityGate(
                        name="Test Coverage",
                        passed=coverage_percent >= thresholds["test_coverage"],
                        reason=f"Coverage is {coverage_percent:.1f}%",
                        metric=coverage_percent,
                        threshold=thresholds["test_coverage"],
                    )
                )

        # Test pass rate gate
        if assessment.get("test_results"):
            summary = assessment["test_results"]["summary"]
            total_tests = summary["total"]
            passed_tests = summary["passed"]

            if total_tests > 0:
                pass_rate = (passed_tests / total_tests) * 100
                gates.append(
                    QualityGate(
                        name="Test Pass Rate",
                        passed=pass_rate >= thresholds["test_pass_rate"],
                        reason=f"{passed_tests}/{total_tests} tests passed ({pass_rate:.1f}%)",
                        metric=pass_rate,
                        threshold=thresholds["test_pass_rate"],
                    )
                )

        # Code quality gates
        if assessment.get("analysis_results"):
            summary = assessment["analysis_results"]["summary"]

            # Error count gate
            gates.append(
                QualityGate(
                    name="Error Count",
                    passed=summary["errors"] <= thresholds["max_errors"],
                    reason=f"{summary['errors']} errors found",
                    metric=float(summary["errors"]),
                    threshold=float(thresholds["max_errors"]),
                )
            )

            # Security gate
            security_issues = 0
            for result in assessment["analysis_results"]["results"]:
                if result["tool"] == "bandit":
                    security_issues = result["errors"]
                    break

            gates.append(
                QualityGate(
                    name="Security Issues",
                    passed=security_issues <= thresholds["max_security_issues"],
                    reason=f"{security_issues} security issues found",
                    metric=float(security_issues),
                    threshold=float(thresholds["max_security_issues"]),
                )
            )

            # Complexity gate
            max_complexity = 0
            for result in assessment["analysis_results"]["results"]:
                if result["tool"] == "complexity":
                    metrics = result.get("metrics", {})
                    if metrics.get("high_complexity_functions", 0) > 0:
                        max_complexity = thresholds["max_complexity"] + 1  # Fail
                    break

            gates.append(
                QualityGate(
                    name="Code Complexity",
                    passed=max_complexity <= thresholds["max_complexity"],
                    reason="All functions within complexity threshold"
                    if max_complexity <= thresholds["max_complexity"]
                    else "High complexity functions detected",
                    metric=float(max_complexity),
                    threshold=float(thresholds["max_complexity"]),
                )
            )

        return gates

    def _make_recommendation(self, gates: list[QualityGate]) -> dict[str, Any]:
        """Make deployment recommendation based on quality gates."""
        all_passed = all(gate.passed for gate in gates)
        critical_gates = ["Error Count", "Security Issues"]
        critical_passed = all(
            gate.passed for gate in gates if gate.name in critical_gates
        )

        if all_passed:
            return {
                "decision": "APPROVE",
                "message": "All quality gates passed. Safe to deploy.",
                "risk_level": "LOW",
            }
        elif critical_passed:
            return {
                "decision": "CONDITIONAL",
                "message": "Critical gates passed but some quality issues exist. Review before deploying.",
                "risk_level": "MEDIUM",
            }
        else:
            return {
                "decision": "REJECT",
                "message": "Critical quality gates failed. Do not deploy.",
                "risk_level": "HIGH",
            }

    def _generate_final_report(
        self, assessment: dict[str, Any], gates: list[QualityGate]
    ) -> None:
        """Generate comprehensive final report."""
        # Display quality gates
        table = Table(title="Quality Gates")
        table.add_column("Gate", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Metric", justify="right")
        table.add_column("Threshold", justify="right")
        table.add_column("Details")

        for gate in gates:
            status = "[green]✓ PASS[/green]" if gate.passed else "[red]✗ FAIL[/red]"
            metric = f"{gate.metric:.1f}" if gate.metric is not None else "N/A"
            threshold = f"{gate.threshold:.1f}" if gate.threshold is not None else "N/A"

            table.add_row(gate.name, status, metric, threshold, gate.reason)

        self.console.print(table)

        # Display recommendation
        rec = assessment["recommendation"]
        color = {"APPROVE": "green", "CONDITIONAL": "yellow", "REJECT": "red"}[
            rec["decision"]
        ]

        self.console.print(
            Panel(
                f"[bold {color}]Decision: {rec['decision']}[/bold {color}]\n\n"
                f"{rec['message']}\n\n"
                f"Risk Level: {rec['risk_level']}",
                title="Deployment Recommendation",
                border_style=color,
            )
        )

        # Save detailed report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.reports_dir / f"quality_report_{timestamp}.json"

        with open(report_path, "w") as f:
            json.dump(assessment, f, indent=2)

        self.console.print(f"\n[green]Full report saved to:[/green] {report_path}")

        # Generate HTML report
        self._generate_html_report(assessment, gates, timestamp)

    def _generate_html_report(
        self, assessment: dict[str, Any], gates: list[QualityGate], timestamp: str
    ) -> None:
        """Generate HTML report for web viewing."""
        html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Quality Report - {timestamp}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .section {{ margin: 20px 0; }}
        .pass {{ color: green; font-weight: bold; }}
        .fail {{ color: red; font-weight: bold; }}
        .conditional {{ color: orange; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .recommendation {{
            padding: 20px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .recommendation.approve {{ background: #d4edda; border: 1px solid #c3e6cb; }}
        .recommendation.reject {{ background: #f8d7da; border: 1px solid #f5c6cb; }}
        .recommendation.conditional {{ background: #fff3cd; border: 1px solid #ffeeba; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Quality Assessment Report</h1>
        <p>Project: {project}</p>
        <p>Generated: {timestamp}</p>
    </div>

    <div class="section">
        <h2>Quality Gates</h2>
        <table>
            <tr>
                <th>Gate</th>
                <th>Status</th>
                <th>Metric</th>
                <th>Threshold</th>
                <th>Details</th>
            </tr>
            {gates_rows}
        </table>
    </div>

    <div class="section recommendation {rec_class}">
        <h2>Deployment Recommendation</h2>
        <p class="{rec_class}">Decision: {decision}</p>
        <p>{message}</p>
        <p>Risk Level: {risk_level}</p>
    </div>

    <div class="section">
        <h2>Test Summary</h2>
        <p>Total Tests: {total_tests}</p>
        <p>Passed: {passed_tests}</p>
        <p>Failed: {failed_tests}</p>
        <p>Success Rate: {test_success_rate:.1f}%</p>
    </div>

    <div class="section">
        <h2>Code Quality Summary</h2>
        <p>Total Issues: {total_issues}</p>
        <p>Errors: {errors}</p>
        <p>Warnings: {warnings}</p>
    </div>
</body>
</html>
"""

        # Build gates rows
        gates_rows = ""
        for gate in gates:
            status_class = "pass" if gate.passed else "fail"
            status_text = "PASS" if gate.passed else "FAIL"
            metric = f"{gate.metric:.1f}" if gate.metric is not None else "N/A"
            threshold = f"{gate.threshold:.1f}" if gate.threshold is not None else "N/A"

            gates_rows += f"""
            <tr>
                <td>{gate.name}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{metric}</td>
                <td>{threshold}</td>
                <td>{gate.reason}</td>
            </tr>
            """

        # Fill template
        rec = assessment["recommendation"]
        rec_class = rec["decision"].lower()

        test_summary = assessment.get("test_results", {}).get("summary", {})
        analysis_summary = assessment.get("analysis_results", {}).get("summary", {})

        html_content = html_template.format(
            timestamp=timestamp,
            project=assessment["project"],
            gates_rows=gates_rows,
            rec_class=rec_class,
            decision=rec["decision"],
            message=rec["message"],
            risk_level=rec["risk_level"],
            total_tests=test_summary.get("total", 0),
            passed_tests=test_summary.get("passed", 0),
            failed_tests=test_summary.get("failed", 0),
            test_success_rate=test_summary.get("success_rate", 0),
            total_issues=analysis_summary.get("total_issues", 0),
            errors=analysis_summary.get("errors", 0),
            warnings=analysis_summary.get("warnings", 0),
        )

        # Save HTML report
        html_path = self.reports_dir / f"quality_report_{timestamp}.html"
        with open(html_path, "w") as f:
            f.write(html_content)

        self.console.print(f"[green]HTML report saved to:[/green] {html_path}")

    def compare_with_baseline(self, current: dict[str, Any]) -> dict[str, Any]:
        """Compare current results with baseline."""
        baseline_path = self.reports_dir / "baseline.json"

        if not baseline_path.exists():
            # Save current as baseline
            with open(baseline_path, "w") as f:
                json.dump(current, f, indent=2)
            return {"status": "baseline_created"}

        # Load baseline
        with open(baseline_path) as f:
            baseline = json.load(f)

        # Compare metrics
        comparison = {
            "test_coverage_change": 0,
            "test_success_rate_change": 0,
            "issues_change": 0,
            "improved": [],
            "degraded": [],
        }

        # Compare test metrics
        if current.get("test_results") and baseline.get("test_results"):
            current_coverage = 0
            baseline_coverage = 0

            for suite in current["test_results"].get("suites", []):
                if suite.get("coverage"):
                    current_coverage = suite["coverage"].get("percent", 0)
                    break

            for suite in baseline["test_results"].get("suites", []):
                if suite.get("coverage"):
                    baseline_coverage = suite["coverage"].get("percent", 0)
                    break

            comparison["test_coverage_change"] = current_coverage - baseline_coverage

            if comparison["test_coverage_change"] > 0:
                comparison["improved"].append(
                    f"Test coverage improved by {comparison['test_coverage_change']:.1f}%"
                )
            elif comparison["test_coverage_change"] < 0:
                comparison["degraded"].append(
                    f"Test coverage decreased by {abs(comparison['test_coverage_change']):.1f}%"
                )

        # Compare code quality
        if current.get("analysis_results") and baseline.get("analysis_results"):
            current_issues = current["analysis_results"]["summary"]["total_issues"]
            baseline_issues = baseline["analysis_results"]["summary"]["total_issues"]

            comparison["issues_change"] = current_issues - baseline_issues

            if comparison["issues_change"] < 0:
                comparison["improved"].append(
                    f"Reduced {abs(comparison['issues_change'])} code issues"
                )
            elif comparison["issues_change"] > 0:
                comparison["degraded"].append(
                    f"Added {comparison['issues_change']} new code issues"
                )

        return comparison
