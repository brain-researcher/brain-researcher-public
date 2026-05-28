"""Unit tests for retention_policy script."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scripts.ops.retention_policy import (
    RootPolicy,
    _collect_mcp_run_dirs,
    _collect_run_dirs,
    _prune_mcp_runs_root,
    _prune_runs_root,
    classify_run_root_mode,
)


def _create_ordinary_run(
    runs_root: Path,
    run_id: str,
    *,
    age_days: float,
    state: str = "succeeded",
) -> Path:
    date_dir = runs_root / "20250101"
    date_dir.mkdir(parents=True, exist_ok=True)
    run_dir = date_dir / run_id
    run_dir.mkdir()
    started_at = time.time() - (age_days * 86400)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "state": state,
                "started_at": started_at,
                "updated_at": started_at + 60,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "stdout.txt").write_text("stdout", encoding="utf-8")
    mtime = started_at + 60
    for file_path in run_dir.rglob("*"):
        os.utime(file_path, (mtime, mtime))
    os.utime(run_dir, (mtime, mtime))
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
    old_mtime = time.time() - (40 * 86400)
    os.utime(run_dir / "run.json", (old_mtime, old_mtime))
    os.utime(run_dir, (old_mtime, old_mtime))
    return run_dir


def test_collect_run_dirs_ignores_mcp_runs_subtree(tmp_path: Path):
    runs_root = tmp_path / "runs"
    ordinary_run = _create_ordinary_run(runs_root, "ordinary_run", age_days=2)
    _create_mcp_run(runs_root, "mcp_001")

    collected = _collect_run_dirs(runs_root)

    assert [path for path, _, _, _ in collected] == [ordinary_run]


def test_prune_runs_root_never_targets_mcp_runs(tmp_path: Path):
    runs_root = tmp_path / "runs"
    ordinary_run = _create_ordinary_run(runs_root, "ordinary_run", age_days=40)
    mcp_run = _create_mcp_run(runs_root, "mcp_001")
    old_mtime = time.time() - (40 * 86400)
    os.utime(mcp_run, (old_mtime, old_mtime))
    os.utime(mcp_run / "run.json", (old_mtime, old_mtime))

    policy = RootPolicy(
        key="data_runs",
        root=runs_root,
        mode="runs",
        max_age_days=30,
        max_total_gb=120.0,
    )

    result = _prune_runs_root(policy, now_ts=time.time(), apply=False)

    deleted_paths = [Path(action["path"]) for action in result["actions_preview"]]
    assert ordinary_run in deleted_paths
    assert all("mcp_runs" not in str(path) for path in deleted_paths)


def test_collect_mcp_run_dirs_reads_run_json_layout(tmp_path: Path):
    runs_root = tmp_path / "runs" / "mcp_runs"
    mcp_run = _create_mcp_run(tmp_path / "runs", "mcp_001")

    collected = _collect_mcp_run_dirs(runs_root)

    assert len(collected) == 1
    assert collected[0][0] == mcp_run
    assert collected[0][3] == "succeeded"


def test_prune_mcp_runs_root_targets_only_mcp_runs(tmp_path: Path):
    root = tmp_path / "runs" / "mcp_runs"
    mcp_run = _create_mcp_run(tmp_path / "runs", "mcp_001")
    # Add a recent active run that should be preserved even if old timestamps exist elsewhere.
    active_run = root / "runs" / "mcp_active"
    active_run.mkdir(parents=True, exist_ok=True)
    (active_run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "mcp_active",
                "created_at": "2025-01-01T00:00:00Z",
                "started_at": "2025-01-01T00:00:01Z",
                "status": "running",
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )

    policy = RootPolicy(
        key="mcp_runs",
        root=root,
        mode="mcp_runs",
        max_age_days=30,
        max_total_gb=120.0,
    )

    result = _prune_mcp_runs_root(policy, now_ts=time.time(), apply=False)

    deleted_paths = [Path(action["path"]) for action in result["actions_preview"]]
    assert mcp_run in deleted_paths
    assert active_run not in deleted_paths


def test_classify_run_root_mode_detects_named_mcp_root(tmp_path: Path):
    root = tmp_path / "runs" / "mcp_runs"

    assert classify_run_root_mode(root) == "mcp_runs"
