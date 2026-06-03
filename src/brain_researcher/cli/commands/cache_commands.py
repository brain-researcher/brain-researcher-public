"""Cache management commands for Brain Researcher CLI (P2.5)."""

import os
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from brain_researcher.cli.utils.http_client import get_orchestrator_url

app = typer.Typer(help="Cache management commands")
console = Console()


def _check_cache_enabled() -> bool:
    """Check if cache is enabled and warn if not."""
    cache_enabled = os.getenv("BR_CACHE_ENABLED", "false").lower() == "true"
    if not cache_enabled:
        console.print(
            "[yellow]Warning: Cache is disabled (BR_CACHE_ENABLED=false)[/yellow]"
        )
        console.print(
            "[dim]Enable with: export BR_CACHE_ENABLED=true[/dim]"
        )
        return False
    return True


@app.command()
def status():
    """Show cache statistics (entries, size, hit rate)."""
    try:
        import httpx
    except ImportError:
        console.print(
            "[red]Error: httpx is required. Install with: pip install httpx[/red]"
        )
        raise typer.Exit(1)

    if not _check_cache_enabled():
        raise typer.Exit(1)

    orchestrator_url = get_orchestrator_url()
    console.print(f"[dim]Fetching cache stats from {orchestrator_url}...[/dim]")

    try:
        response = httpx.get(f"{orchestrator_url}/api/cache/stats", timeout=10.0)
        response.raise_for_status()
        stats = response.json()

        # Create table
        table = Table(title="Cache Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta", justify="right")

        # Entries
        table.add_row("Total Entries", str(stats["total_entries"]))
        table.add_row("├─ Pending", str(stats["pending_entries"]))
        table.add_row("├─ Completed", str(stats["completed_entries"]))
        table.add_row("└─ Failed", str(stats["failed_entries"]))

        # Size
        table.add_row("Total Size", f"{stats['total_size_mb']:.2f} MB")

        # Hit rate
        table.add_row("Hit Count", str(stats["hit_count"]))
        table.add_row("Miss Count", str(stats["miss_count"]))
        hit_rate_pct = stats["hit_rate"] * 100
        table.add_row("Hit Rate", f"{hit_rate_pct:.1f}%")

        console.print(table)

        # Show cache mode
        cache_mode = os.getenv("BR_CACHE_MODE", "fast")
        cache_store = os.getenv("BR_CACHE_STORE", "memory")
        console.print(
            f"\n[dim]Mode: {cache_mode} | Store: {cache_store}[/dim]"
        )

    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching cache stats: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def clear(
    tool_version: Optional[str] = typer.Option(
        None, "--tool", "-t", help="Clear entries for specific tool version (e.g., 'fsl.bet:6.0.7')"
    ),
    git_sha: Optional[str] = typer.Option(
        None, "--git", "-g", help="Clear entries for specific git SHA"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation prompt"
    ),
):
    """Clear cache entries (all, by tool, or by git SHA)."""
    try:
        import httpx
    except ImportError:
        console.print(
            "[red]Error: httpx is required. Install with: pip install httpx[/red]"
        )
        raise typer.Exit(1)

    if not _check_cache_enabled():
        raise typer.Exit(1)

    # Build description for confirmation
    if tool_version:
        desc = f"entries for tool version '{tool_version}'"
    elif git_sha:
        desc = f"entries for git SHA '{git_sha[:8]}...'"
    else:
        desc = "ALL cache entries"

    # Confirm if not --force
    if not force:
        confirm = typer.confirm(f"Clear {desc}?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            return

    orchestrator_url = get_orchestrator_url()
    console.print(f"[dim]Clearing cache entries...[/dim]")

    try:
        # Build query params
        params = {}
        if tool_version:
            params["tool_version"] = tool_version
        elif git_sha:
            params["git_sha"] = git_sha

        response = httpx.delete(
            f"{orchestrator_url}/api/cache",
            params=params,
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()

        console.print(
            f"[green]✓[/green] Deleted {result['deleted']} entries "
            f"(filter: {result['filter']})"
        )

    except httpx.HTTPError as e:
        console.print(f"[red]Error clearing cache: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def gc(
    max_entries: int = typer.Option(
        10000, "--max", "-m", help="Maximum entries to keep (oldest will be evicted)"
    ),
):
    """Run LRU garbage collection to limit cache size."""
    try:
        import httpx
    except ImportError:
        console.print(
            "[red]Error: httpx is required. Install with: pip install httpx[/red]"
        )
        raise typer.Exit(1)

    if not _check_cache_enabled():
        raise typer.Exit(1)

    orchestrator_url = get_orchestrator_url()
    console.print(f"[dim]Running LRU eviction (keeping {max_entries} most recent)...[/dim]")

    try:
        response = httpx.post(
            f"{orchestrator_url}/api/cache/gc",
            params={"max_entries": max_entries},
            timeout=60.0
        )
        response.raise_for_status()
        result = response.json()

        if result["evicted"] > 0:
            console.print(
                f"[green]✓[/green] {result['message']}"
            )
        else:
            console.print(
                f"[dim]No eviction needed (cache under {max_entries} entries)[/dim]"
            )

    except httpx.HTTPError as e:
        console.print(f"[red]Error running garbage collection: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def resolve(
    cache_key: Optional[str] = typer.Option(
        None, "--key", "-k", help="Cache key to resolve (sha256:...)"
    ),
    tool: Optional[str] = typer.Option(
        None, "--tool", "-t", help="Tool name (e.g., 'fsl.bet')"
    ),
    params_file: Optional[Path] = typer.Option(
        None, "--params", "-p", help="JSON file with tool parameters"
    ),
):
    """Resolve cache key to run info or check if parameters are cached.

    Usage:
        # Resolve existing cache key
        br cache resolve --key sha256:abc123...

        # Check if tool execution is cached (from params file)
        br cache resolve --tool fsl.bet --params params.json
    """
    try:
        import httpx
    except ImportError:
        console.print(
            "[red]Error: httpx is required. Install with: pip install httpx[/red]"
        )
        raise typer.Exit(1)

    if not _check_cache_enabled():
        raise typer.Exit(1)

    orchestrator_url = get_orchestrator_url()

    try:
        if cache_key:
            # Resolve existing key
            console.print(f"[dim]Resolving cache key {cache_key[:16]}...[/dim]")
            response = httpx.get(
                f"{orchestrator_url}/api/cache/resolve",
                params={"key": cache_key},
                timeout=10.0
            )
            response.raise_for_status()
            entry = response.json()

            # Display entry details
            console.print(Panel(
                f"[cyan]Run ID:[/cyan] {entry['run_id']}\n"
                f"[cyan]State:[/cyan] {entry['state']}\n"
                f"[cyan]Run Dir:[/cyan] {entry.get('run_dir', 'N/A')}\n"
                f"[cyan]Tool Version:[/cyan] {entry.get('tool_version', 'N/A')}\n"
                f"[cyan]Size:[/cyan] {entry.get('size_bytes', 0) / (1024*1024):.2f} MB\n"
                f"[cyan]Created:[/cyan] {entry['created_at']}\n"
                f"[cyan]Last Accessed:[/cyan] {entry['last_accessed_at']}",
                title=f"Cache Entry: {cache_key[:16]}...",
                border_style="green"
            ))

        elif tool and params_file:
            # Compute key from parameters and resolve
            if not params_file.exists():
                console.print(f"[red]Error: Params file not found: {params_file}[/red]")
                raise typer.Exit(1)

            with open(params_file) as f:
                params_data = json.load(f)

            console.print(f"[dim]Computing cache key for {tool}...[/dim]")

            # Build request payload
            payload = {
                "tool": tool,
                "parameters": params_data.get("parameters", {}),
                "tool_version": params_data.get("tool_version"),
                "container_image": params_data.get("container_image", ""),
            }

            response = httpx.post(
                f"{orchestrator_url}/api/cache/resolve",
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()

            console.print(f"\n[cyan]Cache Key:[/cyan] {result['cache_key'][:64]}...")

            if result["found"]:
                entry = result["entry"]
                console.print(
                    f"[green]✓ Cache HIT[/green] - Result available\n"
                    f"[cyan]Run ID:[/cyan] {entry['run_id']}\n"
                    f"[cyan]Run Dir:[/cyan] {entry.get('run_dir', 'N/A')}\n"
                    f"[cyan]State:[/cyan] {entry['state']}"
                )
            else:
                console.print("[yellow]Cache MISS[/yellow] - Result not cached")

        else:
            console.print(
                "[red]Error: Must provide either --key or (--tool + --params)[/red]"
            )
            raise typer.Exit(1)

    except httpx.HTTPError as e:
        if hasattr(e, 'response') and e.response.status_code == 404:
            console.print("[yellow]Cache entry not found[/yellow]")
        elif hasattr(e, 'response') and e.response.status_code == 503:
            console.print("[red]Cache is not enabled on the orchestrator[/red]")
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
