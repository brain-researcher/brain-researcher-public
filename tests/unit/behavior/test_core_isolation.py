"""Core isolation: importing the behavior package must not require psyflow."""

from __future__ import annotations

import importlib
import sys


def test_imports_without_psyflow(monkeypatch):
    # Force psyflow to look absent for the duration of these imports.
    monkeypatch.setitem(sys.modules, "psyflow", None)
    modules = [
        "brain_researcher.behavior",
        "brain_researcher.behavior.task_spec",
        "brain_researcher.behavior.catalog",
        "brain_researcher.behavior.psyflow_adapter",
        "brain_researcher.behavior.workflow",
    ]
    for mod in modules:
        sys.modules.pop(mod, None)
    for mod in modules:
        importlib.import_module(mod)
