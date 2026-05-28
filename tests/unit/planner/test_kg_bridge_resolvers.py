from __future__ import annotations

from brain_researcher.services.agent.planner import kg_bridge


class _DummySession:
    def __init__(self, value: str | None):
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, k=None):
        # Mimic neo4j result with .single()
        self._row = {"canon": self._value} if self._value is not None else None
        return self

    def single(self):
        return self._row

    def consume(self):
        return None


class _DummyDriver:
    def __init__(self, value: str | None):
        self._value = value

    def session(self):
        return _DummySession(self._value)


def test_resolve_tool_key_prefers_canonical(monkeypatch):
    monkeypatch.setattr(kg_bridge, "_get_driver", lambda: _DummyDriver("tool-canon"))
    assert kg_bridge.resolve_tool_key("tool-alias") == "tool-canon"


def test_resolve_version_key_fallback(monkeypatch):
    # When driver unavailable, returns original key
    monkeypatch.setattr(kg_bridge, "_get_driver", lambda: None)
    assert kg_bridge.resolve_version_key("ver123") == "ver123"
