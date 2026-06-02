"""Legacy launcher for the retired single-port gateway surface."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from brain_researcher.config.paths import get_package_root

console = Console()


def launch_gateway(
    port: int = 8000,
    host: str = "0.0.0.0",
    reload: bool = True,
    workers: int = 1,
) -> None:
    """Fail with guidance because the gateway runtime is retired."""
    gateway_dir = get_package_root() / "services" / "gateway"

    if not gateway_dir.exists():
        console.print(f"[red]Gateway directory not found: {gateway_dir}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            "[yellow]Gateway runtime is retired.[/yellow]\n\n"
            "Use the split-service topology instead:\n"
            "  br serve agent --host 0.0.0.0 --port 8000\n"
            "  br serve orchestrator --host 0.0.0.0 --port 3001\n"
            "  br serve web --host 0.0.0.0 --port 3000\n\n"
            "Or launch the full local stack:\n"
            "  ./scripts/services/start_services.sh",
            title="Legacy Gateway",
            border_style="yellow",
        )
    )
    raise typer.Exit(1)
