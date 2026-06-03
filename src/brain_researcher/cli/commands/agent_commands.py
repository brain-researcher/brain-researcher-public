"""
Agent planning and execution commands for Brain Researcher CLI.

Provides commands for:
- br agent run: Execute jobs with planner integration
- br agent plan: Preview tool selection without execution
- br agent hypothesis: Generate KG-backed hypothesis candidate cards
"""

import json
import time
from dataclasses import asdict
from typing import Any

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brain_researcher.cli.utils.http_client import api_get_sync, api_post_sync
from brain_researcher.services.agent.autoresearch import (
    FailureMotifCard,
    FixCandidate,
    ValidationReport,
    mine_failure_motifs,
    propose_fix_candidates,
    validate_fix_candidate,
)
from brain_researcher.services.agent.harness_scaffolding import (
    HarnessScaffoldResult,
    scaffold_harness_task,
)
from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
    find_candidate_cards_payload,
    find_novelty_calibration_payload,
    find_workflow_result,
)
from brain_researcher.services.agent.repo_repair_context import (
    generate_repo_repair_context,
)

app = typer.Typer(help="Agent planning and execution commands")
console = Console()


def parse_key_value_pairs(params: list[str]) -> dict[str, Any]:
    """
    Parse key=value strings into a dictionary.

    Args:
        params: List of "key=value" strings

    Returns:
        Dict mapping keys to values

    Examples:
        >>> parse_key_value_pairs(["infile=/data/brain.nii.gz", "threshold=0.5"])
        {"infile": "/data/brain.nii.gz", "threshold": "0.5"}
    """
    result = {}
    for param in params:
        if "=" not in param:
            console.print(
                f"[yellow]Warning:[/yellow] Skipping invalid parameter: {param}"
            )
            console.print("[yellow]Expected format:[/yellow] key=value")
            continue

        key, value = param.split("=", 1)
        result[key] = value

    return result


def display_plan_table(plan_data: dict[str, Any]) -> None:
    """
    Display a Plan with selection reasoning.

    P0-1: Updated to show intent, candidates, chosen_tool, selection_reason.

    Args:
        plan_data: Plan result from POST /api/agent/plan
    """
    # P0-1: Display intent (extracted operators)
    intent = plan_data.get("intent", [])
    if intent:
        console.print(f"\n[bold cyan]Intent:[/bold cyan] {', '.join(intent)}")

    # Display query/pipeline
    pipeline = plan_data.get("pipeline") or plan_data.get("query", "N/A")
    console.print(f"[bold]Query:[/bold] {pipeline}\n")

    # P0-1: Create candidates table with new fields
    candidates = plan_data.get("candidates", [])
    if candidates:
        table = Table(
            title="Candidate Tools", show_header=True, header_style="bold magenta"
        )
        table.add_column("Rank", justify="right", style="cyan")
        table.add_column("Tool ID", style="green")
        table.add_column("Score", justify="right", style="yellow")
        table.add_column("Preflight", justify="center")
        table.add_column("Explanation", style="dim")

        for idx, candidate in enumerate(candidates, start=1):
            preflight = "✓" if candidate.get("preflight_passed") else "✗"
            preflight_style = "green" if candidate.get("preflight_passed") else "red"

            table.add_row(
                str(idx),
                candidate.get("tool_id", ""),
                f"{candidate.get('final_score', 0):.2f}",
                f"[{preflight_style}]{preflight}[/{preflight_style}]",
                candidate.get("explanation", ""),
            )

        console.print(table)

    # P0-1: Display chosen tool and selection reason
    chosen_tool = plan_data.get("chosen_tool")
    selection_reason = plan_data.get("selection_reason")

    if chosen_tool:
        console.print(f"\n[bold green]✓ Chosen:[/bold green] {chosen_tool}")
        if selection_reason:
            console.print(f"[bold]Reason:[/bold] {selection_reason}")
    elif not plan_data.get("resolvable", True):
        console.print("\n[bold yellow]⚠ No suitable tool found[/bold yellow]")
        warnings = plan_data.get("warnings", [])
        if warnings:
            for warning in warnings:
                console.print(f"  [yellow]{warning}[/yellow]")


