"""
Test Runner - Main entry point for the testing framework.
"""

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .supervisor import Supervisor


class TestRunner:
    """
    Main test runner that provides CLI interface to the testing framework.
    """

    def __init__(self):
        self.console = Console()

    def run(self, args: list[str] | None = None) -> int:
        """Run the test framework with given arguments."""
        parser = self._create_parser()
        parsed_args = parser.parse_args(args)

        # Handle different commands
        if parsed_args.command == "test":
            return self._run_tests(parsed_args)
        elif parsed_args.command == "analyze":
            return self._run_analysis(parsed_args)
        elif parsed_args.command == "assess":
            return self._run_assessment(parsed_args)
        elif parsed_args.command == "compare":
            return self._compare_baseline(parsed_args)
        else:
            parser.print_help()
            return 1

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser."""
        parser = argparse.ArgumentParser(
            prog="brain-researcher test",
            description="Brain Researcher Testing Framework",
        )

        subparsers = parser.add_subparsers(dest="command", help="Commands")

        # Test command
        test_parser = subparsers.add_parser("test", help="Run tests")
        test_parser.add_argument(
            "--type",
            choices=["unit", "integration", "cli", "all"],
            default="all",
            help="Type of tests to run",
        )
        test_parser.add_argument(
            "--coverage", action="store_true", help="Enable coverage reporting"
        )
        test_parser.add_argument(
            "--path", type=Path, help="Project path (default: current directory)"
        )

        # Analyze command
        analyze_parser = subparsers.add_parser("analyze", help="Run static analysis")
        analyze_parser.add_argument(
            "--tools",
            nargs="+",
            choices=["ruff", "mypy", "security", "complexity", "formatting", "all"],
            default=["all"],
            help="Analysis tools to run",
        )
        analyze_parser.add_argument(
            "--path", type=Path, help="Project path (default: current directory)"
        )

        # Assess command (full assessment)
        assess_parser = subparsers.add_parser(
            "assess", help="Run full quality assessment"
        )
        assess_parser.add_argument(
            "--path", type=Path, help="Project path (default: current directory)"
        )
        assess_parser.add_argument(
            "--config", type=Path, help="Quality configuration file"
        )

        # Compare command
        compare_parser = subparsers.add_parser("compare", help="Compare with baseline")
        compare_parser.add_argument(
            "--path", type=Path, help="Project path (default: current directory)"
        )

        return parser

    def _run_tests(self, args) -> int:
        """Run tests only."""
        from .tester import Tester

        project_path = args.path or Path.cwd()
        tester = Tester(project_path)

        suites = []

        if args.type in ["unit", "all"]:
            suite = tester.run_unit_tests(coverage_enabled=args.coverage)
            suites.append(suite)

        if args.type in ["integration", "all"]:
            suite = tester.run_integration_tests()
            suites.append(suite)

        if args.type in ["cli", "all"]:
            suite = tester.run_cli_tests()
            suites.append(suite)

        # Generate report
        report = tester.generate_report(suites)

        # Return non-zero if any tests failed
        return 0 if report["summary"]["failed"] == 0 else 1

    def _run_analysis(self, args) -> int:
        """Run static analysis only."""
        from .static_analyst import StaticAnalyst

        project_path = args.path or Path.cwd()
        analyst = StaticAnalyst(project_path)

        results = []
        tools = (
            args.tools
            if "all" not in args.tools
            else ["ruff", "mypy", "security", "complexity", "formatting"]
        )

        if "ruff" in tools:
            results.append(analyst.run_ruff())

        if "mypy" in tools:
            results.append(analyst.run_mypy())

        if "security" in tools:
            results.append(analyst.run_security_scan())

        if "complexity" in tools:
            results.append(analyst.analyze_complexity())

        if "formatting" in tools:
            results.append(analyst.check_formatting())

        # Generate report
        report = analyst.generate_report(results)

        # Return non-zero if critical issues found
        return 0 if report["summary"]["errors"] == 0 else 1

    def _run_assessment(self, args) -> int:
        """Run full quality assessment."""
        project_path = args.path or Path.cwd()
        supervisor = Supervisor(project_path)

        # Run assessment
        assessment = supervisor.run_full_assessment()

        # Return based on recommendation
        decision = assessment["recommendation"]["decision"]
        if decision == "APPROVE":
            return 0
        elif decision == "CONDITIONAL":
            return 1
        else:  # REJECT
            return 2

    def _compare_baseline(self, args) -> int:
        """Compare current state with baseline."""
        project_path = args.path or Path.cwd()
        supervisor = Supervisor(project_path)

        # Run assessment first
        self.console.print("[bold]Running current assessment...[/bold]")
        current = supervisor.run_full_assessment()

        # Compare with baseline
        self.console.print("\n[bold]Comparing with baseline...[/bold]")
        comparison = supervisor.compare_with_baseline(current)

        if comparison.get("status") == "baseline_created":
            self.console.print(
                "[yellow]No baseline found. Current results saved as baseline.[/yellow]"
            )
            return 0

        # Display comparison
        self.console.print("\n[bold]Quality Trend:[/bold]")

        if comparison["improved"]:
            self.console.print("\n[green]Improvements:[/green]")
            for improvement in comparison["improved"]:
                self.console.print(f"  ✓ {improvement}")

        if comparison["degraded"]:
            self.console.print("\n[red]Degradations:[/red]")
            for degradation in comparison["degraded"]:
                self.console.print(f"  ✗ {degradation}")

        if not comparison["improved"] and not comparison["degraded"]:
            self.console.print("[dim]No significant changes from baseline.[/dim]")

        return 0


def main():
    """Main entry point."""
    runner = TestRunner()
    sys.exit(runner.run())


if __name__ == "__main__":
    main()
