from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.config import paths


def _clear_caches() -> None:
    paths.clear_path_caches()


def test_get_config_root_defaults_to_repo_configs(monkeypatch):
    monkeypatch.delenv("BR_CONFIG_ROOT", raising=False)
    _clear_caches()

    cfg = paths.get_config_root()
    assert cfg.exists()
    assert cfg.name == "configs"
    assert (cfg / "catalog").exists()


def test_resolve_from_config_joins_parts(monkeypatch):
    monkeypatch.delenv("BR_CONFIG_ROOT", raising=False)
    _clear_caches()

    resolved = paths.resolve_from_config("catalog", "chat_tools.yaml")
    assert resolved.exists()
    assert resolved.name == "chat_tools.yaml"


def test_repo_relative_roots_resolve_from_configs_root(monkeypatch):
    monkeypatch.delenv("BR_CONFIG_ROOT", raising=False)
    _clear_caches()

    repo_root = paths.get_repo_root()
    assert paths.get_src_root() == repo_root / "src"
    assert paths.get_package_root() == repo_root / "src" / "brain_researcher"
    assert paths.get_apps_root() == repo_root / "apps"
    assert paths.get_data_root() == repo_root / "data"
    assert paths.get_outputs_root() == repo_root / "outputs"
    assert paths.resolve_from_repo("apps", "web-ui") == repo_root / "apps" / "web-ui"


def test_default_atlas_output_root_honors_runtime_override(monkeypatch, tmp_path):
    atlas_root = tmp_path / "atlases"
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(atlas_root))
    _clear_caches()

    assert paths.get_default_atlas_output_root() == atlas_root


def test_get_config_root_honors_repo_override(monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("BR_CONFIG_ROOT", str(repo_root))
    _clear_caches()

    assert paths.get_config_root() == repo_root / "configs"


def test_get_config_root_honors_configs_override(monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    configs_root = repo_root / "configs"
    monkeypatch.setenv("BR_CONFIG_ROOT", str(configs_root))
    _clear_caches()

    assert paths.get_config_root() == configs_root


def test_get_config_root_invalid_override_raises(monkeypatch, tmp_path):
    bad = tmp_path / "does_not_exist"
    monkeypatch.setenv("BR_CONFIG_ROOT", str(bad))
    _clear_caches()

    with pytest.raises(FileNotFoundError):
        paths.get_config_root()
