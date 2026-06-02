"""Repo-native CLI entrypoints for line-based autoresearch workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brain_researcher.core.contracts.scientific_review import ScientificReviewVerdict
from brain_researcher.services.review.autoresearch_line_controller import (
    drive_autoresearch_line,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    resolve_autoresearch_workspace_layout,
)
from brain_researcher.services.review.autoresearch_report_preflight import (
    run_autoresearch_report_preflight,
)
from brain_researcher.services.review.autoresearch_scientific_review import (
    distill_autoresearch_scientific_review,
)

app = typer.Typer(help="Line-based autoresearch workspace commands")
console = Console()


def _validate_output_format(output_format: str) -> str:
    fmt = output_format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]Error:[/red] --format must be one of: table, json")
        raise typer.Exit(1)
    return fmt


def _resolve_workspace_root(workspace_or_state: Path) -> Path:
    resolved = workspace_or_state.resolve()
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name == "line_state.json":
        return resolved.parent
    console.print(
        "[red]Error:[/red] workspace must be a directory or a line_state.json path"
    )
    raise typer.Exit(1)


def _load_verdict(verdict_json: Path | None) -> ScientificReviewVerdict | None:
    if verdict_json is None:
        return None
    try:
        payload = json.loads(verdict_json.read_text(encoding="utf-8"))
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Verdict file not found: {verdict_json}")
        raise typer.Exit(1) from None
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error:[/red] Invalid verdict JSON: {exc}")
        raise typer.Exit(1) from None
    try:
        return ScientificReviewVerdict.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive validation path
        console.print(f"[red]Error:[/red] Verdict payload failed validation: {exc}")
        raise typer.Exit(1) from None


def _render_preflight_table(preflight: dict[str, Any]) -> None:
    status = "ready" if preflight["ready_for_review"] else "blocked"
    parse_status = preflight["parse_status"]
    report_path = preflight.get("report_path") or "(missing)"
    console.print(
        Panel.fit(
            f"status={status}  parse_status={parse_status}\nreport={report_path}",
            title="Line Report Preflight",
            border_style="green" if preflight["ready_for_review"] else "yellow",
        )
    )

    blocks = preflight.get("required_blocks") or {}
    if blocks:
        block_table = Table(
            title="Required Blocks", show_header=True, header_style="bold cyan"
        )
        block_table.add_column("Block", style="cyan")
        block_table.add_column("Present", style="magenta")
        for name, present in blocks.items():
            block_table.add_row(name, "yes" if present else "no")
        console.print(block_table)

    issues = preflight.get("issues") or []
    if issues:
        issue_table = Table(
            title="Preflight Issues", show_header=True, header_style="bold red"
        )
        issue_table.add_column("Severity", style="red")
        issue_table.add_column("Code", style="yellow")
        issue_table.add_column("Message", style="white")
        for issue in issues:
            issue_table.add_row(issue["severity"], issue["code"], issue["message"])
        console.print(issue_table)


def _render_advance_table(payload: dict[str, Any]) -> None:
    decision = payload["decision"]
    line_state = payload["line_state"]
    preflight = payload["preflight"]
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"action={decision['action']}",
                    f"updated_status={decision['updated_status']}",
                    f"line_type={line_state.get('line_type') or 'unknown'}",
                    f"persisted={'yes' if payload['persisted'] else 'no'}",
                    f"review_executed={'yes' if payload['review_executed'] else 'no'}",
                ]
            ),
            title="Line Advance",
            border_style="green" if line_state["status"] == "completed" else "cyan",
        )
    )
    console.print(f"[dim]{decision['rationale']}[/dim]")
    if payload.get("review_skipped_reason"):
        console.print(
            f"[yellow]review skipped:[/yellow] {payload['review_skipped_reason']}"
        )
    if not preflight["ready_for_review"]:
        console.print(
            "[yellow]preflight did not pass; controller issued a repair directive[/yellow]"
        )

    trace_event = decision.get("trace_event") or {}
    if trace_event:
        console.print(
            f"[dim]trace_event={trace_event.get('event')} at {trace_event.get('timestamp_utc')}[/dim]"
        )


@app.command("preflight")
def line_preflight(
    workspace: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=True, readable=True
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
) -> None:
    """Run deterministic report preflight for one autoresearch workspace."""
    fmt = _validate_output_format(output_format)
    resolved_workspace = _resolve_workspace_root(workspace)
    preflight = run_autoresearch_report_preflight(resolved_workspace).model_dump(
        mode="json"
    )
    if fmt == "json":
        console.print_json(data=json.loads(json.dumps(preflight)))
        raise typer.Exit(0)
    _render_preflight_table(preflight)


@app.command("advance")
@app.command("run")
def line_advance(
    workspace: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=True, readable=True
    ),
    persist: bool = typer.Option(
        True,
        "--persist/--no-persist",
        help="Persist the updated line_state.json after controller decision",
    ),
    run_review: bool = typer.Option(
        True,
        "--run-review/--no-run-review",
        help="Run scientific review if report preflight passes",
    ),
    verdict_json: Path | None = typer.Option(
        None,
        "--verdict-json",
        help="Optional JSON file with a precomputed ScientificReviewVerdict",
    ),
    logs_dir: Path | None = typer.Option(
        None,
        "--logs-dir",
        help="Optional runner logs directory override for scientific review",
    ),
    task_id: str = typer.Option(
        "liu_component_v1",
        "--task-id",
        help="Task identifier passed into scientific review bundle building",
    ),
    use_judgment_critic: bool = typer.Option(
        True,
        "--use-judgment-critic/--no-use-judgment-critic",
        help="Whether to run the judgment critic during scientific review",
    ),
    force_recompute: bool = typer.Option(
        False,
        "--force-recompute",
        help="Ignore cached scientific review artifacts and recompute",
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
) -> None:
    """Advance one line workspace through preflight, review, and controller logic."""
    fmt = _validate_output_format(output_format)
    resolved_workspace = _resolve_workspace_root(workspace)
    layout = resolve_autoresearch_workspace_layout(resolved_workspace)
    preflight_model = run_autoresearch_report_preflight(resolved_workspace)
    preflight = preflight_model.model_dump(mode="json")

    verdict = _load_verdict(verdict_json)
    review_executed = verdict is not None
    review_skipped_reason: str | None = None
    if verdict is None and run_review:
        if preflight_model.ready_for_review:
            verdict = distill_autoresearch_scientific_review(
                resolved_workspace,
                logs_dir=logs_dir,
                task_id=task_id,
                use_judgment_critic=use_judgment_critic,
                force_recompute=force_recompute,
            )
            review_executed = True
        else:
            review_skipped_reason = "report_preflight_not_ready"
    elif verdict is None and not run_review:
        review_skipped_reason = "scientific_review_disabled"

    updated_state, decision = drive_autoresearch_line(
        resolved_workspace,
        verdict=verdict,
        persist=persist,
    )
    payload = {
        "workspace": str(resolved_workspace),
        "layout": layout.model_dump(mode="json"),
        "preflight": preflight,
        "review_executed": review_executed,
        "review_skipped_reason": review_skipped_reason,
        "persisted": persist,
        "decision": decision.model_dump(mode="json"),
        "line_state": updated_state.model_dump(mode="json"),
        "verdict": None if verdict is None else verdict.model_dump(mode="json"),
    }
    if fmt == "json":
        console.print_json(data=json.loads(json.dumps(payload)))
        raise typer.Exit(0)
    _render_advance_table(payload)