def wait_for_job_completion(job_id: str, poll_interval: int = 2) -> dict[str, Any]:
    """
    Poll job status until it completes.

    Args:
        job_id: Job identifier
        poll_interval: Seconds between polls

    Returns:
        Final job details
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description=f"Waiting for job {job_id}...", total=None)

        while True:
            try:
                job_data = api_get_sync(f"/api/jobs/{job_id}")
                state = job_data.get("state", "unknown")

                if state in ["succeeded", "failed", "cancelled", "timeout"]:
                    progress.update(task, description=f"Job {state}")
                    return job_data

                # Update progress message
                progress.update(task, description=f"Job {state}...")
                time.sleep(poll_interval)

            except Exception as e:
                console.print(f"\n[red]Error polling job:[/red] {e}")
                raise


def _extract_text_fragment(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, dict):
        for key in ("summary", "text", "answer", "content", "message"):
            text = _extract_text_fragment(value.get(key))
            if text:
                return text
        for nested in value.values():
            text = _extract_text_fragment(nested)
            if text:
                return text
    if isinstance(value, list):
        for nested in value:
            text = _extract_text_fragment(nested)
            if text:
                return text
    return None


def _normalize_candidate_cards(raw_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, card in enumerate(raw_cards, start=1):
        title = str(
            card.get("title") or card.get("label") or f"Candidate {idx}"
        ).strip()
        hypothesis = str(
            card.get("hypothesis") or card.get("summary") or card.get("statement") or ""
        ).strip()
        minimal_test = str(card.get("minimal_discriminating_test") or "").strip()
        falsifier_hint = str(card.get("falsifier_hint") or "").strip()
        contradiction_probe = str(card.get("contradiction_probe") or "").strip()
        topology_shift_probe = str(card.get("topology_shift_probe") or "").strip()
        taste_axis = str(card.get("taste_axis") or "").strip() or "unspecified"
        card_id = str(card.get("card_id") or card.get("id") or f"cand_{idx:02d}")
        normalized.append(
            {
                "card_id": card_id,
                "title": title,
                "hypothesis": hypothesis,
                "taste_axis": taste_axis,
                "minimal_discriminating_test": minimal_test,
                "falsifier_hint": falsifier_hint,
                "contradiction_probe": contradiction_probe,
                "topology_shift_probe": topology_shift_probe,
                "active_principle": card.get("active_principle"),
                "principle_confidence": card.get("principle_confidence"),
                "principle_session_key": card.get("principle_session_key"),
                "selection_reason": card.get("selection_reason"),
                "anomaly_flags": card.get("anomaly_flags", []),
                "wow_score": card.get("wow_score"),
                "counterintuitiveness": card.get("counterintuitiveness"),
                "testability": card.get("testability"),
                "impact_radius": card.get("impact_radius"),
                "prior_art_obviousness": card.get("prior_art_obviousness"),
                "execution_gap_only": card.get("execution_gap_only"),
                "broken_default_assumption": card.get("broken_default_assumption"),
                "contradiction_signature": card.get("contradiction_signature"),
                "transfer_signature": card.get("transfer_signature"),
                "why_this_is_not_just_a_bridge": card.get(
                    "why_this_is_not_just_a_bridge"
                ),
                "provenance": card.get("provenance", {}),
            }
        )
    return normalized


def _extract_candidate_cards_from_job(
    final_job: dict[str, Any],
    *,
    query: str,
    top_n: int,
) -> list[dict[str, Any]]:
    raw_cards = find_candidate_cards_payload(final_job)
    if raw_cards:
        return _normalize_candidate_cards(raw_cards[:top_n])

    workflow_result = find_workflow_result(final_job)
    if workflow_result is None:
        return []

    generated = build_candidate_cards_from_workflow_result(
        workflow_result,
        query=query,
        top_n=top_n,
    )
    return _normalize_candidate_cards(generated)


def _extract_novelty_calibration_from_job(
    final_job: dict[str, Any],
) -> dict[str, Any] | None:
    return find_novelty_calibration_payload(final_job)


def _run_deep_research_sync(
    *,
    query: str,
    top_k: int,
    recency_days: int,
    exclude_domains: list[str],
    poll_interval: int = 2,
) -> tuple[str | None, str | None]:
    payload = {
        "prompt": query,
        "tool": "google_deep_research",
        "parameters": {
            "query": query,
            "recency_days": recency_days,
            "exclude_domains": exclude_domains,
        },
    }
    response = api_post_sync("/run", json_data=payload)
    job_id = response.get("job_id") or response.get("run_id")
    if not job_id:
        return None, "No job_id returned for google_deep_research."

    final_job = wait_for_job_completion(str(job_id), poll_interval=poll_interval)
    state = str(final_job.get("state", "unknown"))
    if state != "succeeded":
        return None, f"google_deep_research finished with state={state}"

    summary = _extract_text_fragment(final_job)
    if not summary:
        return None, "google_deep_research returned no summary text"
    return summary, None


def _render_candidate_cards_table(cards: list[dict[str, Any]]) -> None:
    table = Table(
        title="Hypothesis Candidate Cards",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Taste Axis", style="yellow")
    table.add_column("Minimal Discriminating Test", style="white")
    table.add_column("Falsifier Hint", style="dim")

    for idx, card in enumerate(cards, start=1):
        table.add_row(
            str(idx),
            str(card.get("title", "")),
            str(card.get("taste_axis", "")),
            str(card.get("minimal_discriminating_test", "")),
            str(card.get("falsifier_hint", "")),
        )
    console.print(table)


def _render_named_candidate_cards_table(
    cards: list[dict[str, Any]],
    *,
    title: str,
) -> None:
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Taste Axis", style="yellow")
    table.add_column("Minimal Discriminating Test", style="white")
    table.add_column("Falsifier Hint", style="dim")

    for idx, card in enumerate(cards, start=1):
        table.add_row(
            str(idx),
            str(card.get("title", "")),
            str(card.get("taste_axis", "")),
            str(card.get("minimal_discriminating_test", "")),
            str(card.get("falsifier_hint", "")),
        )
    console.print(table)


def _render_failure_motifs_table(cards: list[FailureMotifCard]) -> None:
    table = Table(title="Failure Motifs", show_header=True, header_style="bold magenta")
    table.add_column("Motif", style="green")
    table.add_column("Severity", style="yellow")
    table.add_column("Freq", justify="right", style="cyan")
    table.add_column("Surface", style="white")
    table.add_column("Representative Runs", style="dim")

    for card in cards:
        table.add_row(
            card.motif_id,
            card.severity,
            str(card.frequency),
            card.suspected_surface,
            ", ".join(card.representative_runs[:3]),
        )
    console.print(table)


def _render_fix_candidates_table(candidates: list[FixCandidate]) -> None:
    table = Table(title="Fix Candidates", show_header=True, header_style="bold magenta")
    table.add_column("Candidate", style="green")
    table.add_column("Motif", style="yellow")
    table.add_column("Target Surface", style="white")
    table.add_column("Worktree", style="dim")
    table.add_column("Allowed Paths", style="cyan")

    for candidate in candidates:
        table.add_row(
            candidate.candidate_id,
            candidate.motif_id,
            candidate.target_surface,
            candidate.worktree_path,
            ", ".join(candidate.allowed_paths[:3]),
        )
    console.print(table)


def _render_validation_report(report: ValidationReport) -> None:
    baseline_motif = report.baseline_summary.get("motif_slice", {})
    candidate_motif = report.candidate_summary.get("motif_slice", {})
    baseline_canary = report.baseline_summary.get("canary_slice", {})
    candidate_canary = report.candidate_summary.get("canary_slice", {})

    console.print(
        f"\n[bold]Candidate:[/bold] {report.candidate_id}\n"
        f"[bold]Motif:[/bold] {report.motif_id}\n"
        f"[bold]Verdict:[/bold] {report.gate_verdict}\n"
        f"[bold]Larger Benchmark Eligible:[/bold] {report.larger_benchmark_eligible}"
    )
    if report.status_explanation:
        console.print(f"[bold]Status Summary:[/bold] {report.status_explanation}")
    if report.recommended_action:
        console.print(f"[bold]Recommended Action:[/bold] {report.recommended_action}")
    patch_legibility = (
        report.patch_legibility if isinstance(report.patch_legibility, dict) else {}
    )
    if patch_legibility:
        score = patch_legibility.get("score")
        band = str(patch_legibility.get("band") or "unknown")
        files_touched = int(patch_legibility.get("files_touched", 0) or 0)
        lines_added = int(patch_legibility.get("lines_added", 0) or 0)
        lines_deleted = int(patch_legibility.get("lines_deleted", 0) or 0)
        outside_count = int(patch_legibility.get("outside_allowlist_count", 0) or 0)
        console.print(
            "[bold]Patch Legibility:[/bold] "
            f"score={float(score or 0.0):.1f} "
            f"band={band} "
            f"files={files_touched} "
            f"lines=+{lines_added}/-{lines_deleted} "
            f"outside_allowlist={outside_count}"
        )
        findings = patch_legibility.get("findings")
        if isinstance(findings, list) and findings:
            for finding in findings[:3]:
                console.print(f"[dim]  - {finding}[/dim]")

    table = Table(
        title="Validation Summary", show_header=True, header_style="bold magenta"
    )
    table.add_column("Slice", style="green")
    table.add_column("Baseline Success", justify="right", style="yellow")
    table.add_column("Candidate Success", justify="right", style="yellow")
    table.add_column("Baseline Blockers", justify="right", style="cyan")
    table.add_column("Candidate Blockers", justify="right", style="cyan")
    table.add_column("Baseline Motif Blockers", justify="right", style="white")
    table.add_column("Candidate Motif Blockers", justify="right", style="white")
    table.add_row(
        "motif",
        f"{float(baseline_motif.get('success_rate', 0.0)):.2f}",
        f"{float(candidate_motif.get('success_rate', 0.0)):.2f}",
        str(int(baseline_motif.get("blocker_count", 0))),
        str(int(candidate_motif.get("blocker_count", 0))),
        str(int(baseline_motif.get("motif_blocker_count", 0))),
        str(int(candidate_motif.get("motif_blocker_count", 0))),
    )
    table.add_row(
        "canary",
        f"{float(baseline_canary.get('success_rate', 0.0)):.2f}",
        f"{float(candidate_canary.get('success_rate', 0.0)):.2f}",
        str(int(baseline_canary.get("blocker_count", 0))),
        str(int(candidate_canary.get("blocker_count", 0))),
        "-",
        "-",
    )
    console.print(table)

    if report.fixed_failures:
        console.print(
            f"[green]Fixed failures:[/green] {', '.join(report.fixed_failures)}"
        )
    if report.regressions:
        console.print(f"[red]Regressions:[/red] {', '.join(report.regressions)}")
    if report.warnings:
        for warning in report.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")


def _render_repo_repair_context_table(payload: dict[str, Any]) -> None:
    context = payload.get("repo_repair_context") or {}
    summary = context.get("summary") or {}
    harness = context.get("harness_coverage") or {}
    hot_surfaces = context.get("hot_surfaces") or []
    motifs = context.get("recent_failure_motifs") or []
    absorbed = context.get("absorbed_upstream_candidates") or []
    principles = context.get("golden_principles") or []

    console.print(
        "\n[bold]Repo Repair Context[/bold]\n"
        f"[bold]Generated:[/bold] {context.get('generated_at')}\n"
        f"[bold]Failure Motifs:[/bold] {summary.get('failure_motif_count', 0)}\n"
        f"[bold]Absorbed Upstream:[/bold] "
        f"{summary.get('absorbed_upstream_candidate_count', 0)}\n"
        f"[bold]HARNESS Tasks:[/bold] {summary.get('harness_task_count', 0)}\n"
        f"[bold]Golden Principles:[/bold] {summary.get('golden_principle_count', 0)}"
    )

    hot_surface_table = Table(
        title="Hot Surfaces", show_header=True, header_style="bold magenta"
    )
    hot_surface_table.add_column("Surface", style="green")
    hot_surface_table.add_column("Weight", justify="right", style="cyan")
    for row in hot_surfaces[:8]:
        hot_surface_table.add_row(
            str(row.get("surface") or ""),
            str(row.get("weight") or 0),
        )
    if hot_surfaces:
        console.print(hot_surface_table)

    motif_table = Table(
        title="Recent Failure Motifs", show_header=True, header_style="bold magenta"
    )
    motif_table.add_column("Motif", style="green")
    motif_table.add_column("Freq", justify="right", style="cyan")
    motif_table.add_column("Surface", style="white")
    for row in motifs[:8]:
        motif_table.add_row(
            str(row.get("motif_family") or ""),
            str(row.get("frequency") or 0),
            str(row.get("suspected_surface") or ""),
        )
    if motifs:
        console.print(motif_table)

    absorbed_table = Table(
        title="Absorbed-Upstream Candidates",
        show_header=True,
        header_style="bold magenta",
    )
    absorbed_table.add_column("Candidate", style="green")
    absorbed_table.add_column("Motif", style="yellow")
    absorbed_table.add_column("Surface", style="white")
    absorbed_table.add_column("Legibility", style="cyan")
    for row in absorbed[:8]:
        absorbed_table.add_row(
            str(row.get("candidate_id") or ""),
            str(row.get("motif_family") or ""),
            str(row.get("target_surface") or ""),
            str(row.get("patch_legibility_band") or "unknown"),
        )
    if absorbed:
        console.print(absorbed_table)

    console.print(
        "[bold]Native HARNESS tasks:[/bold] "
        + (", ".join(harness.get("all_harness_tasks") or []) or "none")
    )
    console.print(
        "[bold]Motifs without native HARNESS:[/bold] "
        + (", ".join(harness.get("motifs_without_native_harness") or []) or "none")
    )

    if principles:
        principle_table = Table(
            title="Golden Principles", show_header=True, header_style="bold magenta"
        )
        principle_table.add_column("ID", style="green")
        principle_table.add_column("Title", style="white")
        for row in principles[:8]:
            principle_table.add_row(
                str(row.get("id") or ""),
                str(row.get("title") or ""),
            )
        console.print(principle_table)

    warnings = payload.get("warnings") or []
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


@app.command("run")
def agent_run(
    intent: str = typer.Argument(
        ..., help="Natural language intent (e.g., 'skull strip')"
    ),
    tool: str | None = typer.Option(
        None, "--tool", help="Force specific tool (bypasses planner)"
    ),
    param: list[str] = typer.Option(
        [], "--param", "-p", help="Parameters as key=value (repeatable)"
    ),
    planner_mode: str = typer.Option(
        "autorun", "--planner-mode", help="Planner mode: autorun, advisor, or disabled"
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for job completion"),
):
    """
    Execute a job with optional planner integration.

    Examples:
        br agent run "skull strip" --param infile=/data/T1.nii.gz
        br agent run "segment tissue" --param infile=/data/T1.nii.gz --wait
        br agent run "extract brain" --tool fsl.bet --param infile=/data/T1.nii.gz
        br agent run "register to MNI" --planner-mode advisor
    """
    try:
        # Parse parameters
        parameters = parse_key_value_pairs(param)

        # If advisor mode, show preview first
        if planner_mode == "advisor" and not tool:
            console.print("\n[bold]Generating plan preview...[/bold]")

            try:
                # P0-1: Updated to match new PlanRequest schema
                plan_data = api_post_sync(
                    "/api/agent/plan",
                    json_data={
                        "pipeline": intent,
                        "domain": "neuroimaging",
                        "modality": [],
                        "inputs": parameters,
                    },
                )

                display_plan_table(plan_data)

                # Ask for confirmation
                console.print()
                confirm = typer.confirm("Proceed with execution?", default=True)
                if not confirm:
                    console.print("[yellow]Execution cancelled[/yellow]")
                    raise typer.Exit(0)

            except typer.Exit:
                raise
            except Exception as e:
                console.print(
                    f"\n[yellow]Warning:[/yellow] Could not generate plan preview: {e}"
                )
                console.print("[yellow]Proceeding with execution anyway...[/yellow]\n")

        # Build payload for POST /run
        payload = {"prompt": intent, "parameters": parameters}

        if tool:
            payload["tool"] = tool

        # Create job
        console.print("\n[bold]Creating job...[/bold]")
        response = api_post_sync("/run", json_data=payload)

        job_id = response.get("job_id") or response.get("run_id")
        if not job_id:
            console.print("[red]Error:[/red] No job ID in response")
            raise typer.Exit(1)

        console.print(f"[green]✓ Job created:[/green] {job_id}")

        # Display planner info if available
        if "planner_trace" in response or "plan" in response:
            plan_data = response.get("planner_trace") or response.get("plan")
            if plan_data and isinstance(plan_data, dict):
                chosen = plan_data.get("chosen")
                if chosen:
                    console.print(
                        f"[green]  Tool:[/green] {chosen.get('tool_name')} ({chosen.get('tool_id')})"
                    )

        # Wait for completion if requested
        if wait:
            console.print()
            final_job = wait_for_job_completion(job_id)

            state = final_job.get("state", "unknown")
            if state == "succeeded":
                console.print("\n[bold green]✓ Job completed successfully[/bold green]")
            elif state == "failed":
                console.print("\n[bold red]✗ Job failed[/bold red]")
                error = final_job.get("error")
                if error:
                    console.print(f"[red]Error:[/red] {error}")
            else:
                console.print(f"\n[yellow]Job ended with state: {state}[/yellow]")

            console.print(f"\n[dim]View details:[/dim] br runs inspect {job_id}")
        else:
            console.print(f"\n[dim]Check status:[/dim] br runs inspect {job_id}")
            console.print(f"[dim]Follow logs:[/dim] br runs logs {job_id} --follow")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("plan")
def agent_plan(
    intent: str = typer.Argument(
        ..., help="Natural language intent (e.g., 'skull strip')"
    ),
    param: list[str] = typer.Option(
        [], "--param", "-p", help="Parameters as key=value (repeatable)"
    ),
):
    """
    Preview tool selection without executing.

    Calls the planner to rank candidate tools and show which would be chosen,
    but does not create or execute a job.

    Examples:
        br agent plan "skull strip"
        br agent plan "segment tissue" --param infile=/data/T1.nii.gz
        br agent plan "register to MNI" --param reference=/data/MNI152.nii.gz
    """
    try:
        # Parse parameters
        parameters = parse_key_value_pairs(param)

        # Call planner
        console.print("\n[bold]Generating plan...[/bold]")
        plan_data = api_post_sync(
            "/api/agent/plan", json_data={"intent": intent, "constraints": parameters}
        )

        # Display plan
        display_plan_table(plan_data)

        # Show plan ID if available
        plan_id = plan_data.get("plan_id")
        if plan_id:
            console.print(f"\n[dim]Plan ID:[/dim] {plan_id}")

        console.print(f'\n[dim]To execute:[/dim] br agent run "{intent}"')

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("hypothesis")
def agent_hypothesis(
    query: str = typer.Argument(..., help="Hypothesis query text"),
    seed_kg_id: list[str] = typer.Option(
        [], "--seed-kg-id", help="Optional seed KG ID (repeatable)"
    ),
    relation_type: list[str] = typer.Option(
        [], "--relation-type", help="Optional relation type filter (repeatable)"
    ),
    top: int = typer.Option(
        5, "--top", min=1, max=20, help="Number of candidate cards to return"
    ),
    top_k: int = typer.Option(
        20, "--top-k", min=1, max=200, help="KG leverage search limit"
    ),
    taste_mode: str = typer.Option(
        "novelty_first",
        "--taste-mode",
        help="Taste mode: novelty_first | balanced | evidence_first",
    ),
    candidate_lane_mode: str = typer.Option(
        "broad",
        "--candidate-lane-mode",
        help="Candidate-lane evidence mode: broad | strict",
    ),
    controller_mode: str = typer.Option(
        "legacy",
        "--controller-mode",
        help="Controller mode: legacy | principle_v0",
    ),
    wait: bool = typer.Option(
        True, "--wait/--no-wait", help="Wait for workflow job completion"
    ),
    poll_interval: int = typer.Option(
        2, "--poll-interval", min=1, help="Polling interval in seconds"
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
    with_research: bool = typer.Option(
        False,
        "--with-research/--no-with-research",
        help="Run optional blocking google_deep_research enrichment after cards are generated",
    ),
    research_top_k: int = typer.Option(
        8,
        "--research-top-k",
        min=1,
        max=30,
        help="Reserved (unused) with google_deep_research",
    ),
    recency_days: int = typer.Option(
        365,
        "--recency-days",
        min=0,
        max=3650,
        help="Recency window for google_deep_research",
    ),
    exclude_domain: list[str] = typer.Option(
        [],
        "--exclude-domain",
        help="Domain exclusion for google_deep_research (repeatable)",
    ),
):
    """Generate KG-backed hypothesis candidate cards via declarative workflow."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        workflow_params: dict[str, Any] = {
            "query": query,
            "top_k": int(top_k),
            "n_samples": int(top),
            "taste_mode": taste_mode,
            "candidate_lane_mode": candidate_lane_mode,
            "controller_mode": controller_mode,
        }
        if seed_kg_id:
            workflow_params["seed_kg_ids"] = seed_kg_id
        if relation_type:
            workflow_params["relation_types"] = relation_type

        payload = {
            "prompt": query,
            "tool": "workflow_hypothesis_candidate_cards",
            "parameters": workflow_params,
        }

        console.print("\n[bold]Submitting hypothesis workflow...[/bold]")
        response = api_post_sync("/run", json_data=payload)
        job_id = response.get("job_id") or response.get("run_id")
        if not job_id:
            console.print("[red]Error:[/red] No job_id returned by /run")
            raise typer.Exit(1)

        console.print(f"[green]✓ Job created:[/green] {job_id}")
        if not wait:
            console.print(f"[dim]Check status:[/dim] br runs inspect {job_id}")
            console.print(f"[dim]Follow logs:[/dim] br runs logs {job_id} --follow")
            raise typer.Exit(0)

        final_job = wait_for_job_completion(str(job_id), poll_interval=poll_interval)
        state = str(final_job.get("state", "unknown"))
        if state != "succeeded":
            console.print(f"[red]Workflow failed[/red] (state={state})")
            error = final_job.get("error")
            if error:
                console.print(f"[red]Error:[/red] {error}")
            raise typer.Exit(1)

        candidate_cards = _extract_candidate_cards_from_job(
            final_job,
            query=query,
            top_n=top,
        )
        if not candidate_cards:
            console.print("[yellow]No candidate cards found in job output.[/yellow]")
            if fmt == "json":
                console.print_json(
                    data={
                        "job_id": job_id,
                        "state": state,
                        "candidate_cards": [],
                    }
                )
            raise typer.Exit(0)

        if with_research:
            console.print(
                "[bold]Running optional google_deep_research enrichment...[/bold]"
            )
            summary, research_error = _run_deep_research_sync(
                query=query,
                top_k=research_top_k,
                recency_days=recency_days,
                exclude_domains=exclude_domain,
                poll_interval=poll_interval,
            )
            for card in candidate_cards:
                if summary:
                    card["grounding_status"] = "grounded"
                    card["evidence_summary"] = summary
                else:
                    card["grounding_status"] = "degraded"
                    card["deep_research_error"] = research_error or "unknown"

        result_payload = {
            "job_id": job_id,
            "state": state,
            "candidate_cards": candidate_cards,
        }
        novelty_calibration = _extract_novelty_calibration_from_job(final_job)
        if novelty_calibration:
            result_payload.update(novelty_calibration)

        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(result_payload)))
            raise typer.Exit(0)

        console.print(
            f"\n[bold green]✓ Generated {len(candidate_cards)} candidate cards[/bold green]"
        )
        _render_candidate_cards_table(candidate_cards)
        console.print(f"\n[dim]View details:[/dim] br runs inspect {job_id}")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("mine-failure-motifs")
