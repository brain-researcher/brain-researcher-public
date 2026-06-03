"""Budget and usage tracking CLI commands."""

import json
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

from brain_researcher.services.agent.usage_aggregator import UsageTracker

app = typer.Typer(help="Budget and usage tracking commands")
console = Console()


@app.command("status")
def budget_status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """
    Show current LLM budget status and limits.

    Note: Budget enforcement (Track 1) is not yet implemented.
    This command is a placeholder for future integration.
    """
    # Placeholder for Track 1 BudgetTracker integration
    status_data = {
        "status": "not_implemented",
        "message": "Budget tracking (Track 1) is not yet implemented. Use 'br budget usage' to see actual usage.",
        "limits": {
            "daily_usd": None,
            "monthly_usd": None,
            "daily_tokens": None,
            "monthly_tokens": None,
        },
        "spent": {
            "daily_usd": 0.0,
            "monthly_usd": 0.0,
            "daily_tokens": 0,
            "monthly_tokens": 0,
        },
    }

    if json_output:
        print(json.dumps(status_data, indent=2))
        return

    console.print("[yellow]⚠ Budget enforcement not yet implemented (Track 1)[/yellow]")
    console.print(
        "\nUse [bold]br budget usage[/bold] to view actual LLM usage and costs."
    )


@app.command("usage")
def usage_report(
    start: str | None = typer.Option(
        None,
        "--start",
        help="Start date (YYYY-MM-DD). Defaults to 30 days ago.",
    ),
    end: str | None = typer.Option(
        None,
        "--end",
        help="End date (YYYY-MM-DD). Defaults to today.",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Filter by provider (e.g., google, openai)",
    ),
    bill_to: str | None = typer.Option(
        None,
        "--bill-to",
        help="Filter by billing target (local_oauth, byok, managed)",
    ),
    hours: int | None = typer.Option(
        None,
        "--last-hours",
        help="Show usage for last N hours (overrides start/end)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """
    Show LLM usage report with cost breakdown.

    Examples:
        br budget usage --last-hours 24
        br budget usage --start 2025-01-01 --end 2025-01-31
        br budget usage --provider google --json
        br budget usage --bill-to local_oauth
    """
    tracker = UsageTracker()

    # Determine date range
    if hours:
        summary = tracker.get_recent_usage(hours=hours)
        time_range = f"Last {hours} hours"
    else:
        # Default: last 30 days
        if not start:
            start = (datetime.now() - timedelta(days=30)).date().isoformat()
        if not end:
            end = datetime.now().date().isoformat()

        summary = tracker.get_usage_summary(
            start_date=start,
            end_date=end,
            provider=provider,
            bill_to=bill_to,
        )
        time_range = f"{start} to {end}"

    if json_output:
        # Remove full records from JSON output (too verbose)
        summary_copy = summary.copy()
        summary_copy["records"] = (
            f"{len(summary['records'])} records (use --verbose for details)"
        )
        print(json.dumps(summary_copy, indent=2))
        return

    # Human-readable output
    console.print(f"\n[bold]LLM Usage Report[/bold] ({time_range})\n")

    if summary["total_calls"] == 0:
        console.print("[yellow]No usage found for the specified period.[/yellow]")
        return

    # Overall summary
    console.print(f"[cyan]Total Calls:[/cyan] {summary['total_calls']}")
    console.print(f"[cyan]Total Tokens:[/cyan] {summary['total_tokens']:,}")
    console.print(f"[cyan]Total Cost:[/cyan] ${summary['total_cost']:.4f}\n")

    # By provider
    if summary["by_provider"]:
        table = Table(title="Usage by Provider")
        table.add_column("Provider", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right")

        for provider_name, stats in summary["by_provider"].items():
            table.add_row(
                provider_name,
                str(stats["calls"]),
                f"{stats['tokens']:,}",
                f"${stats['cost']:.4f}",
            )
        console.print(table)
        console.print()

    # By model
    if summary["by_model"]:
        table = Table(title="Usage by Model")
        table.add_column("Model", style="green")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right")

        for model_name, stats in summary["by_model"].items():
            table.add_row(
                model_name,
                str(stats["calls"]),
                f"{stats['tokens']:,}",
                f"${stats['cost']:.4f}",
            )
        console.print(table)
        console.print()

    # By billing target
    if summary["by_bill_to"]:
        table = Table(title="Usage by Billing Target")
        table.add_column("Billing Target", style="magenta")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right")

        for bill_to_val, stats in summary["by_bill_to"].items():
            # Add emoji badges
            if bill_to_val == "local_oauth":
                display_name = "🎁 Local OAuth (Free)"
            elif "byok" in bill_to_val.lower():
                display_name = f"🔑 {bill_to_val}"
            elif "managed" in bill_to_val.lower():
                display_name = f"💳 {bill_to_val}"
            else:
                display_name = bill_to_val

            table.add_row(
                display_name,
                str(stats["calls"]),
                f"{stats['tokens']:,}",
                f"${stats['cost']:.4f}",
            )
        console.print(table)


@app.command("set")
def set_budget(
    daily_usd: float | None = typer.Option(
        None,
        "--daily-usd",
        help="Daily USD budget limit",
    ),
    monthly_usd: float | None = typer.Option(
        None,
        "--monthly-usd",
        help="Monthly USD budget limit",
    ),
    daily_tokens: int | None = typer.Option(
        None,
        "--daily-tokens",
        help="Daily token budget limit",
    ),
    monthly_tokens: int | None = typer.Option(
        None,
        "--monthly-tokens",
        help="Monthly token budget limit",
    ),
):
    """
    Set LLM budget limits.

    Note: Budget enforcement (Track 1) is not yet implemented.
    This command is a placeholder for future integration.

    Example:
        br budget set --monthly-usd 50 --daily-usd 5
    """
    console.print(
        "[yellow]⚠ Budget enforcement not yet implemented (Track 1)[/yellow]\n"
    )
    console.print("Budget limits will be saved once BudgetTracker is implemented.")
    console.print("\nRequested limits:")
    if daily_usd is not None:
        console.print(f"  Daily USD: ${daily_usd:.2f}")
    if monthly_usd is not None:
        console.print(f"  Monthly USD: ${monthly_usd:.2f}")
    if daily_tokens is not None:
        console.print(f"  Daily Tokens: {daily_tokens:,}")
    if monthly_tokens is not None:
        console.print(f"  Monthly Tokens: {monthly_tokens:,}")

    if all(x is None for x in [daily_usd, monthly_usd, daily_tokens, monthly_tokens]):
        console.print("[red]Error: Please specify at least one budget limit.[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
