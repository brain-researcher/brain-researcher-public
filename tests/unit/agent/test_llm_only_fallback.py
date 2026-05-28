"""Tests for the LLM-only fallback path in agent_act_core.

This does not hit the network: we patch the openai client to return a stubbed
response so the test stays hermetic and fast.
"""

import sys
import types

import pytest


class FakeChoice:
    def __init__(self, content: str):
        self.message = types.SimpleNamespace(content=content)


class FakeCompletion:
    def __init__(self, text: str):
        self.choices = [FakeChoice(text)]


class FakeCompletions:
    def __init__(self, text: str):
        self._text = text

    def create(self, model: str, messages):
        # Ignore model/messages for the stub; return deterministic content
        return FakeCompletion(self._text)


class FakeChat:
    def __init__(self, text: str):
        self.completions = FakeCompletions(text)


class FakeOpenAI:
    def __init__(self, api_key=None):
        self.chat = FakeChat("stubbed llm reply")


@pytest.fixture(autouse=True)
def patch_openai(monkeypatch):
    """Patch the openai module so no real network calls happen."""
    fake_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    yield
    # Cleanup is automatic because monkeypatch will restore sys.modules entries


def test_llm_only_fallback_returns_reply(monkeypatch):
    """LLM_ONLY_FALLBACK should return 200-style payload with assistant message."""
    from brain_researcher.services.agent.agent_core import agent_act_core

    monkeypatch.setenv("LLM_ONLY_FALLBACK", "1")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")
    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    payload = {
        "query": "hello",
        "messages": [{"role": "user", "content": "hello"}],
    }

    result = agent_act_core(payload)

    assert "message" in result
    assert result["message"].get("content") == "stubbed llm reply"
    assert result.get("tool_calls") == []
    assert result.get("runCard", {}).get("execution", {}).get("route") == "llm_only_direct"
