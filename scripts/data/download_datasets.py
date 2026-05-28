#!/usr/bin/env python3
"""
Download neuroimaging datasets for Brain Researcher testing and demos.

This script downloads various neuroimaging datasets including:
- OpenNeuro datasets (fMRI/MEG/EEG)
- MNE-Python sample data
- BCI Competition datasets
- Sleep-EDF database
"""

import os
import sys
import json
import shutil
import hashlib
import zipfile
import tarfile
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import typer
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn
from rich.table import Table

app = typer.Typer(help="Download neuroimaging datasets for testing")
console = Console()

# Dataset configurations
DATASETS = {
    "openneuro_ds000114": {
        "name": "OpenNeuro ds000114 - FSL Course fMRI",
        "type": "openneuro",
        "id": "ds000114",
        "description": "FSL course motor and language fMRI dataset",
        "size": "~2GB",
        "modalities": ["fMRI", "T1w"],
    },
    "openneuro_ds000117": {
        "name": "OpenNeuro ds000117 - Wakeman-Henson MEG/EEG",
        "type": "openneuro", 
        "id": "ds000117",
        "description": "Face recognition MEG/EEG dataset with 16 subjects",
        "size": "~60GB",
        "modalities": ["MEG", "EEG", "T1w"],
    },
    "mne_sample": {
        "name": "MNE-Python Sample Dataset",
        "type": "mne",
        "description": "MEG/EEG sample data with anatomical MRI",
        "size": "~1.5GB",
        "modalities": ["MEG", "EEG", "T1w"],
    },
    "bci_competition_iv_2a": {
        "name": "BCI Competition IV Dataset 2a",
        "type": "direct",
        "url": "https://www.bbci.de/competition/download/competition_iv/BCICIV_2a_gdf.zip",
        "description": "Motor imagery EEG dataset (left/right hand, feet, tongue)",
        "size": "~50MB",
        "modalities": ["EEG"],
    },
    "sleep_edf": {
        "name": "Sleep-EDF Database Expanded",
        "type": "physionet",
        "description": "Polysomnographic sleep recordings with EEG",
        "size": "~200MB",
        "modalities": ["EEG", "EOG", "EMG"],
        "files": [
            "sleep-cassette/SC4001E0-PSG.edf",
            "sleep-cassette/SC4001EC-Hypnogram.edf",
            "sleep-cassette/SC4002E0-PSG.edf", 
            "sleep-cassette/SC4002EC-Hypnogram.edf",
        ]
    },
}


def download_file(url: str, dest_path: Path, description: str = "Downloading") -> bool:
    """Download a file with progress bar."""
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if file already exists
        if dest_path.exists():
            console.print(f"[yellow]File already exists: {dest_path}[/yellow]")
            return True
        
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            DownloadColumn(),
            console=console,
        ) as progress:
            download_task = progress.add_task(
                description, total=total_size
            )
            
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    progress.update(download_task, advance=len(chunk))
        
        return True
        
    except requests.exceptions.RequestException as e:
        console.print(f"[red]Download error: {e}[/red]")
        if dest_path.exists():
            dest_path.unlink()
        return False
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        if dest_path.exists():
            dest_path.unlink()
        return False


def download_openneuro(dataset_id: str, output_dir: Path, exclude_derivatives: bool = True) -> bool:
    """Download OpenNeuro dataset using AWS S3 sync (recommended method)."""
    try:
        console.print(f"[bold blue]Downloading {dataset_id} from OpenNeuro S3 bucket...[/bold blue]")
        
        # Create output directory
        dataset_dir = output_dir / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if AWS CLI is available
        if not shutil.which("aws"):
            console.print("[red]AWS CLI not found. Please install it first:[/red]")
            console.print("[yellow]pip install awscli or apt-get install awscli[/yellow]")
            return False
        
        # Build AWS S3 sync command
        cmd = [
            "aws", "s3", "sync",
            "--no-sign-request",  # No authentication required for OpenNeuro
            f"s3://openneuro.org/{dataset_id}/",
            str(dataset_dir)
        ]
        
        # Add exclusions to save space and time
        if exclude_derivatives:
            cmd.extend(["--exclude", "derivatives/*"])
            console.print("[yellow]Excluding derivatives folder to save space[/yellow]")
        
        # Exclude version control files
        cmd.extend([
            "--exclude", ".git/*",
            "--exclude", ".datalad/*",
            "--exclude", ".gitattributes",
            "--exclude", ".gitmodules"
        ])
        
        # Add progress indication
        console.print(f"[cyan]Running: {' '.join(cmd)}[/cyan]")
        console.print("[yellow]This may take several minutes depending on dataset size...[/yellow]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {dataset_id}...", total=None)
            
            # Run AWS S3 sync
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                progress.update(task, description=f"[green]✓ Downloaded {dataset_id}[/green]")
                
                # Count downloaded files
                file_count = sum(1 for _ in dataset_dir.rglob("*") if _.is_file())
                console.print(f"[green]✓ Successfully downloaded {file_count} files to {dataset_dir}[/green]")
                return True
            else:
                progress.update(task, description=f"[red]✗ Failed to download {dataset_id}[/red]")
                console.print(f"[red]Error: {result.stderr}[/red]")
                return False
        
    except Exception as e:
        console.print(f"[red]Error downloading OpenNeuro dataset: {e}[/red]")
        return False


