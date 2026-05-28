"""Active regression tests for ordinary run cleanup guardrails."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.cleanup_run_artifacts import (
    cleanup_by_age,
    cleanup_empty_date_dirs,
    run_retention_cleanup,
    scan_runs,
)


def _create_ordinary_run(runs_root: Path, run_id: str) -> Path:
    date_dir = runs_root / "20250101"
    date_dir.mkdir(parents=True, exist_ok=True)
    run_dir = date_dir / run_id
    run_dir.mkdir()
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "state": "succeeded",
                "started_at": 1.0,
                "updated_at": 2.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "stdout.txt").write_text("stdout", encoding="utf-8")
    old_mtime = 2.0
    os.utime(run_dir / "status.json", (old_mtime, old_mtime))
    os.utime(run_dir / "stdout.txt", (old_mtime, old_mtime))
    os.utime(run_dir, (old_mtime, old_mtime))
    return run_dir


def _create_mcp_run(runs_root: Path, run_id: str) -> Path:
    run_dir = runs_root / "mcp_runs" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": "2025-01-01T00:00:00Z",
                "status": "succeeded",
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_scan_runs_ignores_mcp_run_tree(tmp_path: Path):
    runs_root = tmp_path / "runs"
    ordinary_run = _create_ordinary_run(runs_root, "ordinary_run")
    _create_mcp_run(runs_root, "mcp_001")

    runs = scan_runs(runs_root)

    assert [run.run_dir for run in runs] == [ordinary_run]


def test_cleanup_by_age_does_not_delete_mcp_run_tree(tmp_path: Path):
    runs_root = tmp_path / "runs"
    ordinary_run = _create_ordinary_run(runs_root, "ordinary_run")
    mcp_run = _create_mcp_run(runs_root, "mcp_001")

    deleted = cleanup_by_age(scan_runs(runs_root), max_age_days=0.00001, dry_run=False)

    assert deleted == 1
    assert not ordinary_run.exists()
    assert mcp_run.exists()


def test_cleanup_empty_date_dirs_leaves_non_date_siblings(tmp_path: Path):
    runs_root = tmp_path / "runs"
    (runs_root / "mcp_runs").mkdir(parents=True)

    removed = cleanup_empty_date_dirs(runs_root, dry_run=False)

    assert removed == 0
    assert (runs_root / "mcp_runs").exists()


def test_run_retention_cleanup_routes_ordinary_root_through_runs_mode(tmp_path: Path):
    runs_root = tmp_path / "runs"
    ordinary_run = _create_ordinary_run(runs_root, "ordinary_run")
    mcp_run = _create_mcp_run(runs_root, "mcp_001")

    result = run_retention_cleanup(
        runs_root=runs_root,
        days=0.00001,
        max_gb=None,
        dry_run=False,
    )

    assert result["mode"] == "runs"
    assert not ordinary_run.exists()
    assert mcp_run.exists()


def test_run_retention_cleanup_routes_mcp_root_through_mcp_mode(tmp_path: Path):
    runs_root = tmp_path / "runs"
    mcp_run = _create_mcp_run(runs_root, "mcp_001")
    mcp_root = runs_root / "mcp_runs"
    old_mtime = 2.0
    os.utime(mcp_run / "run.json", (old_mtime, old_mtime))
    os.utime(mcp_run, (old_mtime, old_mtime))

    result = run_retention_cleanup(
        runs_root=mcp_root,
        days=0.00001,
        max_gb=None,
        dry_run=False,
    )

    assert result["mode"] == "mcp_runs"
    assert not mcp_run.exists()
