"""Tests for the lazy psyflow adapter."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_researcher.behavior import psyflow_adapter
from brain_researcher.behavior.catalog import config_mapper_for, resolve_defaults
from brain_researcher.behavior.psyflow_adapter import (
    PsyflowNotInstalledError,
    _import_psyflow,
    ingest_psyflow_run,
    run_psyflow_validate,
    write_psyflow_scaffold,
)


def test_write_scaffold_lives_under_planned(tmp_path: Path):
    spec = resolve_defaults("n_back")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("n_back"))
    planned = Path(bundle.planned_dir)
    assert planned.exists()
    assert (tmp_path / "planned" / "n_back").resolve() == planned.resolve()
    # never under <out>/run/
    assert not str(planned.resolve()).startswith(str((tmp_path / "run").resolve()))
    for rel in bundle.files:
        assert (planned / rel).exists()


def test_write_scaffold_files_contents(tmp_path: Path):
    spec = resolve_defaults("go_no_go")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("go_no_go"))
    planned = Path(bundle.planned_dir)
    digest_on_disk = (planned / "spec_digest.txt").read_text().strip()
    assert digest_on_disk == bundle.spec_digest
    assert (planned / "config" / "config.yaml").read_text()
    assert "def main" in (planned / "main.py").read_text()


def test_import_psyflow_raises_when_absent(monkeypatch: pytest.MonkeyPatch):
    # Simulate ImportError for psyflow regardless of whether extra is installed.
    monkeypatch.setitem(sys.modules, "psyflow", None)
    with pytest.raises(PsyflowNotInstalledError):
        _import_psyflow()


def test_import_psyflow_shims_upstream_version_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Simulate the upstream wheel bug: psyflow imports ``._version`` at module
    # import time, but the real module would explode looking for pyproject.toml.
    pkg_root = tmp_path / "psyflow"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text(
        "from ._version import __version__\n", encoding="utf-8"
    )
    (pkg_root / "_version.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).resolve().parent.parent.joinpath('pyproject.toml').read_text()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "psyflow", raising=False)
    monkeypatch.delitem(sys.modules, "psyflow._version", raising=False)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.1.12")
    mod = _import_psyflow()
    assert mod.__version__ == "0.1.12"


def test_ingest_rejects_path_outside_run_tree(tmp_path: Path):
    spec = resolve_defaults("n_back")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("n_back"))
    bad_dir = tmp_path / "planned" / "n_back"  # not under <out>/run/
    with pytest.raises(ValueError, match="planned vs run split"):
        ingest_psyflow_run(bundle, bad_dir, tmp_path)


def test_ingest_accepts_path_under_run_tree(tmp_path: Path):
    spec = resolve_defaults("n_back")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("n_back"))
    run_dir = tmp_path / "run" / "session1"
    run_dir.mkdir(parents=True)
    # Empty run dir - ingest will likely return error from BehaviorIngestTAPSTool
    # but MUST NOT raise on the path check.
    result = ingest_psyflow_run(bundle, run_dir, tmp_path)
    assert result["run_dir"] == str(run_dir.resolve())
    assert "status" in result


def test_run_psyflow_validate_prefers_validate_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = resolve_defaults("n_back")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("n_back"))
    seen: dict[str, object] = {}

    def fake_validate_config(raw_config, *, required_sections=None):
        seen["raw_config"] = raw_config
        seen["required_sections"] = required_sections
        return None

    monkeypatch.setattr(
        psyflow_adapter,
        "_import_psyflow",
        lambda: SimpleNamespace(validate_config=fake_validate_config),
    )

    result = run_psyflow_validate(bundle)

    assert result["status"] == "success"
    assert isinstance(seen["raw_config"], dict)
    assert seen["raw_config"]["task"]["paradigm"] == "n_back"
    assert seen["required_sections"] is None


def test_run_psyflow_validate_falls_back_to_legacy_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = resolve_defaults("flanker")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("flanker"))
    seen: dict[str, object] = {}

    def fake_validate(cfg_path: str):
        seen["cfg_path"] = cfg_path
        return {"ok": True}

    monkeypatch.setattr(
        psyflow_adapter,
        "_import_psyflow",
        lambda: SimpleNamespace(validate=fake_validate),
    )

    result = run_psyflow_validate(bundle)

    assert result == {"status": "success", "result": {"ok": True}}
    assert seen["cfg_path"] == str(Path(bundle.bundle_dir) / bundle.config_path)


def test_run_psyflow_validate_skips_when_no_known_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = resolve_defaults("go_no_go")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("go_no_go"))

    monkeypatch.setattr(
        psyflow_adapter,
        "_import_psyflow",
        lambda: SimpleNamespace(),
    )

    result = run_psyflow_validate(bundle)

    assert result["status"] == "skipped"
    assert "validate_config" in result["reason"]