def agent_mine_failure_motifs(
    limit: int = typer.Option(
        200, "--limit", min=1, help="Maximum number of real MCP runs to inspect"
    ),
    days: int = typer.Option(14, "--days", min=1, help="Lookback window in days"),
    profile_id: str = typer.Option(
        "external_coding_v1",
        "--profile-id",
        help="Loop profile used to normalize scorecards",
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
):
    """Mine recurring failure motifs from recent MCP runs."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        cards = mine_failure_motifs(limit=limit, days=days, profile_id=profile_id)
        payload = {"failure_motifs": [asdict(card) for card in cards]}
        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(payload)))
            raise typer.Exit(0)

        console.print(
            f"\n[bold green]✓ Mined {len(cards)} recurring failure motifs[/bold green]"
        )
        _render_failure_motifs_table(cards)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("propose-fix-candidates")
def agent_propose_fix_candidates(
    motif_id: str = typer.Argument(..., help="Failure motif ID to target"),
    max_candidates: int = typer.Option(
        3, "--max-candidates", min=1, max=5, help="Maximum candidates to create"
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
):
    """Create bounded fix candidates in isolated git worktrees."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        candidates = propose_fix_candidates(motif_id, max_candidates=max_candidates)
        payload = {"fix_candidates": [asdict(candidate) for candidate in candidates]}
        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(payload)))
            raise typer.Exit(0)

        console.print(
            f"\n[bold green]✓ Created {len(candidates)} fix candidates[/bold green]"
        )
        _render_fix_candidates_table(candidates)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("validate-fix-candidate")
