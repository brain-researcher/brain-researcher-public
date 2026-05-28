"""Local fixtures for ingestion unit tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dirs() -> dict[str, str]:
    """Create temporary directories for data archiver tests."""
    archive_dir = tempfile.mkdtemp()
    staging_dir = tempfile.mkdtemp()
    db_file = tempfile.NamedTemporaryFile(delete=False)
    db_path = db_file.name
    db_file.close()

    yield {
        "archive_dir": archive_dir,
        "staging_dir": staging_dir,
        "db_path": db_path,
    }

    shutil.rmtree(archive_dir, ignore_errors=True)
    shutil.rmtree(staging_dir, ignore_errors=True)
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def temp_dir() -> str:
    """Create a temporary directory path for export pipeline tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def benchmark():
    """Lightweight benchmark shim when pytest-benchmark isn't installed."""
    def _run(func, *args, **kwargs):
        return func(*args, **kwargs)

    return _run
