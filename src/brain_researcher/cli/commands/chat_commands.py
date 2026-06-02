"""
User-friendly chat commands aligned with Web UI behaviour.

Endpoints:
- POST /api/chat          (research/simple)
- POST /api/chat/stream   (coding SSE)
- GET  /api/threads/{id}/messages
"""

import json
import os
import sys
import time
from typing import List, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="Chat with Agent (research & coding modes)")

from brain_researcher.cli.utils.auth import get_token

# Default retry configuration
DEFAULT_RETRY_COUNT = 0
DEFAULT_FALLBACK_MODEL = None
RETRY_BACKOFF_BASE = 1.5  # seconds


def _agent_base() -> str:
    return os.environ.get("AGENT_URL", "http://127.0.0.1:8000").rstrip("/")


def _agent(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{_agent_base()}{path}"


def _print_message(content: str, run_card: Optional[dict] = None) -> None:
    console.print(f"[bold cyan]Assistant:[/bold cyan] {content}")
    if run_card:
        console.print(f"[dim]run_id: {run_card.get('run_id', 'n/a')}[/dim]")


def _should_retry(status_code: int, error_body: dict | None) -> bool:
    """Determine if request should be retried based on error."""
    if status_code in (429, 502, 503, 504):
        return True
    if status_code >= 500:
        return True
    return False


def _get_retry_delay(attempt: int, error_body: dict | None) -> float:
    """Calculate retry delay with exponential backoff."""
    # Use retry_after from server if provided
    if error_body and "retry_after" in error_body:
        return float(error_body["retry_after"])
    return RETRY_BACKOFF_BASE * (2**attempt)


def _format_error(status_code: int, body: dict | str) -> str:
    """Format error message for CLI output."""
    if isinstance(body, dict):
        error = body.get("error", "unknown")
        detail = body.get("detail", str(body))
        retry_after = body.get("retry_after")
        msg = f"[{error}] {detail}"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        return msg
    return str(body)


@app.command("ask")
def chat_ask(
    prompt: str = typer.Argument(..., help="User message"),
    thread: Optional[str] = typer.Option(None, "--thread", help="Existing thread id"),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON"),
    retry: int = typer.Option(
        DEFAULT_RETRY_COUNT, "--retry", help="Number of retries on failure"
    ),
    fallback_model: Optional[str] = typer.Option(
        DEFAULT_FALLBACK_MODEL, "--fallback-model", help="Model to use on final retry"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show request without sending"
    ),
) -> None:
    """Simple (research) chat."""
    payload: dict = {
        "messages": [{"role": "user", "content": prompt}],
    }
    if thread:
        payload["thread_id"] = thread
        payload["session_id"] = thread

    url = _agent("/api/chat")
    headers: dict = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if dry_run:
        console.print(f"[dim]POST {url}[/dim]")
        console.print_json(data=payload)
        return

    last_error = None
    max_attempts = 1 + retry
    for attempt in range(max_attempts):
        # On final fallback attempt, switch model if specified
        current_payload = payload.copy()
        if attempt == max_attempts - 1 and fallback_model and attempt > 0:
            current_payload["model"] = fallback_model
            console.print(
                f"[yellow]Retrying with fallback model: {fallback_model}[/yellow]"
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, json=current_payload, headers=headers)

            if res.status_code == 401:
                console.print("[red]Session expired. Run `br auth login`.[/red]")
                raise typer.Exit(1)

            if res.status_code < 400:
                # Success
                data = res.json()
                if raw:
                    console.print_json(data=data)
                    return
                content = (
                    data.get("message", {}).get("content") or data.get("content") or ""
                )
                _print_message(content, run_card=data.get("runCard"))
                return

            # Error - check if retryable
            try:
                error_body = res.json()
            except Exception:
                error_body = {"detail": res.text}

            if (
                _should_retry(res.status_code, error_body)
                and attempt < max_attempts - 1
            ):
                delay = _get_retry_delay(attempt, error_body)
                console.print(
                    f"[yellow]Request failed (HTTP {res.status_code}). Retrying in {delay:.1f}s...[/yellow]"
                )
                time.sleep(delay)
                continue

            # Final failure
            console.print(
                f"[red]HTTP {res.status_code}[/red] {_format_error(res.status_code, error_body)}"
            )
            raise typer.Exit(1)

        except httpx.TimeoutException:
            if attempt < max_attempts - 1:
                delay = _get_retry_delay(attempt, None)
                console.print(
                    f"[yellow]Request timed out. Retrying in {delay:.1f}s...[/yellow]"
                )
                time.sleep(delay)
                continue
            console.print("[red]Request timed out[/red]")
            raise typer.Exit(1)
        except httpx.ConnectError:
            console.print(f"[red]Cannot connect to Agent at {_agent_base()}[/red]")
            raise typer.Exit(1)


@app.command("code")
def chat_code(
    prompt: str = typer.Argument(..., help="Coding agent instruction"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Repository root path"),
    file: List[str] = typer.Option([], "--file", "-f", help="File paths for context"),
    apply: bool = typer.Option(False, "--apply", help="Allow apply/patch"),
    ctx_dry_run: bool = typer.Option(
        True, "--ctx-dry-run/--no-ctx-dry-run", help="Send ctx.dry_run"
    ),
    timeout: float = typer.Option(180.0, "--timeout", help="Stream timeout seconds"),
    retry: int = typer.Option(
        DEFAULT_RETRY_COUNT, "--retry", help="Number of retries on connection failure"
    ),
    show_request: bool = typer.Option(
        False, "--show-request", help="Show request payload without sending"
    ),
) -> None:
    """Coding mode (SSE) with plan/patch/test/result streaming."""
    payload: dict = {
        "messages": [{"role": "user", "content": prompt}],
        "ctx": {
            "tools": {"mode": "coding"},
            "apply": apply,
            "dry_run": ctx_dry_run,
        },
    }
    if repo:
        payload["ctx"]["repo_root"] = repo
    if file:
        payload["ctx"]["file_paths"] = file

    url = _agent("/api/chat/stream")

    headers: dict = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if show_request:
        console.print(f"[dim]POST {url}[/dim]")
        console.print_json(data=payload)
        return

    console.print(f"[dim]POST {url}[/dim]")

    max_attempts = 1 + retry
    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST", url, json=payload, headers=headers, timeout=timeout
                ) as r:
                    if r.status_code == 401:
                        console.print(
                            "[red]Session expired. Run `br auth login`.[/red]"
                        )
                        raise typer.Exit(1)
                    if r.status_code >= 400:
                        try:
                            error_body = json.loads(r.text)
                        except Exception:
                            error_body = {"detail": r.text}
                        if (
                            _should_retry(r.status_code, error_body)
                            and attempt < max_attempts - 1
                        ):
                            delay = _get_retry_delay(attempt, error_body)
                            console.print(
                                f"[yellow]Request failed (HTTP {r.status_code}). Retrying in {delay:.1f}s...[/yellow]"
                            )
                            time.sleep(delay)
                            continue
                        console.print(
                            f"[red]HTTP {r.status_code}[/red] {_format_error(r.status_code, error_body)}"
                        )
                        raise typer.Exit(1)
                    current_event = None
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            current_event = line.split("event:", 1)[1].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        try:
                            data = json.loads(data_str)
                        except Exception:
                            data = data_str
                        tag = current_event or "message"
                        if tag in {"plan", "patch", "test"}:
                            console.print(f"[yellow]{tag}[/yellow]: {data}")
                        elif tag == "result":
                            console.print(f"[green]result[/green]: {data}")
                        elif tag == "error":
                            console.print(f"[red]error[/red]: {data}")
                        else:
                            console.print(f"[blue]{tag}[/blue]: {data}")
            return  # Success
        except httpx.TimeoutException:
            if attempt < max_attempts - 1:
                delay = _get_retry_delay(attempt, None)
                console.print(
                    f"[yellow]Stream timed out. Retrying in {delay:.1f}s...[/yellow]"
                )
                time.sleep(delay)
                continue
            console.print("[red]Stream timed out[/red]")
            raise typer.Exit(1)
        except httpx.ConnectError:
            if attempt < max_attempts - 1:
                delay = _get_retry_delay(attempt, None)
                console.print(
                    f"[yellow]Cannot connect. Retrying in {delay:.1f}s...[/yellow]"
                )
                time.sleep(delay)
                continue
            console.print(f"[red]Cannot connect to Agent at {_agent_base()}[/red]")
            raise typer.Exit(1)


@app.command("history")
def chat_history(thread: str = typer.Argument(..., help="Thread id")) -> None:
    """Show thread messages."""
    url = _agent(f"/api/threads/{thread}/messages")
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=15.0) as client:
        res = client.get(url, headers=headers)
    if res.status_code >= 400:
        console.print(f"[red]HTTP {res.status_code}[/red] {res.text}")
        raise typer.Exit(1)
    data = res.json()
    rows = data.get("messages", [])
    table = Table(title=f"Thread {thread}", show_lines=False)
    table.add_column("Role", style="cyan")
    table.add_column("Content", style="white")
    for msg in rows:
        table.add_row(msg.get("role", ""), msg.get("content", "")[:200])
    console.print(table)
