#!/usr/bin/env python3
"""Compatibility wrapper for ordinary and MCP run cleanup.

Usage:
    python scripts/cleanup_run_artifacts.py --days 30 --max-gb 100 --dry-run
    python scripts/cleanup_run_artifacts.py --days 7  # Delete runs older than 7 days
    python scripts/cleanup_run_artifacts.py --max-gb 50  # Keep total size under 50 GB
This legacy CLI keeps its flags, but delegates pruning behavior to
`scripts/ops/retention_policy.py`, which is the canonical retention engine.
"""

import argparse
import fcntl
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.config.run_artifacts import (
    get_mcp_run_roots_for_read,
    get_recorder_config,
    is_active_run,
    iter_recorded_run_dirs,
    iter_run_date_dirs,
)
from scripts.ops.retention_policy import (
    RootPolicy,
    classify_run_root_mode,
    prune_root_policy,
)


@dataclass
class RunInfo:
    """Information about a run directory."""

    run_dir: Path
    run_id: str
    state: str
    started_at: float
    size_bytes: int
    mtime: float

    @property
    def age_days(self) -> float:
        """Age of the run in days."""
        return (time.time() - self.started_at) / 86400

    @property
    def size_mb(self) -> float:
        """Size in megabytes."""
        return self.size_bytes / 1_048_576

    @property
    def is_active(self) -> bool:
        """Check if run is active (running or very recent)."""
        return is_active_run(self.state, self.mtime)


def get_dir_size(path: Path) -> int:
    """Calculate total size of directory and all its contents."""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except (OSError, PermissionError):
                    pass  # Skip files we can't access
    except (OSError, PermissionError):
        pass
    return total


def parse_run_info(run_dir: Path) -> RunInfo | None:
    """Parse run directory to extract metadata."""
    try:
        # Read status.json to get state and started_at
        status_file = run_dir / "status.json"
        if not status_file.exists():
            # Incomplete run, use directory mtime
            return RunInfo(
                run_dir=run_dir,
                run_id=run_dir.name,
                state="unknown",
                started_at=run_dir.stat().st_mtime,
                size_bytes=get_dir_size(run_dir),
                mtime=run_dir.stat().st_mtime,
            )

        with open(status_file) as f:
            status = json.load(f)

        return RunInfo(
            run_dir=run_dir,
            run_id=run_dir.name,
            state=status.get("state", "unknown"),
            started_at=status.get("started_at", run_dir.stat().st_mtime),
            size_bytes=get_dir_size(run_dir),
            mtime=run_dir.stat().st_mtime,
        )
    except (OSError, json.JSONDecodeError, KeyError):
        # If we can't parse, treat as unknown but still get basic info
        try:
            return RunInfo(
                run_dir=run_dir,
                run_id=run_dir.name,
                state="unknown",
                started_at=run_dir.stat().st_mtime,
                size_bytes=get_dir_size(run_dir),
                mtime=run_dir.stat().st_mtime,
            )
        except OSError:
            return None


def scan_runs(runs_root: Path) -> list[RunInfo]:
    """Scan all run directories and collect metadata."""
    runs = []

    if not runs_root.exists():
        return runs

    for run_dir in iter_recorded_run_dirs(runs_root):
        run_info = parse_run_info(run_dir)
        if run_info:
            runs.append(run_info)

    return runs


def cleanup_by_age(runs: list[RunInfo], max_age_days: float, dry_run: bool = False) -> int:
    """Delete runs older than max_age_days.

    Args:
        runs: List of run information
        max_age_days: Maximum age in days
        dry_run: If True, only print what would be deleted

    Returns:
        Number of runs deleted (or would be deleted in dry-run mode)
    """
    deleted_count = 0
    total_bytes_freed = 0

    for run in runs:
        if run.is_active:
            continue

        if run.age_days > max_age_days:
            if dry_run:
                print(
                    f"[DRY-RUN] Would delete: {run.run_dir} "
                    f"(age: {run.age_days:.1f} days, size: {run.size_mb:.1f} MB, state: {run.state})"
                )
            else:
                print(
                    f"Deleting: {run.run_dir} "
                    f"(age: {run.age_days:.1f} days, size: {run.size_mb:.1f} MB, state: {run.state})"
                )
                try:
                    shutil.rmtree(run.run_dir)
                except OSError as e:
                    print(f"  ERROR: Failed to delete {run.run_dir}: {e}")
                    continue

            deleted_count += 1
            total_bytes_freed += run.size_bytes

    if deleted_count > 0:
        print(
            f"\n{'[DRY-RUN] Would delete' if dry_run else 'Deleted'} {deleted_count} runs, "
            f"freeing {total_bytes_freed / 1_073_741_824:.2f} GB"
        )

    return deleted_count


