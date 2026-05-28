"""Agent service launcher for Brain Researcher CLI."""

import os
import signal
import socket
import subprocess
import sys
import time

from rich.console import Console

from brain_researcher.config.paths import get_package_root

console = Console()


def find_free_port(start_port: int, max_attempts: int = 100) -> int | None:
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return None


def check_port_available(host: str, port: int) -> bool:
    """Check if a port is available on the given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def wait_for_service(host: str, port: int, timeout: int = 30) -> bool:
    """Wait for an HTTP service to be accepting connections.

    Strategy:
    - First, try a TCP connect (fast signal that a listener is up)
    - Then, try GET /health with a short timeout; tolerate timeouts/errors
    """
    import socket as _socket
    import urllib.request

    start_time = time.time()
    base = f"http://{host}:{port}"

    while time.time() - start_time < timeout:
        # TCP probe first
        try:
            with _socket.create_connection((host, port), timeout=1):
                # Listener is up; optionally confirm HTTP quickly
                try:
                    with urllib.request.urlopen(f"{base}/health", timeout=1) as resp:
                        if 200 <= getattr(resp, "status", 200) < 500:
                            return True
                except Exception:
                    # If HTTP probe fails, but TCP is up, consider service started
                    return True
        except OSError:
            # No listener yet
            pass

        time.sleep(1)

    return False


def launch_agent_service(
    host: str = "127.0.0.1",
    port: int | None = None,
    verbose: bool = False,
) -> None:
    """Launch the Brain Researcher agent service.

    Args:
        host: Host to bind the agent service to
        port: Port for the agent service (default: 8000 or next available)
        verbose: Enable verbose output
    """
    agent_dir = get_package_root() / "services" / "agent"

    # Check if agent directory exists
    if not agent_dir.exists():
        console.print(
            f"[red]Error: Agent service directory not found at {agent_dir}[/red]"
        )
        sys.exit(1)

    # Find available port for agent
    if port is None:
        port = find_free_port(8000)
        if port is None:
            console.print(
                "[red]Error: Could not find an available port for agent service[/red]"
            )
            sys.exit(1)
    elif not check_port_available(host, port):
        console.print(f"[red]Error: Port {port} is already in use[/red]")
        sys.exit(1)

    # Set environment variables
    env = os.environ.copy()
    env["HOST"] = host
    env["PORT"] = str(port)
    # Flask shim reads AGENT_PORT; set it to keep compatibility
    env["AGENT_PORT"] = str(port)

    # Check for BR-KG API
    neurokg_url = env.get("NEUROKG_API_URL", "http://localhost:5000")
    try:
        import urllib.request

        with urllib.request.urlopen(f"{neurokg_url}/health", timeout=2) as response:
            if response.status == 200:
                console.print(f"[green]✓ BR-KG API found at {neurokg_url}[/green]")
    except Exception:
        console.print(f"[yellow]⚠ BR-KG API not found at {neurokg_url}[/yellow]")
        console.print(
            "[dim]  The agent will have limited functionality without BR-KG[/dim]"
        )

    # Start agent service
    console.print("\n[bold]Starting Brain Researcher Agent Service[/bold]")
    console.print(f"[dim]Host:[/dim] {host}:{port}")

    # Canonical agent runtime is the Flask HTTP service only. Web UI and
    # orchestrator are launched separately via their own entrypoints.
    agent_cmd = [
        sys.executable,
        "-m",
        "brain_researcher.services.agent.web_service",
    ]

    if verbose:
        agent_process = subprocess.Popen(agent_cmd, cwd=agent_dir, env=env)
    else:
        agent_process = subprocess.Popen(
            agent_cmd,
            cwd=agent_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    # Wait for agent to start
    console.print("[dim]Waiting for agent service to start...[/dim]")
    if wait_for_service(host, port):
        console.print(f"[green]✓ Agent API running at http://{host}:{port}[/green]")
    else:
        console.print("[red]✗ Agent service failed to start[/red]")
        # Try to surface recent stderr/stdout to help debugging
        try:
            # Give the process a moment to flush
            time.sleep(0.5)
            # Do not block indefinitely when reading pipes
            if agent_process.stderr:
                try:
                    err = agent_process.stderr.read().decode(errors="ignore")
                    if err:
                        tail = "\n".join(err.strip().splitlines()[-50:])
                        console.print("[dim]Agent stderr (last lines):[/dim]")
                        console.print(tail)
                except Exception:
                    pass
            if agent_process.stdout:
                try:
                    out = agent_process.stdout.read().decode(errors="ignore")
                    if out:
                        tail = "\n".join(out.strip().splitlines()[-20:])
                        console.print("[dim]Agent stdout (last lines):[/dim]")
                        console.print(tail)
                except Exception:
                    pass
        finally:
            agent_process.terminate()
        sys.exit(1)

    # Summary
    console.print("\n[bold green]Brain Researcher Agent is running![/bold green]")
    console.print(f"\n🔌 Agent API: http://{host}:{port}")
    console.print("\n[dim]Press Ctrl+C to stop[/dim]\n")

    # Handle shutdown
    def shutdown(signum, frame):
        console.print("\n[dim]Shutting down services...[/dim]")

        agent_process.terminate()
        try:
            agent_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            agent_process.kill()

        console.print("[green]Services stopped[/green]")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep running and monitor processes
    try:
        while True:
            # Check if agent is still running
            if agent_process.poll() is not None:
                console.print("[red]Agent process died unexpectedly![/red]")
                sys.exit(1)

            time.sleep(2)
    except KeyboardInterrupt:
        shutdown(None, None)