def download_mne_sample(output_dir: Path) -> bool:
    """Download MNE sample dataset."""
    try:
        import mne
        
        console.print("[bold blue]Downloading MNE sample dataset...[/bold blue]")
        
        # MNE will download to its default location
        sample_path = mne.datasets.sample.data_path(verbose=True)
        
        # Copy to our dataset directory
        dest_dir = output_dir / "mne" / "sample"
        if dest_dir.exists():
            console.print(f"[yellow]MNE sample already exists at {dest_dir}[/yellow]")
            return True
            
        shutil.copytree(sample_path, dest_dir)
        console.print(f"[green]✓ MNE sample dataset copied to {dest_dir}[/green]")
        return True
        
    except ImportError:
        console.print("[red]MNE-Python not installed. Install with: pip install mne[/red]")
        
        # Alternative: direct download
        console.print("[yellow]Attempting direct download...[/yellow]")
        url = "https://github.com/mne-tools/mne-testing-data/archive/refs/heads/main.zip"
        dest_path = output_dir / "mne" / "mne-testing-data.zip"
        
        if download_file(url, dest_path, "Downloading MNE testing data"):
            # Extract the archive
            with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                zip_ref.extractall(output_dir / "mne")
            dest_path.unlink()  # Remove zip file
            console.print("[green]✓ Downloaded MNE testing data[/green]")
            return True
            
        return False
    except Exception as e:
        console.print(f"[red]Error downloading MNE sample: {e}[/red]")
        return False


def download_bci_competition(output_dir: Path) -> bool:
    """Download BCI Competition IV Dataset 2a using kagglehub."""
    console.print("[bold blue]Downloading BCI Competition IV Dataset 2a...[/bold blue]")
    
    dest_dir = output_dir / "bci_competition" / "iv_2a"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        import kagglehub
        
        console.print("[cyan]Using kagglehub to download dataset...[/cyan]")
        console.print("[yellow]Note: This will download to Kaggle's cache first, then copy to destination[/yellow]")
        
        # Download using kagglehub
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading BCI Competition dataset...", total=None)
            
            # Download dataset (will cache in ~/.cache/kagglehub/datasets/)
            kaggle_path = kagglehub.dataset_download("aymanmostafa11/eeg-motor-imagery-bciciv-2a")
            
            progress.update(task, description="Copying files to destination...")
            
            # Copy files from kaggle cache to our destination
            kaggle_path = Path(kaggle_path)
            if kaggle_path.exists():
                # Copy all files to destination
                for item in kaggle_path.rglob("*"):
                    if item.is_file():
                        relative_path = item.relative_to(kaggle_path)
                        dest_file = dest_dir / relative_path
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_file)
                
                # Count files
                file_count = sum(1 for _ in dest_dir.rglob("*") if _.is_file())
                
                progress.update(task, description=f"[green]✓ Downloaded BCI Competition dataset[/green]")
                console.print(f"[green]✓ Successfully copied {file_count} files to {dest_dir}[/green]")
                
                # Create README with dataset info
                readme_path = dest_dir / "README.md"
                readme_content = """# BCI Competition IV Dataset 2a

## Dataset Information

Motor imagery EEG dataset with 4 classes:
- Left hand
- Right hand  
- Feet
- Tongue

## Dataset Details
- 9 subjects
- 2 sessions per subject (training and evaluation)
- 22 EEG channels
- 250 Hz sampling rate
- GDF file format

## Files
- A0[1-9]T.gdf: Training data for subjects 1-9
- A0[1-9]E.gdf: Evaluation data for subjects 1-9
- true_labels_*.csv: True labels for evaluation data

## Citation
Brunner, C., Leeb, R., Müller-Putz, G., Schlögl, A., & Pfurtscheller, G. (2008). 
BCI Competition 2008 – Graz data set A.

## Source
Downloaded from: https://www.kaggle.com/datasets/aymanmostafa11/eeg-motor-imagery-bciciv-2a
"""
                readme_path.write_text(readme_content)
                
                return True
            else:
                console.print("[red]Error: Downloaded path not found[/red]")
                return False
                
    except ImportError:
        console.print("[red]kagglehub not installed. Install with: pip install kagglehub[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Error downloading dataset: {e}[/red]")
        console.print("[yellow]You may need to authenticate with Kaggle first:[/yellow]")
        console.print("[cyan]1. Go to https://www.kaggle.com/settings/account[/cyan]")
        console.print("[cyan]2. Create an API token (it will download kaggle.json)[/cyan]")
        console.print("[cyan]3. Place kaggle.json in ~/.kaggle/[/cyan]")
        return False


