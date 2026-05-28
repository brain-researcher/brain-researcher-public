import builtins

import pytest

from brain_researcher.services.orchestrator.job_store_factory import get_job_store
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def _block_sqlite_job_store_import(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("sqlite_job_store"):
            raise ImportError("simulated missing sqlite dependency")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_sqlite_backend_falls_back_to_memory_when_not_strict(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("BR_STRICT_SQLITE_BACKEND", "0")
    _block_sqlite_job_store_import(monkeypatch)

    store = get_job_store(backend="sqlite", db_path="/tmp/test-jobs.sqlite")
    assert isinstance(store, MemoryJobStore)


def test_sqlite_backend_raises_in_strict_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_STRICT_SQLITE_BACKEND", "1")
    _block_sqlite_job_store_import(monkeypatch)

    with pytest.raises(RuntimeError, match="Strict sqlite mode is enabled"):
        get_job_store(backend="sqlite", db_path="/tmp/test-jobs.sqlite")


def test_sqlite_backend_is_strict_by_default_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BR_STRICT_SQLITE_BACKEND", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    _block_sqlite_job_store_import(monkeypatch)

    with pytest.raises(RuntimeError, match="Strict sqlite mode is enabled"):
        get_job_store(backend="sqlite", db_path="/tmp/test-jobs.sqlite")
