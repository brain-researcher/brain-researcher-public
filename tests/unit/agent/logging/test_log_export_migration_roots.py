from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.agent.logging.export import LogExporter
from brain_researcher.services.agent.logging.migration import LogMigrator


def _write_session_log(root: Path, date: str, payloads: list[dict]) -> None:
    session_file = root / "sessions" / f"{date}.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    with session_file.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload) + "\n")


def test_log_exporter_reads_primary_and_alias_metadata_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    primary_root = tmp_path / "artifacts" / "metadata"
    legacy_root = tmp_path / "legacy-metadata"
    monkeypatch.setenv("BR_METADATA_DIR", str(primary_root))
    monkeypatch.setenv("BR_METADATA_DIR_ALIASES", str(legacy_root))

    _write_session_log(
        primary_root,
        "2026-03-14",
        [
            {
                "run_id": "run_primary",
                "phase": "planning",
                "status": "SUCCESS",
                "request": {"query": "primary"},
                "timestamps": {
                    "ts_event_utc": "2026-03-14T12:00:00Z",
                    "perf": {"duration_ms": 1},
                },
            }
        ],
    )
    _write_session_log(
        legacy_root,
        "2026-03-15",
        [
            {
                "run_id": "run_legacy",
                "phase": "execution",
                "status": "SUCCESS",
                "request": {"query": "legacy"},
                "timestamps": {
                    "ts_event_utc": "2026-03-15T12:00:00Z",
                    "perf": {"duration_ms": 2},
                },
            }
        ],
    )

    exporter = LogExporter()
    logs = exporter._load_logs()

    assert [log["run_id"] for log in logs] == ["run_primary", "run_legacy"]


def test_log_exporter_dedupes_identical_records_across_read_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    primary_root = tmp_path / "artifacts" / "metadata"
    legacy_root = tmp_path / "legacy-metadata"
    monkeypatch.setenv("BR_METADATA_DIR", str(primary_root))
    monkeypatch.setenv("BR_METADATA_DIR_ALIASES", str(legacy_root))

    payload = {
        "run_id": "run_duplicate",
        "phase": "planning",
        "status": "SUCCESS",
        "request": {"query": "duplicate"},
        "timestamps": {
            "ts_event_utc": "2026-03-14T12:00:00Z",
            "perf": {"duration_ms": 1},
        },
    }
    _write_session_log(primary_root, "2026-03-14", [payload])
    _write_session_log(legacy_root, "2026-03-14", [payload])

    exporter = LogExporter()
    logs = exporter._load_logs()

    assert len(logs) == 1
    assert logs[0]["run_id"] == "run_duplicate"


def test_log_migrator_reads_target_jsonl_files_across_primary_and_alias_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    primary_root = tmp_path / "artifacts" / "metadata"
    legacy_root = tmp_path / "legacy-metadata"
    monkeypatch.setenv("BR_METADATA_DIR", str(primary_root))
    monkeypatch.setenv("BR_METADATA_DIR_ALIASES", str(legacy_root))

    _write_session_log(primary_root, "2026-03-14", [{"run_id": "run_primary"}])
    _write_session_log(legacy_root, "2026-03-15", [{"run_id": "run_legacy"}])

    migrator = LogMigrator()
    files = migrator.iter_target_jsonl_files()

    assert migrator.target_path == primary_root.resolve()
    assert {path.parent.parent for path in files} == {
        primary_root.resolve(),
        legacy_root.resolve(),
    }
