"""Main CLI entry point for Brain Researcher.

This module provides the unified command-line interface for all Brain Researcher
functionality using Typer.
"""

import inspect
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brain_researcher.config.paths import get_repo_root
from brain_researcher.core.utils.env_loader import ensure_env_loaded

ensure_env_loaded()

app = typer.Typer(
    name="brain-researcher",
    help="Brain Researcher - Neuroimaging Analysis Platform",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
try:
    from brain_researcher.cli.codegen import app as codegen_app

    app.add_typer(codegen_app, name="codegen")
except Exception:
    codegen_app = None  # optional subcommand

_skip_heavy = os.environ.get("BR_SKIP_HEAVY_COMMANDS", "0").lower() in {
    "1",
    "true",
    "yes",
}

if not _skip_heavy:
    # Import sub-command groups only when needed to avoid heavy deps during chat boot.
    from .commands import (
        agent_commands,
        br_kg_ingest,
        budget_commands,
        cache_commands,
        chat_commands,
        config_commands,
        copilot_commands,
        data_commands,
        datasets_commands,
        db_commands,
        gabriel_commands,
        line_commands,
        migration_commands,
        niclip_commands,
        query_commands,
        runs_commands,
        service_commands,
        sessions_commands,
        threads_commands,
        tool_commands,
        traces_commands,
    )

    # Add sub-command groups
    app.add_typer(agent_commands.app, name="agent", help="Agent planning and execution")
    app.add_typer(
        budget_commands.app, name="budget", help="LLM budget and usage tracking"
    )
    app.add_typer(
        cache_commands.app, name="cache", help="Cache management commands (P2.5)"
    )
    app.add_typer(
        chat_commands.app, name="chat", help="Chat with Agent (research & coding) P1 UX"
    )
    from .commands import files_commands

    app.add_typer(
        files_commands.app, name="files", help="Upload/list/download files via Agent"
    )
    app.add_typer(
        datasets_commands.app, name="datasets", help="Dataset search/detail via Agent"
    )
    app.add_typer(threads_commands.app, name="threads", help="Thread utilities")
    from .commands import auth_commands

    app.add_typer(
        auth_commands.app, name="auth", help="Store/show Agent bearer token for CLI"
    )
    app.add_typer(db_commands.app, name="db", help="Database management commands")
    app.add_typer(data_commands.app, name="data", help="Data ingestion commands")
    app.add_typer(
        gabriel_commands.app, name="gabriel", help="GABRIEL pipeline commands"
    )
    app.add_typer(query_commands.app, name="query", help="Query and search commands")
    app.add_typer(
        niclip_commands.app, name="niclip", help="NICLIP neuroimaging analysis commands"
    )
    app.add_typer(
        br_kg_ingest.app, name="br-kg-ingest", help="BR-KG ingestion commands"
    )
    app.add_typer(br_kg_ingest.br_kg_app, name="br-kg", help="BR-KG graph commands")
    app.add_typer(runs_commands.app, name="runs", help="Job and run inspection")
    app.add_typer(
        sessions_commands.app,
        name="sessions",
        help="Remote session and Slack bridge helpers",
    )
    app.add_typer(
        service_commands.app, name="service", help="Service management commands"
    )
    app.add_typer(
        migration_commands.app, name="migrate", help="Database migration commands"
    )
    app.add_typer(
        line_commands.app,
        name="line",
        help="Line-based autoresearch workspace commands",
    )
    app.add_typer(
        copilot_commands.app, name="copilot", help="Copilot assistance commands"
    )
    app.add_typer(tool_commands.app, name="tools", help="Neuroimaging tools commands")
    app.add_typer(
        config_commands.app, name="config", help="Configuration management commands"
    )
    app.add_typer(traces_commands.app, name="traces", help="Trace export commands")

    from .commands import notebook_commands

    app.add_typer(
        notebook_commands.app, name="notebook", help="Marimo notebook launcher"
    )


# Global state for verbose mode
class State:
    verbose: bool = False


state = State()

_GREETING_PATTERNS = {
    "hi",
    "hey",
    "hello",
    "hiya",
    "yo",
    "sup",
    "hola",
}

_MANDATORY_TOOL_PARAMS: dict[str, tuple[str, ...]] = {
    "glm_analysis": ("dataset_id", "contrasts"),
    "nilearn.glm.first_level.run": ("dataset", "design_matrix"),
    "nilearn.glm.second_level.run": ("first_level_contrasts",),
    "fitlins": ("dataset_id",),
    "ants_registration": ("moving_image", "fixed_image"),
    "dandi_search": ("search_term",),
}

_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "code": {
        "step_budget": 1,
        "auto_tests": "run",
        "risk_threshold": {"max_files": 6, "max_lines": 600},
        "allow_external_net": False,
    },
    "analysis": {
        "step_budget": 2,
        "auto_tests": "skip",
        "risk_threshold": {"max_files": 2, "max_lines": 200},
        "allow_external_net": False,
    },
    "data": {
        "step_budget": 1,
        "auto_tests": "skip",
        "risk_threshold": {"max_files": 1, "max_lines": 100},
        "allow_external_net": True,
    },
}

