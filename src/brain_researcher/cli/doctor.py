"""
Doctor Command - Health Check for Brain Researcher Environment

Verifies Package Management, containers, modules, and tool availability.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from brain_researcher.core.package_resolver import PackageResolver

app = typer.Typer(help="Health check and diagnostic tools")
console = Console()


def check_cvmfs() -> Dict[str, Any]:
    """Check Package Management status and configuration."""
    status = {
        "mounted": False,
        "neurodesk": False,
        "containers": 0,
        "cache_size": None,
        "cache_location": None,
    }

    # Check if Package Management is mounted
    cvmfs_path = Path("/cvmfs")
    if cvmfs_path.exists():
        status["mounted"] = True

        # Check Neurodesk
        neurodesk_path = cvmfs_path / "neurodesk.ardc.edu.au"
        if neurodesk_path.exists():
            status["neurodesk"] = True

            # Count containers
            containers_path = neurodesk_path / "containers"
            if containers_path.exists():
                containers = list(containers_path.iterdir())
                status["containers"] = len([c for c in containers if c.is_dir()])

    # Check Package Management cache configuration
    try:
        result = subprocess.run(
            ["cvmfs_config", "stat", "neurodesk.ardc.edu.au"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "CACHE_SIZE" in line or "CACHEMAX" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            size_mb = int(parts[-1])
                            status["cache_size"] = f"{size_mb / 1000:.1f} GB"
                        except ValueError:
                            pass
                elif "CACHEDIR" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        status["cache_location"] = parts[-1]
    except Exception:
        pass

    return status


def check_module_system() -> Dict[str, Any]:
    """Check module system availability."""
    status = {
        "type": None,
        "available": False,
        "modules_count": 0,
        "neuroimaging_tools": [],
    }

    # Check for Lmod
    try:
        result = subprocess.run(
            ["module", "--version"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            if "Lmod" in result.stderr or "Lmod" in result.stdout:
                status["type"] = "Lmod"
                status["available"] = True
            else:
                status["type"] = "Environment Modules"
                status["available"] = True
    except Exception:
        pass

    # List available neuroimaging modules
    if status["available"]:
        try:
            result = subprocess.run(
                ["module", "avail"], capture_output=True, text=True, timeout=5
            )
            output = result.stderr + result.stdout

            # Parse neuroimaging tools
            tools = []
            for line in output.split("\n"):
                line_lower = line.lower()
                for tool in [
                    "fsl",
                    "mrtrix",
                    "ants",
                    "freesurfer",
                    "spm",
                    "afni",
                    "fmriprep",
                ]:
                    if tool in line_lower and "/" in line:
                        parts = line.strip().split()
                        for part in parts:
                            if tool in part.lower() and "/" in part:
                                tools.append(part)
                                break

            status["neuroimaging_tools"] = sorted(list(set(tools)))[:10]  # Top 10
            status["modules_count"] = len(tools)

        except Exception:
            pass

    return status


def check_containers() -> Dict[str, Any]:
    """Check container runtime status."""
    status = {"runtime": None, "version": None, "available": False}

    for cmd in ["apptainer", "singularity"]:
        try:
            result = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                status["runtime"] = cmd
                status["version"] = result.stdout.strip().split()[-1]
                status["available"] = True
                break
        except Exception:
            continue

    return status


def check_python_packages() -> Dict[str, List[str]]:
    """Check installed Python neuroimaging packages."""
    packages = {"core": [], "optional": [], "missing": []}

    # Core packages
    core_pkgs = ["nibabel", "nilearn", "numpy", "scipy", "pandas"]
    for pkg in core_pkgs:
        try:
            __import__(pkg)
            packages["core"].append(pkg)
        except ImportError:
            packages["missing"].append(pkg)

    # Optional packages
    optional_pkgs = [
        "mne",
        "nipype",
        "antspyx",
        "fooof",
        "autoreject",
        "rsatoolbox",
        "bctpy",
        "pymc",
        "tensorly",
        "nimare",
    ]
    for pkg in optional_pkgs:
        try:
            # Handle special import names
            import_name = pkg
            if pkg == "bctpy":
                import_name = "bct"
            elif pkg == "rsatoolbox":
                import_name = "rsatoolbox"

            __import__(import_name)
            packages["optional"].append(pkg)
        except ImportError:
            pass

    return packages


def check_tools_availability() -> Dict[str, Any]:
    """Check availability of neuroimaging tools via Package Management resolver."""
    resolver = PackageResolver()
    tools = resolver.list_available_tools()

    summary = {"total_tools": len(tools), "tools": {}}

    for tool_name, backends in tools.items():
        best_backend = backends[0] if backends else None
        if best_backend:
            summary["tools"][tool_name] = {
                "version": best_backend.version,
                "type": best_backend.type.value,
                "backends": len(backends),
            }

    return summary


@app.command()
def check(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Run comprehensive health check on Brain Researcher environment.
    """
    console.print(
        "\n[bold cyan]Brain Researcher Environment Health Check[/bold cyan]\n"
    )

    results = {"timestamp": datetime.now().isoformat(), "checks": {}}

    # 1. Check Package Management
    with console.status("[bold green]Checking Package Management..."):
        cvmfs = check_cvmfs()
        results["checks"]["cvmfs"] = cvmfs

    # 2. Check Module System
    with console.status("[bold green]Checking module system..."):
        modules = check_module_system()
        results["checks"]["modules"] = modules

    # 3. Check Container Runtime
    with console.status("[bold green]Checking container runtime..."):
        containers = check_containers()
        results["checks"]["containers"] = containers

    # 4. Check Python Packages
    with console.status("[bold green]Checking Python packages..."):
        packages = check_python_packages()
        results["checks"]["python"] = packages

    # 5. Check Available Tools
    with console.status("[bold green]Discovering neuroimaging tools..."):
        tools = check_tools_availability()
        results["checks"]["tools"] = tools

    if json_output:
        # Output as JSON
        console.print_json(json.dumps(results, indent=2))
    else:
        # Display results in tables
        display_results(results, verbose)

    # Overall status
    overall_status = evaluate_overall_status(results)

    if not json_output:
        if overall_status["healthy"]:
            console.print(f"\n✅ [bold green]Environment is healthy![/bold green]")
        else:
            console.print(f"\n⚠️  [bold yellow]Environment has issues:[/bold yellow]")
            for issue in overall_status["issues"]:
                console.print(f"  - {issue}")

    return 0 if overall_status["healthy"] else 1


