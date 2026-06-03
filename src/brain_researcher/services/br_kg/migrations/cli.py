"""
CLI for database migrations.
Provides commands for creating, running, and managing migrations.
"""

import json
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from brain_researcher.services.br_kg.migrations import MigrationManager

console = Console()


@click.group()
def cli():
    """BR-KG Database Migration Tool"""
    pass


@cli.command()
@click.argument("name")
@click.option(
    "--dir", "-d", "migrations_dir", default="migrations", help="Migrations directory"
)
def create(name: str, migrations_dir: str):
    """
    Create a new migration file.

    Example:
        br_kg-migrate create add_users_table
    """
    manager = MigrationManager(migrations_dir=migrations_dir)

    # Sanitize name
    name = name.lower().replace(" ", "_").replace("-", "_")

    # Create migration
    file_path = manager.create_migration(name)

    console.print(f"[green]✓[/green] Created migration: {file_path}")
    console.print("\nEdit the file to implement your migration:")

    # Show template
    with open(file_path) as f:
        content = f.read()
        syntax = Syntax(content, "python", line_numbers=True, theme="monokai")
        console.print(syntax)


@cli.command()
@click.option("--target", "-t", help="Target version to migrate to")
@click.option("--db", "-d", "db_path", default="br_kg_graph.db", help="Database path")
@click.option(
    "--dir", "migrations_dir", default="migrations", help="Migrations directory"
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
def migrate(target: str | None, db_path: str, migrations_dir: str, dry_run: bool):
    """
    Run pending migrations.

    Examples:
        br_kg-migrate migrate                    # Run all pending
        br_kg-migrate migrate --target 001       # Migrate to version 001
        br_kg-migrate migrate --dry-run          # Preview changes
    """
    manager = MigrationManager(migrations_dir=migrations_dir, db_path=db_path)

    # Get status
    status = manager.status()

    if dry_run:
        console.print("\n[yellow]DRY RUN MODE - No changes will be made[/yellow]\n")

    # Show current status
    console.print(
        Panel(
            f"Database: {status['database']}\n"
            f"Applied: {status['applied']}\n"
            f"Pending: {status['pending']}\n"
            f"Total: {status['total']}",
            title="Migration Status",
            border_style="blue",
        )
    )

    if status["pending"] == 0:
        console.print("\n[green]✓[/green] All migrations are up to date!")
        return

    # Show pending migrations
    console.print("\n[bold]Pending Migrations:[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Version", style="cyan")
    table.add_column("Description")

    for migration in status["pending_migrations"]:
        if target and migration["version"] > target:
            break
        table.add_row(migration["version"], migration["description"])

    console.print(table)

    if dry_run:
        return

    # Confirm
    if not click.confirm("\nDo you want to apply these migrations?"):
        console.print("[yellow]Aborted[/yellow]")
        return

    # Run migrations
    console.print("\n[bold]Applying migrations...[/bold]")

    with console.status("[bold green]Running migrations...") as status:
        success = manager.migrate(target=target)

    if success:
        console.print("\n[green]✓[/green] All migrations applied successfully!")
    else:
        console.print("\n[red]✗[/red] Migration failed! Check logs for details.")
        raise click.Exit(1)


@cli.command()
@click.option("--steps", "-s", default=1, help="Number of migrations to rollback")
@click.option("--db", "-d", "db_path", default="br_kg_graph.db", help="Database path")
@click.option(
    "--dir", "migrations_dir", default="migrations", help="Migrations directory"
)
@click.option("--force", is_flag=True, help="Skip confirmation")
def rollback(steps: int, db_path: str, migrations_dir: str, force: bool):
    """
    Rollback last N migrations.

    Examples:
        br_kg-migrate rollback              # Rollback last migration
        br_kg-migrate rollback --steps 3    # Rollback last 3 migrations
    """
    manager = MigrationManager(migrations_dir=migrations_dir, db_path=db_path)

    # Get applied migrations
    status = manager.status()
    applied = status["applied_migrations"]

    if not applied:
        console.print("[yellow]No migrations to rollback[/yellow]")
        return

    # Show migrations to rollback
    to_rollback = applied[-steps:]

    console.print("\n[bold]Migrations to rollback:[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Version", style="cyan")
    table.add_column("Applied At")
    table.add_column("Status")

    for migration in to_rollback:
        applied_at = datetime.fromisoformat(migration["applied_at"]).strftime(
            "%Y-%m-%d %H:%M"
        )
        table.add_row(migration["version"], applied_at, migration["status"])

    console.print(table)

    # Confirm
    if not force:
        console.print("\n[red]WARNING: This will rollback database changes![/red]")
        if not click.confirm("Do you want to continue?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    # Rollback
    console.print("\n[bold]Rolling back migrations...[/bold]")

    with console.status("[bold yellow]Rolling back...") as status:
        success = manager.rollback(steps=steps)

    if success:
        console.print(
            f"\n[green]✓[/green] Rolled back {steps} migration(s) successfully!"
        )
    else:
        console.print("\n[red]✗[/red] Rollback failed! Check logs for details.")
        raise click.Exit(1)


@cli.command()
@click.option("--db", "-d", "db_path", default="br_kg_graph.db", help="Database path")
@click.option(
    "--dir", "migrations_dir", default="migrations", help="Migrations directory"
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(db_path: str, migrations_dir: str, as_json: bool):
    """
    Show migration status.

    Examples:
        br_kg-migrate status
        br_kg-migrate status --json
    """
    manager = MigrationManager(migrations_dir=migrations_dir, db_path=db_path)
    status = manager.status()

    if as_json:
        console.print(json.dumps(status, indent=2))
        return

    # Show summary
    console.print(
        Panel(
            f"Database: {status['database']}\n"
            f"Applied: {status['applied']}\n"
            f"Pending: {status['pending']}\n"
            f"Total: {status['total']}",
            title="Migration Status",
            border_style="blue",
        )
    )

    # Show applied migrations
    if status["applied_migrations"]:
        console.print("\n[bold]Applied Migrations:[/bold]")
        table = Table(show_header=True, header_style="bold green")
        table.add_column("Version", style="cyan")
        table.add_column("Applied At")
        table.add_column("Execution Time")
        table.add_column("Status")

        for migration in status["applied_migrations"]:
            applied_at = datetime.fromisoformat(migration["applied_at"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            exec_time = f"{migration['execution_time']:.2f}s"

            status_style = "green" if migration["status"] == "applied" else "red"

            table.add_row(
                migration["version"],
                applied_at,
                exec_time,
                f"[{status_style}]{migration['status']}[/{status_style}]",
            )

        console.print(table)

    # Show pending migrations
    if status["pending_migrations"]:
        console.print("\n[bold]Pending Migrations:[/bold]")
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Version", style="cyan")
        table.add_column("Description")

        for migration in status["pending_migrations"]:
            table.add_row(migration["version"], migration["description"])

        console.print(table)


@cli.command()
@click.option("--db", "-d", "db_path", default="br_kg_graph.db", help="Database path")
@click.option(
    "--dir", "migrations_dir", default="migrations", help="Migrations directory"
)
def verify(db_path: str, migrations_dir: str):
    """
    Verify migration checksums.

    Checks if any applied migrations have been modified.
    """
    manager = MigrationManager(migrations_dir=migrations_dir, db_path=db_path)

    console.print("[bold]Verifying migration checksums...[/bold]\n")

    results = manager.runner.verify_checksums(manager.migrations)

    if not results:
        console.print("[yellow]No migrations to verify[/yellow]")
        return

    # Show results
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Version", style="cyan")
    table.add_column("Status")

    all_valid = True
    for version, is_valid in results:
        if is_valid:
            table.add_row(version, "[green]✓ Valid[/green]")
        else:
            table.add_row(version, "[red]✗ Modified[/red]")
            all_valid = False

    console.print(table)

    if all_valid:
        console.print("\n[green]✓[/green] All checksums are valid!")
    else:
        console.print(
            "\n[red]✗[/red] Some migrations have been modified after being applied!"
        )
        console.print(
            "[yellow]This could cause issues. Consider creating new migrations instead.[/yellow]"
        )
        raise click.Exit(1)


@cli.command()
@click.option("--db", "-d", "db_path", default="br_kg_graph.db", help="Database path")
@click.option(
    "--dir", "migrations_dir", default="migrations", help="Migrations directory"
)
@click.option("--force", is_flag=True, help="Skip confirmation")
def reset(db_path: str, migrations_dir: str, force: bool):
    """
    Reset all migrations (DANGEROUS!).

    This will rollback ALL migrations, potentially destroying data.
    """
    manager = MigrationManager(migrations_dir=migrations_dir, db_path=db_path)

    # Get status
    status = manager.status()

    if status["applied"] == 0:
        console.print("[yellow]No migrations to reset[/yellow]")
        return

    console.print("[bold red]⚠️  WARNING ⚠️[/bold red]")
    console.print("This will rollback ALL migrations and potentially destroy data!")
    console.print(f"Migrations to rollback: {status['applied']}")

    if not force:
        console.print("\n[red]This action cannot be undone![/red]")
        confirm = click.prompt("Type 'RESET' to confirm", type=str)
        if confirm != "RESET":
            console.print("[yellow]Aborted[/yellow]")
            return

    # Reset
    console.print("\n[bold]Resetting all migrations...[/bold]")

    with console.status("[bold red]Resetting...") as status:
        success = manager.reset()

    if success:
        console.print("\n[green]✓[/green] All migrations have been reset!")
    else:
        console.print("\n[red]✗[/red] Reset failed! Check logs for details.")
        raise click.Exit(1)


if __name__ == "__main__":
    cli()
