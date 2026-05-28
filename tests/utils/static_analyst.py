"""
StaticAnalyst role - Responsible for code quality analysis and linting.
"""

import ast
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


@dataclass
class CodeIssue:
    """Represents a code quality issue."""

    file: str
    line: int
    column: int
    code: str
    message: str
    severity: str  # error, warning, info
    tool: str


@dataclass
class AnalysisResult:
    """Result of static analysis."""

    tool: str
    start_time: datetime
    end_time: datetime | None = None
    issues: list[CodeIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    passed: bool = True

    @property
    def duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


class StaticAnalyst:
    """
    StaticAnalyst - Performs static code analysis.

    Responsibilities:
    - Run linters (ruff, mypy)
    - Check code style and formatting
    - Analyze code complexity
    - Security scanning
    - Generate quality reports
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.console = Console()
        self.source_dir = self.project_root / "src/brain_researcher"

    def run_ruff(self) -> AnalysisResult:
        """Run ruff linter."""
        self.console.print("[bold blue]Running Ruff linter...[/bold blue]")

        result = AnalysisResult(tool="ruff", start_time=datetime.now())

        # Run ruff with JSON output
        proc = subprocess.run(
            ["ruff", "check", str(self.source_dir), "--output-format=json"],
            capture_output=True,
            text=True,
        )

        if proc.stdout:
            try:
                issues = json.loads(proc.stdout)
                for issue in issues:
                    result.issues.append(
                        CodeIssue(
                            file=issue["filename"],
                            line=issue["location"]["row"],
                            column=issue["location"]["column"],
                            code=issue["code"],
                            message=issue["message"],
                            severity="error" if issue.get("fix") else "warning",
                            tool="ruff",
                        )
                    )
            except json.JSONDecodeError:
                self.console.print("[red]Failed to parse ruff output[/red]")

        result.passed = proc.returncode == 0
        result.end_time = datetime.now()

        # Collect metrics
        result.metrics = {
            "total_files": len(set(i.file for i in result.issues)),
            "total_issues": len(result.issues),
            "fixable": sum(1 for i in result.issues if i.severity == "warning"),
        }

        return result

    def run_mypy(self) -> AnalysisResult:
        """Run mypy type checker."""
        self.console.print("[bold blue]Running MyPy type checker...[/bold blue]")

        result = AnalysisResult(tool="mypy", start_time=datetime.now())

        # Run mypy
        proc = subprocess.run(
            [
                "mypy",
                str(self.source_dir),
                "--ignore-missing-imports",
                "--show-error-codes",
                "--no-error-summary",
            ],
            capture_output=True,
            text=True,
        )

        # Parse mypy output
        for line in proc.stdout.splitlines():
            match = re.match(r"(.+):(\d+):(\d+): (\w+): (.+) \[(.+)\]", line)
            if match:
                result.issues.append(
                    CodeIssue(
                        file=match.group(1),
                        line=int(match.group(2)),
                        column=int(match.group(3)),
                        code=match.group(6),
                        message=match.group(5),
                        severity=match.group(4).lower(),
                        tool="mypy",
                    )
                )

        result.passed = proc.returncode == 0
        result.end_time = datetime.now()

        # Collect metrics
        result.metrics = {
            "type_errors": result.error_count,
            "type_warnings": result.warning_count,
            "files_with_errors": len(set(i.file for i in result.issues)),
        }

        return result

    def run_security_scan(self) -> AnalysisResult:
        """Run bandit security scanner."""
        self.console.print("[bold blue]Running security scan...[/bold blue]")

        result = AnalysisResult(tool="bandit", start_time=datetime.now())

        # Run bandit
        proc = subprocess.run(
            ["bandit", "-r", str(self.source_dir), "-f", "json", "-q"],
            capture_output=True,
            text=True,
        )

        if proc.stdout:
            try:
                report = json.loads(proc.stdout)
                for issue in report.get("results", []):
                    result.issues.append(
                        CodeIssue(
                            file=issue["filename"],
                            line=issue["line_number"],
                            column=0,
                            code=issue["test_id"],
                            message=issue["issue_text"],
                            severity=issue["issue_severity"].lower(),
                            tool="bandit",
                        )
                    )

                result.metrics = report.get("metrics", {})
            except json.JSONDecodeError:
                self.console.print("[red]Failed to parse bandit output[/red]")

        result.passed = len(result.issues) == 0
        result.end_time = datetime.now()

        return result

    def analyze_complexity(self) -> AnalysisResult:
        """Analyze code complexity metrics."""
        self.console.print("[bold blue]Analyzing code complexity...[/bold blue]")

        result = AnalysisResult(tool="complexity", start_time=datetime.now())

        total_complexity = 0
        file_count = 0
        function_count = 0
        class_count = 0

        # Analyze Python files
        for py_file in self.source_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())

                file_count += 1

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        function_count += 1
                        complexity = self._calculate_complexity(node)
                        total_complexity += complexity

                        # Flag high complexity functions
                        if complexity > 10:
                            result.issues.append(
                                CodeIssue(
                                    file=str(py_file),
                                    line=node.lineno,
                                    column=node.col_offset,
                                    code="C901",
                                    message=f"Function '{node.name}' has complexity {complexity}",
                                    severity="warning" if complexity <= 15 else "error",
                                    tool="complexity",
                                )
                            )

                    elif isinstance(node, ast.ClassDef):
                        class_count += 1

            except Exception as e:
                self.console.print(f"[yellow]Failed to analyze {py_file}: {e}[/yellow]")

        result.metrics = {
            "total_files": file_count,
            "total_functions": function_count,
            "total_classes": class_count,
            "average_complexity": total_complexity / function_count
            if function_count > 0
            else 0,
            "high_complexity_functions": sum(
                1 for i in result.issues if i.code == "C901"
            ),
        }

        result.passed = result.error_count == 0
        result.end_time = datetime.now()

        return result

    def check_formatting(self) -> AnalysisResult:
        """Check code formatting."""
        self.console.print("[bold blue]Checking code formatting...[/bold blue]")

        result = AnalysisResult(tool="formatting", start_time=datetime.now())

        # Check with black
        proc = subprocess.run(
            ["black", "--check", "--diff", str(self.source_dir)],
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            # Parse diff output to find files needing formatting
            for line in proc.stdout.splitlines():
                if line.startswith("---") or line.startswith("+++"):
                    filename = line.split()[1]
                    if filename.startswith("a/") or filename.startswith("b/"):
                        filename = filename[2:]

                    result.issues.append(
                        CodeIssue(
                            file=filename,
                            line=0,
                            column=0,
                            code="BLK100",
                            message="File needs formatting",
                            severity="warning",
                            tool="black",
                        )
                    )

        result.passed = proc.returncode == 0
        result.end_time = datetime.now()

        return result

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate cyclomatic complexity of a function."""
        complexity = 1  # Base complexity

        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For)):
                complexity += 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        return complexity

    def generate_report(self, results: list[AnalysisResult]) -> dict[str, Any]:
        """Generate comprehensive analysis report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_issues": sum(len(r.issues) for r in results),
                "errors": sum(r.error_count for r in results),
                "warnings": sum(r.warning_count for r in results),
                "tools_passed": sum(1 for r in results if r.passed),
                "tools_failed": sum(1 for r in results if not r.passed),
            },
            "results": [],
        }

        # Display summary table
        table = Table(title="Static Analysis Results")
        table.add_column("Tool", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Errors", justify="right", style="red")
        table.add_column("Warnings", justify="right", style="yellow")
        table.add_column("Duration", justify="right")

        for result in results:
            status = (
                "[green]✓ Passed[/green]" if result.passed else "[red]✗ Failed[/red]"
            )
            table.add_row(
                result.tool.title(),
                status,
                str(result.error_count),
                str(result.warning_count),
                f"{result.duration:.2f}s",
            )

            report["results"].append(
                {
                    "tool": result.tool,
                    "passed": result.passed,
                    "duration": result.duration,
                    "metrics": result.metrics,
                    "issue_count": len(result.issues),
                    "errors": result.error_count,
                    "warnings": result.warning_count,
                }
            )

        self.console.print(table)

        # Show top issues
        if report["summary"]["total_issues"] > 0:
            self.console.print("\n[bold]Top Issues:[/bold]")

            # Group issues by file
            issues_by_file = {}
            for result in results:
                for issue in result.issues:
                    if issue.file not in issues_by_file:
                        issues_by_file[issue.file] = []
                    issues_by_file[issue.file].append(issue)

            # Show up to 10 files with most issues
            sorted_files = sorted(
                issues_by_file.items(), key=lambda x: len(x[1]), reverse=True
            )[:10]

            for file, issues in sorted_files:
                self.console.print(f"\n[yellow]{file}[/yellow] ({len(issues)} issues)")
                for issue in issues[:3]:  # Show up to 3 issues per file
                    severity_color = "red" if issue.severity == "error" else "yellow"
                    self.console.print(
                        f"  [{severity_color}]{issue.line}:{issue.column}[/{severity_color}] "
                        f"[{issue.tool}:{issue.code}] {issue.message}"
                    )
                if len(issues) > 3:
                    self.console.print(f"  ... and {len(issues) - 3} more")

        # Save detailed report
        report_path = self.project_root / "analysis_report.json"
        detailed_report = report.copy()
        detailed_report["issues"] = []

        for result in results:
            for issue in result.issues:
                detailed_report["issues"].append(
                    {
                        "file": issue.file,
                        "line": issue.line,
                        "column": issue.column,
                        "code": issue.code,
                        "message": issue.message,
                        "severity": issue.severity,
                        "tool": issue.tool,
                    }
                )

        with open(report_path, "w") as f:
            json.dump(detailed_report, f, indent=2)

        self.console.print(f"\n[green]Detailed report saved to:[/green] {report_path}")

        return report
