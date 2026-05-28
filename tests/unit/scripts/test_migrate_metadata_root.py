from __future__ import annotations

from pathlib import Path

from scripts import migrate_metadata_root as module


def _write_jsonl(path: Path, content: str, *, mtime: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        path.touch()
        path.chmod(0o644)
        import os

        os.utime(path, (mtime, mtime))


def test_migrate_metadata_root_moves_files_and_prunes_source(tmp_path: Path) -> None:
    source_root = tmp_path / "metadata"
    target_root = tmp_path / "artifacts" / "metadata"
    _write_jsonl(source_root / "sessions" / "2026-03-14.jsonl", "session\n")
    _write_jsonl(source_root / "agent" / "executions.jsonl", "agent\n")

    stats = module.migrate_metadata_root(
        source_root=source_root,
        target_root=target_root,
        mode="move",
        dry_run=False,
    )

    assert stats.files_transferred == 2
    assert stats.files_skipped == 0
    assert (target_root / "sessions" / "2026-03-14.jsonl").read_text(
        encoding="utf-8"
    ) == "session\n"
    assert (target_root / "agent" / "executions.jsonl").read_text(
        encoding="utf-8"
    ) == "agent\n"
    assert not source_root.exists()
    assert stats.source_root_removed is True


def test_migrate_metadata_root_skips_newer_destination(tmp_path: Path) -> None:
    source_root = tmp_path / "metadata"
    target_root = tmp_path / "artifacts" / "metadata"
    _write_jsonl(
        source_root / "sessions" / "2026-03-14.jsonl",
        "older-source\n",
        mtime=100,
    )
    _write_jsonl(
        target_root / "sessions" / "2026-03-14.jsonl",
        "newer-target\n",
        mtime=200,
    )

    stats = module.migrate_metadata_root(
        source_root=source_root,
        target_root=target_root,
        mode="move",
        dry_run=False,
    )

    assert stats.files_transferred == 0
    assert stats.files_skipped == 1
    assert (target_root / "sessions" / "2026-03-14.jsonl").read_text(
        encoding="utf-8"
    ) == "newer-target\n"
    assert (source_root / "sessions" / "2026-03-14.jsonl").exists()


def test_migrate_metadata_root_overwrites_older_destination(tmp_path: Path) -> None:
    source_root = tmp_path / "metadata"
    target_root = tmp_path / "artifacts" / "metadata"
    _write_jsonl(
        source_root / "planner" / "executions.jsonl",
        "new-source\n",
        mtime=200,
    )
    _write_jsonl(
        target_root / "planner" / "executions.jsonl",
        "old-target\n",
        mtime=100,
    )

    stats = module.migrate_metadata_root(
        source_root=source_root,
        target_root=target_root,
        mode="move",
        dry_run=False,
    )

    assert stats.files_transferred == 1
    assert stats.files_overwritten == 1
    assert (target_root / "planner" / "executions.jsonl").read_text(
        encoding="utf-8"
    ) == "new-source\n"
    assert not source_root.exists()


def test_migrate_metadata_root_dry_run_does_not_modify_files(tmp_path: Path) -> None:
    source_root = tmp_path / "metadata"
    target_root = tmp_path / "artifacts" / "metadata"
    _write_jsonl(source_root / "sessions" / "2026-03-14.jsonl", "session\n")

    stats = module.migrate_metadata_root(
        source_root=source_root,
        target_root=target_root,
        mode="move",
        dry_run=True,
    )

    assert stats.files_transferred == 1
    assert source_root.exists()
    assert not target_root.exists()


def test_migrate_metadata_root_reports_missing_source(tmp_path: Path) -> None:
    stats = module.migrate_metadata_root(
        source_root=tmp_path / "metadata",
        target_root=tmp_path / "artifacts" / "metadata",
        mode="move",
        dry_run=False,
    )

    assert stats.source_missing is True
    assert stats.files_transferred == 0
