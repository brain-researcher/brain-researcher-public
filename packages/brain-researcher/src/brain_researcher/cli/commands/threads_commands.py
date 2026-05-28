"""
Lightweight helpers for threads endpoints.
"""

import os
import uuid

import httpx
import typer
from rich.console import Console

from brain_researcher.cli.utils.auth import get_token

console = Console()
app = typer.Typer(help="Thread utilities (history & new id)")


def _agent_base() -> str:
    return os.environ.get("AGENT_URL", "http://127.0.0.1:8000").rstrip("/")


def _agent(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{_agent_base()}{path}"


@app.command("new")
def new_thread() -> None:
    tid = str(uuid.uuid4())
    console.print(f"[green]{tid}[/green] (use with --thread or ctx.thread_id)")


@app.command("messages")
def messages(thread_id: str = typer.Argument(...)) -> None:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = _agent(f"/api/threads/{thread_id}/messages")
    with httpx.Client(timeout=15.0) as client:
        res = client.get(url, headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    console.print_json(data=res.json())