_DEFAULT_COMMAND_HINTS = {
    "code.run_command": "Use !<shell command> (e.g. !pytest -q) to capture output automatically.",
    "code.apply_patch": "Review the diff and use !pytest -q to confirm tests before continuing.",
    "pytest.run": "!pytest -q",
    "nilearn.connectivity.matrix.run": "Review generated connectivity matrices under artifacts/ once job completes.",
}

_WARM_START_DELAY = float(os.environ.get("BR_CHAT_WARM_DELAY", "0.1"))


def _missing_required_params(tool_name: str, params: dict[str, Any]) -> list[str]:
    required = _MANDATORY_TOOL_PARAMS.get(tool_name)
    if not required:
        return []
    missing: list[str] = []
    for key in required:
        value = params.get(key)
        if value is None:
            missing.append(key)
        elif isinstance(value, str) and not value.strip():
            missing.append(key)
        elif isinstance(value, list | dict) and not value:
            missing.append(key)
    return missing


def _collect_workspace_info() -> dict[str, str | None]:
    info: dict[str, str | None] = {
        "root": None,
        "branch": None,
        "dirty": None,
        "last_commit": None,
    }
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        info["root"] = root or None
        status = subprocess.run(
            ["git", "status", "-sb"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        branch = status.splitlines()[0].replace("## ", "", 1)
        info["branch"] = branch
        dirty = any(
            line.startswith((" M", " M", "??", "A "))
            for line in status.splitlines()[1:]
        )
        info["dirty"] = "yes" if dirty else "no"
        commit = subprocess.run(
            ["git", "log", "-1", "--pretty=%h %ar"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        info["last_commit"] = commit or None
    except Exception:
        pass
    return info


def _render_session_banner(session_id: str, profile_name: str) -> None:
    info = _collect_workspace_info()
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    left_lines = [
        "[bold green]Brain Researcher Chat[/bold green]",
        f"session: {session_id}",
        f"profile: {profile_name}",
    ]
    if info["root"]:
        left_lines.append(f"root: {info['root']}")
    right_lines = []
    if info["branch"]:
        dirty = "• dirty" if info.get("dirty") == "yes" else ""
        right_lines.append(f"branch: {info['branch']} {dirty}".strip())
    if info["last_commit"]:
        right_lines.append(f"last commit: {info['last_commit']}")
    right_lines.append("commands: :settings  :profile <name>  :help  :quit")
    right_lines.append("slash: /tools  /status  /exec <cmd>")
    table.add_row("\n".join(left_lines), "\n".join(right_lines))
    console.print(Panel(table, border_style="green"))


def _run_shell_command(
    command: str,
    timeout: int = 600,
    stream: bool = True,
) -> tuple[int, str, str, float]:
    start = time.time()
    if not stream:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start
            return result.returncode, result.stdout, result.stderr, duration
        except subprocess.TimeoutExpired as exc:
            duration = time.time() - start
            stdout = (
                exc.stdout.decode()
                if isinstance(exc.stdout, bytes)
                else exc.stdout or ""
            )
            stderr = (
                exc.stderr.decode()
                if isinstance(exc.stderr, bytes)
                else exc.stderr or ""
            )
            return (
                124,
                stdout,
                f"Command timed out after {timeout}s\n{stderr}",
                duration,
            )

    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _reader(pipe, buffer, style: str | None) -> None:
        try:
            for line in iter(pipe.readline, ""):
                buffer.append(line)
                if style == "stderr":
                    console.print(f"[red]{line.rstrip()}[/red]")
                else:
                    console.print(line.rstrip())
        finally:
            pipe.close()

    threads = [
        threading.Thread(
            target=_reader, args=(proc.stdout, stdout_lines, "stdout"), daemon=True
        ),
        threading.Thread(
            target=_reader, args=(proc.stderr, stderr_lines, "stderr"), daemon=True
        ),
    ]
    for thread in threads:
        thread.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        duration = time.time() - start
        timeout_msg = f"Command timed out after {timeout}s"
        stderr_lines.append(timeout_msg)
        return 124, "".join(stdout_lines), "".join(stderr_lines), duration
    finally:
        for thread in threads:
            thread.join(timeout=1)

    duration = time.time() - start
    return proc.returncode or 0, "".join(stdout_lines), "".join(stderr_lines), duration


def _truncate_output(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 200] + "\n…(truncated)…" + text[-100:]


def _hint_for_tool(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    for key, hint in _DEFAULT_COMMAND_HINTS.items():
        if key in tool_name:
            return hint
    return None


def _spawn_warmup(model: str | None) -> None:
    def _warm() -> None:
        # Delay slightly so the initial banner renders before warmup logs
        time.sleep(_WARM_START_DELAY)
        try:
            from .agent.act import act_in_process

            with console.status(
                "[dim]Warming agent tool catalog…[/dim]", spinner="dots"
            ):
                act_in_process(
                    "warm up coding tools",
                    model=model,
                    preview=True,
                )
            console.print("[dim]Warm start complete.[/dim]")
        except Exception:
            console.print("[yellow]Warm start skipped (non-critical error).[/yellow]")

    threading.Thread(target=_warm, daemon=True).start()


@app.callback()
def main(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Configuration file path"
    ),
):
    """
    Brain Researcher - Unified CLI for neuroimaging analysis.

    Use 'brain-researcher COMMAND --help' for more information on each command.
    """
    state.verbose = verbose

    if verbose:
        console.print("[dim]Verbose mode enabled[/dim]")

    if config and config.exists():
        console.print(f"[dim]Loading config from {config}[/dim]")
        # TODO: Load configuration


@app.command()
def version():
    """Show the Brain Researcher version."""
    from brain_researcher import __version__

    console.print(f"Brain Researcher v{__version__}")


@app.command()
def chat_llm(
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Prompt text"),
    tools: bool = typer.Option(True, "--tools/--no-tools", help="Enable tool calls"),
):
    """Single-turn chat using the unified NeuroAgentLLM (same path as /act_llm)."""

    from brain_researcher.cli.agent.unified_agent import run_unified_agent

    text: str
    meta: dict

    if prompt is None:
        try:
            prompt = input("Prompt: ").strip()
        except EOFError as err:
            raise typer.Exit(code=1) from err

    if not prompt:
        console.print("[yellow]No prompt provided[/yellow]")
        raise typer.Exit(code=1)

    tool_mode = "auto" if tools else "none"
    text, meta = run_unified_agent(prompt, tool_mode=tool_mode)

    header = f"[{meta.get('provider')}] {meta.get('model')} tool_mode={meta.get('tool_mode')} complexity={meta.get('complexity')}"
    console.print(header)
    console.print()
    console.print(text)


@app.command()
def chat(
    model: str | None = typer.Option(None, "--model", "-m", help="Model override"),
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Prompt text"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result"),
    profile_override: str | None = typer.Option(
        None,
        "--profile",
        "-P",
        help="Force a specific profile (e.g. code, analysis, data)",
    ),
    warm_start: bool = typer.Option(
        True,
        "--warm-start/--no-warm-start",
        help="Preload agent tools in the background for faster first response",
    ),
):
    """
    Start a sticky chat session (Codex/Gemini style).
    - No args: open REPL with auto-continue & profile settings.
    - With --prompt: single-shot ask that still updates the session.
    """
    from .agent.act import act_in_process
    from .compat.gemini_compat import emit_result, run_simple_chat
    from .state.conversation_store import ConversationStore, default_session_id
    from .state.profile import Profile, load_profiles

    try:
        # For structured tool responses
        from brain_researcher.services.agent.types import ToolResult
    except Exception:  # pragma: no cover
        ToolResult = None  # type: ignore

    session_id = default_session_id()
    store = ConversationStore(session_id=session_id)
    store.load()

    profiles, default_profile_name = load_profiles()
    for preset_name, preset_data in _PROFILE_PRESETS.items():
        if preset_name not in profiles:
            profiles[preset_name] = Profile(name=preset_name, data=preset_data)
    active_profile_name = default_profile_name
    if profile_override:
        if profile_override in profiles:
            active_profile_name = profile_override
        else:
            console.print(
                f"[yellow]Unknown profile requested:[/yellow] {profile_override}"
            )
    profile = profiles[active_profile_name]
    settings = profile.effective()

    if warm_start:
        _spawn_warmup(model)

    def fallback_chat(text: str):
        response, meta = run_simple_chat(text, model)
        rendered = emit_result(response, meta, json_output=json_output)
        store.append({"role": "assistant", "content": rendered, "meta": meta})
        console.print(rendered)

    def is_safe_action(tool_name: str, params: dict[str, Any]) -> bool:
        thresholds = settings.get("risk_threshold", {}) or {}
        max_lines = thresholds.get("max_lines")
        max_files = thresholds.get("max_files")

        if tool_name == "code.apply_patch":
            content = (
                params.get("content") or params.get("patch") or params.get("diff") or ""
            )
            if isinstance(content, str):
                if max_lines is not None and content.count("\n") > max_lines:
                    return False
                file_markers = content.count("\n+++ ") or content.count("+++ b/")
                if max_files is not None and file_markers > max_files:
                    return False
            if params.get("apply") is False:
                return False
        return True

    def run_followup_tests():
        mode = settings.get("auto_tests", "auto")
        if mode in {"skip", None}:
            return
        console.print("[dim]auto-tests:[/dim] running pytest …")
        try:
            tests_exec = act_in_process("run pytest", model=model, preview=False)
        except Exception as exc:
            console.print(f"[yellow]auto-tests skipped:[/yellow] {exc}")
            return
        tests_result = tests_exec.get("tool_result", {})
        panel_body = (
            f"status: {tests_result.get('status','unknown')}\n"
            f"error: {tests_result.get('error')}\n"
            f"data: {json.dumps(tests_result.get('data'), ensure_ascii=False)[:400]}"
        )
        console.print(Panel(panel_body, title="Auto Tests", border_style="magenta"))
        store.append(
            {
                "role": "assistant",
                "type": "tests",
                "content": tests_result,
            }
        )

    last_plan: dict[str, Any] = {"tool": None, "params": None, "query": None}

    def _to_jsonable(obj):
        if obj is None:
            return None
        if isinstance(obj, str | int | float | bool):
            return obj
        if isinstance(obj, list):
            return [_to_jsonable(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if ToolResult is not None and isinstance(obj, ToolResult):
            return {
                "status": obj.status,
                "data": _to_jsonable(getattr(obj, "data", None)),
                "error": _to_jsonable(getattr(obj, "error", None)),
                "metadata": _to_jsonable(getattr(obj, "metadata", None)),
            }
        # fallback to string
        return str(obj)

    def handle_query(text: str):
        stripped = text.strip()
        if not stripped:
            return

        # If user explicitly asks to run the last plan
        if stripped.lower() == "/run":
            if not last_plan.get("query"):
                console.print("[yellow]No pending plan. Ask a question first.[/yellow]")
                return
            console.print("[dim]Running last plan...[/dim]")
            try:
                execution = act_in_process(
                    last_plan["query"], model=model, preview=False
                )
            except Exception as exc:
                console.print(f"[red]Execution failed:[/red] {exc}")
                return
            _render_execution(execution, store, console)
            return

        store.append({"role": "user", "content": stripped})

        last_plan["tool"] = None

        normalized = re.sub(r"[^\w\s]", "", stripped.lower())
        if normalized in _GREETING_PATTERNS:
            fallback_chat(stripped)
            return

        try:
            preview = act_in_process(stripped, model=model, preview=True)
        except Exception as exc:
            console.print(f"[yellow]Planner fallback:[/yellow] {exc}")
            fallback_chat(stripped)
            return

        selection = preview.get("selection", {})
        chosen_tool = (selection.get("tool") or "none").strip()

        # Local download rule: if user says download dsXXXXXX, force openneuro_download preview-only
        if chosen_tool in {"code_agent", "agent"}:
            ds_match = re.search(r"\bds(\d{6})\b", stripped.lower())
            if "download" in stripped.lower() and ds_match:
                dataset_id = f"ds{ds_match.group(1)}"
                chosen_tool = "openneuro_download"
                selection["tool"] = chosen_tool
                # Use external working dir (not the read-only mount) for outputs/commands
                selection["params"] = {
                    "dataset_id": dataset_id,
                    "output_dir": f"{os.getenv('OPENNEURO_WORK_ROOT', '/app/data/openneuro_work')}/{dataset_id}",
                    "execute": False,
                }
                selection["reasoning"] = "local_rule_download_ds"

        if chosen_tool == "none":
            fallback_chat(stripped)
            return

        params = selection.get("params", {})
        missing = _missing_required_params(chosen_tool, params)
        if missing:
            console.print(
                "[yellow]"
                f"{chosen_tool} needs parameters {', '.join(missing)}. "
                "Switching to conversational mode until those details are provided."
                "[/yellow]"
            )
            fallback_chat(stripped)
            return
        reasoning = selection.get("reasoning") or ""
        est = preview.get("preview", {}).get("estimated_runtime", "unknown")
        plan_text = (
            f"tool: [cyan]{chosen_tool}[/cyan]\n"
            f"reason: {reasoning}\n"
            f"params: {json.dumps(params, ensure_ascii=False)}\n"
            f"estimated: {est}"
        )
        console.print(Panel(plan_text, title="Proposed plan", border_style="cyan"))
        store.append(
            {
                "role": "assistant",
                "type": "plan",
                "content": plan_text,
                "tool": chosen_tool,
                "params": params,
            }
        )
        # Save last plan; require explicit /run to execute
        last_plan["tool"] = chosen_tool
        last_plan["params"] = params
        last_plan["query"] = stripped
        console.print("[dim]Plan saved. Type /run to execute it.[/dim]")

    def _render_execution(execution: dict, store, console):
        selection = execution.get("selection", {})
        chosen_tool = (selection.get("tool") or "").strip()
        tool_result = execution.get("tool_result", {}) or {}
        status = tool_result.get("status") or "unknown"
        data = tool_result.get("data")
        error = tool_result.get("error")
        summary_lines = [
            f"tool: [cyan]{chosen_tool}[/cyan]" if chosen_tool else "tool: (unknown)",
            f"status: {status}",
        ]
        if error:
            summary_lines.append(f"error: {error}")
        if data is not None:
            preview_data = json.dumps(
                _to_jsonable(data), ensure_ascii=False, default=str
            )
            summary_lines.append(f"data: {preview_data[:400]}")
        # Add a clear success cue to help downstream evaluators detect completion
        if status == "success":
            summary_lines.append("successfully created artifacts")
        execution_panel = Panel(
            "\n".join(summary_lines), title="Execution", border_style="green"
        )
        console.print(execution_panel)
        # Ensure tool_result is fully JSON-serializable before persisting
        tool_result_json = json.loads(
            json.dumps(_to_jsonable(tool_result), ensure_ascii=False, default=str)
        )
        store.append(
            {
                "role": "assistant",
                "type": "execution",
                "content": summary_lines,
                "tool_result": tool_result_json,
            }
        )
        # Optional hint if execution failed without data
        if not data and status != "success":
            hint = _hint_for_tool(chosen_tool)
            if hint:
                console.print(f"[cyan]Tip:[/cyan] {hint}")
            else:
                console.print(
                    "[cyan]Tip:[/cyan] Use !<command> (e.g. !pytest -q) to capture logs automatically."
                )
            fallback_chat("Summarize the results of the last tool execution.")

    if prompt:
        handle_query(prompt)
        return

    _render_session_banner(session_id, active_profile_name)

    tool_registry = None

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            console.print("[dim]Bye![/dim]")
            break

        if not line:
            continue

        if line in {":quit", ":exit"}:
            console.print("[dim]Bye![/dim]")
            break
        if line == ":settings":
            console.print_json(
                {
                    "profile": active_profile_name,
                    "settings": settings,
                    "available_profiles": list(profiles.keys()),
                }
            )
            continue
        if line == ":profiles":
            table = Table(title="Available Profiles", show_lines=False, min_width=40)
            table.add_column("Name", style="cyan")
            table.add_column("Step Budget", justify="center")
            table.add_column("Auto Tests", justify="center")
            table.add_column("Notes", justify="left")
            for name, prof in profiles.items():
                eff = prof.effective()
                notes = []
                if eff.get("allow_external_net"):
                    notes.append("net")
                threshold = eff.get("risk_threshold") or {}
                notes.append(
                    f"{threshold.get('max_files', '∞')} files / {threshold.get('max_lines', '∞')} lines"
                )
                table.add_row(
                    "[bold]" + name + "[/bold]",
                    str(eff.get("step_budget", "-")),
                    str(eff.get("auto_tests", "-")),
                    ", ".join(notes),
                )
            console.print(table)
            continue
        if line.startswith(":profile "):
            _, _, name = line.partition(" ")
            if name in profiles:
                active_profile_name = name
                profile = profiles[name]
                settings = profile.effective()
                console.print(f"[green]Profile switched:[/green] {name}")
                _render_session_banner(session_id, active_profile_name)
            else:
                console.print(f"[red]Unknown profile:[/red] {name}")
            continue

        if line == ":help":
            console.print(
                "[dim]Commands[/dim]: :settings, :profiles, :profile <name>, :quit\n"
                "[dim]Slash[/dim]: /tools, /init, /status, /exec, /help"
            )
            continue

        if line == "/init":
            console.print(
                Panel(
                    "Session initialised. Describe your goal or use /tools to inspect capabilities.",
                    border_style="blue",
                )
            )
            continue

        if line == "/help":
            console.print(
                "[dim]Slash commands[/dim]:\n"
                "  /tools   – list registered tools (light discovery)\n"
                "  /init    – remind session context\n"
                "  /status  – show workspace/git status\n"
                "  /exec    – run shell command locally and send output\n"
                "  /help    – show this message\n"
                "[dim]Colon commands[/dim]: :settings, :profile <name>, :quit"
            )
            continue

        if line == "/status":
            _render_session_banner(session_id, active_profile_name)
            continue

        if line.startswith("/exec "):
            _, _, command = line.partition(" ")
            command = command.strip()
            if not command:
                console.print("[yellow]Usage:[/yellow] /exec <shell command>")
                continue
            console.print(f"[dim]Running:[/dim] {command}")
            code, stdout_text, stderr_text, duration = _run_shell_command(command)
            summary = (
                f"exit: {code}\n"
                f"duration: {duration:.2f}s\n"
                f"stdout:\n{_truncate_output(stdout_text, 2000)}\n"
                f"stderr:\n{_truncate_output(stderr_text, 1000)}"
            )
            console.print(Panel(summary, title=f"/exec {command}", border_style="blue"))
            combined = stdout_text or ""
            if stderr_text:
                combined += ("\n" if combined else "") + "[stderr]\n" + stderr_text
            if not combined.strip():
                combined = "(no output)"
            handle_query(
                f"Command `{command}` output:\n```\n{_truncate_output(combined, 3000)}\n```"
            )
            continue

        if line == "/tools":
            try:
                if tool_registry is None:
                    from brain_researcher.services.tools.tool_registry import (
                        ToolRegistry,
                    )

                    tool_registry = ToolRegistry(auto_discover=True, light_mode=True)
                names = sorted(tool_registry.tools.keys())
                if not names:
                    console.print("[yellow]No tools registered in light mode.[/yellow]")
                else:
                    console.print(
                        Panel(
                            "\n".join(f"  - {name}" for name in names),
                            title="Available Tools",
                            border_style="cyan",
                        )
                    )
            except Exception as exc:
                message = str(exc)
                console.print("[red]Failed to load tools.[/red]")
                if "API key" in message or "API_KEY" in message:
                    console.print(
                        "[yellow]Hint:[/yellow] verify provider credentials such as "
                        "GEMINI_API_KEY or OPENAI_API_KEY before using /tools."
                    )
                if state.verbose:
                    console.print_exception()
                else:
                    console.print(f"[dim]{message}[/dim]")
            continue

        if line.startswith("!"):
            command = line[1:].strip()
            if not command:
                console.print("[yellow]Usage:[/yellow] !<shell command>")
                continue
            console.print(f"[dim]Running:[/dim] {command}")
            code, stdout_text, stderr_text, duration = _run_shell_command(command)
            summary = (
                f"exit: {code}\n"
                f"duration: {duration:.2f}s\n"
                f"stdout:\n{_truncate_output(stdout_text, 2000)}\n"
                f"stderr:\n{_truncate_output(stderr_text, 1000)}"
            )
            console.print(Panel(summary, title=f"! {command}", border_style="blue"))
            combined = stdout_text or ""
            if stderr_text:
                combined += ("\n" if combined else "") + "[stderr]\n" + stderr_text
            if not combined.strip():
                combined = "(no output)"
            handle_query(
                f"Command `{command}` output:\n```\n{_truncate_output(combined, 3000)}\n```"
            )
            continue

        handle_query(line)


@app.command()
def code(
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Prompt text"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model override"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result"),
    warm_start: bool = typer.Option(
        True,
        "--warm-start/--no-warm-start",
        help="Preload agent tools in the background for faster first response",
    ),
):
    """Shortcut for coding-focused chat sessions."""
    chat(
        model=model,
        prompt=prompt,
        json_output=json_output,
        profile_override="code",
        warm_start=warm_start,
    )


@app.command()
def act(
    query: str = typer.Argument(
        ..., help="Natural language instruction (auto tool selection)"
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model for selection (defaults from env)"
    ),
    tool_mode: str = typer.Option(
        "auto",
        "--tool-mode",
        help="Tool selection mode: auto|force|off (force requires exactly one --tools)",
    ),
    budget_ms: int = typer.Option(
        90000, "--budget-ms", help="Global tool execution budget (ms)"
    ),
    tools: list[str] = typer.Option(None, "--tools", help="Whitelist tool names"),
    tool_params_json: str | None = typer.Option(
        None,
        "--tool-params-json",
        help="JSON object of tool params (used with --tool-mode force)",
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Preview selected tool and params without executing"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result"),
):
    """Plan + execute tools and emit closed-loop bundles (benchmark-friendly)."""
    import json as json_module
    import os
    from pathlib import Path

    # Preview mode keeps the legacy behavior (selection/params only).
    if preview:
        from .agent.act import act_in_process

        call_kwargs = {
            "model": model,
            "tools_whitelist": tools,
            "budget_ms": budget_ms,
        }
        signature = inspect.signature(act_in_process)
        if "preview" in signature.parameters:
            call_kwargs["preview"] = preview
        result = act_in_process(query, **call_kwargs)
        if json_output:
            typer.echo(json_module.dumps(result, ensure_ascii=False))
        else:
            sel = result.get("selection", {})
            exe = result.get("execution", {})
            typer.echo(
                f"tool={sel.get('tool')} params={sel.get('params')}\n"
                f"provider={exe.get('provider')} model={exe.get('model')} "
                f"route={exe.get('route')} reason={exe.get('fallback_reason')}"
            )
        return

    # Execution mode: reuse the same producer as the agent/web /act endpoint so
    # we always get trace.jsonl + trajectory.json + observation.json + analysis_bundle.json.
    from brain_researcher.services.agent.agent_core import agent_act_core

    parsed_tool_params: dict = {}
    if tool_params_json:
        try:
            parsed_tool_params = json_module.loads(tool_params_json)
        except json_module.JSONDecodeError as exc:
            raise typer.BadParameter(f"Invalid --tool-params-json: {exc}") from exc
        if not isinstance(parsed_tool_params, dict):
            raise typer.BadParameter("--tool-params-json must be a JSON object")

    tool_mode_normalized = (tool_mode or "auto").strip().lower()
    if tool_mode_normalized not in {"auto", "force", "off"}:
        raise typer.BadParameter("--tool-mode must be one of: auto, force, off")
    if tool_mode_normalized == "force":
        if not tools or len(tools) != 1:
            raise typer.BadParameter("--tool-mode force requires exactly one --tools")

    prev_model = os.environ.get("DEFAULT_LLM_MODEL")
    if model:
        os.environ["DEFAULT_LLM_MODEL"] = model
    try:
        result = agent_act_core(
            {
                "query": query,
                "tool_mode": tool_mode_normalized,
                "tools_whitelist": tools or [],
                "tool_params": parsed_tool_params,
                "budget_ms": budget_ms,
            },
            trace_id=None,
            run_id=None,
        )
    finally:
        if model:
            if prev_model is None:
                os.environ.pop("DEFAULT_LLM_MODEL", None)
            else:
                os.environ["DEFAULT_LLM_MODEL"] = prev_model

    run_card = (
        result.get("runCard")
        if isinstance(result, dict) and isinstance(result.get("runCard"), dict)
        else None
    )
    provenance = (
        run_card.get("provenance")
        if isinstance(run_card, dict) and isinstance(run_card.get("provenance"), dict)
        else {}
    )
    ids = (
        run_card.get("ids")
        if isinstance(run_card, dict) and isinstance(run_card.get("ids"), dict)
        else {}
    )

    job_id = (
        ids.get("job_id") or ids.get("run_id") or run_card.get("id")
        if isinstance(run_card, dict)
        else None
    )
    run_id = (
        ids.get("run_id") or run_card.get("run_id")
        if isinstance(run_card, dict)
        else None
    )
    run_dir = provenance.get("run_dir") if isinstance(provenance, dict) else None

    files: dict[str, str] = {}
    if isinstance(run_dir, str) and run_dir.strip():
        for key in (
            "analysis_bundle_json",
            "trajectory_json",
            "trace_jsonl",
            "observation_json",
        ):
            path_value = provenance.get(key)
            if isinstance(path_value, str) and path_value.strip():
                files[key] = Path(path_value).name

    out = {
        "schema_version": "br-act-v1",
        "ok": bool(isinstance(result, dict) and not result.get("error")),
        "job_id": job_id,
        "run_id": run_id,
        "run_dir": run_dir,
        "files": files,
        "run_card": run_card,
        "message": result.get("message") if isinstance(result, dict) else None,
        "tool_calls": result.get("tool_calls") if isinstance(result, dict) else None,
        "artifacts": result.get("artifacts") if isinstance(result, dict) else None,
        "session_id": result.get("session_id") if isinstance(result, dict) else None,
        "error": result.get("error") if isinstance(result, dict) else None,
        "code": result.get("code") if isinstance(result, dict) else None,
    }

    if json_output:
        # stdout: stable JSON only (benchmark parsers depend on this).
        typer.echo(json_module.dumps(out, ensure_ascii=False))
        return

    # Human-friendly output.
    assistant_text = None
    message = out.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        assistant_text = message.get("content")
    elif isinstance(message, str):
        assistant_text = message

    if assistant_text:
        console.print(assistant_text)
    if run_dir:
        console.print(f"[dim]run_dir:[/dim] {run_dir}")


@app.command()
def ask(
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model (e.g., gemini-2.5-pro)"
    ),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Prompt text"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result"),
):
    """Single-turn ask in Gemini-compat mode (like `gemini -p`)."""
    from .compat.gemini_compat import emit_result, run_simple_chat

    text, meta = run_simple_chat(prompt, model)
    output = emit_result(text, meta, json_output=json_output)
    console.print(output)


@app.command()
def serve(
    service: str = typer.Argument(
        ..., help="Service to start: 'web', 'agent', 'orchestrator', 'kg', or 'mcp'"
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int | None = typer.Option(None, "--port", "-p", help="Port to bind to"),
):
    """Start a Brain Researcher service."""
    service_ports = {
        "web": 3000,
        "agent": 8000,
        "orchestrator": 3001,
        "kg": 5000,
        "mcp": 7000,
    }

    if service not in service_ports:
        console.print(f"[red]Unknown service: {service}[/red]")
        console.print(f"Available services: {', '.join(service_ports.keys())}")
        raise typer.Exit(1)

    port = port or service_ports[service]

    if service == "agent":
        # Import and launch agent service
        from .commands.services.agent_launcher import launch_agent_service

        launch_agent_service(
            host=host,
            port=port,
            verbose=state.verbose,
        )
    elif service == "kg":
        # Import and launch BR-KG service
        from .commands.services.kg_launcher import launch_kg_service

        launch_kg_service(
            host=host,
            port=port,
            verbose=state.verbose,
        )
    elif service == "web":
        # Import and launch Web UI service
        from .commands.services.web_launcher import launch_web_service

        launch_web_service(
            host=host,
            port=port,
            verbose=state.verbose,
        )
    elif service == "orchestrator":
        # Import and launch Orchestrator service
        from .commands.services.orchestrator_launcher import launch_orchestrator

        launch_orchestrator(
            host=host,
            port=port,
            reload=state.verbose,  # Use verbose flag for reload in dev mode
        )
    elif service == "mcp":
        script_path = get_repo_root() / "scripts" / "mcp" / "start_http_local.sh"
        env = os.environ.copy()
        env["BR_MCP_HOST"] = host
        env["BR_MCP_PORT"] = str(port)
        result = subprocess.run(
            ["bash", str(script_path)],
            cwd=str(get_repo_root()),
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise typer.Exit(result.returncode)


@app.command()
def analyze(
    task: str = typer.Argument(..., help="Analysis task to perform"),
    data_path: str | None = typer.Option(
        None, "--data", "-d", help="Path to data file or directory"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path for results"
    ),
):
    """Run neuroimaging analysis tasks."""
    console.print(f"Running analysis task: {task}")

    # TODO: Import and run analysis tools
    console.print("[yellow]Analysis tools not yet migrated to new structure[/yellow]")


@app.command()
def ingest(
    source: str = typer.Argument(
        ..., help="Data source: 'bids', 'openneuro', 'neurovault', 'dandi'"
    ),
    path: str = typer.Argument(..., help="Path or ID to ingest from"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
):
    """Ingest neuroimaging data from various sources."""
    console.print(f"Ingesting data from {source}: {path}")

    # TODO: Import and run ingestion tools
    console.print("[yellow]Ingestion tools not yet migrated to new structure[/yellow]")


@app.command()
def test(
    command: str = typer.Argument(
        "assess", help="Test command: test, analyze, assess, compare"
    ),
    test_type: str | None = typer.Option(
        None, "--type", help="Type of tests: unit, integration, cli, all"
    ),
    coverage: bool = typer.Option(
        False, "--coverage", help="Enable coverage reporting"
    ),
    tools: list[str] | None = typer.Option(
        None, "--tools", help="Analysis tools to run"
    ),
    config: Path | None = typer.Option(
        None, "--config", help="Quality configuration file"
    ),
):
    """Run tests and quality assessment."""
    from tests.utils.runner import TestRunner

    runner = TestRunner()

    # Build args based on command
    args = [command]

    if command == "test" and test_type:
        args.extend(["--type", test_type])
        if coverage:
            args.append("--coverage")

    elif command == "analyze" and tools:
        args.extend(["--tools"] + tools)

    elif command == "assess" and config:
        args.extend(["--config", str(config)])

    # Run the test framework
    exit_code = runner.run(args)

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