def download_sleep_edf(output_dir: Path, full_download: bool = True) -> bool:
    """Download Sleep-EDF database from PhysioNet using AWS S3."""
    console.print("[bold blue]Downloading Sleep-EDF Database Expanded...[/bold blue]")
    
    dest_dir = output_dir / "sleep_edf"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    if full_download:
        # Use AWS S3 sync for full dataset (recommended by PhysioNet)
        console.print("[cyan]Downloading complete Sleep-EDF dataset (8.1 GB)...[/cyan]")
        
        # Check if AWS CLI is available
        if not shutil.which("aws"):
            console.print("[red]AWS CLI not found. Please install it first:[/red]")
            console.print("[yellow]pip install awscli or apt-get install awscli[/yellow]")
            return False
        
        # Build AWS S3 sync command for PhysioNet
        cmd = [
            "aws", "s3", "sync",
            "--no-sign-request",  # No authentication required
            "s3://physionet-open/sleep-edfx/1.0.0/",
            str(dest_dir / "full_dataset")
        ]
        
        console.print(f"[cyan]Running: {' '.join(cmd)}[/cyan]")
        console.print("[yellow]This will download ~8.1 GB of data...[/yellow]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading Sleep-EDF dataset...", total=None)
            
            # Run AWS S3 sync
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                progress.update(task, description="[green]✓ Downloaded Sleep-EDF dataset[/green]")
                
                # Count downloaded files
                file_count = sum(1 for _ in (dest_dir / "full_dataset").rglob("*") if _.is_file())
                console.print(f"[green]✓ Successfully downloaded {file_count} files[/green]")
            else:
                progress.update(task, description="[red]✗ Failed to download Sleep-EDF[/red]")
                console.print(f"[red]Error: {result.stderr}[/red]")
                return False
    else:
        # Download sample files only
        console.print("[yellow]Downloading sample files only (use --full for complete dataset)[/yellow]")
        
        base_url = "https://physionet.org/files/sleep-edfx/1.0.0/"
        sample_files = [
            "sleep-cassette/SC4001E0-PSG.edf",
            "sleep-cassette/SC4001EC-Hypnogram.edf",
            "sleep-cassette/SC4002E0-PSG.edf",
            "sleep-cassette/SC4002EC-Hypnogram.edf",
        ]
        
        success_count = 0
        for file_path in sample_files:
            url = f"{base_url}{file_path}"
            dest_path = dest_dir / file_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            if download_file(url, dest_path, f"Downloading {Path(file_path).name}"):
                success_count += 1
        
        if success_count > 0:
            console.print(f"[green]✓ Downloaded {success_count} Sleep-EDF sample files[/green]")
    
    # Create README
    readme_path = dest_dir / "README.md"
    readme_content = """# Sleep-EDF Database Expanded

## Dataset Information

The Sleep-EDF Database Expanded contains 197 whole-night polysomnographic sleep recordings, 
containing EEG, EOG, chin EMG, and event markers.

### Subjects:
- 153 SC* files: Recordings from 78 healthy Caucasians aged 25-101
- 44 ST* files: Recordings from 22 subjects with mild insomnia

### Channels:
- EEG: Fpz-Cz and Pz-Oz (100 Hz sampling)
- EOG: Horizontal EOG
- EMG: Submental chin EMG
- Event markers

### Files:
- *-PSG.edf: Contains the polysomnography signals
- *-Hypnogram.edf: Contains sleep stage annotations

## Data Structure

```
sleep_edf/
├── full_dataset/        # Complete 8.1 GB dataset
│   ├── sleep-cassette/  # 153 recordings (SC*)
│   └── sleep-telemetry/ # 44 recordings (ST*)
└── sleep-cassette/      # Sample files
```

## Usage Example

```python
import mne

# Load a PSG recording
raw = mne.io.read_raw_edf('sleep-cassette/SC4001E0-PSG.edf')

# Load hypnogram
hypnogram = mne.io.read_raw_edf('sleep-cassette/SC4001EC-Hypnogram.edf')
```

## Citation

Kemp B, Zwinderman AH, Tuk B, Kamphuisen HAC, Oberye JJL. 
Analysis of a sleep-dependent neuronal feedback loop: the slow-wave 
microcontinuity of the EEG. IEEE Trans Biomed Eng 2000; 47(9):1185-1194.

Goldberger AL, Amaral LAN, Glass L, Hausdorff JM, Ivanov PCh, Mark RG, 
Mietus JE, Moody GB, Peng C-K, Stanley HE. PhysioBank, PhysioToolkit, and 
PhysioNet: Components of a New Research Resource for Complex Physiologic Signals. 
Circulation 101(23):e215-e220, 2000.

## Source

https://www.physionet.org/content/sleep-edfx/1.0.0/
"""
    readme_path.write_text(readme_content)
    return True


