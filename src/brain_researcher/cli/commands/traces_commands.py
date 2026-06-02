"""Trace export commands."""

import asyncio
import json
import tarfile
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from brain_researcher.services.orchestrator.job_store import JobState
from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore

app = typer.Typer(help="Export learnable traces")
console = Console()


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.write_bytes(src.read_bytes())
    return True


def _collect_run(run_dir: Path, out_dir: Path) -> Optional[dict]:
    obs = run_dir / "observation.json"
    trace = run_dir / "trace.jsonl"
    trajectory = run_dir / "trajectory.json"
    if not obs.exists() or (not trace.exists() and not trajectory.exists()):
        return None
    run_id = run_dir.name
    target = out_dir / run_id
    target.mkdir(parents=True, exist_ok=True)
    for src in (obs, trace, trajectory):
        if not src.exists():
            continue
        dst = target / src.name
        dst.write_bytes(src.read_bytes())
    info = {
        "run_id": run_id,
        "observation": obs.name,
    }
    if trace.exists():
        info["trace"] = trace.name
    if trajectory.exists():
        info["trajectory_json"] = trajectory.name
    extras = {
        "analysis_json": "analysis.json",
        "analysis_bundle_json": "analysis_bundle.json",
        "artifact_manifest_json": "artifact_manifest.json",
        "reward_breakdown_json": "reward_breakdown.json",
    }
    for key, name in extras.items():
        src = run_dir / name
        dst = target / name
        if _copy_if_exists(src, dst):
            info[key] = name
    return info


def _find_runs(root: Path, pattern: str) -> List[Path]:
    out: List[Path] = []
    for p in root.glob(pattern):
        if not (p / "observation.json").exists():
            continue
        if (p / "trace.jsonl").exists() or (p / "trajectory.json").exists():
            out.append(p)
    return out


def _deid(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


async def _runs_from_sqlite(
    db_path: Path, state: Optional[str], limit: int
) -> List[Path]:
    store = SqliteJobStore(db_path=str(db_path), total_gpu_slots=0)
    await store.initialize()
    if state:
        jobs = await store.list_by_state(JobState(state), limit=limit)
    else:
        jobs = await store.list_all(limit=limit)
    run_dirs: List[Path] = []
    for job in jobs:
        if job.run_dir:
            rd = Path(job.run_dir)
            if rd.exists():
                run_dirs.append(rd)
    try:
        await store.close()
    except Exception:
        pass
    return run_dirs


@app.command("export")
def export_traces(
    run_dirs: List[Path] = typer.Argument(
        None,
        help="Explicit run dirs (each containing observation.json and trace.jsonl and/or trajectory.json)",
    ),
    from_root: Optional[Path] = typer.Option(
        None, "--from-root", help="Root to scan for runs"
    ),
    glob: str = typer.Option("*", "--glob", help="Glob under from-root to find runs"),
    sqlite_jobstore: Optional[Path] = typer.Option(
        None, "--sqlite-jobstore", help="Sqlite job store to pull run_dirs from"
    ),
    state: Optional[str] = typer.Option(
        None, "--state", help="Filter by job state when using job store"
    ),
    limit: int = typer.Option(
        500, "--limit", help="Max runs to pull from job store or glob scan"
    ),
    output: Path = typer.Option(
        Path("traces_export.tar.gz"), "--out", "-o", help="Output tar.gz"
    ),
    version: str = typer.Option("trace-export-v1", "--version"),
    deid: bool = typer.Option(
        False, "--deid", help="Hash run_ids for de-identification"
    ),
):
    """
    Export traces/observations into a tar.gz bundle. You can pass run dirs directly or scan a root with --from-root.
    """
    temp_out = Path(".trace_export_tmp")
    if temp_out.exists():
        typer.echo("Temp folder .trace_export_tmp already exists; remove it first.")
        raise typer.Exit(code=1)
    temp_out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": version,
        "runs": [],
    }
    try:
        targets: List[Path] = []
        if run_dirs:
            targets.extend(run_dirs)
        if from_root:
            targets.extend(_find_runs(from_root, glob))
        if sqlite_jobstore:
            found = asyncio.run(_runs_from_sqlite(sqlite_jobstore, state, limit))
            targets.extend(found)
        if not targets:
            console.print("[yellow]No runs provided/found[/yellow]")
            return

        for rd in targets:
            info = _collect_run(rd, temp_out)
            if info:
                if deid:
                    orig_run_id = info["run_id"]
                    anon = _deid(orig_run_id)
                    info["anon_run_id"] = anon
                    info["run_id"] = anon
                    orig_dir = temp_out / orig_run_id
                    target_dir = temp_out / anon
                    if orig_dir.exists():
                        orig_dir.rename(target_dir)
                # enrich manifest with dataset/tool summary if available
                obs_path = rd / "observation.json"
                try:
                    obs = json.loads(obs_path.read_text())
                    datasets = obs.get("run_card", {}).get("datasets") or []
                    info["datasets"] = datasets
                    tools = obs.get("run_card", {}).get("tools") or []
                    info["tools"] = tools
                except Exception:
                    pass
                manifest["runs"].append(info)

        if not manifest["runs"]:
            console.print(
                "[yellow]No runs with observation.json + trace/trajectory found[/yellow]"
            )
            return
        (temp_out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with tarfile.open(output, "w:gz") as tar:
            tar.add(temp_out, arcname="traces")
        console.print(
            f"[green]Exported {len(manifest['runs'])} runs → {output}[/green]"
        )
    finally:
        import shutil

        shutil.rmtree(temp_out, ignore_errors=True)


__all__ = ["app"]
