from __future__ import annotations

import importlib
import sys


def test_web_service_defaults_orchestrator_to_3001(monkeypatch) -> None:
    for key in (
        "BR_ORCHESTRATOR_URL",
        "ORCHESTRATOR_BASE_URL",
        "ORCHESTRATOR_URL",
        "ORCHESTRATOR_API_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    sys.modules.pop("brain_researcher.services.agent.web_service", None)
    module = importlib.import_module("brain_researcher.services.agent.web_service")

    assert module.ORCHESTRATOR_BASE_URL == "http://localhost:3001"
