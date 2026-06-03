"""BR-KG service launcher for the Brain Researcher CLI."""

import os
import sys

from rich.console import Console

from brain_researcher.cli.utils.port_manager import port_manager
from brain_researcher.config.paths import get_data_root

console = Console()


def _ensure_neo4j_env() -> str:
    """Ensure Neo4j credentials are available before starting the service."""
    uri = os.environ.get("NEO4J_URI")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not password:
        console.print(
            "[red]Neo4j is required. Set NEO4J_URI and NEO4J_PASSWORD before launching the service.[/red]"
        )
        sys.exit(1)
    return uri


def launch_kg_service(
    host: str = "127.0.0.1",
    port: int = 5000,
    verbose: bool = False,
    auto_port: bool = True,
):
    """Launch the BR-KG service.

    Args:
        host: Host to bind the service to
        port: Port to bind the service to
        verbose: Enable verbose output
        auto_port: Automatically handle port conflicts
    """
    try:
        # Handle port conflicts
        if auto_port:
            # Check if auto mode is set in environment
            auto_mode = os.environ.get("PORT_CONFLICT_MODE", "prompt")
            port = port_manager.handle_port_conflict(
                service="kg", requested_port=port, host=host, auto_mode=auto_mode
            )
        elif not port_manager.check_port(port, host):
            console.print(f"[red]Error: Port {port} is already in use[/red]")
            console.print(
                "[yellow]Use --auto-port flag to handle conflicts automatically[/yellow]"
            )
            sys.exit(1)

        # Set environment variables
        os.environ["FLASK_APP"] = "brain_researcher.services.br_kg.app:app"
        os.environ["PORT"] = str(port)

        # Ensure Neo4j credentials are present
        _ensure_neo4j_env()

        # Optional GLM FitLins SQLite (legacy) path for specific endpoints
        db_path = os.environ.get("BR_KG_GLMFITLINS_DB_PATH")
        if not db_path:
            # Try to find default database
            default_db = get_data_root() / "br_kg" / "db" / "br_kg_glmfitlins.db"
            if default_db.exists():
                os.environ["BR_KG_GLMFITLINS_DB_PATH"] = str(default_db)
                if verbose:
                    console.print(f"[dim]Using database: {default_db}[/dim]")
            else:
                console.print(
                    "[yellow]GLM FitLins database not found; related endpoints may be disabled.[/yellow]"
                )

        console.print(f"[green]Starting BR-KG service on {host}:{port}...[/green]")
        console.print(f"[dim]Health: http://{host}:{port}/health[/dim]")
        console.print(f"[dim]Stats:  http://{host}:{port}/api/statistics[/dim]")
        console.print(f"[dim]Graph:  http://{host}:{port}/api/graph[/dim]")
        console.print(f"[dim]GraphQL: http://{host}:{port}/graphql[/dim]")

        # Import and run the Flask app
        from brain_researcher.services.br_kg.app import app

        # Run the Flask development server
        app.run(
            host=host,
            port=port,
            debug=verbose,
            use_reloader=False,  # Disable reloader to avoid issues with CLI
        )

    except ImportError as e:
        console.print(f"[red]Error: Could not import BR-KG service: {e}[/red]")
        console.print(
            "[yellow]Make sure the BR-KG dependencies are installed:[/yellow]"
        )
        console.print("  pip install -e '.[br-kg]'")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error starting BR-KG service: {e}[/red]")
        if verbose:
            import traceback

            console.print(traceback.format_exc())
        sys.exit(1)


def launch_kg_service_production(
    host: str = "0.0.0.0",
    port: int = 5000,
    workers: int = 4,
    verbose: bool = False,
):
    """Launch the BR-KG service using Gunicorn for production.

    Args:
        host: Host to bind the service to
        port: Port to bind the service to
        workers: Number of worker processes
        verbose: Enable verbose output
    """
    try:
        import subprocess

        # Set environment variables
        os.environ["PORT"] = str(port)

        # Ensure Neo4j credentials are present
        _ensure_neo4j_env()

        # Check for database path
        db_path = os.environ.get("BR_KG_GLMFITLINS_DB_PATH")
        if not db_path:
            default_db = get_data_root() / "br_kg" / "db" / "br_kg_glmfitlins.db"
            if default_db.exists():
                os.environ["BR_KG_GLMFITLINS_DB_PATH"] = str(default_db)
            elif verbose:
                console.print(
                    "[yellow]GLM FitLins database not found; related endpoints may be disabled.[/yellow]"
                )

        console.print(
            f"[green]Starting BR-KG service (production) on {host}:{port}...[/green]"
        )
        console.print(f"[dim]Workers: {workers}[/dim]")

        # Run with gunicorn
        cmd = [
            "gunicorn",
            "brain_researcher.services.br_kg.app:app",
            f"--bind={host}:{port}",
            f"--workers={workers}",
            "--worker-class=sync",
            "--timeout=120",
            "--access-logfile=-" if verbose else "--access-logfile=/dev/null",
            "--error-logfile=-",
        ]

        if verbose:
            cmd.append("--log-level=debug")
        else:
            cmd.append("--log-level=info")

        subprocess.run(cmd)

    except ImportError:
        console.print("[red]Error: Gunicorn not installed.[/red]")
        console.print("[yellow]For production deployment, install gunicorn:[/yellow]")
        console.print("  pip install gunicorn")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error starting BR-KG service: {e}[/red]")
        sys.exit(1)