def display_results(results: Dict[str, Any], verbose: bool = False):
    """Display health check results in formatted tables."""

    # Package Management Status
    cvmfs = results["checks"]["cvmfs"]
    cvmfs_table = Table(title="Package Management Status", box=box.ROUNDED)
    cvmfs_table.add_column("Check", style="cyan")
    cvmfs_table.add_column("Status", style="green")

    cvmfs_table.add_row(
        "Package Management Mounted", "✅ Yes" if cvmfs["mounted"] else "❌ No"
    )
    cvmfs_table.add_row(
        "Neurodesk Available", "✅ Yes" if cvmfs["neurodesk"] else "❌ No"
    )
    if cvmfs["containers"] > 0:
        cvmfs_table.add_row("Containers Available", f"✅ {cvmfs['containers']}")
    if cvmfs["cache_size"]:
        cvmfs_table.add_row("Cache Size", cvmfs["cache_size"])
    if cvmfs["cache_location"]:
        cvmfs_table.add_row("Cache Location", cvmfs["cache_location"])

    console.print(cvmfs_table)
    console.print()

    # Module System
    modules = results["checks"]["modules"]
    module_table = Table(title="Module System", box=box.ROUNDED)
    module_table.add_column("Check", style="cyan")
    module_table.add_column("Status", style="green")

    module_table.add_row(
        "Module System", modules["type"] if modules["available"] else "❌ Not Available"
    )
    if modules["available"]:
        module_table.add_row("Neuroimaging Modules", f"✅ {modules['modules_count']}")
        if verbose and modules["neuroimaging_tools"]:
            for tool in modules["neuroimaging_tools"][:5]:
                module_table.add_row("  Example", tool)

    console.print(module_table)
    console.print()

    # Container Runtime
    containers = results["checks"]["containers"]
    container_table = Table(title="Container Runtime", box=box.ROUNDED)
    container_table.add_column("Check", style="cyan")
    container_table.add_column("Status", style="green")

    if containers["available"]:
        container_table.add_row("Runtime", f"✅ {containers['runtime']}")
        container_table.add_row("Version", containers["version"])
    else:
        container_table.add_row("Runtime", "❌ Not Available")

    console.print(container_table)
    console.print()

    # Python Packages
    packages = results["checks"]["python"]
    pkg_table = Table(title="Python Packages", box=box.ROUNDED)
    pkg_table.add_column("Category", style="cyan")
    pkg_table.add_column("Packages", style="green")

    pkg_table.add_row(
        "Core Packages",
        f"✅ {len(packages['core'])}/{len(packages['core']) + len(packages['missing'])}",
    )
    if verbose and packages["core"]:
        pkg_table.add_row("  Installed", ", ".join(packages["core"]))

    if packages["optional"]:
        pkg_table.add_row("Optional Packages", f"✅ {len(packages['optional'])}/10")
        if verbose:
            pkg_table.add_row("  Installed", ", ".join(packages["optional"]))

    if packages["missing"]:
        pkg_table.add_row("Missing Core", f"❌ {', '.join(packages['missing'])}")

    console.print(pkg_table)
    console.print()

    # Available Tools
    tools = results["checks"]["tools"]
    if tools["total_tools"] > 0:
        tool_table = Table(title="Neuroimaging Tools", box=box.ROUNDED)
        tool_table.add_column("Tool", style="cyan")
        tool_table.add_column("Version", style="green")
        tool_table.add_column("Backend", style="yellow")

        for tool_name, info in list(tools["tools"].items())[:10]:
            tool_table.add_row(tool_name, info["version"], info["type"])

        if tools["total_tools"] > 10:
            tool_table.add_row(f"... and {tools['total_tools'] - 10} more", "", "")

        console.print(tool_table)


