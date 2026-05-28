"""Service management commands for Brain Researcher CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import requests
import typer
from rich.console import Console
from rich.prompt import Confirm

from brain_researcher.cli.commands.services.agent_launcher import launch_agent_service
from brain_researcher.cli.commands.services.kg_launcher import launch_kg_service
from brain_researcher.cli.commands.services.orchestrator_launcher import (
    launch_orchestrator,
)
from brain_researcher.cli.commands.services.web_launcher import launch_web_service
from brain_researcher.cli.utils.port_manager import port_manager
from brain_researcher.config.paths import get_package_root, get_repo_root

app = typer.Typer(help="Service management commands")
console = Console()

ACTIVE_SERVICES = ("web", "agent", "orchestrator", "kg", "mcp")
ACTIVE_STOP_ORDER = ("web", "mcp", "orchestrator", "agent", "kg")
LEGACY_CLEANUP_PORTS = (5001, 8001, 8050, 8080)


# ------------------------------
# Docker compose helper commands
# ------------------------------
docker_app = typer.Typer(help="Docker Compose helpers (Neo4j/API, etc.)")
app.add_typer(docker_app, name="docker")


def _ensure_docker() -> bool:
    if shutil.which("docker") is None:
        console.print("[red]Docker is not installed or not on PATH.[/red]")
        return False
    return True


def _compose(cmd: list[str], workdir: Path) -> int:
    try:
        res = subprocess.run(cmd, cwd=str(workdir), check=False)
        return res.returncode
    except FileNotFoundError:
        console.print("[red]docker compose not found. Install Docker or use 'docker-compose'.[/red]")
        return 1


@docker_app.command("start")
def docker_start(
    stack: str = typer.Argument("kg", help="Stack: kg | all"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for /health (kg)"),
    timeout: int = typer.Option(90, "--timeout", help="Wait timeout seconds"),
):
    """Start dockerized services (kg: Neo4j + API, all: root stack)."""
    if not _ensure_docker():
        raise typer.Exit(1)

    repo_root = get_repo_root()
    kg_dir = get_package_root() / "services" / "neurokg"

    if stack == "kg":
        console.print("[cyan]Starting Neo4j + BR-KG API (docker compose)...[/cyan]")
        code = _compose(["docker", "compose", "up", "-d", "neo4j", "api"], kg_dir)
        if code != 0:
            raise typer.Exit(code)
        console.print("[green]✓ Started kg stack[/green]")
        if wait:
            console.print("[dim]Waiting for API health at http://localhost:5000/health ...[/dim]")
            deadline = time.time() + max(5, timeout)
            healthy = False
            while time.time() < deadline:
                try:
                    response = requests.get("http://localhost:5000/health", timeout=3)
                    if response.ok and response.json().get("status") in {"healthy", "ok"}:
                        healthy = True
                        break
                except Exception:
                    pass
                time.sleep(3)
            if healthy:
                console.print("[green]✓ API healthy[/green]")
            else:
                console.print("[yellow]API health not confirmed within timeout[/yellow]")
        console.print("[dim]Seed with: br service docker seed[/dim]")
    elif stack == "all":
        console.print("[cyan]Starting all services from root compose...[/cyan]")
        code = _compose(["docker", "compose", "up", "-d"], repo_root)
        if code != 0:
            raise typer.Exit(code)
        console.print("[green]✓ Started all services[/green]")
    else:
        console.print("[red]Unknown stack. Use 'kg' or 'all'.[/red]")
        raise typer.Exit(1)


@docker_app.command("stop")
def docker_stop(stack: str = typer.Argument("kg", help="Stack: kg | all")):
    """Stop dockerized services."""
    if not _ensure_docker():
        raise typer.Exit(1)

    repo_root = get_repo_root()
    kg_dir = get_package_root() / "services" / "neurokg"

    if stack == "kg":
        console.print("[cyan]Stopping kg stack...[/cyan]")
        code = _compose(["docker", "compose", "down"], kg_dir)
        if code != 0:
            raise typer.Exit(code)
        console.print("[green]✓ Stopped kg stack[/green]")
    elif stack == "all":
        console.print("[cyan]Stopping all services...[/cyan]")
        code = _compose(["docker", "compose", "down"], repo_root)
        if code != 0:
            raise typer.Exit(code)
        console.print("[green]✓ Stopped all services[/green]")
    else:
        console.print("[red]Unknown stack. Use 'kg' or 'all'.[/red]")
        raise typer.Exit(1)


@docker_app.command("status")
def docker_status(stack: str = typer.Argument("kg", help="Stack: kg | all")):
    """Show docker compose status."""
    if not _ensure_docker():
        raise typer.Exit(1)
    repo_root = get_repo_root()
    workdir = get_package_root() / "services" / "neurokg" if stack == "kg" else repo_root
    _compose(["docker", "compose", "ps"], workdir)


@docker_app.command("logs")
def docker_logs(
    stack: str = typer.Argument("kg", help="Stack: kg | all"),
    follow: bool = typer.Option(False, "--follow", "-f"),
):
    """Show docker compose logs (kg or all)."""
    if not _ensure_docker():
        raise typer.Exit(1)
    repo_root = get_repo_root()
    workdir = get_package_root() / "services" / "neurokg" if stack == "kg" else repo_root
    args = ["docker", "compose", "logs"] + (["-f"] if follow else [])
    _compose(args, workdir)


@docker_app.command("seed")
def docker_seed():
    """Seed the Neo4j/SQLite DB using the API container (kg stack)."""
    if not _ensure_docker():
        raise typer.Exit(1)
    kg_dir = get_package_root() / "services" / "neurokg"
    console.print("[cyan]Seeding demo data via API container...[/cyan]")
    code = _compose(
        ["docker", "compose", "exec", "-T", "api", "python", "-m", "scripts.seed_neo4j"],
        kg_dir,
    )
    if code != 0:
        raise typer.Exit(code)
    console.print("[green]✓ Seed complete[/green]")


def _service_choices() -> str:
    return ", ".join(ACTIVE_SERVICES)


def _launch_service(service: str, host: str, port: int) -> None:
    if service == "kg":
        launch_kg_service(host=host, port=port)
        return

    if service == "agent":
        launch_agent_service(host=host, port=port, verbose=False)
        return

    if service == "web":
        launch_web_service(host=host, port=port, verbose=False)
        return

    if service == "orchestrator":
        launch_orchestrator(host=host, port=port, reload=False)
        return

    if service == "mcp":
        script_path = get_repo_root() / "scripts" / "mcp" / "start_http_local.sh"
        env = os.environ.copy()
        env["BR_MCP_HOST"] = host
        env["BR_MCP_PORT"] = str(port)
        result = subprocess.run(
            ["bash", str(script_path)],
            cwd=str(get_repo_root()),
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise typer.Exit(result.returncode)
        return

    console.print(f"[red]Unknown service: {service}[/red]")
    raise typer.Exit(1)


@app.command()
def status():
    """Show status of all Brain Researcher services."""
    console.print("\n[bold cyan]Brain Researcher Service Status[/bold cyan]\n")
    port_manager.display_service_status()

    console.print("\n[dim]Tips:[/dim]")
    console.print("[dim]• Start a service: br serve <service>[/dim]")
    console.print("[dim]• Stop a service: br service stop <service>[/dim]")
    console.print("[dim]• Restart a service: br service restart <service>[/dim]")


@app.command()
def stop(
    service: str = typer.Argument(..., help=f"Service to stop: {_service_choices()}, or 'all'"),
    force: bool = typer.Option(False, "--force", "-f", help="Force stop without confirmation"),
):
    """Stop a running service."""
    if service == "all":
        console.print("[yellow]Stopping all active services...[/yellow]")
        if not force and not Confirm.ask("Stop all active services?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

        for svc in ACTIVE_STOP_ORDER:
            if port_manager.stop_service(svc, force=force):
                console.print(f"[green]✓ Stopped {svc}[/green]")
        return

    if service not in ACTIVE_SERVICES:
        console.print(f"[red]Unknown service: {service}[/red]")
        console.print(f"[dim]Available services: {_service_choices()}[/dim]")
        raise typer.Exit(1)

    if port_manager.stop_service(service, force=force):
        console.print(f"[green]✓ Service {service} stopped[/green]")
    else:
        console.print(f"[yellow]Service {service} was not running[/yellow]")


@app.command()
def restart(
    service: str = typer.Argument(..., help=f"Service to restart: {_service_choices()}"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int | None = typer.Option(None, "--port", "-p", help="Port to bind to"),
):
    """Restart a service."""
    if service not in ACTIVE_SERVICES:
        console.print(f"[red]Unknown service: {service}[/red]")
        console.print(f"[dim]Available services: {_service_choices()}[/dim]")
        raise typer.Exit(1)

    console.print(f"[yellow]Restarting {service} service...[/yellow]")
    port_manager.stop_service(service, force=True)
    console.print("[dim]Waiting for port to be released...[/dim]")
    time.sleep(2)

    resolved_port = port or port_manager.DEFAULT_PORTS[service]
    console.print(f"[green]Starting {service} on {host}:{resolved_port}...[/green]")
    _launch_service(service, host, resolved_port)


@app.command()
def ports():
    """List all ports used by Brain Researcher services."""
    console.print("\n[bold cyan]Port Configuration[/bold cyan]\n")

    console.print("[bold]Default Ports:[/bold]")
    for service, port in port_manager.DEFAULT_PORTS.items():
        status = "✓ Available" if port_manager.check_port(port) else "✗ In Use"
        color = "green" if "Available" in status else "red"
        console.print(f"  {service:12} : {port:5} [{color}]{status}[/{color}]")

    if port_manager.custom_ports:
        console.print("\n[bold]Custom Ports:[/bold]")
        for service, port in port_manager.custom_ports.items():
            console.print(f"  {service:12} : {port:5}")

    console.print("\n[bold]Environment Variables:[/bold]")
    for service, env_var in port_manager.SERVICE_ENV_VARS.items():
        if env_var in os.environ:
            console.print(f"  {env_var:18} : {os.environ[env_var]} [dim]({service})[/dim]")

    console.print("\n[dim]To set a custom port: export SERVICE_PORT=<port>[/dim]")
    console.print("[dim]Example: export AGENT_PORT=8000[/dim]")


@app.command()
def cleanup(
    force: bool = typer.Option(False, "--force", "-f", help="Force cleanup without confirmation"),
):
    """Clean up orphaned processes and ports."""
    console.print("[yellow]Searching for orphaned Brain Researcher processes...[/yellow]")

    orphaned = []
    ports_to_check = sorted(set(port_manager.DEFAULT_PORTS.values()) | set(LEGACY_CLEANUP_PORTS))
    for port in ports_to_check:
        process_info = port_manager.get_process_on_port(port)
        if process_info:
            orphaned.append(process_info)

    if not orphaned:
        console.print("[green]✓ No orphaned processes found[/green]")
        return

    console.print(f"\n[yellow]Found {len(orphaned)} orphaned process(es):[/yellow]")
    for proc in orphaned:
        console.print(f"  Port {proc.port}: {proc.name} (PID: {proc.pid})")

    if not force and not Confirm.ask("\n[red]Kill all orphaned processes?[/red]"):
        console.print("[yellow]Cancelled[/yellow]")
        return

    for proc in orphaned:
        if port_manager.kill_process_on_port(proc.port, force=True):
            console.print(f"[green]✓ Killed process on port {proc.port}[/green]")
        else:
            console.print(f"[red]✗ Failed to kill process on port {proc.port}[/red]")

    console.print("\n[green]Cleanup complete[/green]")


@app.command()
def logs(
    service: str = typer.Argument(..., help=f"Service to show logs for: {_service_choices()}"),
    lines: int = typer.Option(100, "--lines", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """Show logs for a service."""
    if service not in ACTIVE_SERVICES:
        console.print(f"[red]Unknown service: {service}[/red]")
        console.print(f"[dim]Available services: {_service_choices()}[/dim]")
        raise typer.Exit(1)

    log_path = get_repo_root() / "logs" / f"{service}.log"
    console.print(f"[yellow]Log viewing not yet implemented for {service}[/yellow]")
    console.print("[dim]Logs are typically found in:[/dim]")
    console.print(f"[dim]  {log_path}[/dim]")
    console.print(f"[dim]  tail -n {lines} {log_path}[/dim]")
    if follow:
        console.print(f"[dim]  tail -f {log_path}[/dim]")


if __name__ == "__main__":
    app()
