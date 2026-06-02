#!/usr/bin/env python3
"""
Download and setup data files for Brain Researcher.

This script helps download large data files that are not stored in Git.
"""

import hashlib
import os
import sys
from pathlib import Path

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn
from rich.table import Table

app = typer.Typer()
console = Console()

# Data source configurations
DATA_SOURCES = {
    "neurosynth": {
        "description": "Neurosynth meta-analysis database",
        "files": {
            "coordinates": {
                "url": "https://github.com/neurosynth/neurosynth-data/raw/master/data-neurosynth_version-7_coordinates.tsv.gz",
                "path": "data/neurosynth_nimare/neurosynth_v7/data-neurosynth_version-7_coordinates.tsv.gz",
                "size": "3.5MB",
                "md5": None,  # Add checksums if available
            },
            "metadata": {
                "url": "https://github.com/neurosynth/neurosynth-data/raw/master/data-neurosynth_version-7_metadata.tsv.gz",
                "path": "data/neurosynth_nimare/neurosynth_v7/data-neurosynth_version-7_metadata.tsv.gz",
                "size": "1.2MB",
                "md5": None,
            },
        },
    },
    "mni_templates": {
        "description": "MNI brain templates",
        "files": {
            "mni152_2mm": {
                "url": "https://github.com/nilearn/nilearn-data/raw/main/mni_icbm152_t1_tal_nlin_sym_09a_converted.nii.gz",
                "path": "data/templates/MNI152_T1_2mm.nii.gz",
                "size": "1.9MB",
                "md5": None,
            }
        },
    },
    "example_data": {
        "description": "Example neuroimaging datasets",
        "files": {
            "haxby": {
                "url": None,  # Use nilearn fetcher
                "path": "data/examples/haxby/",
                "size": "~100MB",
                "fetcher": "fetch_haxby",
            }
        },
    },
}


def download_file(url: str, dest_path: Path, show_progress: bool = True) -> bool:
    """Download a file with progress bar."""
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        if show_progress and total_size > 0:
            with Progress(
                TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                console=console,
            ) as progress:
                download_task = progress.add_task(
                    "download", filename=dest_path.name, total=total_size
                )

                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        progress.update(download_task, advance=len(chunk))
        else:
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        return True

    except Exception as e:
        console.print(f"[red]Error downloading {url}: {e}[/red]")
        return False


def verify_checksum(file_path: Path, expected_md5: str | None) -> bool:
    """Verify file checksum if provided."""
    if not expected_md5:
        return True

    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)

    actual_md5 = md5_hash.hexdigest()
    return actual_md5 == expected_md5


@app.command()
def list_sources():
    """List available data sources."""
    table = Table(title="Available Data Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Description")
    table.add_column("Files", style="green")
    table.add_column("Total Size", style="yellow")

    for source_name, source_info in DATA_SOURCES.items():
        file_count = len(source_info["files"])
        table.add_row(
            source_name, source_info["description"], str(file_count), "Varies"
        )

    console.print(table)


@app.command()
def download(
    source: str = typer.Argument(..., help="Data source to download"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Verify checksums"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-download"),
):
    """Download data from a specific source."""
    if source not in DATA_SOURCES:
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print("Use 'list-sources' to see available sources")
        raise typer.Exit(1)

    source_info = DATA_SOURCES[source]
    console.print(f"[bold]Downloading {source_info['description']}[/bold]")

    success_count = 0
    for file_name, file_info in source_info["files"].items():
        dest_path = Path(file_info["path"])

        if dest_path.exists() and not force:
            console.print(f"[yellow]Skipping {file_name} (already exists)[/yellow]")
            continue

        console.print(f"\nDownloading {file_name}...")

        if file_info.get("url"):
            success = download_file(file_info["url"], dest_path)

            if success and verify and file_info.get("md5"):
                if verify_checksum(dest_path, file_info["md5"]):
                    console.print("[green]✓ Checksum verified[/green]")
                else:
                    console.print("[red]✗ Checksum mismatch![/red]")
                    success = False

            if success:
                success_count += 1
                console.print(f"[green]✓ Downloaded to {dest_path}[/green]")

        elif file_info.get("fetcher"):
            # Use specialized fetcher (e.g., nilearn)
            console.print(f"[yellow]Use nilearn to fetch {file_name}[/yellow]")
            console.print(
                f"Run: python -c \"from nilearn.datasets import {file_info['fetcher']}; {file_info['fetcher']}()\""
            )

    console.print(
        f"\n[bold]Downloaded {success_count}/{len(source_info['files'])} files[/bold]"
    )


@app.command()
def setup():
    """Set up all recommended data files."""
    console.print("[bold]Setting up Brain Researcher data files...[/bold]\n")

    # Create data directories
    data_dirs = [
        "data/br-kg/db",
        "data/br-kg/raw",
        "data/br-kg/logs",
        "data/templates",
        "data/examples",
        "data/test_data",
    ]

    for dir_path in data_dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    console.print("[green]✓ Created data directories[/green]")

    # Check Git LFS
    console.print("\n[bold]Checking Git LFS...[/bold]")
    lfs_installed = os.system("git lfs version > /dev/null 2>&1") == 0

    if lfs_installed:
        console.print("[green]✓ Git LFS is installed[/green]")
    else:
        console.print(
            "[yellow]⚠ Git LFS not found. Install with: git lfs install[/yellow]"
        )

    console.print("\n[bold]Data setup complete![/bold]")
    console.print("Run 'download <source>' to download specific datasets")


@app.command()
def check():
    """Check data file status."""
    console.print("[bold]Checking data files...[/bold]\n")

    # Check key data files
    key_files = [
        ("BR-KG Database", "data/br-kg/db/br_kg_full.db"),
        ("GLM Database", "data/br-kg/db/br_kg_glmfitlins.db"),
        ("PubMed Data", "data/br-kg/raw/pubmed_publications.json"),
        ("WikiData", "data/br-kg/raw/wikidata_brain_regions_sample_200.json"),
    ]

    table = Table(title="Data File Status")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Size", style="yellow")

    for name, path in key_files:
        file_path = Path(path)
        if file_path.exists():
            size = file_path.stat().st_size
            size_str = (
                f"{size / 1024 / 1024:.1f} MB"
                if size > 1024 * 1024
                else f"{size / 1024:.1f} KB"
            )
            table.add_row(name, "✓ Present", size_str)
        else:
            table.add_row(name, "✗ Missing", "-")

    console.print(table)


if __name__ == "__main__":
    app()
