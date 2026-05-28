from __future__ import annotations

from brain_researcher.services.agent import agent_factory


def test_get_llm_agent_uses_gemini_3_flash_as_default_chat(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    monkeypatch.delenv("DEFAULT_CODING_MODEL", raising=False)

    captured = {}

    def fake_get_cached_agent(model: str, tool_mode: str, coding_bias: bool):
        captured["model"] = model
        captured["tool_mode"] = tool_mode
        captured["coding_bias"] = coding_bias
        return "agent"

    monkeypatch.setattr(agent_factory, "_get_cached_agent", fake_get_cached_agent)

    result = agent_factory.get_llm_agent(tool_mode="auto", coding_bias=False)

    assert result == "agent"
    assert captured == {
        "model": "gemini-3-flash-preview",
        "tool_mode": "auto",
        "coding_bias": False,
    }


def test_get_llm_agent_uses_gemini_3_flash_as_default_coding(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    monkeypatch.delenv("DEFAULT_CODING_MODEL", raising=False)

    captured = {}

    def fake_get_cached_agent(model: str, tool_mode: str, coding_bias: bool):
        captured["model"] = model
        captured["tool_mode"] = tool_mode
        captured["coding_bias"] = coding_bias
        return "agent"

    monkeypatch.setattr(agent_factory, "_get_cached_agent", fake_get_cached_agent)

    result = agent_factory.get_llm_agent(tool_mode="required", coding_bias=True)

    assert result == "agent"
    assert captured == {
        "model": "gemini-3-flash-preview",
        "tool_mode": "required",
        "coding_bias": True,
    }