def agent_validate_fix_candidate(
    candidate_id: str = typer.Argument(..., help="Fix candidate ID"),
    profile_id: str = typer.Option(
        "external_coding_v1",
        "--profile-id",
        help="Loop profile used to enrich benchmark scorecards",
    ),
    timeout: int = typer.Option(
        600, "--timeout", min=60, help="Per-attempt timeout for small benchmark slices"
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
):
    """Validate a fix candidate with local checks and a fail-fast benchmark gate."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        report = validate_fix_candidate(
            candidate_id,
            loop_profile_id=profile_id,
            timeout_s=timeout,
        )
        payload = {"validation_report": asdict(report)}
        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(payload)))
            raise typer.Exit(0)

        _render_validation_report(report)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command("repo-repair-context")
def agent_repo_repair_context(
    top_n: int = typer.Option(
        8, "--top", min=1, max=50, help="Maximum motif/candidate rows to include"
    ),
    persist: bool = typer.Option(
        True,
        "--persist/--no-persist",
        help="Persist the artifact under data/autoresearch",
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
):
    """Build an agent-readable repo repair context artifact from recent autoresearch state."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        payload = generate_repo_repair_context(top_n=top_n, persist=persist)
        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(payload)))
            raise typer.Exit(0)

        _render_repo_repair_context_table(payload)
        persisted_files = payload.get("persisted_files") or []
        if persisted_files:
            console.print(
                "[dim]Persisted:[/dim] "
                + ", ".join(str(path) for path in persisted_files)
            )
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


