"""
CLI commands for BR-KG standards validation and management.

This module provides commands to validate standards compliance,
check invariants, and manage configuration.
"""

import json
import importlib.util
from pathlib import Path
from typing import Optional
import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from brain_researcher.config.paths import get_repo_root

app = typer.Typer(help="BR-KG standards validation and management")
console = Console()


def _load_standards_validator() -> type:
    """Load the legacy standards validator from ``scripts/`` without mutating sys.path."""

    script_path = get_repo_root() / "scripts" / "validate_standards.py"
    spec = importlib.util.spec_from_file_location(
        "brain_researcher_legacy_validate_standards",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load standards validator from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.StandardsValidator


@app.command()
def validate(
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Path to save validation report"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed validation output"
    )
):
    """Validate codebase compliance with BR-KG standards."""

    console.print("[bold blue]BR-KG Standards Validation[/bold blue]")
    console.print("Checking compliance with defined invariants...\n")

    with console.status("[bold green]Running validation checks..."):
        StandardsValidator = _load_standards_validator()
        validator = StandardsValidator()
        results = validator.run_all_validations()

    # Create results table
    table = Table(title="Validation Results", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    # Add check results
    for check_name in ["ID Generation", "Relationship Whitelist",
                       "Provenance Requirements", "NDJSON Contract",
                       "Coordinate Space", "Loader Compliance"]:
        if check_name in results:
            status = results[check_name]
            if status == "PASS":
                status_str = "[green]✓ PASS[/green]"
            elif status == "FAIL":
                status_str = "[red]✗ FAIL[/red]"
            else:
                status_str = "[yellow]⚠ ERROR[/yellow]"

            # Get relevant details
            details = ""
            if verbose:
                if status == "FAIL" and results.get("failed"):
                    details = results["failed"][0] if results["failed"] else ""

            table.add_row(check_name, status_str, details)

    console.print(table)

    # Show summary
    overall = results.get("overall", "UNKNOWN")
    if overall == "PASS":
        console.print(Panel.fit(
            "[bold green]✓ All standards checks PASSED[/bold green]",
            title="Overall Result",
            border_style="green"
        ))
    else:
        console.print(Panel.fit(
            "[bold red]✗ Some standards checks FAILED[/bold red]",
            title="Overall Result",
            border_style="red"
        ))

        # Show failures
        if results.get("failed"):
            console.print("\n[bold red]Failures:[/bold red]")
            for failure in results["failed"]:
                console.print(f"  • {failure}")

    # Show warnings
    if results.get("warnings"):
        console.print("\n[bold yellow]Warnings:[/bold yellow]")
        for warning in results["warnings"]:
            console.print(f"  ⚠ {warning}")

    # Save report if requested
    if output:
        with open(output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        console.print(f"\n[dim]Report saved to {output}[/dim]")

    # Exit with appropriate code
    raise typer.Exit(0 if overall == "PASS" else 1)


@app.command()
def check_id(
    entity_type: str = typer.Argument(..., help="Entity type (e.g., Publication, Task)"),
    entity_data: str = typer.Argument(..., help="JSON string of entity data")
):
    """Check if an entity ID would be generated correctly."""

    from brain_researcher.services.br_kg.schemas.node_schemas import validate_node

    try:
        data = json.loads(entity_data)

        # Add minimal provenance if missing
        if "prov" not in data:
            data["prov"] = {
                "source": "manual",
                "method": "check",
                "loader_version": "cli"
            }

        node = validate_node(entity_type, data)

        console.print(Panel.fit(
            f"[bold green]Generated ID:[/bold green] {node.id}",
            title=f"{entity_type} ID Generation",
            border_style="green"
        ))

        # Show ID components
        console.print("\n[bold]ID Components:[/bold]")
        console.print(f"  Type: {entity_type}")
        if hasattr(node, 'pmid') and node.pmid:
            console.print(f"  PMID: {node.pmid}")
        if hasattr(node, 'doi') and node.doi:
            console.print(f"  DOI: {node.doi}")
        if hasattr(node, 'cognitive_atlas_id') and node.cognitive_atlas_id:
            console.print(f"  Cognitive Atlas: {node.cognitive_atlas_id}")

    except json.JSONDecodeError:
        console.print("[red]Error: Invalid JSON data[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
def show_config(
    config_type: str = typer.Argument(
        ...,
        help="Configuration type: thresholds, scoring, or all"
    )
):
    """Display current configuration settings."""

    config_dir = get_repo_root() / "configs" / "br-kg"

    configs = {
        "thresholds": config_dir / "thresholds.yaml",
        "scoring": config_dir / "edge_scoring.yaml"
    }

    if config_type == "all":
        files_to_show = configs.values()
    elif config_type in configs:
        files_to_show = [configs[config_type]]
    else:
        console.print(f"[red]Unknown config type: {config_type}[/red]")
        console.print("Available: thresholds, scoring, all")
        raise typer.Exit(1)

    for config_file in files_to_show:
        if config_file.exists():
            with open(config_file) as f:
                config = yaml.safe_load(f)

            console.print(Panel.fit(
                f"[bold]{config_file.name}[/bold]",
                border_style="blue"
            ))

            # Pretty print config
            _print_config_recursive(config)
            console.print()
        else:
            console.print(f"[yellow]Config file not found: {config_file}[/yellow]")


def _print_config_recursive(config, indent=0):
    """Recursively print configuration."""
    for key, value in config.items():
        if isinstance(value, dict):
            console.print(" " * indent + f"[bold cyan]{key}:[/bold cyan]")
            _print_config_recursive(value, indent + 2)
        elif isinstance(value, list):
            console.print(" " * indent + f"[bold cyan]{key}:[/bold cyan]")
            for item in value:
                if isinstance(item, dict):
                    _print_config_recursive(item, indent + 2)
                else:
                    console.print(" " * (indent + 2) + f"- {item}")
        else:
            console.print(" " * indent + f"[cyan]{key}:[/cyan] {value}")


@app.command()
def export_schema(
    output_format: str = typer.Option(
        "json",
        "--format", "-f",
        help="Output format: json, yaml, or cypher"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path"
    )
):
    """Export BR-KG schema definitions."""

    from brain_researcher.services.br_kg.schemas.node_schemas import NODE_TYPES
    from brain_researcher.services.br_kg.schemas.edge_schemas import (
        EDGE_TYPES,
        ALLOWED_EDGES,
        OPTIONAL_EDGE_SIGNATURES,
    )

    schema = {
        "node_types": list(NODE_TYPES.keys()),
        "edge_types": list(EDGE_TYPES.keys()),
        "allowed_relationships": {}
    }

    # Build allowed relationships
    for edge_type, (source, target) in ALLOWED_EDGES.items():
        schema["allowed_relationships"][edge_type] = {
            "source": source if isinstance(source, str) else list(source),
            "target": target if isinstance(target, str) else list(target)
        }

    if OPTIONAL_EDGE_SIGNATURES:
        schema["optional_relationship_signatures"] = {}
        for edge_type, signatures in OPTIONAL_EDGE_SIGNATURES.items():
            schema["optional_relationship_signatures"][edge_type] = [
                {"source": src, "target": tgt} for src, tgt in signatures
            ]

    if output_format == "json":
        output_str = json.dumps(schema, indent=2)
    elif output_format == "yaml":
        output_str = yaml.dump(schema, default_flow_style=False)
    elif output_format == "cypher":
        # Generate Cypher constraints
        cypher_lines = ["// BR-KG Schema Constraints\n"]

        # Node constraints
        for node_type in NODE_TYPES.keys():
            cypher_lines.append(
                f"CREATE CONSTRAINT {node_type.lower()}_id IF NOT EXISTS "
                f"FOR (n:{node_type}) REQUIRE n.id IS UNIQUE;"
            )

        output_str = "\n".join(cypher_lines)
    else:
        console.print(f"[red]Unknown format: {output_format}[/red]")
        raise typer.Exit(1)

    if output:
        with open(output, "w") as f:
            f.write(output_str)
        console.print(f"[green]Schema exported to {output}[/green]")
    else:
        console.print(output_str)


@app.command()
def list_invariants():
    """List all defined invariants from the standards document."""

    invariants_path = get_repo_root() / "docs" / "standards" / "invariants.md"

    if not invariants_path.exists():
        console.print("[red]Invariants document not found[/red]")
        raise typer.Exit(1)

    # Parse invariants from markdown
    with open(invariants_path) as f:
        lines = f.readlines()

    table = Table(title="BR-KG Invariants", show_header=True)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Category", style="yellow")
    table.add_column("Description", style="white")
    table.add_column("Owner", style="dim")

    # Simple parser for the table
    in_table = False
    for line in lines:
        if "| Rule |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" not in line:
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 4 and parts[0].startswith("**"):
                rule_id = parts[0].replace("**", "")
                desc = parts[1]
                owner = parts[4] if len(parts) > 4 else "Platform"

                # Extract category from rule ID
                category = rule_id.split("-")[0]

                table.add_row(rule_id, category, desc[:50] + "..." if len(desc) > 50 else desc, owner)

    console.print(table)
    console.print(f"\n[dim]Full details: {invariants_path}[/dim]")


if __name__ == "__main__":
    app()
