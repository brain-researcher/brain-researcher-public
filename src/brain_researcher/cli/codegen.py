import json
from typing import List, Optional

import typer

from brain_researcher.services.agent.codegen.render import render_result_for_chat
from brain_researcher.services.tools.llm_router_tool import CodingAgentTool

app = typer.Typer(help="Direct coding agent entrypoint (code_agent).")


@app.command()
def run(
    task: str = typer.Argument(..., help="Coding task (bugfix/refactor/write tests)."),
    paths: List[str] = typer.Option(
        None, "--paths", "-p", help="Files/dirs to focus on", show_default=False
    ),
    tests: List[str] = typer.Option(
        None, "--tests", "-t", help="Test commands to run", show_default=False
    ),
    apply: bool = typer.Option(False, "--apply", help="Apply patches to repo"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview apply without writing"
    ),
    max_iters: int = typer.Option(3, "--max-iters", help="Max codegen iterations"),
    json_output: bool = typer.Option(False, "--json", help="Emit raw JSON result"),
):
    """Run the coding agent directly (non-interactive)."""

    tool = CodingAgentTool()
    if max_iters > 0:
        tool._code_loop.max_iters = max_iters  # noqa: SLF001

    result = tool._run(
        instruction=task,
        file_paths=paths or None,
        test_command=tests[0] if tests else None,
        apply=apply,
        dry_run=dry_run,
        max_iters=max_iters,
    )

    data = result.data or {}
    if json_output:
        typer.echo(
            json.dumps(
                {"status": result.status, "data": data, "error": result.error},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise typer.Exit(code=0 if result.status == "success" else 1)

    if data.get("summary"):
        typer.echo(data["summary"])
    else:
        typer.echo(render_result_for_chat(_to_codegen_result(data)))

    if data.get("apply_logs"):
        typer.echo("\n".join(data["apply_logs"]))

    if data.get("patches") and not apply:
        typer.echo("\n--- Suggested patch (not applied) ---")
        for p in data["patches"]:
            typer.echo(p)

    raise typer.Exit(code=0 if result.status == "success" else 1)


def _to_codegen_result(data: dict):
    from brain_researcher.services.agent.codegen.context import (
        CodegenResult,
        ExecutionResult,
    )

    exec_res = None
    if data.get("exec_stdout") is not None or data.get("exec_stderr") is not None:
        exec_res = ExecutionResult(
            success=data.get("test_status") == "passed",
            stdout=data.get("exec_stdout") or "",
            stderr=data.get("exec_stderr") or "",
            exit_code=None,
        )

    return CodegenResult(
        status=data.get("status", "unknown"),
        iterations=data.get("iterations", 1),
        response_text=data.get("response", ""),
        patches=data.get("patches") or [],
        files_touched=data.get("files_touched") or [],
        exec_result=exec_res,
        errors=data.get("errors"),
        provider=data.get("provider"),
        model=data.get("model"),
        usage=data.get("usage") or {},
        fallback_reason=data.get("fallback_reason"),
    )


__all__ = ["app"]