@app.command()
def list_datasets():
    """List available datasets for download."""
    table = Table(title="Available Neuroimaging Datasets")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Size", style="yellow")
    table.add_column("Modalities", style="magenta")
    
    for dataset_id, info in DATASETS.items():
        modalities = ", ".join(info.get("modalities", []))
        table.add_row(
            dataset_id,
            info["name"],
            info.get("size", "Unknown"),
            modalities
        )
    
    console.print(table)


@app.command()
def download(
    dataset_id: str = typer.Argument(None, help="Dataset ID to download (or 'all' for all datasets)"),
    output_dir: Path = typer.Option(
        Path("/app/data"),
        "--output", "-o",
        help="Output directory for datasets"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-download if exists"),
):
    """Download specified neuroimaging dataset(s)."""
    
    if not dataset_id:
        list_datasets()
        console.print("\n[yellow]Specify a dataset ID to download, or use 'all' for all datasets[/yellow]")
        return
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine which datasets to download
    if dataset_id == "all":
        datasets_to_download = list(DATASETS.keys())
    elif dataset_id in DATASETS:
        datasets_to_download = [dataset_id]
    else:
        console.print(f"[red]Unknown dataset: {dataset_id}[/red]")
        console.print("Use 'list-datasets' command to see available datasets")
        return
    
    # Download datasets
    success_count = 0
    for ds_id in datasets_to_download:
        dataset_info = DATASETS[ds_id]
        console.print(f"\n[bold]{dataset_info['name']}[/bold]")
        console.print(f"[dim]{dataset_info['description']}[/dim]")
        
        success = False
        
        if dataset_info["type"] == "openneuro":
            success = download_openneuro(dataset_info["id"], output_dir / "openneuro")
        elif dataset_info["type"] == "mne":
            success = download_mne_sample(output_dir)
        elif dataset_info["type"] == "direct" and ds_id == "bci_competition_iv_2a":
            success = download_bci_competition(output_dir)
        elif dataset_info["type"] == "physionet":
            success = download_sleep_edf(output_dir)
        
        if success:
            success_count += 1
    
    # Summary
    console.print(f"\n[bold]Download Summary[/bold]")
    console.print(f"Successfully downloaded: {success_count}/{len(datasets_to_download)} datasets")
    console.print(f"Datasets location: {output_dir}")


@app.command()
def verify(
    output_dir: Path = typer.Option(
        Path("/app/data"),
        "--output", "-o", 
        help="Dataset directory to verify"
    ),
):
    """Verify downloaded datasets."""
    console.print("[bold]Verifying downloaded datasets...[/bold]\n")
    
    checks = [
        ("OpenNeuro ds000114", output_dir / "openneuro" / "ds000114" / "dataset_description.json"),
        ("OpenNeuro ds000117", output_dir / "openneuro" / "ds000117" / "dataset_description.json"),
        ("MNE Sample", output_dir / "mne" / "sample"),
        ("BCI Competition", output_dir / "bci_competition" / "iv_2a"),
        ("Sleep-EDF", output_dir / "sleep_edf" / "sleep-cassette"),
    ]
    
    table = Table(title="Dataset Verification")
    table.add_column("Dataset", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Path", style="yellow")
    
    for name, path in checks:
        if path.exists():
            if path.is_file():
                size = path.stat().st_size / 1024  # KB
                status = f"✓ Present ({size:.1f} KB)"
            else:
                # Count files in directory
                file_count = len(list(path.rglob("*")))
                status = f"✓ Present ({file_count} files)"
        else:
            status = "✗ Missing"
        
        table.add_row(name, status, str(path))
    
    console.print(table)


if __name__ == "__main__":
    app()