"""Marimo runtime import shim for direct psyflow task execution.

TaskBeacon task packages import ``psyflow`` directly. The pinned psyflow wheel
currently imports ``psyflow._version``, which tries to read a missing
``pyproject.toml`` from site-packages. BR's internal adapter already primes this
shim for managed calls; this runtime-only sitecustomize covers shell execution
such as ``python main.py qa`` inside hosted marimo workspaces.
"""

from __future__ import annotations

import importlib.metadata
import sys
from types import ModuleType


def _prime_psyflow_version_shim() -> None:
    if "psyflow._version" in sys.modules:
        return
    try:
        version = importlib.metadata.version("psyflow")
    except importlib.metadata.PackageNotFoundError:
        return
    shim = ModuleType("psyflow._version")
    shim.__version__ = version
    sys.modules["psyflow._version"] = shim


_prime_psyflow_version_shim()
