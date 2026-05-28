from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.agent.preflight import (
    PreflightConfig,
    PreflightMode,
    run_preflight,
)


def test_run_preflight_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BR_PREFLIGHT_MIN_DISK_GB", "0.0001")
    data_file = tmp_path / "input.nii"
    data_file.write_bytes(b"test")

    report = run_preflight(
        tool_name="demo_tool",
        params={"input": str(data_file)},
        attachments=[{"name": "input.nii", "size": 10}],
        config=PreflightConfig(min_disk_gb=0.0001, check_timeout_sec=2, root_path=tmp_path),
    )

    assert report.ok is True
    assert report.disk_free_gb >= 0


def test_run_preflight_missing_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BR_PREFLIGHT_MIN_DISK_GB", "0.0001")

    missing = tmp_path / "missing.nii"
    report = run_preflight(
        tool_name="demo_tool",
        params={"input": str(missing)},
        config=PreflightConfig(min_disk_gb=0.0001, check_timeout_sec=2, root_path=tmp_path),
    )

    assert report.ok is False
    assert any(item.check == "input_files" for item in report.blockers)


def test_preflight_mode_from_env(monkeypatch) -> None:
    monkeypatch.setenv("BR_PREFLIGHT_MODE", "HARD_FAIL")
    assert PreflightMode.from_env() is PreflightMode.HARD_FAIL

    monkeypatch.setenv("BR_PREFLIGHT_MODE", "warn")  # lower case should map to WARN
    assert PreflightMode.from_env() is PreflightMode.WARN

    monkeypatch.setenv("BR_PREFLIGHT_MODE", "INVALID")
    assert PreflightMode.from_env() is PreflightMode.WARN
