"""Database management commands for Brain Researcher CLI."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Database management commands")
console = Console()


def _get_neo4j_db():
    try:
        from brain_researcher.services.br_kg.db.bootstrap import get_db

        return get_db(require_neo4j=True)
    except Exception as exc:
        console.print(
            "[red]Neo4j is required for database commands.[/red] "
            "Set NEO4J_URI/NEO4J_PASSWORD and try again."
        )
        console.print(f"[dim]{exc}[/dim]")
        raise typer.Exit(1)


@app.command()
def init(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force recreation of existing database"
    ),
):
    """Initialize the BR-KG database."""
    try:
        from brain_researcher.services.br_kg.db.schema import (
            setup_schema,
        )

        console.print("[bold blue]Initializing Neo4j schema...[/bold blue]")

        if force:
            console.print(
                "[yellow]--force is not supported for Neo4j schema initialization.[/yellow]"
            )

        db = _get_neo4j_db()
        setup_schema(db)
        db.close()
        console.print("[green]✓[/green] Neo4j schema initialized successfully")

    except ImportError:
        console.print("[red]Error: Database initialization module not found[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error initializing database: {e}")
        raise typer.Exit(1)


@app.command()
def validate(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed validation results"
    ),
):
    """Validate database contents and integrity."""
    try:
        console.print("[bold blue]Validating Neo4j connectivity...[/bold blue]")

        db = _get_neo4j_db()
        stats = db.get_stats()
        db.close()
        console.print("[green]✓[/green] Neo4j reachable")
        console.print(f"[dim]Nodes: {stats.get('total_nodes', 0)}[/dim]")
        console.print(f"[dim]Relationships: {stats.get('total_relationships', 0)}[/dim]")

    except ImportError:
        console.print("[red]Error: Validation module not found[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status(
):
    """Check database status and statistics."""
    try:
        console.print("[bold blue]Neo4j Status[/bold blue]")

        db = _get_neo4j_db()
        stats = db.get_stats()
        db.close()

        table = Table(title="Neo4j Database Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta", justify="right")

        table.add_row("Total Nodes", str(stats.get("total_nodes", 0)))
        table.add_row("Total Relationships", str(stats.get("total_relationships", 0)))
        table.add_row("Node Labels", str(len(stats.get("node_labels", []))))
        table.add_row("Relationship Types", str(len(stats.get("relationship_types", []))))

        console.print(table)
    except Exception as e:
        console.print(f"[red]Error checking status: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def optimize(
    vacuum: bool = typer.Option(
        True, "--vacuum/--no-vacuum", help="Run VACUUM to reclaim space"
    ),
    analyze: bool = typer.Option(
        True, "--analyze/--no-analyze", help="Run ANALYZE to update statistics"
    ),
):
    """Optimize database performance."""
    try:
        console.print(
            "[yellow]Optimization is not supported for Neo4j via this CLI. "
            "Use Neo4j admin tools instead.[/yellow]"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Optimization error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def merge(
    source_dbs: list[Path] = typer.Argument(..., help="Source database paths to merge"),
    target_db: Path = typer.Option(..., "--target", "-t", help="Target database path"),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="Create backup before merging"
    ),
):
    """Merge multiple databases into one."""
    try:
        console.print(
            "[yellow]SQLite merge is deprecated. Use Neo4j admin tooling "
            "for backup/restore instead.[/yellow]"
        )
        raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Merge error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
