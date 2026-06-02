"""Copilot CLI commands (AGENT-007)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON

from brain_researcher.cli.utils.http_client import get_orchestrator_url
from brain_researcher.services.agent.copilot import CopilotAssistant
from brain_researcher.services.tools.tool_registry import ToolRegistry

app = typer.Typer(help="Copilot assistance: suggestions, autocomplete, learning")
console = Console()


def _parse_json_arg(arg: Optional[str]) -> dict:
    if not arg:
        return {}
    # If it's a file path, read it
    p = Path(arg)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    # Else parse as JSON string
    try:
        return json.loads(arg)
    except Exception:
        return {}


def _get_copilot() -> CopilotAssistant:
    # Use default registry discovery for broad suggestions
    reg = ToolRegistry(auto_discover=True)
    return CopilotAssistant(tool_registry=reg)


@app.command("suggest")
def suggest(
    query: str = typer.Argument(..., help="Natural language task description"),
    metadata: Optional[str] = typer.Option(
        None, "--metadata", "-m", help="Dataset metadata as JSON or file path"
    ),
    k: int = typer.Option(5, "--k", help="Number of suggestions to return"),
):
    """Suggest appropriate tools with autocomplete hints and examples."""
    meta = _parse_json_arg(metadata)
    copilot = _get_copilot()
    suggestions = copilot.suggest_tools(query, dataset_metadata=meta, k=k)
    out = [
        {
            "name": s.name,
            "score": s.score,
            "reason": s.reason,
            "required_params": s.required_params,
            "autocomplete": s.autocomplete,
            "examples": s.examples,
        }
        for s in suggestions
    ]
    console.print(JSON.from_data({"suggestions": out}))


@app.command("autocomplete")
def autocomplete(
    tool: str = typer.Argument(..., help="Tool name to complete params for"),
    params: Optional[str] = typer.Option(
        None, "--params", "-p", help="Partial params as JSON or file path"
    ),
    metadata: Optional[str] = typer.Option(
        None, "--metadata", "-m", help="Dataset metadata as JSON or file path"
    ),
):
    """Auto-complete parameters using dataset metadata and mappings."""
    partial = _parse_json_arg(params)
    meta = _parse_json_arg(metadata)
    copilot = _get_copilot()
    completed = copilot.autocomplete_parameters(tool, partial, meta)
    console.print(JSON.from_data({"tool": tool, "completed": completed}))


@app.command("learn")
def learn(
    tool: str = typer.Argument(..., help="Tool name selected by the user"),
    accepted_params: Optional[str] = typer.Option(
        None, "--params", "-p", help="Accepted params as JSON or file path"
    ),
):
    """Record user selection and accepted params to improve ranking."""
    params = _parse_json_arg(accepted_params)
    copilot = _get_copilot()
    copilot.learn_selection(tool, params)
    console.print(JSON.from_data({"status": "ok", "tool": tool}))


@app.command("demo")
def demo(
    query: str = typer.Argument(..., help="Prompt to demo suggestions for"),
    api_url: str = typer.Option(
        None,
        "--orchestrator-url",
        "--agent-url",
        help="Copilot API base URL (defaults from Orchestrator env vars or http://localhost:3001)",
    ),
    k: int = typer.Option(3, "--k", help="Number of suggestions"),
):
    """Demo suggestions via Orchestrator copilot API if available; fallback to local engine."""
    import urllib.request

    base = api_url or get_orchestrator_url()
    payload = json.dumps({"query": query, "k": k}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/copilot/suggest",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    suggestions = None
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            suggestions = data.get("suggestions", [])
    except Exception:
        pass

    if suggestions is None:
        # Fallback to local engine
        copilot = _get_copilot()
        suggestions = [
            {
                "name": s.name,
                "score": s.score,
                "reason": s.reason,
                "required_params": s.required_params,
                "autocomplete": s.autocomplete,
                "examples": s.examples,
            }
            for s in copilot.suggest_tools(query, k=k)
        ]

    console.print(
        JSON.from_data({"api_url": base, "query": query, "suggestions": suggestions})
    )