def evaluate_overall_status(results: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate overall environment health."""
    status = {"healthy": True, "issues": []}

    # Check Package Management
    if not results["checks"]["cvmfs"]["mounted"]:
        status["issues"].append("Package Management not mounted")
        status["healthy"] = False
    elif not results["checks"]["cvmfs"]["neurodesk"]:
        status["issues"].append("Neurodesk not available in Package Management")

    # Check container runtime
    if not results["checks"]["containers"]["available"]:
        status["issues"].append("No container runtime (apptainer/singularity) found")

    # Check Python packages
    if results["checks"]["python"]["missing"]:
        status["issues"].append(
            f"Missing core Python packages: {', '.join(results['checks']['python']['missing'])}"
        )
        status["healthy"] = False

    # Check tools
    if results["checks"]["tools"]["total_tools"] == 0:
        status["issues"].append("No neuroimaging tools discovered")

    return status


@app.command()
def test_skull_strip(
    input_file: str = typer.Argument(..., help="Input NIfTI file"),
    output_dir: str = typer.Option(None, help="Output directory for results"),
    benchmark: bool = typer.Option(
        False, "--benchmark", help="Run benchmark on all backends"
    ),
):
    """
    Test skull stripping capability with available backends.
    """
    # REFACTORING: Capabilities removed - use fsl_bet_tool or ants_tool directly
    raise typer.Exit(1)
    # from brain_researcher.tools.capabilities.skull_strip import SkullStripCapability

    input_path = Path(input_file)
    if not input_path.exists():
        console.print(f"[red]Error: Input file not found: {input_file}[/red]")
        raise typer.Exit(1)

    # Initialize capability
    capability = SkullStripCapability()

    # Show available backends
    backends = capability.get_available_backends()

    console.print("\n[bold cyan]Available Skull Stripping Backends:[/bold cyan]")
    for name, info in backends.items():
        console.print(f"  - {name}: {info['type']} (v{info['version']})")

    if benchmark:
        # Run benchmark
        console.print(
            "\n[bold yellow]Running benchmark on all backends...[/bold yellow]"
        )

        results = capability.benchmark(
            input_file=str(input_path), output_dir=output_dir
        )

        # Display results
        bench_table = Table(title="Benchmark Results", box=box.ROUNDED)
        bench_table.add_column("Backend", style="cyan")
        bench_table.add_column("Status", style="green")
        bench_table.add_column("Time (s)", style="yellow")
        bench_table.add_column("Output", style="white")

        for backend, result in results.items():
            bench_table.add_row(
                backend,
                "✅" if result["success"] else "❌",
                f"{result['time']:.2f}",
                Path(result["output"]).name if result["output"] else "N/A",
            )

        console.print(bench_table)
    else:
        # Run single test
        output_path = Path(output_dir) if output_dir else Path.cwd()
        output_file = output_path / "brain_extracted.nii.gz"

        console.print(f"\n[bold green]Running skull stripping...[/bold green]")
        console.print(f"Input: {input_file}")
        console.print(f"Output: {output_file}")

        success = capability.run(
            input_file=str(input_path), output_file=str(output_file)
        )

        if success:
            console.print("\n✅ [bold green]Skull stripping successful![/bold green]")
            console.print(f"Output saved to: {output_file}")
        else:
            console.print("\n❌ [bold red]Skull stripping failed![/bold red]")
            raise typer.Exit(1)


@app.command()
def list_tools(
    category: str = typer.Option(None, help="Filter by category"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """
    List all available neuroimaging tools.
    """
    resolver = PackageResolver()
    tools = resolver.list_available_tools()

    if json_output:
        # Convert to JSON-serializable format
        output = {}
        for tool_name, backends in tools.items():
            output[tool_name] = [
                {"type": b.type.value, "version": b.version, "priority": b.priority}
                for b in backends
            ]
        console.print_json(json.dumps(output, indent=2))
    else:
        # Display as table
        table = Table(title="Available Neuroimaging Tools", box=box.ROUNDED)
        table.add_column("Tool", style="cyan")
        table.add_column("Best Backend", style="green")
        table.add_column("Version", style="yellow")
        table.add_column("Alternatives", style="white")

        for tool_name, backends in sorted(tools.items()):
            if backends:
                best = backends[0]
                table.add_row(
                    tool_name,
                    best.type.value,
                    best.version,
                    str(len(backends) - 1) if len(backends) > 1 else "-",
                )

        console.print(table)
        console.print(f"\nTotal: {len(tools)} tools available")


if __name__ == "__main__":
    app()