def _render_harness_scaffold_report(report: HarnessScaffoldResult) -> None:
    console.print(
        f"\n[bold green]✓ Scaffolded {report.task_id}[/bold green] "
        f"for motif `[cyan]{report.motif_family}[/cyan]`"
    )
    console.print(f"[bold]Title:[/bold] {report.title}")
    console.print(f"[bold]Activation:[/bold] {report.activation_mode}")
    console.print(f"[bold]Profile:[/bold] {report.profile}")
    console.print(f"[bold]Task Root:[/bold] {report.task_root}")
    if report.created_paths:
        console.print("[bold]Created:[/bold]")
        for path in report.created_paths:
            console.print(f"  - {path}")
    if report.updated_paths:
        console.print("[bold]Updated:[/bold]")
        for path in report.updated_paths:
            console.print(f"  - {path}")
    if report.warnings:
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in report.warnings:
            console.print(f"  - {warning}")


@app.command("scaffold-harness-task")
def agent_scaffold_harness_task(
    motif_family: str = typer.Argument(..., help="Failure motif family to scaffold"),
    task_id: str | None = typer.Option(
        None, "--task-id", help="Explicit HARNESS-XXX ID (defaults to next available)"
    ),
    title: str | None = typer.Option(
        None, "--title", help="Custom task title (defaults to family template)"
    ),
    activate: bool = typer.Option(
        False,
        "--activate/--draft",
        help="Register as active task_ids/canary_task_ids instead of draft scaffold fields",
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table | json"
    ),
):
    """Scaffold a new HARNESS task skeleton plus draft benchmark registrations."""
    try:
        fmt = output_format.strip().lower()
        if fmt not in {"table", "json"}:
            console.print("[red]Error:[/red] --format must be one of: table, json")
            raise typer.Exit(1)

        report = scaffold_harness_task(
            motif_family,
            task_id=task_id,
            title=title,
            activate=activate,
        )
        payload = {"harness_scaffold": asdict(report)}
        if fmt == "json":
            console.print_json(data=json.loads(json.dumps(payload)))
            raise typer.Exit(0)

        _render_harness_scaffold_report(report)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
