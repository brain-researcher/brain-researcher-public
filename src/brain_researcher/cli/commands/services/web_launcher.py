"""Launcher for the Web UI service."""

import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from brain_researcher.config.paths import get_apps_root

console = Console()


def _get_web_ui_dir() -> Path:
    """Return the canonical Next.js app directory."""
    return get_apps_root() / "web-ui"


def launch_web_service(
    host: str = "localhost",
    port: int = 3000,
    verbose: bool = False,
):
    """Launch the Next.js web UI service.

    Args:
        host: Host to bind to
        port: Port to run the service on
        verbose: Enable verbose output
    """
    # Get the canonical web UI directory
    web_ui_dir = _get_web_ui_dir()

    if not web_ui_dir.exists():
        console.print(f"[red]Web UI directory not found: {web_ui_dir}[/red]")
        console.print(
            "[yellow]Please ensure the web UI is properly installed.[/yellow]"
        )
        sys.exit(1)

    # Check if package.json exists
    package_json = web_ui_dir / "package.json"
    if not package_json.exists():
        console.print(f"[red]package.json not found in {web_ui_dir}[/red]")
        console.print("[yellow]The web UI appears to be incomplete.[/yellow]")
        sys.exit(1)

    # Check if node_modules exists, if not, install dependencies
    node_modules = web_ui_dir / "node_modules"
    if not node_modules.exists():
        console.print(
            "[yellow]Installing dependencies (this may take a few minutes)...[/yellow]"
        )
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=str(web_ui_dir),
                check=True,
                capture_output=not verbose,
            )
            console.print("[green]✓ Dependencies installed[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to install dependencies: {e}[/red]")
            sys.exit(1)
        except FileNotFoundError:
            console.print("[red]npm not found. Please install Node.js and npm.[/red]")
            console.print("[dim]Visit: https://nodejs.org/[/dim]")
            sys.exit(1)

    # Start the Next.js development server
    console.print(f"[cyan]Starting Web UI on http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop the server[/dim]\n")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOSTNAME"] = host

    try:
        # Use npm run dev for development
        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", str(port), "-H", host],
            cwd=str(web_ui_dir),
            env=env,
            stdout=subprocess.PIPE if not verbose else None,
            stderr=subprocess.PIPE if not verbose else None,
            text=True,
        )

        # If not verbose, consume and display filtered output
        if not verbose:
            console.print(f"[green]✓ Web UI started on http://{host}:{port}[/green]")
            console.print(
                "[dim]Server logs suppressed. Use --verbose to see full output.[/dim]"
            )

            # Keep the process running
            try:
                process.wait()
            except KeyboardInterrupt:
                console.print("\n[yellow]Shutting down Web UI...[/yellow]")
                process.terminate()
                process.wait(timeout=5)
                console.print("[green]✓ Web UI stopped[/green]")
        else:
            # In verbose mode, let output stream naturally
            process.wait()

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to start Web UI: {e}[/red]")
        sys.exit(1)
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js and npm.[/red]")
        console.print("[dim]Visit: https://nodejs.org/[/dim]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Web UI stopped by user[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    launch_web_service()
