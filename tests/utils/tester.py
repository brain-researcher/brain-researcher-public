"""
Tester role - Responsible for executing tests and collecting results.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import coverage
import pytest
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_id: str
    status: str  # passed, failed, skipped, error
    duration: float
    output: str = ""
    error: str | None = None
    traceback: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSuite:
    """Collection of test results."""

    name: str
    start_time: datetime
    end_time: datetime | None = None
    results: list[TestResult] = field(default_factory=list)
    coverage_data: dict[str, Any] | None = None

    @property
    def duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == "error")


class Tester:
    """
    Tester - Executes tests and collects results.

    Responsibilities:
    - Run unit tests
    - Run integration tests
    - Execute performance tests
    - Collect coverage data
    - Generate test reports
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.console = Console()
        self.test_dir = self.project_root / "tests"
        self.coverage_dir = self.project_root / "htmlcov"

    def run_unit_tests(
        self, pattern: str = "test_*.py", coverage_enabled: bool = True
    ) -> TestSuite:
        """Run unit tests with optional coverage."""
        self.console.print("[bold blue]Running unit tests...[/bold blue]")

        suite = TestSuite(name="Unit Tests", start_time=datetime.now())

        # Setup coverage if enabled
        cov = None
        if coverage_enabled:
            cov = coverage.Coverage(
                source=[str(self.project_root / "src/brain_researcher")],
                omit=["*/tests/*", "*/testing/*", "*/__pycache__/*"],
            )
            cov.start()

        try:
            # Run pytest programmatically
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
            ) as progress:
                task = progress.add_task("Running tests...", total=None)

                # Capture pytest output
                result = pytest.main(
                    [
                        str(self.test_dir / "unit"),
                        "-v",
                        "--tb=short",
                        "--json-report",
                        "--json-report-file=test_report.json",
                    ]
                )

                progress.update(task, completed=True)

            # Parse results
            if Path("test_report.json").exists():
                with open("test_report.json") as f:
                    report = json.load(f)

                for test in report.get("tests", []):
                    test_result = TestResult(
                        test_id=test["nodeid"],
                        status=test["outcome"],
                        duration=test.get("duration", 0.0),
                        output=test.get("call", {}).get("stdout", ""),
                        error=test.get("call", {}).get("longrepr", None),
                    )
                    suite.results.append(test_result)

                Path("test_report.json").unlink()

        finally:
            if cov:
                cov.stop()
                cov.save()

                # Generate coverage report
                coverage_data = {"percent": cov.report(), "files": {}}

                for filename in cov.get_data().measured_files():
                    analysis = cov.analysis2(filename)
                    coverage_data["files"][filename] = {
                        "statements": len(analysis[1]),
                        "missing": len(analysis[3]),
                        "coverage": 100 * (1 - len(analysis[3]) / len(analysis[1]))
                        if analysis[1]
                        else 100,
                    }

                suite.coverage_data = coverage_data

                # Generate HTML report
                cov.html_report(directory=str(self.coverage_dir))

        suite.end_time = datetime.now()
        return suite

    def run_integration_tests(self) -> TestSuite:
        """Run integration tests."""
        self.console.print("[bold blue]Running integration tests...[/bold blue]")

        suite = TestSuite(name="Integration Tests", start_time=datetime.now())

        # Run integration tests
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(self.test_dir / "integration"),
                "-v",
                "--tb=short",
            ],
            capture_output=True,
            text=True,
        )

        # Parse output (simplified)
        if result.returncode == 0:
            suite.results.append(
                TestResult(
                    test_id="integration_tests",
                    status="passed",
                    duration=0.0,
                    output=result.stdout,
                )
            )
        else:
            suite.results.append(
                TestResult(
                    test_id="integration_tests",
                    status="failed",
                    duration=0.0,
                    output=result.stdout,
                    error=result.stderr,
                )
            )

        suite.end_time = datetime.now()
        return suite

    def run_performance_tests(self) -> TestSuite:
        """Run performance/benchmark tests."""
        self.console.print("[bold blue]Running performance tests...[/bold blue]")

        suite = TestSuite(name="Performance Tests", start_time=datetime.now())

        # Run performance benchmarks
        perf_script = self.test_dir / "performance" / "run_benchmarks.py"
        if perf_script.exists():
            result = subprocess.run(
                [sys.executable, str(perf_script)], capture_output=True, text=True
            )

            suite.results.append(
                TestResult(
                    test_id="performance_benchmarks",
                    status="passed" if result.returncode == 0 else "failed",
                    duration=0.0,
                    output=result.stdout,
                    error=result.stderr if result.returncode != 0 else None,
                )
            )
        else:
            suite.results.append(
                TestResult(
                    test_id="performance_benchmarks",
                    status="skipped",
                    duration=0.0,
                    output="No performance tests found",
                )
            )

        suite.end_time = datetime.now()
        return suite

    def run_cli_tests(self) -> TestSuite:
        """Run CLI command tests."""
        self.console.print("[bold blue]Running CLI tests...[/bold blue]")

        suite = TestSuite(name="CLI Tests", start_time=datetime.now())

        # Test various CLI commands
        cli_commands = [
            ["brain-researcher", "--version"],
            ["brain-researcher", "--help"],
            ["brain-researcher", "db", "--help"],
            ["brain-researcher", "query", "--help"],
        ]

        for cmd in cli_commands:
            start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True)
            duration = time.time() - start

            suite.results.append(
                TestResult(
                    test_id=" ".join(cmd),
                    status="passed" if result.returncode == 0 else "failed",
                    duration=duration,
                    output=result.stdout,
                    error=result.stderr if result.returncode != 0 else None,
                )
            )

        suite.end_time = datetime.now()
        return suite

    def generate_report(self, suites: list[TestSuite]) -> dict[str, Any]:
        """Generate comprehensive test report."""
        total_tests = sum(len(suite.results) for suite in suites)
        total_passed = sum(suite.passed for suite in suites)
        total_failed = sum(suite.failed for suite in suites)
        total_skipped = sum(suite.skipped for suite in suites)
        total_errors = sum(suite.errors for suite in suites)

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total_tests,
                "passed": total_passed,
                "failed": total_failed,
                "skipped": total_skipped,
                "errors": total_errors,
                "success_rate": (total_passed / total_tests * 100)
                if total_tests > 0
                else 0,
            },
            "suites": [],
        }

        # Display summary table
        table = Table(title="Test Results Summary")
        table.add_column("Test Suite", style="cyan")
        table.add_column("Total", justify="right")
        table.add_column("Passed", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Skipped", justify="right", style="yellow")
        table.add_column("Duration", justify="right")

        for suite in suites:
            table.add_row(
                suite.name,
                str(len(suite.results)),
                str(suite.passed),
                str(suite.failed),
                str(suite.skipped),
                f"{suite.duration:.2f}s",
            )

            suite_data = {
                "name": suite.name,
                "duration": suite.duration,
                "results": [
                    {
                        "test_id": r.test_id,
                        "status": r.status,
                        "duration": r.duration,
                        "error": r.error,
                    }
                    for r in suite.results
                ],
            }

            if suite.coverage_data:
                suite_data["coverage"] = suite.coverage_data

            report["suites"].append(suite_data)

        table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{total_tests}[/bold]",
            f"[bold green]{total_passed}[/bold green]",
            f"[bold red]{total_failed}[/bold red]",
            f"[bold yellow]{total_skipped}[/bold yellow]",
            f"[bold]{sum(s.duration for s in suites):.2f}s[/bold]",
        )

        self.console.print(table)

        # Save report
        report_path = self.project_root / "test_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        self.console.print(f"\n[green]Report saved to:[/green] {report_path}")

        return report
