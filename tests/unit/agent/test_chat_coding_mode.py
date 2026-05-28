"""Integration-ish tests for coding mode in ChatOrchestrator.

These tests avoid real LLM/tool execution by patching CodeOrchestrator and Router.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.code_orchestrator import CodeResult


class DummyRouter:
    def __init__(self):
        self.last_prompt = None

    def route_chat(self, prompt, **kwargs):
        self.last_prompt = prompt
        return SimpleNamespace(
            text="fallback coder reply", metadata=SimpleNamespace(**{})
        )


class DummyMemory:
    def append(self, *args, **kwargs):  # pragma: no cover - not essential for logic
        return None


@pytest.fixture()
def orchestrator(monkeypatch):
    router = DummyRouter()
    orch = ChatOrchestrator(router=router, memory=DummyMemory(), error_recovery=False)
    return orch


def test_coding_mode_defaults_to_llm(monkeypatch, orchestrator):
    """coding mode should stay local-first unless remote execution is enabled."""

    mock_code_orchestrator = MagicMock()

    monkeypatch.setenv("CODE_AGENT_MODEL_HINT", "gpt-test")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-default")
    monkeypatch.setenv("LLM_ONLY_FALLBACK", "0")
    monkeypatch.setenv("DISABLE_GEMINI_CLI", "1")
    monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        user_msg="write a factorial function",
        history=[],
        ctx={
            "tools": {"mode": "coding", "model_hint": "gpt-coder"},
            "repo_root": "/tmp/repo",
        },
    )

    mock_code_orchestrator.run_task.assert_not_called()
    assert reply.metadata["type"] == "coding_llm"
    assert reply.tool_calls == []
    assert "fallback coder reply" in reply.answer.lower()


def test_force_code_agent_with_env_opt_in_invokes_code_orchestrator(
    monkeypatch, orchestrator
):
    """force_code_agent should only work when BR_ENABLE_CODE_AGENT_TOOL=1."""

    captured = {}

    mock_code_orchestrator = MagicMock()
    mock_code_orchestrator.run_task.return_value = CodeResult(
        status="success",
        answer="done",
        patches=["patch1"],
        files_touched=["test.py"],
        iterations=1,
        test_status="passed",
        metadata={},
    )

    def capture_run_task(*args, **kwargs):
        captured["kwargs"] = kwargs
        return mock_code_orchestrator.run_task.return_value

    mock_code_orchestrator.run_task.side_effect = capture_run_task

    monkeypatch.setenv("CODE_AGENT_MODEL_HINT", "gpt-test")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-default")
    monkeypatch.setenv("LLM_ONLY_FALLBACK", "0")
    monkeypatch.setenv("DISABLE_GEMINI_CLI", "1")
    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        user_msg="write a factorial function",
        history=[],
        ctx={
            "tools": {"mode": "coding", "model_hint": "gpt-coder"},
            "repo_root": "/tmp/repo",
            "force_code_agent": True,
        },
    )

    mock_code_orchestrator.run_task.assert_called_once()
    assert captured["kwargs"]["ctx"]["tools"]["model_hint"] == "gpt-coder"
    assert reply.metadata["type"] == "coding_tool"
    assert reply.tool_calls


def test_coding_mode_fallback_to_llm(monkeypatch, orchestrator):
    """If CodeOrchestrator fails, fall back to coder LLM."""

    mock_code_orchestrator = MagicMock()
    mock_code_orchestrator.run_task.side_effect = RuntimeError("boom")

    monkeypatch.setenv("LLM_ONLY_FALLBACK", "0")
    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        user_msg="write a factorial function",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "repo_root": "/tmp/repo",
            "force_code_agent": True,
        },
    )

    assert reply.metadata["type"] == "coding_llm"
    assert reply.tool_calls == []
    # Fallback should come from coder LLM
    assert "reply" in reply.answer.lower()
