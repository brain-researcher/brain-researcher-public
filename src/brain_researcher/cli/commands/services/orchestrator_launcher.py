"""
CLI launcher for the orchestrator service.
"""

import importlib.util
import os
import subprocess
import sys

import typer
from rich.console import Console
from rich.panel import Panel

from brain_researcher.config.paths import get_package_root, get_repo_root
from brain_researcher.core.utils.env_loader import ensure_env_loaded

console = Console()


def launch_orchestrator(
    port: int = 3001,
    host: str = "0.0.0.0",
    reload: bool = True,
    workers: int = 1,
) -> None:
    """
    Launch the orchestrator API service.

    Args:
        port: Port to run the service on
        host: Host to bind to
        reload: Enable auto-reload for development
        workers: Number of worker processes
    """
    ensure_env_loaded()
    repo_root = get_repo_root()
    orchestrator_dir = get_package_root() / "services" / "orchestrator"

    if not orchestrator_dir.exists():
        console.print(
            f"[red]Orchestrator directory not found: {orchestrator_dir}[/red]"
        )
        raise typer.Exit(1)

    # Check if required dependencies are installed
    required_packages = ("fastapi", "uvicorn", "httpx", "sse_starlette")
    missing_packages = [
        name for name in required_packages if importlib.util.find_spec(name) is None
    ]
    if missing_packages:
        console.print(
            Panel(
                "[yellow]Missing dependencies for orchestrator service[/yellow]\n\n"
                "Please install required packages:\n"
                "[cyan]pip install fastapi uvicorn httpx sse-starlette[/cyan]",
                title="⚠️ Dependencies Missing",
                border_style="yellow",
            )
        )
        raise typer.Exit(1)

    # Display startup message
    console.print(
        Panel(
            f"[green]Starting Brain Researcher Orchestrator[/green]\n\n"
            f"[cyan]Service:[/cyan] Orchestrator API Gateway\n"
            f"[cyan]Port:[/cyan] {port}\n"
            f"[cyan]Host:[/cyan] {host}\n"
            f"[cyan]Workers:[/cyan] {workers}\n"
            f"[cyan]Auto-reload:[/cyan] {'Yes' if reload else 'No'}\n\n"
            "[dim]Orchestrator coordinates between Agent, BR-KG, and other services[/dim]",
            title="🚀 Orchestrator Service",
            border_style="green",
        )
    )

    # Build uvicorn command
    # Launch using module path so relative imports in orchestrator package work
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "brain_researcher.services.orchestrator.main_enhanced:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if reload:
        cmd.append("--reload")
    else:
        cmd.extend(["--workers", str(workers)])

    env = os.environ.copy()
    # Service URLs for orchestrator to connect to
    env["AGENT_URL"] = env.get("AGENT_URL", "http://localhost:8000")
    env["BR_KG_URL"] = env.get("BR_KG_URL", "http://localhost:5000")
    env["NICLIP_URL"] = env.get("NICLIP_URL", "http://localhost:8001")

    console.print(f"\n[dim]Running command: {' '.join(cmd)}[/dim]\n")
    console.print("[yellow]Orchestrator API will be available at:[/yellow]")
    console.print(f"  • Local: http://localhost:{port}")
    console.print(f"  • Network: http://{host}:{port}")
    console.print(f"  • Health: http://localhost:{port}/health")
    console.print(f"  • Docs: http://localhost:{port}/docs")
    console.print("\n[yellow]Connecting to services:[/yellow]")
    console.print(f"  • Agent: {env['AGENT_URL']}")
    console.print(f"  • BR-KG: {env['BR_KG_URL']}")
    console.print(f"  • NICLIP: {env['NICLIP_URL']}")
    console.print("\n[dim]Press Ctrl+C to stop the server[/dim]\n")

    try:
        # Run from the repo root so dotenv discovery and relative state/workspace
        # paths resolve to the local checkout rather than the package subdir.
        subprocess.run(cmd, cwd=repo_root, env=env, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to start orchestrator: {e}[/red]")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        console.print("\n[yellow]Orchestrator service stopped[/yellow]")
        raise typer.Exit(0) from None


if __name__ == "__main__":
    typer.run(launch_orchestrator)
