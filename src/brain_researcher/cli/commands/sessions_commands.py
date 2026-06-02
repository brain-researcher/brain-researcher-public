"""Remote session and Slack bridge helpers for the CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brain_researcher.cli.utils.auth import get_token
from brain_researcher.cli.utils.http_client import (
    format_http_error,
    get_orchestrator_url,
)
from brain_researcher.config.paths import get_repo_root

app = typer.Typer(help="Remote session and Slack bridge helpers")
console = Console()

_MANIFEST_TEMPLATE_PATH = (
    get_repo_root() / "configs" / "runtime" / "slack_app_manifest.template.yaml"
)


def _auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    base_url = get_orchestrator_url().rstrip("/")
    url = f"{base_url}{path if path.startswith('/') else '/' + path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method.upper(),
                url,
                json=json_body,
                params=params,
                headers=_auth_headers(),
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Error:[/red] {format_http_error(exc.response)}")
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise typer.Exit(1) from exc


def _render_manifest(public_base_url: str) -> str:
    template = _MANIFEST_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__PUBLIC_BASE_URL__", public_base_url.rstrip("/"))


def _print_session_summary(session: dict[str, Any]) -> None:
    body_lines = [
        f"[bold]ID:[/bold] {session.get('id', 'n/a')}",
        f"[bold]Kind:[/bold] {session.get('kind', 'n/a')}",
        f"[bold]Status:[/bold] {session.get('status', 'n/a')}",
        f"[bold]Session Ref:[/bold] {session.get('session_ref', 'n/a')}",
    ]
    if session.get("thread_id"):
        body_lines.append(f"[bold]Thread:[/bold] {session['thread_id']}")
    summary = str(session.get("summary") or "").strip()
    if summary:
        body_lines.append(f"[bold]Summary:[/bold] {summary}")
    console.print(
        Panel(
            "\n".join(body_lines),
            title=str(session.get("display_name") or "Session"),
            border_style="green",
        )
    )


@app.command("ls")
def list_sessions(
    kind: str | None = typer.Option(
        None, "--kind", help="Filter by kind: coding_session or mcp_run"
    ),
    thread_id: str | None = typer.Option(
        None, "--thread-id", help="Filter by orchestrator thread id"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum sessions to show"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON output"),
) -> None:
    params: dict[str, Any] = {"limit": limit}
    if kind:
        params["kind"] = kind
    if thread_id:
        params["thread_id"] = thread_id
    payload = _request_json("GET", "/api/sessions", params=params)
    items = payload.get("items") or []
    if json_output:
        console.print_json(data=payload)
        return
    if not items:
        console.print("[yellow]No sessions found[/yellow]")
        return
    table = Table(
        title=f"Sessions ({len(items)})", show_header=True, header_style="bold magenta"
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Kind", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Display", style="white")
    table.add_column("Thread", style="blue")
    table.add_column("Summary", style="dim")
    for item in items:
        table.add_row(
            str(item.get("id") or ""),
            str(item.get("kind") or ""),
            str(item.get("status") or ""),
            str(item.get("display_name") or ""),
            str(item.get("thread_id") or ""),
            str(item.get("summary") or ""),
        )
    console.print(table)


@app.command("attach")
def attach_session(
    kind: str = typer.Argument(..., help="Session kind: coding_session or mcp_run"),
    session_ref: str = typer.Argument(
        ..., help="Thread id, job id, or MCP run id to wrap"
    ),
    display_name: str | None = typer.Option(
        None, "--display-name", "-n", help="Human-friendly label for the session"
    ),
    thread_id: str | None = typer.Option(
        None, "--thread-id", help="Existing orchestrator thread to bind"
    ),
    slack_channel: str | None = typer.Option(
        None, "--slack-channel", help="Bind the new session to this Slack channel ID"
    ),
    slack_thread_ts: str | None = typer.Option(
        None,
        "--slack-thread-ts",
        help="Existing Slack thread timestamp; omit to post a new root message",
    ),
    mirror_chat: bool = typer.Option(
        True,
        "--mirror-chat/--no-mirror-chat",
        help="Mirror thread messages to Slack",
    ),
    cluster_profile: str | None = typer.Option(
        None, "--cluster-profile", help="Optional cluster profile for external runs"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON output"),
) -> None:
    payload: dict[str, Any] = {
        "kind": kind,
        "session_ref": session_ref,
        "display_name": display_name or f"{kind}:{session_ref}",
        "mirror_chat": mirror_chat,
    }
    if thread_id:
        payload["thread_id"] = thread_id
    if slack_channel:
        payload["slack_channel_id"] = slack_channel
    if slack_thread_ts:
        payload["slack_thread_ts"] = slack_thread_ts
    if cluster_profile:
        payload["cluster_profile"] = cluster_profile

    response = _request_json("POST", "/api/sessions/attach", json_body=payload)
    session = response.get("session") or {}
    if json_output:
        console.print_json(data=response)
        return
    console.print("[green]Attached session[/green]")
    _print_session_summary(session)
    if slack_channel:
        console.print(
            f"[dim]Slack bridge requested for channel {slack_channel}. Open Slack on your phone and reply in the thread.[/dim]"
        )
    else:
        console.print(
            f"[dim]Bind Slack later:[/dim] br sessions bind-slack {session.get('id', '<session_id>')} --channel-id C123"
        )


@app.command("bind-slack")
def bind_slack(
    session_id: str = typer.Argument(
        ..., help="Session id returned by br sessions attach"
    ),
    channel_id: str = typer.Option(..., "--channel-id", help="Slack channel ID"),
    thread_ts: str | None = typer.Option(
        None, "--thread-ts", help="Existing Slack thread timestamp"
    ),
    mirror_chat: bool = typer.Option(
        True,
        "--mirror-chat/--no-mirror-chat",
        help="Mirror thread messages to Slack",
    ),
    initial_message: str | None = typer.Option(
        None, "--initial-message", help="Custom root message when creating a new thread"
    ),
    post_root_message: bool = typer.Option(
        True,
        "--post-root-message/--no-post-root-message",
        help="Post a root message when thread_ts is omitted",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON output"),
) -> None:
    payload: dict[str, Any] = {
        "channel_id": channel_id,
        "mirror_chat": mirror_chat,
        "post_root_message": post_root_message,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if initial_message:
        payload["initial_message"] = initial_message
    response = _request_json(
        "POST",
        f"/api/sessions/{session_id}/bridges/slack",
        json_body=payload,
    )
    if json_output:
        console.print_json(data=response)
        return
    bridge = response.get("bridge") or {}
    console.print("[green]Slack bridge created[/green]")
    console.print(
        Panel(
            "\n".join(
                [
                    f"[bold]Bridge ID:[/bold] {bridge.get('id', 'n/a')}",
                    f"[bold]Channel:[/bold] {channel_id}",
                    f"[bold]Thread TS:[/bold] {bridge.get('config', {}).get('thread_ts', thread_ts or 'new root')}",
                ]
            ),
            title="Slack Bridge",
            border_style="green",
        )
    )


@app.command("slack-manifest")
def slack_manifest(
    public_base_url: str | None = typer.Option(
        None,
        "--public-base-url",
        help="Public HTTPS base URL for orchestrator callbacks (for example https://abc.ngrok-free.app)",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the rendered manifest to this file"
    ),
) -> None:
    resolved_base_url = (
        public_base_url
        or os.getenv("BR_PUBLIC_BASE_URL")
        or os.getenv("PUBLIC_ORCHESTRATOR_URL")
    )
    if not resolved_base_url:
        console.print(
            "[red]Error:[/red] Provide --public-base-url or set BR_PUBLIC_BASE_URL."
        )
        raise typer.Exit(1)
    manifest = _render_manifest(resolved_base_url.rstrip("/"))
    if output is not None:
        output.write_text(manifest, encoding="utf-8")
        console.print(f"[green]Wrote manifest[/green] to {output}")
        return
    console.print(manifest, end="")


@app.command("get")
def get_session(
    session_id: str = typer.Argument(..., help="Session id"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON output"),
) -> None:
    response = _request_json("GET", f"/api/sessions/{session_id}")
    if json_output:
        console.print_json(data=response)
        return
    session = response.get("session") or {}
    _print_session_summary(session)
    console.print_json(
        data={
            "control_capabilities": session.get("control_capabilities") or [],
            "chat_bindings": session.get("chat_bindings") or [],
            "metadata": session.get("metadata") or {},
        }
    )