def cleanup_by_size(runs: list[RunInfo], max_size_gb: float, dry_run: bool = False) -> int:
    """Delete oldest runs until total size is under max_size_gb.

    Args:
        runs: List of run information
        max_size_gb: Maximum total size in GB
        dry_run: If True, only print what would be deleted

    Returns:
        Number of runs deleted (or would be deleted in dry-run mode)
    """
    # Filter out active runs
    inactive_runs = [r for r in runs if not r.is_active]

    # Calculate current total size
    total_bytes = sum(r.size_bytes for r in inactive_runs)
    max_bytes = int(max_size_gb * 1_073_741_824)

    if total_bytes <= max_bytes:
        print(f"Total size {total_bytes / 1_073_741_824:.2f} GB is under limit {max_size_gb} GB")
        return 0

    print(
        f"Total size {total_bytes / 1_073_741_824:.2f} GB exceeds limit {max_size_gb} GB, "
        f"cleaning up oldest runs..."
    )

    # Sort by age (oldest first)
    sorted_runs = sorted(inactive_runs, key=lambda r: r.started_at)

    deleted_count = 0
    bytes_freed = 0

    for run in sorted_runs:
        if total_bytes - bytes_freed <= max_bytes:
            break

        if dry_run:
            print(
                f"[DRY-RUN] Would delete: {run.run_dir} "
                f"(age: {run.age_days:.1f} days, size: {run.size_mb:.1f} MB, state: {run.state})"
            )
        else:
            print(
                f"Deleting: {run.run_dir} "
                f"(age: {run.age_days:.1f} days, size: {run.size_mb:.1f} MB, state: {run.state})"
            )
            try:
                shutil.rmtree(run.run_dir)
            except OSError as e:
                print(f"  ERROR: Failed to delete {run.run_dir}: {e}")
                continue

        deleted_count += 1
        bytes_freed += run.size_bytes

    if deleted_count > 0:
        remaining_size = (total_bytes - bytes_freed) / 1_073_741_824
        print(
            f"\n{'[DRY-RUN] Would delete' if dry_run else 'Deleted'} {deleted_count} runs, "
            f"freeing {bytes_freed / 1_073_741_824:.2f} GB. "
            f"Remaining: {remaining_size:.2f} GB"
        )

    return deleted_count


def cleanup_empty_date_dirs(runs_root: Path, dry_run: bool = False) -> int:
    """Remove empty date directories after cleanup.

    Args:
        runs_root: Root directory containing date directories
        dry_run: If True, only print what would be deleted

    Returns:
        Number of directories removed
    """
    removed_count = 0

    if not runs_root.exists():
        return 0

    for date_dir in iter_run_date_dirs(runs_root):
        # Check if directory is empty
        try:
            if not any(date_dir.iterdir()):
                if dry_run:
                    print(f"[DRY-RUN] Would remove empty directory: {date_dir}")
                else:
                    print(f"Removing empty directory: {date_dir}")
                    date_dir.rmdir()
                removed_count += 1
        except OSError:
            pass

    return removed_count


def acquire_cleanup_lock(runs_root: Path) -> int | None:
    """Acquire exclusive lock for cleanup to prevent concurrent runs.

    Returns:
        File descriptor of lock file, or None if lock couldn't be acquired
    """
    lock_file = runs_root / ".cleanup.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = open(lock_file, "w")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (OSError, BlockingIOError):
        return None


def release_cleanup_lock(lock_fd):
    """Release cleanup lock."""
    if lock_fd:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
        except OSError:
            pass


def run_retention_cleanup(
    *,
    runs_root: Path,
    days: float | None,
    max_gb: float | None,
    dry_run: bool,
) -> dict:
    """Delegate pruning to the canonical retention policy implementation."""

    mode = classify_run_root_mode(runs_root)
    policy = RootPolicy(
        key="mcp_runs" if mode == "mcp_runs" else "data_runs",
        root=runs_root,
        mode=mode,
        max_age_days=days if days is not None else float("inf"),
        max_total_gb=max_gb if max_gb is not None else float("inf"),
    )
    return prune_root_policy(policy, now_ts=time.time(), apply=not dry_run)


def main():
    """Main cleanup routine."""
    parser = argparse.ArgumentParser(
        description="Cleanup run artifacts with age and size-based retention policies"
    )
    parser.add_argument(
        "--days",
        type=float,
        help="Delete runs older than N days",
    )
    parser.add_argument(
        "--max-gb",
        type=float,
        help="Keep total size under N GB (delete oldest runs first)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        help="Override runs root directory (default: from config)",
    )

    args = parser.parse_args()

    if not args.days and not args.max_gb:
        parser.error("At least one of --days or --max-gb must be specified")

    # Get runs root from config or override
    if args.runs_root:
        runs_root = args.runs_root
    else:
        config = get_recorder_config()
        runs_root = config.root

    print(f"Cleaning up run artifacts in: {runs_root}")
    mode = classify_run_root_mode(runs_root)
    if mode == "mcp_runs":
        aliases = ", ".join(str(path) for path in get_mcp_run_roots_for_read())
        print(f"Detected MCP metadata run root (aliases: {aliases})")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    # Acquire cleanup lock
    lock_fd = acquire_cleanup_lock(runs_root)
    if lock_fd is None:
        print("ERROR: Another cleanup process is already running")
        return 1

    try:
        result = run_retention_cleanup(
            runs_root=runs_root,
            days=args.days,
            max_gb=args.max_gb,
            dry_run=args.dry_run,
        )
        deleted_count = int(result.get("deleted_by_age_count", 0)) + int(
            result.get("deleted_by_size_count", 0)
        )
        total_before = float(result.get("total_before_bytes", 0)) / 1_073_741_824
        total_after = float(result.get("total_after_bytes", 0)) / 1_073_741_824

        print(f"Policy mode: {result.get('mode')}")
        print(f"Total size before: {total_before:.2f} GB")
        print(f"Total size after: {total_after:.2f} GB")
        print(
            f"Deleted by age: {result.get('deleted_by_age_count', 0)} "
            f"({float(result.get('deleted_by_age_bytes', 0)) / 1_073_741_824:.2f} GB)"
        )
        print(
            f"Deleted by size: {result.get('deleted_by_size_count', 0)} "
            f"({float(result.get('deleted_by_size_bytes', 0)) / 1_073_741_824:.2f} GB)"
        )

        if deleted_count == 0:
            print("No runs to delete")
        else:
            print(
                f"{'[DRY-RUN] Would delete' if args.dry_run else 'Deleted'} "
                f"{deleted_count} runs total"
            )

        return 0

    finally:
        release_cleanup_lock(lock_fd)


if __name__ == "__main__":
    exit(main())
