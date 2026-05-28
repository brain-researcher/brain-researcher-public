"""Regression tests for local-first coding behavior in ChatOrchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from brain_researcher.services.agent.chat_orchestrator import (
    ChatOrchestrator,
)
from brain_researcher.services.agent.code_orchestrator import CodeResult


class DummyRouter:
    """Minimal router stub for tests."""

    def route_chat(self, prompt: str, *_, **__):
        return SimpleNamespace(text=f"LLM:{prompt}")


def make_orchestrator():
    return ChatOrchestrator(router=DummyRouter())


def test_coding_mode_prefers_local_llm_instructions(monkeypatch):
    """Coding mode should default to the local LLM path."""
    orchestrator = make_orchestrator()

    mock_code_orchestrator = MagicMock()
    monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        "modify the Makefile to add target demo-echo",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "repo_root": "/tmp/repo",
            "apply": False,
            "file_paths": ["Makefile"],
            "model_hint": "gemini-2.5-flash",
        },
    )

    mock_code_orchestrator.run_task.assert_not_called()
    assert reply.metadata["type"] == "coding_llm"
    assert reply.answer.startswith("LLM:")


def test_code_agent_escape_hatch_requires_explicit_opt_in_and_flag(monkeypatch):
    orchestrator = make_orchestrator()

    monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)
    assert orchestrator._should_use_code_agent_escape_hatch({}) is False
    assert (
        orchestrator._should_use_code_agent_escape_hatch({"force_code_agent": True})
        is False
    )

    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
    assert (
        orchestrator._should_use_code_agent_escape_hatch({"force_code_agent": True})
        is True
    )
    assert (
        orchestrator._should_use_code_agent_escape_hatch(
            {"force_code_agent": True, "explain_only": True}
        )
        is False
    )


def test_force_code_agent_routes_to_code_orchestrator(monkeypatch):
    """The explicit escape hatch should delegate to CodeOrchestrator.run_task()."""
    orchestrator = make_orchestrator()
    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")

    fake_result = CodeResult(
        status="success",
        answer="done",
        patches=["patch1"],
        files_touched=["Makefile"],
        iterations=1,
        test_status="passed",
        metadata={},
    )
    mock_code_orchestrator = MagicMock()
    mock_code_orchestrator.run_task.return_value = fake_result

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        "modify the Makefile to add target demo-echo",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "repo_root": "/tmp/repo",
            "apply": False,
            "file_paths": ["Makefile"],
            "model_hint": "gemini-2.5-flash",
            "force_code_agent": True,
        },
    )

    mock_code_orchestrator.run_task.assert_called_once()
    call_kwargs = mock_code_orchestrator.run_task.call_args[1]
    assert call_kwargs["instruction"].startswith("modify the Makefile")
    assert reply.metadata["type"] == "coding_tool"
    assert reply.metadata["tool"] == "code_agent"
    assert reply.answer == "done"


def test_force_code_agent_ignored_when_remote_code_agent_disabled(monkeypatch):
    """force_code_agent alone should not bypass local-first defaults."""
    orchestrator = make_orchestrator()

    mock_code_orchestrator = MagicMock()
    monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)
    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        "modify the Makefile to add target demo-echo",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "repo_root": "/tmp/repo",
            "force_code_agent": True,
        },
    )

    mock_code_orchestrator.run_task.assert_not_called()
    assert reply.metadata["type"] == "coding_llm"
    assert reply.answer.startswith("LLM:")


def test_explain_only_bypasses_tool_even_when_forced(monkeypatch):
    """explain_only should bypass CodeOrchestrator and use pure LLM."""
    orchestrator = make_orchestrator()

    mock_code_orchestrator = MagicMock()
    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.get_code_orchestrator",
        lambda: mock_code_orchestrator,
    )

    reply = orchestrator.handle_chat(
        "Explain how to write a factorial in Python",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "explain_only": True,
            "force_code_agent": True,
        },
    )

    mock_code_orchestrator.run_task.assert_not_called()
    assert reply.metadata["type"] == "coding_llm"
    assert reply.answer.startswith("LLM:")


def test_repair_context_uses_repair_specific_llm_prompt():
    """Repair loops should not reuse the generic 'return runnable code first' coder prompt."""
    orchestrator = make_orchestrator()

    reply = orchestrator.handle_chat(
        "Repair this failed Studio validation run.",
        history=[],
        ctx={
            "tools": {"mode": "coding"},
            "repair_context": {
                "run_id": "run-123",
                "error_type": "missing_input",
            },
        },
    )

    assert reply.metadata["type"] == "coding_llm"
    assert "neuroimaging repair assistant inside Studio" in reply.answer
    assert "Return runnable code first" not in reply.answer
