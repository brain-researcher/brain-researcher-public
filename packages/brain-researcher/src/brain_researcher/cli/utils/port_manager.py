"""Port management utilities for Brain Researcher services."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

console = Console()


@dataclass
class ProcessInfo:
    """Information about a process using a port."""

    pid: int
    name: str
    cmdline: str
    create_time: float
    username: str
    port: int


class PortManager:
    """Manage port allocation and conflicts for active services."""

    PORT_RANGES = {
        "default": (5000, 5099),
        "instance_a": (5100, 5199),
        "instance_b": (5200, 5299),
        "testing": (5300, 5399),
    }
    DEFAULT_PORTS = {
        "web": 3000,
        "orchestrator": 3001,
        "kg": 5000,
        "mcp": 7000,
        "agent": 8000,
    }
    SERVICE_ENV_VARS = {
        "web": "WEB_PORT",
        "orchestrator": "ORCHESTRATOR_PORT",
        "kg": "KG_PORT",
        "mcp": "BR_MCP_PORT",
        "agent": "AGENT_PORT",
    }

    def __init__(self) -> None:
        self.config_file = Path.home() / ".brain_researcher" / "ports.json"
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.custom_ports: dict[str, int] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load port configuration from file."""
        if not self.config_file.exists():
            self.custom_ports = {}
            return

        try:
            with self.config_file.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self.custom_ports = {}
            return

        if isinstance(loaded, dict):
            self.custom_ports = {
                str(key): int(value)
                for key, value in loaded.items()
                if isinstance(value, int | str) and str(value).isdigit()
            }
        else:
            self.custom_ports = {}

    def save_config(self) -> None:
        """Save port configuration to file."""
        with self.config_file.open("w", encoding="utf-8") as handle:
            json.dump(self.custom_ports, handle, indent=2, sort_keys=True)

    def check_port(self, port: int, host: str = "127.0.0.1") -> bool:
        """Return True when the port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                return sock.connect_ex((host, port)) != 0
        except OSError:
            return False

    def find_available_port(
        self,
        start_port: int,
        max_attempts: int = 100,
        host: str = "127.0.0.1",
    ) -> int | None:
        """Find an available port starting from ``start_port``."""
        for offset in range(max_attempts):
            candidate = start_port + offset
            if self.check_port(candidate, host):
                return candidate
        return None

    def get_process_on_port(self, port: int) -> ProcessInfo | None:
        """Get information about the process listening on ``port``."""
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue
            if conn.laddr.port != port or conn.pid is None:
                continue
            try:
                process = psutil.Process(conn.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
            return ProcessInfo(
                pid=conn.pid,
                name=process.name(),
                cmdline=" ".join(process.cmdline()),
                create_time=process.create_time(),
                username=process.username(),
                port=port,
            )
        return None

    def kill_process_on_port(self, port: int, force: bool = False) -> bool:
        """Kill the process listening on ``port``."""
        process_info = self.get_process_on_port(port)
        if not process_info:
            return False

        if not force:
            console.print(f"\n[yellow]Process using port {port}:[/yellow]")
            console.print(f"  PID: {process_info.pid}")
            console.print(f"  Name: {process_info.name}")
            console.print(f"  Command: {process_info.cmdline[:100]}...")
            console.print(f"  User: {process_info.username}")
            console.print(f"  Started: {time.ctime(process_info.create_time)}")
            if not Confirm.ask("\n[red]Kill this process?[/red]"):
                return False

        try:
            process = psutil.Process(process_info.pid)
            process.terminate()
            time.sleep(1)
            if process.is_running():
                process.kill()
            console.print(f"[green]✓ Killed process {process_info.pid}[/green]")
            return True
        except (psutil.Error, OSError) as err:
            console.print(f"[red]Failed to kill process: {err}[/red]")
            return False

    def handle_port_conflict(
        self,
        service: str,
        requested_port: int,
        host: str = "127.0.0.1",
        auto_mode: str = "prompt",
    ) -> int:
        """Resolve a port conflict interactively or with a simple policy."""
        if self.check_port(requested_port, host):
            return requested_port

        process_info = self.get_process_on_port(requested_port)
        console.print(f"\n[yellow]⚠ Port {requested_port} is already in use[/yellow]")
        if process_info:
            console.print(f"[dim]Process: {process_info.name} (PID: {process_info.pid})[/dim]")
            console.print(f"[dim]Command: {process_info.cmdline[:80]}...[/dim]")

        if auto_mode == "auto_increment":
            new_port = self.find_available_port(requested_port + 1, host=host)
            if new_port is None:
                console.print("[red]No available ports found[/red]")
                sys.exit(1)
            console.print(f"[green]→ Using port {new_port} instead[/green]")
            return new_port

        if auto_mode == "kill":
            if self.kill_process_on_port(requested_port, force=True):
                time.sleep(1)
                return requested_port
            console.print("[red]Failed to kill process[/red]")
            sys.exit(1)

        if auto_mode == "fail":
            console.print("[red]Exiting due to port conflict[/red]")
            sys.exit(1)

        console.print("\n[bold]Options:[/bold]")
        console.print("1. Kill the existing process")
        console.print("2. Use a different port")
        console.print("3. Cancel")

        choice = Prompt.ask("Choose an option", choices=["1", "2", "3"], default="2")
        if choice == "1":
            if self.kill_process_on_port(requested_port):
                time.sleep(1)
                return requested_port
            console.print("[red]Failed to kill process, trying different port[/red]")
            choice = "2"

        if choice == "2":
            suggested_port = self.find_available_port(requested_port + 1, host=host)
            if suggested_port:
                console.print(f"[dim]Suggested port: {suggested_port}[/dim]")

            new_port = IntPrompt.ask(
                "Enter port number",
                default=suggested_port or requested_port + 1,
            )
            if not self.check_port(new_port, host):
                console.print(f"[red]Port {new_port} is also in use![/red]")
                return self.handle_port_conflict(service, new_port, host, auto_mode)

            self.custom_ports[service] = new_port
            self.save_config()
            return new_port

        console.print("[yellow]Cancelled[/yellow]")
        sys.exit(0)

    def get_service_port(
        self,
        service: str,
        default_port: int | None = None,
        instance: str = "default",
    ) -> int:
        """Get the configured port for a service."""
        del instance

        env_var = self.SERVICE_ENV_VARS.get(service, f"{service.upper()}_PORT")
        if env_var in os.environ:
            try:
                return int(os.environ[env_var])
            except ValueError:
                pass

        if service in self.custom_ports:
            return self.custom_ports[service]
        if default_port is not None:
            return default_port
        return self.DEFAULT_PORTS.get(service, 5000)

    def list_all_services(self) -> list[ProcessInfo]:
        """List active services on the default service ports."""
        services: list[ProcessInfo] = []
        for port in sorted(self.DEFAULT_PORTS.values()):
            process_info = self.get_process_on_port(port)
            if process_info:
                services.append(process_info)
        return services

    def display_service_status(self) -> None:
        """Display a table of all running services."""
        services = self.list_all_services()
        if not services:
            console.print("[yellow]No Brain Researcher services are currently running[/yellow]")
            return

        table = Table(title="Running Brain Researcher Services")
        table.add_column("Service", style="cyan")
        table.add_column("Port", style="green")
        table.add_column("PID", style="yellow")
        table.add_column("Started", style="magenta")
        table.add_column("User", style="blue")

        for service in services:
            cmdline = service.cmdline.lower()
            if service.port == 3000 or "next" in cmdline:
                service_type = "Web UI"
            elif service.port == 3001 or "orchestrator" in cmdline:
                service_type = "Orchestrator"
            elif service.port == 5000 or "neurokg" in cmdline:
                service_type = "BR-KG"
            elif service.port == 7000 or "services.mcp.server" in cmdline:
                service_type = "MCP"
            elif service.port == 8000 or "agent" in cmdline:
                service_type = "Agent"
            else:
                service_type = "Unknown"

            table.add_row(
                service_type,
                str(service.port),
                str(service.pid),
                time.strftime("%H:%M:%S", time.localtime(service.create_time)),
                service.username,
            )

        console.print(table)

    def stop_service(self, service_name: str, force: bool = False) -> bool:
        """Stop a running service by name."""
        port = self.DEFAULT_PORTS.get(service_name)
        if port is None:
            console.print(f"[red]Unknown service: {service_name}[/red]")
            return False

        process_info = self.get_process_on_port(port)
        if not process_info:
            console.print(f"[yellow]Service {service_name} is not running[/yellow]")
            return False

        return self.kill_process_on_port(port, force=force)

    def restart_service(self, service_name: str, launcher_func=None) -> bool:
        """Restart a service using an optional launcher callback."""
        self.stop_service(service_name, force=True)
        time.sleep(2)

        if launcher_func is None:
            console.print(f"[yellow]Please run 'br serve {service_name}' to start the service[/yellow]")
            return False

        launcher_func()
        return True


port_manager = PortManager()
