#!/usr/bin/env python3
"""Move legacy repo-root metadata logs into the canonical artifacts root."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from brain_researcher.config.run_artifacts import (
    METADATA_ROOT_LEGACY_FALLBACK,
    get_metadata_root,
)


@dataclass
class MigrationStats:
    """Summary of a metadata-root migration run."""

    source_root: Path
    target_root: Path
    mode: str
    dry_run: bool
    files_transferred: int = 0
    files_skipped: int = 0
    files_overwritten: int = 0
    dirs_pruned: int = 0
    source_missing: bool = False
    source_root_removed: bool = False


def _resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _target_within_source(source_root: Path, target_root: Path) -> bool:
    try:
        target_root.relative_to(source_root)
    except ValueError:
        return False
    return True


def _should_skip(src: Path, dst: Path) -> bool:
    """Return True when destination is already newer (or same file)."""

    if not dst.exists():
        return False
    src_stat = src.stat()
    dst_stat = dst.stat()
    if dst_stat.st_mtime_ns > src_stat.st_mtime_ns:
        return True
    return (
        dst_stat.st_mtime_ns == src_stat.st_mtime_ns
        and dst_stat.st_size == src_stat.st_size
    )


def _iter_source_files(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*") if path.is_file())


def _prune_empty_dirs(source_root: Path) -> int:
    """Remove empty directories under source_root, including source_root itself."""

    pruned = 0
    for directory in sorted(
        (path for path in source_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            continue
        pruned += 1
    try:
        source_root.rmdir()
    except OSError:
        return pruned
    return pruned + 1


def migrate_metadata_root(
    *,
    source_root: str | Path | None = None,
    target_root: str | Path | None = None,
    mode: str = "move",
    dry_run: bool = False,
) -> MigrationStats:
    """Migrate repo-root metadata files into the canonical artifacts root."""

    resolved_source = _resolve_path(source_root or METADATA_ROOT_LEGACY_FALLBACK)
    resolved_target = _resolve_path(target_root or get_metadata_root())
    chosen_mode = mode.lower().strip()
    if chosen_mode not in {"move", "copy"}:
        raise ValueError(f"Unsupported mode: {mode}")
    if resolved_source == resolved_target:
        raise ValueError("Source and target metadata roots must differ")
    if _target_within_source(resolved_source, resolved_target):
        raise ValueError("Target metadata root may not live under the source root")

    stats = MigrationStats(
        source_root=resolved_source,
        target_root=resolved_target,
        mode=chosen_mode,
        dry_run=dry_run,
    )

    if not resolved_source.exists():
        stats.source_missing = True
        return stats

    for src in _iter_source_files(resolved_source):
        relative_path = src.relative_to(resolved_source)
        dst = resolved_target / relative_path

        if _should_skip(src, dst):
            stats.files_skipped += 1
            continue

        stats.files_transferred += 1
        if dst.exists():
            stats.files_overwritten += 1

        if dry_run:
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if chosen_mode == "move":
            src.unlink()

    if chosen_mode == "move" and not dry_run and resolved_source.exists():
        stats.dirs_pruned = _prune_empty_dirs(resolved_source)
        stats.source_root_removed = not resolved_source.exists()

    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Move legacy repo-root metadata logs into the canonical artifacts root."
        )
    )
    parser.add_argument(
        "--source",
        default=str(METADATA_ROOT_LEGACY_FALLBACK),
        help="Legacy metadata root to migrate from (default: repo-root metadata/)",
    )
    parser.add_argument(
        "--target",
        default=str(get_metadata_root()),
        help="Canonical metadata root to migrate into (default: artifacts/metadata)",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would move without modifying the filesystem",
    )
    return parser


def _print_summary(stats: MigrationStats) -> None:
    if stats.source_missing:
        print(f"Source missing: {stats.source_root}")
        return
    print(f"Source: {stats.source_root}")
    print(f"Target: {stats.target_root}")
    print(f"Mode: {stats.mode}")
    print(f"Dry run: {stats.dry_run}")
    print(f"Transferred: {stats.files_transferred}")
    print(f"Skipped newer targets: {stats.files_skipped}")
    print(f"Overwrote older targets: {stats.files_overwritten}")
    if stats.mode == "move" and not stats.dry_run:
        print(f"Pruned empty dirs: {stats.dirs_pruned}")
        print(f"Removed source root: {stats.source_root_removed}")


def main() -> int:
    args = _build_parser().parse_args()
    stats = migrate_metadata_root(
        source_root=args.source,
        target_root=args.target,
        mode="copy" if args.copy else "move",
        dry_run=args.dry_run,
    )
    _print_summary(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
