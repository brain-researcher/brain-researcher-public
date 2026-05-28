from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "runtime"
    / "psyflow_sitecustomize.py"
)


def test_psyflow_sitecustomize_primes_version_module(
    monkeypatch,
) -> None:
    sys.modules.pop("psyflow._version", None)

    def _fake_version(name: str) -> str:
        if name == "psyflow":
            return "9.9.9"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _fake_version)

    spec = importlib.util.spec_from_file_location(
        "br_psyflow_sitecustomize_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    shim = sys.modules["psyflow._version"]
    assert shim.__version__ == "9.9.9"

    sys.modules.pop("psyflow._version", None)
