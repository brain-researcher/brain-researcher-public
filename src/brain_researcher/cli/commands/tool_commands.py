"""Neuroimaging Tool CLI commands.

Provides Neurodesk command generation and listing via CLI.
Also provides NiWrap tool browsing and execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from brain_researcher.services.tools.metadata_schema import (
    normalize_tags,  # type: ignore
)
from brain_researcher.services.tools.metadata_schema import (
    DOMAIN,
    FUNCTION,
    RISK,
)
from brain_researcher.services.tools.neurodesk_tools import (
    NEURODESK_TOOLS,
    NeurodeskTools,
)

app = typer.Typer(help="Neuroimaging tools commands")
console = Console()

# Create niwrap sub-application
niwrap_app = typer.Typer(help="NiWrap neuroimaging tools")
app.add_typer(niwrap_app, name="niwrap")


@app.command("list")
def list_tools():
    """List available Neurodesk tools (from built-in registry)."""
    tools = NeurodeskTools().list_available_tools()
    console.print(JSON.from_data({"tools": tools}))


@app.command("catalog")
def catalog_list(
    domain: Optional[str] = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter by domain (e.g., fmri, fmri.glm, dmri.tractography)",
    ),
    function: Optional[str] = typer.Option(
        None,
        "--function",
        "-f",
        help="Filter by function (e.g., preproc, glm, connectivity)",
    ),
    risk: Optional[str] = typer.Option(
        None,
        "--risk",
        "-r",
        help="Filter by risk (safe|dangerous|external_net|high_cost)",
    ),
    allow_dangerous: bool = typer.Option(
        False, "--allow-dangerous", help="Include tools tagged dangerous/high_cost"
    ),
    limit: int = typer.Option(30, "--limit", "-l", help="Max rows to show"),
):
    """List catalog tools with metadata filters (domain/function/risk)."""
    merged = Path("configs/tools_catalog_merged.json")
    if not merged.exists():
        console.print("[red]Missing configs/tools_catalog_merged.json[/red]")
        raise typer.Exit(1)
    obj = json.loads(merged.read_text())
    tools = obj.get("tools", obj if isinstance(obj, list) else [])
    domain_vals = set(DOMAIN)
    function_vals = set(FUNCTION)
    risk_vals = set(RISK)

    def match(val, allowed):
        return val in allowed if allowed else True

    filtered = []
    for t in tools:
        d = t.get("domain")
        f = t.get("function")
        r = t.get("risk")
        if domain and d != domain:
            continue
        if function and f != function:
            continue
        if risk and r != risk:
            continue
        if (r in ("dangerous", "high_cost")) and not allow_dangerous:
            continue
        # skip invalid entries
        if d not in domain_vals or f not in function_vals or r not in risk_vals:
            continue
        filtered.append(t)
        if len(filtered) >= limit:
            break

    table = Table(title=f"Tools (n={len(filtered)})", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("domain", style="green")
    table.add_column("function", style="yellow")
    table.add_column("risk", style="red")
    table.add_column("runtime", style="magenta")
    for t in filtered:
        table.add_row(
            t.get("name", ""),
            t.get("domain", ""),
            t.get("function", ""),
            t.get("risk", ""),
            t.get("runtime_kind", ""),
        )
    console.print(table)
    console.print("[dim]Use --domain/--function/--risk to narrow results[/dim]")


@app.command("audit")
def audit_tools(
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Directory to write audit TSVs (default: artifacts/tool_audit)",
    ),
    tool_universe: Optional[Path] = typer.Option(
        None,
        "--tool-universe",
        help="Path to tool_universe.tsv (default: repo_root/tool_universe.tsv; generated if missing)",
    ),
    family_suggestions: Optional[Path] = typer.Option(
        None,
        "--family-suggestions",
        help="Path to tool_family_suggestions.tsv (default: repo_root/tool_family_suggestions.tsv; generated if missing)",
    ),
    neo4j_uri: Optional[str] = typer.Option(
        None, "--neo4j-uri", help="Neo4j URI (default: NEO4J_URI env/.env)"
    ),
    neo4j_user: Optional[str] = typer.Option(
        None, "--neo4j-user", help="Neo4j user (default: NEO4J_USER env/.env)"
    ),
    neo4j_password: Optional[str] = typer.Option(
        None,
        "--neo4j-password",
        help="Neo4j password (default: NEO4J_PASSWORD env/.env)",
        hide_input=True,
    ),
    neo4j_database: Optional[str] = typer.Option(
        None,
        "--neo4j-database",
        help="Neo4j database (default: NEO4J_DATABASE env/.env)",
    ),
):
    """Generate repeatable tool audit reports (TSV) to drive catalog quality improvements."""
    from brain_researcher.services.tools.tool_audit import generate_tool_audit_reports

    outputs, paths = generate_tool_audit_reports(
        output_dir=output_dir,
        tool_universe_path=tool_universe,
        family_suggestions_path=family_suggestions,
        uri=neo4j_uri,
        username=neo4j_user,
        password=neo4j_password,
        database=neo4j_database,
    )

    panel = Panel.fit(
        "\n".join([f"[bold]{k}[/bold]: {v}" for k, v in paths.items()]),
        title="Tool audit outputs",
    )
    console.print(panel)
    console.print(JSON.from_data(outputs.stats))


def _parse_params(p: Optional[str]) -> dict:
    if not p:
        return {}
    # If path, read
    path = Path(p)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    try:
        return json.loads(p)
    except Exception:
        # allow key=val,key=val shorthand
        params: dict[str, str] = {}
        for item in p.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                params[k.strip()] = v.strip()
        return params


@app.command("gen")
def generate(
    tool: str = typer.Option(..., "--tool", "-t", help="Neurodesk tool key, e.g., fsl"),
    command: str = typer.Option(..., "--command", "-c", help="Command, e.g., bet"),
    input: list[str] = typer.Option(
        ..., "--input", "-i", help="Input file(s)", rich_help_panel="Inputs"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output path"),
    params: Optional[str] = typer.Option(
        None, "--params", "-p", help="JSON or k=v pairs"
    ),
    mode: str = typer.Option("module", "--mode", help="module or cvmfs"),
):
    """Generate a Neurodesk command for a given tool/command.

    Examples:
      br tools gen -t fsl -c bet -i input.nii.gz -o output.nii.gz -p '{"f":0.5}'
      br tools gen -t fsl -c flirt -i in.nii.gz -o out.nii.gz -p 'dof=6,searchrx=-90,90'
    """
    nd = NeurodeskTools().general
    parameters = _parse_params(params)
    use_module = mode == "module"
    result = nd.run(
        tool_name=tool,
        command=command,
        input_files=list(input),
        output_path=output,
        parameters=parameters,
        use_module=use_module,
    )

    console.print(JSON.from_data(result))


@app.command("batch")
def batch(
    spec: str = typer.Argument(
        ..., help="Path to JSON file with commands list, or JSON string"
    ),
    pipeline_name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Pipeline name"
    ),
    parallel: bool = typer.Option(False, "--parallel/--sequential"),
):
    """Generate a batch script that chains multiple Neurodesk commands.

    Spec format (JSON):
      {"commands": [{"tool_name":"fsl","command":"bet","input_files":["in.nii.gz"],"output_path":"out.nii.gz"}, ...]}
    """
    # Load spec from file or parse as JSON
    path = Path(spec)
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = json.loads(spec)

    commands = data.get("commands", data if isinstance(data, list) else [])
    result = NeurodeskTools().batch.run(
        commands=commands, pipeline_name=pipeline_name, parallel=parallel
    )
    console.print(JSON.from_data(result))


# ============================================================================
# NiWrap Tool Commands
# ============================================================================


@niwrap_app.command("list")
def niwrap_list(
    package: Optional[str] = typer.Option(
        None,
        "--package",
        "-p",
        help="Filter by package (afni, fsl, ants, freesurfer)",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", help="Maximum number of tools to display"
    ),
    test_mode: bool = typer.Option(
        True, "--test/--all", help="Load test subset (4 tools) or all ~1900 tools"
    ),
):
    """NiWrap MCP catalog has been removed."""
    console.print("[red]NiWrap MCP catalog is no longer available.")


@niwrap_app.command("info")
def niwrap_info(
    tool_name: str = typer.Argument(
        ..., help="Full tool name (e.g., afni.24.2.06.3dBlurInMask.run)"
    ),
    show_schema: bool = typer.Option(
        True, "--schema/--no-schema", help="Show full input schema"
    ),
):
    """NiWrap MCP catalog has been removed."""
    console.print("[red]NiWrap MCP catalog is no longer available.")


@niwrap_app.command("preview")
def niwrap_preview(
    tool_name: str = typer.Argument(..., help="Full tool name"),
    params: str = typer.Option(
        ..., "--params", "-p", help="Parameters as JSON string or path to JSON file"
    ),
):
    """NiWrap MCP catalog has been removed."""
    console.print("[red]NiWrap MCP catalog is no longer available.")


@niwrap_app.command("execute")
def niwrap_execute(
    tool_name: str = typer.Argument(..., help="Full tool name"),
    params: str = typer.Option(
        ..., "--params", "-p", help="Parameters as JSON string or path to JSON file"
    ),
    allow_write: bool = typer.Option(
        False, "--allow-write", help="Allow tools to write to disk"
    ),
    container_override: str | None = typer.Option(
        None, "--container-config", help="Path to container override JSON"
    ),
):
    """NiWrap MCP catalog has been removed."""
    console.print("[red]NiWrap MCP catalog is no longer available.")
