"""
Job and run inspection commands for Brain Researcher CLI.

Provides commands for:
- br runs ls: List jobs
- br runs inspect: View job details
- br runs plan: View planner decision trace
- br runs logs: Stream job logs
- br runs artifacts: List output files
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional, Union

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from brain_researcher.cli.utils.http_client import (
    api_get_sync,
    api_post_sync,
    api_stream,
)

app = typer.Typer(help="Job and run inspection commands")
console = Console()


def format_timestamp(value: Union[int, float, str, None]) -> str:
    """Convert timestamps (epoch seconds or ISO strings) into readable UTC text."""
    if value in (None, ""):
        return "N/A"

    dt: Optional[datetime] = None
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            dt = None
    elif isinstance(value, str):
        cleaned = value.strip()
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            try:
                dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            except ValueError:
                dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)

    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "Invalid"


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_confidence(value: Optional[float]) -> str:
    """Format confidence score (0-1) as a percentage string."""
    if value is None:
        return "N/A"
    try:
        return f"{value * 100:.0f}%"
    except (TypeError, ValueError):
        return "N/A"


@app.command("ls")
def list_jobs(
    state: Optional[str] = typer.Option(
        None, "--state", "-s", help="Filter by state (running, succeeded, failed, etc.)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-n", help="Maximum number of jobs to show"
    ),
):
    """
    List recent jobs.

    Examples:
        br runs ls
        br runs ls --state running
        br runs ls --limit 10
        br runs ls --state succeeded --limit 20
    """
    try:
        # Build search request payload
        search_payload = {"limit": limit, "sort_by": "created_at", "sort_desc": True}
        if state:
            search_payload["status"] = [state]

        # Fetch jobs using search endpoint
        response = api_post_sync("/api/jobs/search", json_data=search_payload)
        jobs = response.get("jobs", [])
        total = response.get("total", 0)

        if not jobs:
            console.print("[yellow]No jobs found[/yellow]")
            return

        # Create table with Plan Status column
        table = Table(
            title=f"Recent Jobs ({len(jobs)} of {total} total)",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Job ID", style="cyan", no_wrap=True)
        table.add_column("State", style="yellow")
        table.add_column("Tool", style="green")
        table.add_column("Prompt", style="dim")
        table.add_column("Plan Status", style="magenta")
        table.add_column("Created", style="blue")

        for job in jobs:
            # Format state with color
            state_str = job.get("status", "unknown")
            if state_str in ("succeeded", "completed"):
                state_display = f"[green]{state_str}[/green]"
            elif state_str == "failed":
                state_display = f"[red]{state_str}[/red]"
            elif state_str == "running":
                state_display = f"[yellow]{state_str}[/yellow]"
            else:
                state_display = state_str

            # Truncate prompt if too long
            prompt = job.get("prompt", "")
            if len(prompt) > 30:
                prompt = prompt[:27] + "..."

            # Extract plan status from plan_summary
            plan_summary = job.get("plan_summary", {})
            plan_status = (
                plan_summary.get("plan_status", "N/A") if plan_summary else "N/A"
            )

            table.add_row(
                job.get("id", ""),
                state_display,
                job.get("tool", "N/A"),
                prompt,
                plan_status,
                format_timestamp(job.get("created_at", 0)),
            )

        console.print(table)
        console.print(f"\n[dim]View details:[/dim] br runs inspect <job_id>")

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("inspect")
def inspect_job(
    job_id: str = typer.Argument(..., help="Job ID to inspect"),
):
    """
    View detailed job information.

    Shows job status, metadata, timing, and planner information if available.

    Examples:
        br runs inspect run_abc123
        br runs inspect exec_xyz789
    """
    try:
        # Fetch job details
        job = api_get_sync(f"/api/jobs/{job_id}")

        # Basic info panel
        info_lines = [
            f"[bold]Job ID:[/bold] {job.get('job_id', 'N/A')}",
            f"[bold]State:[/bold] {job.get('state', 'N/A')}",
            f"[bold]Tool:[/bold] {job.get('tool', 'N/A')}",
            f"[bold]Priority:[/bold] {job.get('priority', 0)}",
        ]

        prompt = job.get("prompt")
        if prompt:
            info_lines.append(f"[bold]Prompt:[/bold] {prompt}")

        console.print(
            Panel("\n".join(info_lines), title="Job Information", border_style="cyan")
        )

        # Timing panel
        timing_lines = [
            f"[bold]Created:[/bold] {format_timestamp(job.get('created_at', 0))}",
        ]

        if job.get("queued_at"):
            timing_lines.append(
                f"[bold]Queued:[/bold] {format_timestamp(job.get('queued_at'))}"
            )
        if job.get("claimed_at"):
            timing_lines.append(
                f"[bold]Claimed:[/bold] {format_timestamp(job.get('claimed_at'))}"
            )
        if job.get("started_at"):
            timing_lines.append(
                f"[bold]Started:[/bold] {format_timestamp(job.get('started_at'))}"
            )
        if job.get("completed_at"):
            timing_lines.append(
                f"[bold]Completed:[/bold] {format_timestamp(job.get('completed_at'))}"
            )

        console.print(
            Panel("\n".join(timing_lines), title="Timing", border_style="blue")
        )

        # Plan summary panel if available
        plan_summary = job.get("plan_summary")
        if plan_summary:
            plan_conf = plan_summary.get("plan_conf")
            if plan_conf is None:
                plan_conf = plan_summary.get("confidence_score")
            plan_lines = [
                f"[bold]Plan ID:[/bold] {plan_summary.get('plan_id', 'N/A')}",
                f"[bold]Version:[/bold] {plan_summary.get('version', 'N/A')}",
                f"[bold]Status:[/bold] {plan_summary.get('plan_status', 'N/A')}",
                f"[bold]Steps:[/bold] {plan_summary.get('step_count', 0)}",
                f"[bold]Plan Confidence:[/bold] {format_confidence(plan_conf)}",
                f"[bold]POR Token:[/bold] {'Set' if plan_summary.get('por_token_set') else 'Not set'}",
            ]
            console.print(
                Panel(
                    "\n".join(plan_lines),
                    title="Plan of Record",
                    border_style="magenta",
                )
            )

        # Error panel if failed
        error = job.get("error")
        if error:
            console.print(Panel(error, title="Error", border_style="red"))

        # Show planner info if available
        try:
            plan = api_get_sync(f"/api/jobs/{job_id}/plan")
            console.print(
                Panel(
                    f"[bold]Intent:[/bold] {plan.get('intent', 'N/A')}\n"
                    f"[bold]Chosen Tool:[/bold] {plan.get('chosen', {}).get('tool_name', 'N/A')} "
                    f"(score: {plan.get('chosen', {}).get('score', 0):.2f})\n"
                    f"[bold]Candidates:[/bold] {len(plan.get('candidates', []))}",
                    title="Planner Trace",
                    border_style="green",
                )
            )
            console.print(f"\n[dim]View full plan:[/dim] br runs plan {job_id}")
        except:
            pass  # Plan not available

        # Additional commands
        console.print(f"\n[dim]View plan:[/dim] br runs plan {job_id}")
        console.print(f"[dim]View logs:[/dim] br runs logs {job_id}")
        console.print(f"[dim]View artifacts:[/dim] br runs artifacts {job_id}")

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("plan")
def view_plan(
    job_id: str = typer.Argument(..., help="Job ID"),
):
    """
    View planner decision trace for a job.

    Shows why a specific tool was chosen, including ranked candidates,
    preflight results, and reasoning.

    Examples:
        br runs plan run_abc123
    """
    try:
        # Fetch plan
        plan = api_get_sync(f"/api/jobs/{job_id}/plan")

        # Display intent
        console.print(f"\n[bold cyan]Intent:[/bold cyan] {plan.get('intent', 'N/A')}\n")

        # Create candidates table
        candidates = plan.get("candidates", [])
        if candidates:
            table = Table(
                title="Candidate Tools", show_header=True, header_style="bold magenta"
            )
            table.add_column("Rank", justify="right", style="dim")
            table.add_column("Tool ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Score", justify="right", style="yellow")
            table.add_column("Preflight", justify="center")
            table.add_column("Reason", style="dim")

            for i, candidate in enumerate(candidates, 1):
                preflight = "✓" if candidate.get("preflight_ok") else "✗"
                preflight_style = "green" if candidate.get("preflight_ok") else "red"

                # Highlight chosen tool
                if candidate.get("tool_id") == plan.get("chosen", {}).get("tool_id"):
                    rank_display = f"[bold green]#{i} ✓[/bold green]"
                else:
                    rank_display = f"#{i}"

                table.add_row(
                    rank_display,
                    candidate.get("tool_id", ""),
                    candidate.get("tool_name", ""),
                    f"{candidate.get('score', 0):.2f}",
                    f"[{preflight_style}]{preflight}[/{preflight_style}]",
                    candidate.get("reason", ""),
                )

            console.print(table)

        # Display chosen tool details
        chosen = plan.get("chosen")
        if chosen:
            console.print(f"\n[bold green]✓ Selected Tool[/bold green]")
            console.print(
                f"  [bold]Tool:[/bold] {chosen.get('tool_name')} ({chosen.get('tool_id')})"
            )
            console.print(f"  [bold]Score:[/bold] {chosen.get('score', 0):.2f}")
            console.print(f"  [bold]Image:[/bold] {chosen.get('image', 'N/A')}")
            console.print(f"  [bold]Reason:[/bold] {chosen.get('reason', 'N/A')}")

        # Show constraints if available
        constraints = plan.get("constraints", {})
        if constraints:
            console.print(f"\n[bold]Constraints:[/bold]")
            for key, value in constraints.items():
                console.print(f"  {key}: {value}")

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if "404" in str(e):
            console.print(
                f"[yellow]Tip:[/yellow] This job may not have used the planner"
            )
        raise typer.Exit(1)


@app.command("logs")
def view_logs(
    job_id: str = typer.Argument(..., help="Job ID"),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Stream logs in real-time"
    ),
    stream_type: str = typer.Option(
        "all", "--stream", "-s", help="Log stream: stdout, stderr, or all"
    ),
):
    """
    View or stream job logs.

    Examples:
        br runs logs run_abc123
        br runs logs run_abc123 --follow
        br runs logs run_abc123 --stream stdout
    """
    try:
        if follow:
            # Stream logs in real-time
            console.print(
                f"[dim]Streaming logs for {job_id} (Ctrl+C to stop)...[/dim]\n"
            )

            async def stream_logs():
                params = {"follow": "true"}
                if stream_type != "all":
                    params["stream"] = stream_type

                try:
                    async for line in api_stream(
                        f"/api/jobs/{job_id}/logs/stream", params=params
                    ):
                        if line.strip():
                            try:
                                log_data = json.loads(line)
                                # Format log entry
                                timestamp = log_data.get("timestamp", "")
                                text = log_data.get("text", "")
                                console.print(f"[dim]{timestamp}[/dim] {text}")
                            except json.JSONDecodeError:
                                # Plain text line
                                console.print(line)
                except KeyboardInterrupt:
                    console.print("\n[yellow]Stream stopped[/yellow]")

            asyncio.run(stream_logs())
        else:
            # Fetch static logs
            params = {}
            if stream_type != "all":
                params["stream"] = stream_type

            response = api_get_sync(f"/api/jobs/{job_id}/logs/stream", params=params)

            # Display logs
            logs = response.get("logs", [])
            if not logs:
                console.print("[yellow]No logs available[/yellow]")
                return

            for log_entry in logs:
                if isinstance(log_entry, dict):
                    timestamp = log_entry.get("timestamp", "")
                    text = log_entry.get("text", "")
                    console.print(f"[dim]{timestamp}[/dim] {text}")
                else:
                    console.print(log_entry)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("artifacts")
def list_artifacts(
    job_id: str = typer.Argument(..., help="Job ID"),
):
    """
    List output artifacts for a job.

    Shows all files generated by the job in its run directory.

    Examples:
        br runs artifacts run_abc123
    """
    try:
        # Fetch artifacts
        response = api_get_sync(f"/api/jobs/{job_id}/artifacts/files")

        run_id = response.get("run_id", "N/A")
        run_dir = response.get("run_dir", "N/A")
        files = response.get("files", [])

        console.print(f"\n[bold]Run Directory:[/bold] {run_dir}")
        console.print(f"[bold]Files:[/bold] {len(files)}\n")

        if not files:
            console.print("[yellow]No artifact files found[/yellow]")
            return

        # Create table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("File Name", style="cyan")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Modified", style="blue")

        for file_info in files:
            table.add_row(
                file_info.get("name", ""),
                format_file_size(file_info.get("size", 0)),
                file_info.get("modified", "N/A"),
            )

        console.print(table)
        console.print(f"\n[dim]Download files from:[/dim] {run_dir}")

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if "404" in str(e):
            console.print(
                f"[yellow]Tip:[/yellow] Job may not have completed or run directory not available"
            )
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
