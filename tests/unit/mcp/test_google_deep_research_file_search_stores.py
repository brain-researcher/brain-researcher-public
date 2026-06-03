from __future__ import annotations

import sys
from types import SimpleNamespace


def test_google_deep_research_start_uses_multi_store_env(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv(
        "BR_FILE_SEARCH_STORE_NAMES",
        "papers-fmri-oa-20152025-uni-aqus07ky5cos,brain-researcher-codebase-5i70bkfmcumj",
    )

    captured: dict[str, object] = {}

    class FakeInteraction:
        id = "int-multi-store"
        status = "pending"

        @staticmethod
        def model_dump():
            return {"id": FakeInteraction.id, "status": FakeInteraction.status}

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            Tool=object,
            FileSearch=object,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_start(input="test request")

    assert resp["ok"] is True
    assert resp["poll_tool"] == "run_get"
    assert resp["compat_poll_tool"] == "google_deep_research_get"
    assert resp["data"]["interaction_id"] == "int-multi-store"
    tools = captured["tools"]
    assert all(isinstance(tool, dict) and tool.get("type") for tool in tools)
    assert tools == [
        {"type": "google_search"},
        {
            "type": "file_search",
            "file_search_store_names": [
                "fileSearchStores/papers-fmri-oa-20152025-uni-aqus07ky5cos",
                "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj",
            ],
        }
    ]
