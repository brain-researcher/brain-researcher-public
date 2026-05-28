from __future__ import annotations

import os

from brain_researcher.core.utils import env_loader


def _reset_env_loader(monkeypatch) -> None:
    monkeypatch.setattr(env_loader, "_loaded", False)
    monkeypatch.setattr(env_loader, "_loaded_path", None)


def test_ensure_env_loaded_loads_env_and_env_local_with_local_precedence(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text(
        "FROM_ENV=base\nSHARED_KEY=from_env\n", encoding="utf-8"
    )
    (tmp_path / ".env.local").write_text(
        "FROM_LOCAL=local\nSHARED_KEY=from_local\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FROM_ENV", raising=False)
    monkeypatch.delenv("FROM_LOCAL", raising=False)
    monkeypatch.delenv("SHARED_KEY", raising=False)
    _reset_env_loader(monkeypatch)

    loaded_path = env_loader.ensure_env_loaded()

    assert loaded_path == (tmp_path / ".env.local").resolve()
    assert os.getenv("FROM_ENV") == "base"
    assert os.getenv("FROM_LOCAL") == "local"
    assert os.getenv("SHARED_KEY") == "from_local"


def test_ensure_env_loaded_does_not_override_process_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "PROC_WINS=from_env\nENV_ONLY=env_value\n", encoding="utf-8"
    )
    (tmp_path / ".env.local").write_text(
        "PROC_WINS=from_env_local\nLOCAL_ONLY=local_value\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROC_WINS", "from_process")
    monkeypatch.delenv("ENV_ONLY", raising=False)
    monkeypatch.delenv("LOCAL_ONLY", raising=False)
    _reset_env_loader(monkeypatch)

    loaded_path = env_loader.ensure_env_loaded()

    assert loaded_path == (tmp_path / ".env.local").resolve()
    assert os.getenv("PROC_WINS") == "from_process"
    assert os.getenv("ENV_ONLY") == "env_value"
    assert os.getenv("LOCAL_ONLY") == "local_value"
