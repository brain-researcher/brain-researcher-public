"""
Simple file helpers aligned with Web UI proxy.
"""

import os
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="Files API helpers (upload/list/download/delete)")

from brain_researcher.cli.utils.auth import get_token


def _agent_base() -> str:
    return os.environ.get("AGENT_URL", "http://127.0.0.1:8000").rstrip("/")


def _agent(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{_agent_base()}{path}"


@app.command("ls")
def files_ls() -> None:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=15.0) as client:
        res = client.get(_agent("/api/files"), headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    data = res.json()
    files = data if isinstance(data, list) else data.get("files", [])
    table = Table(title="Files", show_lines=False)
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("size")
    for f in files:
        table.add_row(
            str(f.get("id") or f.get("file_id")),
            f.get("file_name", ""),
            str(f.get("size_bytes", "")),
        )
    console.print(table)


@app.command("upload")
def files_upload(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=60.0) as client:
        with path.open("rb") as fh:
            res = client.post(
                _agent("/api/files/upload"),
                files={"file": (path.name, fh, "application/octet-stream")},
                headers=headers,
            )
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    console.print(f"[green]Uploaded[/green] {path.name}")


@app.command("download")
def files_download(
    file_id: str = typer.Argument(...),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    url = _agent(f"/api/files/{file_id}")
    out_path = out or Path(f"{file_id}")
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=60.0) as client:
        res = client.get(url, headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    out_path.write_bytes(res.content)
    console.print(f"[green]Downloaded[/green] -> {out_path}")


@app.command("rm")
def files_rm(file_id: str = typer.Argument(...)) -> None:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=15.0) as client:
        res = client.delete(_agent(f"/api/files/{file_id}"), headers=headers)
    if not res.is_success:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    console.print(f"[green]Deleted[/green] {file_id}")
