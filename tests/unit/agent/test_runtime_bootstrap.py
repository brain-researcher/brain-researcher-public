from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_default_project_root_resolves_repo_root(monkeypatch) -> None:
    monkeypatch.setenv("BR_AGENT_BOOTSTRAP_DISABLED", "1")
    sys.modules.pop("brain_researcher.services.agent.runtime_bootstrap", None)

    module = importlib.import_module("brain_researcher.services.agent.runtime_bootstrap")
    expected_root = Path(__file__).resolve().parents[3]

    assert module._default_project_root() == expected_root
