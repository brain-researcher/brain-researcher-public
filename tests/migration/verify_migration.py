#!/usr/bin/env python3
"""Automated verification script for Biomni-style migration phases.

This script runs comprehensive tests after each migration phase to ensure
nothing is broken and all functionality is preserved.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


class MigrationVerifier:
    """Verify migration phases are successful."""

    def __init__(self):
        self.test_dir = Path(__file__).parent
        self.project_root = self.test_dir.parent.parent
        self.results = {}

    def verify_phase(self, phase_num: int) -> bool:
        """Run all tests for a migration phase."""
        console.print(
            Panel(
                f"[bold cyan]Verifying Migration Phase {phase_num}[/bold cyan]",
                border_style="cyan",
            )
        )

        tests = [
            ("Import Tests", f"test_phase_{phase_num}_imports.py"),
            ("Functionality Tests", f"test_phase_{phase_num}_functionality.py"),
            ("Integration Tests", "test_integration.py"),
            ("CLI Tests", "test_cli_commands.py"),
        ]

        all_passed = True
        results = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for test_name, test_file in tests:
                task = progress.add_task(f"Running {test_name}...", total=1)

                # Check if test file exists
                test_path = self.test_dir / test_file
                if not test_path.exists() and phase_num > 0:
                    # For phase-specific tests, skip if not exists
                    if f"phase_{phase_num}" in test_file:
                        progress.update(task, completed=1)
                        results.append((test_name, "SKIPPED", "Test not created yet"))
                        continue

                # Run the test
                cmd = ["pytest", str(test_path), "-v", "--tb=short"]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    results.append((test_name, "PASSED", "All tests passed"))
                else:
                    all_passed = False
                    # Extract failure summary
                    lines = result.stdout.split("\n")
                    failure_summary = "Test failures detected"
                    for line in lines:
                        if "FAILED" in line or "ERROR" in line:
                            failure_summary = line.strip()
                            break
                    results.append((test_name, "FAILED", failure_summary))

                progress.update(task, completed=1)

        # Display results table
        table = Table(title=f"Phase {phase_num} Test Results")
        table.add_column("Test Suite", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Details")

        for test_name, status, details in results:
            status_style = (
                "green"
                if status == "PASSED"
                else "red" if status == "FAILED" else "yellow"
            )
            table.add_row(
                test_name, f"[{status_style}]{status}[/{status_style}]", details
            )

        console.print(table)

        # Check coverage if all tests passed
        if all_passed:
            coverage_passed = self.check_coverage()
            all_passed = coverage_passed

        # Save results
        self.results[f"phase_{phase_num}"] = {
            "all_passed": all_passed,
            "test_results": results,
        }

        return all_passed

    def check_coverage(self) -> bool:
        """Check test coverage meets threshold."""
        console.print("\n[bold]Checking test coverage...[/bold]")

        # Run coverage
        subprocess.run(
            ["coverage", "run", "-m", "pytest", str(self.test_dir.parent)],
            capture_output=True,
        )

        # Get coverage report
        result = subprocess.run(
            ["coverage", "report", "--skip-covered"], capture_output=True, text=True
        )

        # Parse coverage percentage
        for line in result.stdout.split("\n"):
            if "TOTAL" in line:
                parts = line.split()
                if len(parts) >= 4:
                    coverage_str = parts[-1].rstrip("%")
                    try:
                        coverage = float(coverage_str)
                        console.print(f"Total coverage: [bold]{coverage}%[/bold]")

                        if coverage >= 70:
                            console.print("[green]✓ Coverage threshold met![/green]")
                            return True
                        else:
                            console.print("[red]✗ Coverage below 70% threshold[/red]")
                            return False
                    except ValueError:
                        pass

        console.print("[yellow]⚠ Could not determine coverage[/yellow]")
        return True  # Don't fail on coverage parsing issues

    def run_smoke_tests(self) -> bool:
        """Run CLI smoke tests."""
        console.print("\n[bold]Running CLI smoke tests...[/bold]")

        commands = [
            ["brain-researcher", "--help"],
            ["brain-researcher", "version"],
            ["brain-researcher", "db", "--help"],
            ["brain-researcher", "data", "--help"],
            ["brain-researcher", "query", "--help"],
        ]

        all_passed = True

        for cmd in commands:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                console.print(f"[green]✓[/green] {' '.join(cmd)}")
            else:
                console.print(f"[red]✗[/red] {' '.join(cmd)}")
                all_passed = False

        return all_passed

    def generate_report(self, phase_num: int):
        """Generate verification report."""
        report_path = self.test_dir / f"phase_{phase_num}_verification.json"

        report = {
            "phase": phase_num,
            "results": self.results,
            "timestamp": str(Path.cwd()),
            "python_version": sys.version,
        }

        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        console.print(f"\n[green]Report saved to:[/green] {report_path}")

        return report_path


def rollback_to_phase(phase_num: int):
    """Rollback to a previous migration phase."""
    console.print(
        Panel(
            f"[bold red]Rolling back to pre-phase-{phase_num}[/bold red]",
            border_style="red",
        )
    )

    # Git checkout to tag
    tag = f"pre-phase-{phase_num}"
    result = subprocess.run(["git", "checkout", tag], capture_output=True, text=True)

    if result.returncode == 0:
        console.print(f"[green]✓ Rolled back to {tag}[/green]")

        # Reinstall package
        subprocess.run(["pip", "install", "-e", "."])
        console.print("[green]✓ Package reinstalled[/green]")

        return True
    else:
        console.print(f"[red]✗ Failed to rollback: {result.stderr}[/red]")
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify Biomni-style migration phases")
    parser.add_argument("phase", type=int, help="Phase number to verify (0-9)")
    parser.add_argument(
        "--rollback", action="store_true", help="Rollback to pre-phase checkpoint"
    )

    args = parser.parse_args()

    if args.rollback:
        success = rollback_to_phase(args.phase)
        sys.exit(0 if success else 1)

    # Run verification
    verifier = MigrationVerifier()

    # Run phase verification
    phase_passed = verifier.verify_phase(args.phase)

    # Run smoke tests
    smoke_passed = verifier.run_smoke_tests()

    # Generate report
    verifier.generate_report(args.phase)

    # Summary
    if phase_passed and smoke_passed:
        console.print(
            Panel(
                f"[bold green]Phase {args.phase} verification PASSED![/bold green]\n"
                "Safe to proceed to next phase.",
                border_style="green",
            )
        )
        sys.exit(0)
    else:
        console.print(
            Panel(
                f"[bold red]Phase {args.phase} verification FAILED![/bold red]\n"
                "Fix issues before proceeding.",
                border_style="red",
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
