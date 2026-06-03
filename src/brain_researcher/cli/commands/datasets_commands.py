"""
Friendly dataset search/detail commands hitting Agent datasets API.
"""

import os

import httpx
import typer
from rich.console import Console
from rich.table import Table

from brain_researcher.cli.utils.auth import get_token

console = Console()
app = typer.Typer(help="Dataset search & detail via Agent")


def _agent_base() -> str:
    return os.environ.get("AGENT_URL", "http://127.0.0.1:8000").rstrip("/")


def _agent(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{_agent_base()}{path}"


@app.command("search")
def search(
    query: str = typer.Argument("", help="Search term"),
    limit: int = typer.Option(5, "--limit"),
    modality: list[str] = typer.Option([], "--modality"),
) -> None:
    payload = {"query": query, "limit": limit}
    if modality:
        payload["modalities"] = modality
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=20.0) as client:
        res = client.post(_agent("/api/datasets/search"), json=payload, headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    data = res.json()
    results = data.get("results", [])
    table = Table(title=f"Datasets (top {len(results)})", show_lines=False)
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("modalities")
    for item in results:
        table.add_row(
            item.get("id", ""),
            item.get("name", ""),
            ", ".join(item.get("modalities", [])),
        )
    console.print(table)


@app.command("get")
def get(dataset_id: str = typer.Argument(..., help="Dataset id")) -> None:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = _agent(f"/api/datasets/{dataset_id}")
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    console.print_json(data=res.json())
