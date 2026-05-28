"""NICLIP commands for Brain Researcher CLI.

This module provides command-line interface for NICLIP functionality including:
- Health/status checks
- Encoding text into embeddings
- Semantic search over NiCLIP vocabularies
- Analyzing brain images (optional model)
- Loading NICLIP data into BR-KG
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from brain_researcher.services.neurokg.niclip.engine import (
    NiclipEngine,
    NiclipEngineConfig,
)

app = typer.Typer(help="NICLIP neuroimaging analysis commands")
console = Console()


def _build_engine(
    *,
    niclip_path: Path | None = None,
    model_path: Path | None = None,
    model_name: str | None = None,
    section: str | None = None,
    device: str | None = None,
    force_reload: bool = False,
) -> NiclipEngine:
    cfg = NiclipEngineConfig.from_env()
    if niclip_path is not None:
        cfg.data_path = str(niclip_path)
    if model_path is not None:
        cfg.model_path = str(model_path)
    if model_name is not None:
        cfg.model_name = model_name
    if section is not None:
        cfg.section = section
    if device is not None:
        cfg.device = device
    return NiclipEngine.get(cfg, force_reload=force_reload)


@app.command()
def health(
    niclip_path: Path | None = typer.Option(
        None, "--data-path", "-d", help="Path to NICLIP data directory"
    ),
):
    """Show NiCLIP engine health/status."""
    try:
        engine = _build_engine(niclip_path=niclip_path, force_reload=bool(niclip_path))
        status = engine.status()
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    table = Table(title="NiCLIP Engine Status")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    for key, value in status.items():
        table.add_row(str(key), str(value))
    console.print(table)


@app.command()
def analyze(
    nifti_path: Path = typer.Argument(
        ..., help="Path to NIfTI file to analyze", exists=True
    ),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of top predictions"),
    model_path: Path | None = typer.Option(
        None, "--model", "-m", help="Path to NICLIP model checkpoint"
    ),
    model_name: str = typer.Option(
        "BrainGPT-7B-v0.2", "--model-name", help="Model name to use"
    ),
    section: str = typer.Option(
        "abstract", "--section", help="Text section embeddings to use"
    ),
    device: str | None = typer.Option(
        None, "--device", help="Device override (cpu/cuda/mps)"
    ),
    use_bayes: bool = typer.Option(
        True, "--bayes/--no-bayes", help="Use Bayesian inference with priors"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Save results to CSV file"
    ),
):
    """Analyze a brain image and predict cognitive processes."""
    console.print(f"[bold blue]Analyzing brain image:[/bold blue] {nifti_path}")

    try:
        with console.status("[bold green]Loading NICLIP engine..."):
            engine = _build_engine(
                niclip_path=None,
                model_path=model_path,
                model_name=model_name,
                section=section,
                device=device,
                force_reload=True,
            )

        # Get predictions
        with console.status("[bold green]Computing predictions..."):
            predictions = engine.predict_from_nifti(
                str(nifti_path), top_k=top_k, use_bayes=use_bayes
            )

        # Display results in a table
        table = Table(title="Top Predicted Cognitive Processes")
        table.add_column("Rank", style="cyan", no_wrap=True)
        table.add_column("Cognitive Process", style="magenta")

        # Check column names
        if "prob" in predictions.columns:
            table.add_column("Probability", style="green")
            score_col = "prob"
        elif "similarity" in predictions.columns:
            table.add_column("Similarity", style="green")
            score_col = "similarity"
        else:
            score_col = None

        for _, row in predictions.iterrows():
            if score_col:
                task_name = row.get("pred", row.get("task", "Unknown"))
                table.add_row(
                    str(row.get("rank", "")), task_name, f"{row[score_col]:.4f}"
                )
            else:
                task_name = row.get("pred", row.get("task", "Unknown"))
                table.add_row(str(row.get("rank", "")), task_name, "N/A")

        console.print(table)

        # Save if requested
        if output:
            predictions.to_csv(output, index=False)
            console.print(f"\n[green]Results saved to:[/green] {output}")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Query term to search for"),
    niclip_path: Path | None = typer.Option(
        None,
        "--data-path",
        "-d",
        help="Path to NICLIP data directory (optional override)",
    ),
    vocabulary: str = typer.Option(
        "cogatlas_task-names", "--vocab", "-v", help="Vocabulary type to search"
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of similar items"),
):
    """Search for similar cognitive concepts/tasks."""
    try:
        with console.status("[bold green]Loading NiCLIP engine..."):
            engine = _build_engine(
                niclip_path=niclip_path, force_reload=bool(niclip_path)
            )

        console.print(f"\n[bold]Searching NiCLIP for:[/bold] '{query}'")
        results = engine.search(
            query,
            top_k=top_k,
            vocabulary_type=vocabulary,
        )

        # Display results in a table
        table = Table(title="Similar Cognitive Concepts")
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Concept", style="magenta")
        table.add_column("Similarity", style="green")

        for i, item in enumerate(results, 1):
            table.add_row(str(i), item["item"], f"{item['similarity']:.3f}")

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def encode(
    text: list[str] = typer.Argument(
        ..., help="Text (repeatable) to encode with NiCLIP"
    ),
    niclip_path: Path | None = typer.Option(
        None, "--data-path", "-d", help="Path to NICLIP data directory"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Optional .npy output path"
    ),
):
    """Encode text into NiCLIP embeddings."""
    try:
        engine = _build_engine(niclip_path=niclip_path, force_reload=bool(niclip_path))
        embeddings = engine.encode_text(text if len(text) > 1 else text[0])
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    if output:
        import numpy as np

        np.save(output, embeddings)
        console.print(f"[green]Saved embeddings to:[/green] {output}")

    shape = embeddings.shape
    table = Table(title="NiCLIP Encode Result")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_row("shape", str(shape))
    table.add_row("items", str(len(text)))
    console.print(table)


@app.command()
def load(
    db_path: Path = typer.Option(
        ..., "--db", "-d", help="Path to BR-KG database", exists=True
    ),
    niclip_path: Path = typer.Option(
        Path("/data/ECoG-foundation-model/mnndl_temp/niclip"),
        "--data-path",
        help="Path to NICLIP data directory",
    ),
    model: str = typer.Option(
        "BrainGPT-7B-v0.2",
        "--model",
        "-m",
        help="Which NiCLIP model to use",
    ),
    section: str = typer.Option(
        "abstract", "--section", "-s", help="Which section embeddings to use"
    ),
    weight_threshold: float = typer.Option(
        0.3, "--threshold", "-t", help="Minimum weight threshold for creating edges"
    ),
    add_embeddings: bool = typer.Option(
        True, "--embeddings/--no-embeddings", help="Add embeddings to nodes"
    ),
    test_mode: bool = typer.Option(
        False, "--test", help="Run in test mode (no edges created)"
    ),
):
    """Load NICLIP data into BR-KG database."""
    from brain_researcher.services.neurokg.db.bootstrap import get_db
    from brain_researcher.services.neurokg.etl.loaders.niclip_loader_enhanced import (
        EnhancedNiCLIPLoader,
    )

    console.print("[bold blue]Loading NICLIP data into BR-KG...[/bold blue]")
    if db_path is not None:
        console.print("[yellow]--db is ignored; Neo4j is required.[/yellow]")
    console.print("Database: Neo4j (from NEO4J_URI/NEO4J_PASSWORD)")
    console.print(f"Model: {model}")
    console.print(f"Section: {section}")

    try:
        # Initialize database
        db = get_db(require_neo4j=True)

        def _count_relationships(rel_type: str) -> int | None:
            try:
                rows = db.execute_query(
                    f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
                )
                return int(rows[0].get("cnt", 0)) if rows else 0
            except Exception:
                return None

        # Get initial stats
        initial_activates = _count_relationships("ACTIVATES")
        if initial_activates is not None:
            console.print(
                f"\n[cyan]Initial ACTIVATES relationships:[/cyan] {initial_activates}"
            )

        # Create loader
        with console.status("[bold green]Loading NICLIP data..."):
            loader = EnhancedNiCLIPLoader(
                db,
                niclip_data_path=str(niclip_path),
                model_name=model,
                section=section,
                use_model_weights=True,
            )

            # Load and create edges
            edges_created = loader.load_and_create_edges(
                weight_threshold=weight_threshold,
                add_embeddings=add_embeddings,
                test_mode=test_mode,
            )

        # Final stats
        if not test_mode:
            final_activates = _count_relationships("ACTIVATES")
            if final_activates is not None and initial_activates is not None:
                console.print(
                    f"\n[cyan]Final ACTIVATES relationships:[/cyan] {initial_activates} → {final_activates}"
                )
            console.print(f"[green]New edges created:[/green] {edges_created}")

        db.close()

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def info(
    niclip_path: Path = typer.Option(
        Path("/data/ECoG-foundation-model/mnndl_temp/niclip"),
        "--data-path",
        "-d",
        help="Path to NICLIP data directory",
    ),
):
    """Display information about available NICLIP data."""
    if not niclip_path.exists():
        console.print(f"[red]NICLIP data directory not found:[/red] {niclip_path}")
        return

    console.print("[bold blue]NICLIP Data Information[/bold blue]")
    console.print("=" * 50)

    # Check for key directories
    data_path = niclip_path / "osf_data/dsj56/osfstorage/osfstorage/data"
    results_path = niclip_path / "osf_data/dsj56/osfstorage/osfstorage/results"

    if data_path.exists():
        console.print("\n[bold]Available data:[/bold]")

        # Check cognitive atlas
        ca_path = data_path / "cognitive_atlas"
        if ca_path.exists():
            files = list(ca_path.glob("*.json")) + list(ca_path.glob("*.csv"))
            console.print(f"  • Cognitive Atlas: {len(files)} files")

        # Check embeddings
        for emb_type in ["text", "image", "vocabulary"]:
            emb_path = data_path / emb_type
            if emb_path.exists():
                files = list(emb_path.glob("*.npy"))
                console.print(
                    f"  • {emb_type.capitalize()} embeddings: {len(files)} files"
                )

    if results_path.exists():
        console.print("\n[bold]Available models:[/bold]")

        # Check for model checkpoints
        model_files = list(results_path.glob("**/*best.pth"))
        for model_file in model_files:
            size_mb = model_file.stat().st_size / (1024 * 1024)
            console.print(f"  • {model_file.name} ({size_mb:.1f} MB)")

    # Try to get more detailed info
    try:
        config = EmbeddingConfig()
        service = NICLIPEmbeddingService(str(niclip_path), config)

        console.print("\n[bold]Vocabulary statistics:[/bold]")
        for vocab_type in ["cogatlas_task-names", "cogatlasred_task-names"]:
            try:
                vocab, _ = service.load_vocabulary_embeddings(vocab_type)
                console.print(f"  • {vocab_type}: {len(vocab)} items")
            except:
                pass

    except Exception:
        pass
