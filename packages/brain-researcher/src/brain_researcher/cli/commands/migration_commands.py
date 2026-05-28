"""
BR-KG Migration CLI Commands.
"""

import typer
from pathlib import Path
from typing import Optional

from brain_researcher.services.neurokg.migrations.cli import cli as migration_cli

app = typer.Typer(name="migrate", help="Database migration commands")


@app.command()
def create(name: str):
    """Create a new migration file."""
    migration_cli(["create", name])


@app.command()
def up(target: Optional[str] = None):
    """Apply pending migrations."""
    args = ["migrate"]
    if target:
        args.extend(["--target", target])
    migration_cli(args)


@app.command()
def down(steps: int = 1):
    """Rollback migrations."""
    migration_cli(["rollback", "--steps", str(steps)])


@app.command()
def status():
    """Show migration status."""
    migration_cli(["status"])


@app.command()
def verify():
    """Verify migration checksums."""
    migration_cli(["verify"])


@app.command()
def list():
    """List all migrations."""
    migration_cli(["list"])


if __name__ == "__main__":
    app()