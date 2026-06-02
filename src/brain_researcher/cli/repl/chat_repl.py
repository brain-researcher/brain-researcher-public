from __future__ import annotations

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from brain_researcher.services.agent.tool_metadata_bridge import (
    get_example_payload,
    get_output_examples,
    get_resource_hints,
)

console = Console()


HELP_TEXT = (
    "Commands:\n"
    "  /help                Show this help\n"
    "  /auto                Toggle auto tool mode (LLM picks and runs tools)\n"
    "  /model <name>       Switch model (e.g., gemini-3-flash-preview)\n"
    "  /plan <goal>        Generate a brief plan\n"
    '  /tool <name> [json] Call a tool or view an example payload, e.g. /tool gemini_cli.chat {"prompt":"hi"}\n'
    '  /edit <json>       Apply or dry-run a patch via code.apply_patch (e.g., {"file":"path","content":"...","apply":false})\n'
    '  /test <json>       Run pytest via tests.run (e.g., {"pattern":"tests/unit"})\n'
    "  /preview <text>    Preview selected tool + params for a query (no execution)\n"
    "  /exit | /quit       Exit\n"
)


def run_chat_repl(
    initial_model: Optional[str] = None, json_output: bool = False
) -> None:
    from brain_researcher.cli.compat.gemini_compat import emit_result, run_simple_chat

    model = initial_model
    auto_mode = False
    domain_filter: list[str] = []
    function_filter: list[str] = []
    risk_filter: list[str] = []

    console.print(
        Panel(
            "[bold green]Brain Researcher — Chat (Gemini‑compat)[/bold green]\n"
            "Type a message, or use slash commands. Type /help for options.",
            border_style="green",
        )
    )

    console.print(f"[dim]Model:[/dim] {model or '(default)'}\n")

    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            break

        if not line:
            continue

        if line in {"/exit", "/quit"}:
            console.print("[dim]Bye![/dim]")
            break

        if line == "/help":
            console.print(
                HELP_TEXT
                + "\nFilters: /domain <vals>, /function <vals>, /risk <vals>, /clearfilters"
            )
            continue

        if line == "/auto":
            auto_mode = not auto_mode
            console.print(
                f"[green]✓ Auto tool mode:[/green] {'on' if auto_mode else 'off'}"
            )
            continue

        if line.startswith("/domain "):
            _, _, val = line.partition(" ")
            val = val.strip()
            if val:
                domain_filter = [v.strip() for v in val.split(",") if v.strip()]
                console.print(f"[green]✓ Domain filter:[/green] {domain_filter}")
            continue

        if line.startswith("/function "):
            _, _, val = line.partition(" ")
            val = val.strip()
            if val:
                function_filter = [v.strip() for v in val.split(",") if v.strip()]
                console.print(f"[green]✓ Function filter:[/green] {function_filter}")
            continue

        if line.startswith("/risk "):
            _, _, val = line.partition(" ")
            val = val.strip()
            if val:
                risk_filter = [v.strip() for v in val.split(",") if v.strip()]
                console.print(f"[green]✓ Risk filter:[/green] {risk_filter}")
            continue

        if line == "/clearfilters":
            domain_filter = []
            function_filter = []
            risk_filter = []
            console.print("[green]✓ Cleared domain/function/risk filters[/green]")
            continue

        if line.startswith("/model "):
            _, _, name = line.partition(" ")
            name = name.strip()
            if not name:
                console.print("[yellow]Usage: /model <name>[/yellow]")
                continue
            model = name
            console.print(f"[green]✓ Model changed:[/green] {model}")
            continue

        if line.startswith("/plan "):
            goal = line[len("/plan ") :].strip()
            plan_prompt = (
                "You are a planning assistant. Create a concise, numbered plan for: "
                + goal
            )
            text, meta = run_simple_chat(plan_prompt, model)
            console.print(emit_result(text, meta, json_output=json_output))
            continue

        if line.startswith("/preview "):
            q = line[len("/preview ") :].strip()
            from brain_researcher.cli.agent.act import act_in_process

            # Preview selection only
            result = act_in_process(
                q,
                model=model,
                preview=True,
                domain_filter=domain_filter,
                function_filter=function_filter,
                risk_filter=risk_filter,
            )
            console.print_json(data=result)
            continue

        if line.startswith("/tool "):
            console.print("[red]MCP tool calls are no longer available.")
            continue

        if line.startswith("/edit "):
            console.print("[red]/edit is disabled (MCP removed).")
            continue

        if line.startswith("/test "):
            console.print("[red]/test is disabled (MCP removed).")
            continue

        # Default: auto tool selection (if enabled) or plain chat
        if auto_mode:
            from brain_researcher.cli.agent.act import act_in_process

            # Streaming: provide a progress callback that prints stage updates
            def _progress(ev):
                stage = ev.get("stage")
                msg = ev.get("message")
                console.print(f"[dim]{stage}: {msg}[/dim]")

            result = act_in_process(
                line,
                model=model,
                progress_callback=_progress,
                domain_filter=domain_filter,
                function_filter=function_filter,
                risk_filter=risk_filter,
            )
            console.print_json(data=result)
        else:
            text, meta = run_simple_chat(
                line,
                model,
                domain_filter=domain_filter,
                function_filter=function_filter,
                risk_filter=risk_filter,
            )
            console.print(emit_result(text, meta, json_output=json_output))
