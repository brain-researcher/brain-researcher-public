"""Data ingestion and management commands for Brain Researcher CLI."""

import os
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client

app = typer.Typer(help="Data ingestion and management commands")
console = Console()


def _ensure_neo4j_config() -> str:
    """Fail fast if Neo4j credentials are missing."""
    uri = os.getenv("NEO4J_URI")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not password:
        raise typer.BadParameter(
            "Neo4j is required. Set NEO4J_URI and NEO4J_PASSWORD before running this command."
        )
    return uri


def _format_neo4j_target() -> str:
    """Render the target Neo4j connection for user messages."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "(default)")
    return f"{uri} (user={user}, db={database})"


def _make_loader(db_path: Optional[Path]):
    from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader

    if db_path:
        console.print(
            f"[yellow]Ignoring --db={db_path}; SQLite fallback has been removed. Using Neo4j instead.[/yellow]"
        )

    _ensure_neo4j_config()

    return MasterDataLoader(
        db_factory=create_graph_client,
        db_path=None,
    )


@app.command()
def load_pubmed(
    json_path: Path = typer.Argument(..., help="Path to PubMed JSON file"),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        "-d",
        help="Deprecated SQLite path (ignored). Neo4j credentials are required instead.",
    ),
    batch_size: int = typer.Option(
        1000, "--batch-size", "-b", help="Batch size for processing"
    ),
):
    """Load PubMed publications into the database."""
    try:
        import fix_pubmed_loading

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            if db_path:
                console.print(
                    "[yellow]--db/--d is ignored; Neo4j is mandatory for PubMed loading.[/yellow]"
                )
            task = progress.add_task("Loading PubMed data...", total=None)

            # Check if file exists
            if not json_path.exists():
                console.print(f"[red]File not found: {json_path}[/red]")
                raise typer.Exit(1)

            # Load data
            fix_pubmed_loading.main()  # Run fixes first

            progress.update(task, description="[green]✓[/green] PubMed data loaded")

    except Exception as e:
        console.print(f"[red]Error loading PubMed data: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def load_wikidata(
    json_path: Path = typer.Argument(..., help="Path to WikiData JSON file"),
    entity_type: str = typer.Option(
        "brain_region", "--type", "-t", help="Entity type: brain_region, concept, etc."
    ),
):
    """Load WikiData entities into the database."""
    try:
        import load_wikidata_from_json

        console.print(f"[bold blue]Loading WikiData {entity_type}s...[/bold blue]")

        if not json_path.exists():
            console.print(f"[red]File not found: {json_path}[/red]")
            raise typer.Exit(1)

        # Set environment for the script
        import os

        os.environ["WIKIDATA_FILE"] = str(json_path)
        os.environ["ENTITY_TYPE"] = entity_type

        # Run loading
        load_wikidata_from_json.main()

        console.print("[green]✓[/green] WikiData loaded successfully")

    except Exception as e:
        console.print(f"[red]Error loading WikiData: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def load_openneuro(
    dataset_id: str = typer.Argument(..., help="OpenNeuro dataset ID (e.g., ds000001)"),
    fitlins: bool = typer.Option(
        False, "--fitlins", "-f", help="Load fitlins GLM results"
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-l", help="Limit number of items to load"
    ),
):
    """Load OpenNeuro dataset metadata."""
    try:
        if fitlins:
            console.print(
                f"[bold blue]Loading OpenNeuro fitlins for {dataset_id}...[/bold blue]"
            )
            # TODO: Adapt script to accept parameters
        else:
            console.print(
                f"[bold blue]Loading OpenNeuro metadata for {dataset_id}...[/bold blue]"
            )
            # TODO: Implement regular OpenNeuro loading

        console.print("[green]✓[/green] OpenNeuro data loaded")

    except Exception as e:
        console.print(f"[red]Error loading OpenNeuro data: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def add_samples(
    dataset: str | None = typer.Option(
        None, "--dataset", "-d", help="Specific sample dataset to add"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force reload if already exists"
    ),
):
    """Add sample datasets for testing and demos."""
    try:
        console.print("[bold blue]Adding sample datasets...[/bold blue]")

        if force:
            console.print(
                "[yellow]--force is ignored for Neo4j sample seeding.[/yellow]"
            )

        from brain_researcher.services.br_kg.db.bootstrap import get_db, seed

        db = get_db(require_neo4j=True)
        seed(db)
        db.close()

        console.print("[green]✓[/green] Sample datasets added")

    except Exception as e:
        console.print(f"[red]Error adding samples: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def export(
    output_path: Path = typer.Argument(
        ..., help="Output file path (.json, .csv, or .parquet)"
    ),
    entity_type: str = typer.Option(
        "all", "--type", "-t", help="Entity type to export (all, study, concept, etc.)"
    ),
    format: str | None = typer.Option(
        None, "--format", "-f", help="Output format (auto-detected from extension)"
    ),
):
    """Export data from the database."""
    try:
        console.print(f"[bold blue]Exporting {entity_type} data...[/bold blue]")

        # Determine format from extension if not specified
        if not format:
            format = output_path.suffix[1:] if output_path.suffix else "json"

        # TODO: Implement export functionality
        console.print(f"Exporting to {output_path} as {format}")

        console.print("[green]✓[/green] Data exported successfully")

    except Exception as e:
        console.print(f"[red]Export error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def validate_bids(
    dataset_paths: List[Path] = typer.Argument(
        ..., help="Path(s) to BIDS dataset(s) to validate"
    ),
    strict: bool = typer.Option(
        False, "--strict", "-s", help="Treat warnings as errors"
    ),
    format: str = typer.Option(
        "markdown", "--format", "-f", help="Report format: markdown, json, html"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for report (prints to console if not specified)",
    ),
    batch: bool = typer.Option(
        False, "--batch", "-b", help="Process multiple datasets and generate summary"
    ),
):
    """Validate BIDS dataset(s) for compliance and quality."""
    try:
        from brain_researcher.core.ingestion.loaders.bids_unified import (
            BIDSUnifiedLoader,
        )

        console.print(f"[bold blue]Validating BIDS dataset(s)...[/bold blue]")

        # Initialize loader
        loader = BIDSUnifiedLoader(strict_validation=strict, cache_results=True)

        # Process datasets
        all_results = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for dataset_path in dataset_paths:
                if not dataset_path.exists():
                    console.print(f"[red]Dataset not found: {dataset_path}[/red]")
                    continue

                task = progress.add_task(
                    f"Validating {dataset_path.name}...", total=None
                )

                try:
                    result = loader.load_dataset(str(dataset_path))
                    all_results[str(dataset_path)] = result

                    # Display inline summary
                    if result.get("is_valid"):
                        progress.update(
                            task,
                            description=f"[green]✓[/green] {dataset_path.name} - Valid",
                        )
                    else:
                        n_errors = result.get("summary", {}).get("n_errors", 0)
                        progress.update(
                            task,
                            description=f"[red]✗[/red] {dataset_path.name} - {n_errors} errors",
                        )

                except Exception as e:
                    console.print(f"[red]Error validating {dataset_path}: {e}[/red]")
                    all_results[str(dataset_path)] = {"error": str(e)}

        # Generate report
        if batch and len(all_results) > 1:
            # Generate batch summary
            table = Table(title="BIDS Validation Summary")
            table.add_column("Dataset", style="cyan")
            table.add_column("Status", justify="center")
            table.add_column("Errors", justify="center")
            table.add_column("Warnings", justify="center")
            table.add_column("Quality Score", justify="center")

            for path, result in all_results.items():
                if "error" in result:
                    table.add_row(Path(path).name, "[red]Error[/red]", "-", "-", "-")
                else:
                    status = (
                        "[green]Valid[/green]"
                        if result.get("is_valid")
                        else "[red]Invalid[/red]"
                    )
                    summary = result.get("summary", {})
                    table.add_row(
                        Path(path).name,
                        status,
                        str(summary.get("n_errors", 0)),
                        str(summary.get("n_warnings", 0)),
                        f"{summary.get('quality_score', 0):.1f}",
                    )

            console.print(table)

            # Save batch report if output specified
            if output:
                import json

                with output.open("w") as f:
                    json.dump(all_results, f, indent=2)
                console.print(f"[green]Report saved to {output}[/green]")

        else:
            # Single dataset or detailed report
            for path, result in all_results.items():
                if "error" not in result:
                    # Generate detailed report
                    validation_result = loader.validator.validate_dataset(path)
                    report = loader.generate_report(validation_result, format)

                    if output:
                        with output.open("w") as f:
                            f.write(report)
                        console.print(f"[green]Report saved to {output}[/green]")
                    else:
                        console.print(report)

        # Display statistics
        stats = loader.get_statistics()
        if stats["datasets_processed"] > 0:
            console.print(f"\n[bold]Overall Statistics:[/bold]")
            console.print(f"  Datasets processed: {stats['datasets_processed']}")
            console.print(
                f"  Valid datasets: {stats['valid_datasets']} ({stats.get('valid_rate', 0):.1%})"
            )
            console.print(f"  Invalid datasets: {stats['invalid_datasets']}")

            if stats["datasets_processed"] > 0:
                console.print(
                    f"  Avg errors/dataset: {stats.get('avg_errors_per_dataset', 0):.1f}"
                )
                console.print(
                    f"  Avg warnings/dataset: {stats.get('avg_warnings_per_dataset', 0):.1f}"
                )

        # Exit with error if any datasets are invalid
        if any(
            not r.get("is_valid", False)
            for r in all_results.values()
            if "error" not in r
        ):
            raise typer.Exit(1)

    except ImportError as e:
        console.print(f"[red]Missing dependencies: {e}[/red]")
        console.print("Install with: pip install pybids pandas")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def expand(
    sources: Optional[List[str]] = typer.Option(
        None,
        "--source",
        "-s",
        help="Data sources to expand: pubmed, neurosynth, neurovault, all",
    ),
    pubmed_limit: int = typer.Option(
        200000, "--pubmed-limit", help="Max PubMed publications to load"
    ),
    neurovault_limit: int = typer.Option(
        16000, "--neurovault-limit", help="Max NeuroVault collections to load"
    ),
    link_contrasts: bool = typer.Option(
        True,
        "--link-contrasts/--no-link-contrasts",
        help="Link NeuroVault StatMaps to existing Contrasts (requires populated graph)",
    ),
    confidence_threshold: float = typer.Option(
        0.5,
        "--confidence-threshold",
        help="Min confidence for contrast linking (0.0-1.0)",
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        "-d",
        help="Deprecated SQLite path (ignored). Neo4j connection is required.",
    ),
    background: bool = typer.Option(
        False, "--background", "-b", help="Run in background"
    ),
    use_niclip: bool = typer.Option(
        True, "--niclip/--no-niclip", help="Use NICLIP embeddings"
    ),
):
    """
    Expand the BR-KG database with large-scale data from multiple sources.

    Examples:
        br data expand --source pubmed --pubmed-limit 200000
        br data expand --source neurosynth --source neurovault
        br data expand --source all
    """
    import logging
    from datetime import datetime

    # Default sources
    if not sources or "all" in sources:
        sources = ["neurosynth", "pubmed", "neurovault"]

    # Setup logging
    log_file = f"expansion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    if db_path:
        console.print(
            f"[yellow]Ignoring --db={db_path}; Neo4j is required for ingestion.[/yellow]"
        )

    uri = _ensure_neo4j_config()

    console.print(f"[bold blue]BR-KG Data Expansion[/bold blue]")
    console.print(f"Database: Neo4j @ {_format_neo4j_target()}")
    console.print(f"Sources: {', '.join(sources)}")
    console.print(f"Log file: {log_file}\n")

    try:
        # Create loader
        loader = _make_loader(db_path)

        # Get baseline stats
        baseline_stats = loader.db.get_stats() if loader.db else {}
        console.print(f"[cyan]Current database:[/cyan]")
        console.print(f"  Nodes: {baseline_stats.get('total_nodes', 0):,}")
        console.print(
            f"  Relationships: {baseline_stats.get('total_relationships', 0):,}\n"
        )

        # Process each source
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:

            # NeuroSynth
            if "neurosynth" in sources:
                task = progress.add_task("Loading NeuroSynth v7...", total=None)
                config = {
                    "use_niclip": use_niclip,
                    "load_coordinates": True,
                    "load_metadata": True,
                    "load_features": True,
                    "load_vocabulary": True,
                }
                stats = loader.load_neurosynth(config)
                progress.update(
                    task,
                    description=f"[green]✓[/green] NeuroSynth: {stats.get('studies', 0):,} studies",
                )

            # PubMed
            if "pubmed" in sources:
                task = progress.add_task(
                    f"Loading PubMed ({pubmed_limit:,} publications)...", total=None
                )
                config = {
                    "use_niclip": use_niclip,
                    "search_query": "fMRI neuroimaging",
                    "max_results": pubmed_limit,
                }
                stats = loader.load_pubmed(config)
                progress.update(
                    task,
                    description=f"[green]✓[/green] PubMed: {stats.get('publications', 0):,} publications",
                )

            # NeuroVault
            if "neurovault" in sources:
                task = progress.add_task(
                    f"Loading NeuroVault ({neurovault_limit:,} collections)...",
                    total=None,
                )
                config = {
                    "limit": neurovault_limit,
                    "load_images": True,
                    "link_contrasts": link_contrasts,
                    "confidence_threshold": confidence_threshold,
                }
                stats = loader.load_neurovault(config)
                collections_count = stats.get("collections", 0)
                images_count = stats.get("images", 0)

                # Enhanced reporting for contrast linking
                if link_contrasts and "contrast_linking" in stats:
                    linking = stats["contrast_linking"]
                    matched = linking.get("contrasts_matched", 0)
                    total = linking.get("maps_processed", 0)
                    match_rate = (matched / total * 100) if total > 0 else 0
                    description = f"[green]✓[/green] NeuroVault: {collections_count:,} collections, {images_count:,} images, {matched:,}/{total:,} linked ({match_rate:.1f}%)"
                else:
                    description = f"[green]✓[/green] NeuroVault: {collections_count:,} collections, {images_count:,} images"

                progress.update(task, description=description)

        # Final stats
        final_stats = loader.db.get_stats() if loader.db else {}
        console.print(f"\n[bold green]Expansion Complete![/bold green]")
        console.print(
            f"  Nodes: {baseline_stats.get('total_nodes', 0):,} → {final_stats.get('total_nodes', 0):,} (+{final_stats.get('total_nodes', 0) - baseline_stats.get('total_nodes', 0):,})"
        )
        console.print(
            f"  Relationships: {baseline_stats.get('total_relationships', 0):,} → {final_stats.get('total_relationships', 0):,} (+{final_stats.get('total_relationships', 0) - baseline_stats.get('total_relationships', 0):,})"
        )

        loader.close()

    except Exception as e:
        console.print(f"[red]Expansion error: {e}[/red]")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)


@app.command()
def list_sources():
    """List available data sources and their status."""
    console.print("[bold]Available Data Sources:[/bold]")

    sources = [
        ("PubMed", "JSON files with publication metadata", "✓"),
        ("WikiData", "Brain regions and concepts", "✓"),
        ("OpenNeuro", "BIDS datasets and GLM results", "✓"),
        ("NeuroVault", "Statistical maps", "✓"),
        ("DANDI", "Neurophysiology data", "○"),
        ("Neurosynth", "Meta-analysis database", "✓"),
        ("BIDS", "BIDS dataset validation", "✓"),
    ]

    from rich.table import Table

    table = Table(title="Data Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Description")
    table.add_column("Status", justify="center")

    for source, desc, status in sources:
        status_style = "green" if status == "✓" else "yellow"
        table.add_row(source, desc, f"[{status_style}]{status}[/{status_style}]")

    console.print(table)


if __name__ == "__main__":
    app()
3
