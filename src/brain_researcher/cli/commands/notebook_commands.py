"""Marimo notebook launcher for Brain Researcher.

Provides ``br notebook`` helpers for opening, validating, and onboarding
Marimo notebooks that use the BR SDK.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Marimo notebook launcher")
console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TEMPLATES_DIR = _REPO_ROOT / "notebooks" / "templates"
_MCP_GUIDE = _REPO_ROOT / "docs" / "mcp.md"
_OPERATIONS_GUIDE = _REPO_ROOT / "docs" / "OPERATIONS.md"


def _find_template(name: str) -> Path:
    """Resolve a template name to an absolute path."""
    candidate = Path(name)
    if candidate.exists():
        return candidate.resolve()

    if not name.endswith(".py"):
        name = f"{name}.py"
    builtin = _TEMPLATES_DIR / name
    if builtin.exists():
        return builtin

    console.print(f"[red]Template not found:[/red] {name}")
    console.print(f"Available templates in {_TEMPLATES_DIR}:")
    for p in sorted(_TEMPLATES_DIR.glob("*.py")):
        console.print(f"  {p.stem}")
    raise typer.Exit(1)


def _require_marimo() -> None:
    if not shutil.which("marimo"):
        console.print(
            "[red]marimo is not installed.[/red]  "
            "Install it with: [bold]pip install 'brain_researcher[notebook]'[/bold]"
        )
        raise typer.Exit(1)


@app.command("open")
def open_notebook(
    template: str = typer.Argument("br_quickstart", help="Template name or path"),
    port: int = typer.Option(2718, help="Port for the Marimo editor"),
) -> None:
    """Launch a Marimo notebook with the Brain Researcher SDK configured."""
    _require_marimo()
    path = _find_template(template)
    console.print(f"Opening [bold]{path.name}[/bold] on port {port}")

    env = os.environ.copy()
    env.setdefault("BR_MCP_SERVER_COMMAND", "brain-researcher-mcp")

    os.execvpe(
        "marimo",
        ["marimo", "edit", str(path), "--port", str(port)],
        env,
    )


@app.command("list")
def list_templates() -> None:
    """List available notebook templates."""
    if not _TEMPLATES_DIR.is_dir():
        console.print("[yellow]No templates directory found.[/yellow]")
        raise typer.Exit(0)

    templates = sorted(_TEMPLATES_DIR.glob("*.py"))
    if not templates:
        console.print("[yellow]No templates found.[/yellow]")
        raise typer.Exit(0)

    for p in templates:
        console.print(f"  [bold]{p.stem}[/bold]  {p}")


@app.command("agent-setup")
def agent_setup(
    template: str = typer.Argument("br_quickstart", help="Template name or path"),
    port: int = typer.Option(2718, help="Port of the running Marimo notebook"),
) -> None:
    """Print the recommended Marimo external-agent onboarding flow."""
    _require_marimo()
    path = _find_template(template)
    url = f"http://127.0.0.1:{port}/"
    claude_cmd = f'''claude "$(uvx marimo@latest pair prompt --url '{url}' --claude)"'''
    codex_cmd = f'''codex "$(uvx marimo@latest pair prompt --url '{url}' --codex)"'''

    console.print("[bold]Marimo Agent Setup[/bold]")
    console.print("[bold]Preferred path:[/bold] marimo Pair with an agent")
    console.print(
        f"  1. Open the notebook with [bold]br notebook open {path.stem} --port {port}[/bold]"
    )
    console.print(
        "  2. Install the pairing skill: [bold]npx skills add marimo-team/marimo-pair[/bold]"
    )
    console.print("  3. In marimo, open [bold]Config -> Pair with an agent[/bold]")
    console.print(f"  4. Claude Code: [bold]{claude_cmd}[/bold]")
    console.print(f"  5. Codex: [bold]{codex_cmd}[/bold]")
    console.print(
        f"  6. Once paired, also point the agent at [bold]{_MCP_GUIDE}[/bold]"
    )
    console.print(
        "  7. Ask the agent to edit the notebook .py file directly and use the BR sdk"
    )
    if _OPERATIONS_GUIDE.exists():
        console.print(f"  8. Operations guide: [bold]{_OPERATIONS_GUIDE}[/bold]")

    console.print("\n[bold]Codex troubleshooting:[/bold]")
    console.print(
        "  If Codex says /marimo-pair cannot be found, verify "
        "[bold]~/.codex/skills/marimo-pair[/bold] exists."
    )

    console.print(
        "\n[bold]Fallback path:[/bold] external agent + watched file workflow"
    )
    console.print(f"  marimo edit --watch {path}")

    console.print("\n[bold]Runtime transport:[/bold]")
    console.print(
        "  Local default: [bold]BR_MCP_SERVER_COMMAND=brain-researcher-mcp[/bold]"
    )
    console.print(
        "  Hosted / prod: [bold]BR_MCP_HTTP_URL=https://${PUBLIC_HOSTNAME}/mcp[/bold]"
    )
    console.print('                 [bold]BR_MCP_AUTH_HEADER="Bearer <token>"[/bold]')
    console.print("                 or [bold]BR_MCP_TOKEN=<token>[/bold]")

    console.print("\n[bold]Editing contract:[/bold]")
    console.print(
        "  - prefer [bold]br.search(), br.recipe(), br.execute(), br.call(), br.display.*[/bold]"
    )
    console.print(
        "  - use [bold]br.call(...)[/bold] for direct MCP endpoints without a dedicated helper"
    )
    console.print(
        "  - use [bold]br.execute(...)[/bold] for registry tools that must run through tool_execute"
    )
    console.print(
        "  - avoid raw HTTP from notebook cells unless the SDK cannot express the task"
    )

    console.print("\n[bold]Validation:[/bold]")
    console.print(f"  br notebook check {path}")
    console.print("  marimo check <notebook.py>")


@app.command("check")
def check_notebook(
    notebook: str = typer.Argument(
        "br_quickstart", help="Template name or notebook path"
    ),
    fix: bool = typer.Option(False, help="Apply marimo fixes in place"),
    strict: bool = typer.Option(False, help="Fail on warnings as well as errors"),
    quiet: bool = typer.Option(False, help="Reduce marimo check output"),
) -> None:
    """Run ``marimo check`` on a BR notebook template or file."""
    _require_marimo()
    path = _find_template(notebook)

    cmd = ["marimo", "check", str(path)]
    if fix:
        cmd.append("--fix")
    if strict:
        cmd.append("--strict")
    if quiet:
        cmd.append("--quiet")

    completed = subprocess.run(cmd, check=False)
    raise typer.Exit(completed.returncode)
