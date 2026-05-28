"""
Store and show Agent bearer token for CLI commands.
"""

import typer
from rich.console import Console

from brain_researcher.cli.utils.auth import save_token, clear_token, TOKEN_PATH, get_token

console = Console()
app = typer.Typer(help="Auth helpers for Agent API (Bearer token)")


@app.command("login")
def login(token: str = typer.Argument(..., help="JWT or bearer token for Agent")) -> None:
    path = save_token(token)
    console.print(f"[green]Token saved[/green] to {path}")
    console.print("CLI will also read AGENT_TOKEN env if set.")


@app.command("show")
def show() -> None:
    token = get_token()
    if not token:
        console.print("[yellow]No token configured[/yellow]")
        return
    console.print(f"[green]Token in use:[/green] {token[:4]}... (length {len(token)})")
    console.print(f"Source: AGENT_TOKEN or {TOKEN_PATH}")


@app.command("logout")
def logout() -> None:
    clear_token()
    console.print("[green]Token cleared[/green]")
