from __future__ import annotations

import json
from types import SimpleNamespace

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.memory import ConversationMemory


class DummyRouter:
    def route_chat(self, prompt, *args, **kwargs):
        if isinstance(prompt, str) and "Respond ONLY with JSON" in prompt:
            return SimpleNamespace(
                text=json.dumps({"tool": "no_tool", "params": {}, "reasoning": "none"}),
                metadata=None,
            )
        return SimpleNamespace(text="direct answer", metadata=None)


class StubToolRouter:
    def get_candidates(self, user_msg, history=None, ctx=None):
        return []


class StubRegistry:
    def get_runtime_tool(self, tool_id):
        return None

    def get_all_tools(self):
        return []


def _make_orchestrator(tmp_path):
    return ChatOrchestrator(
        router=DummyRouter(),
        tool_router=StubToolRouter(),
        tool_registry=StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
        enable_knowledge_layer=False,
    )


def test_chat_orchestrator_autoroutes_mcp_selftest_quick(monkeypatch, tmp_path):
    calls = []

    def _fake_selftest(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "mode": kwargs.get("mode", "quick"),
            "overall": "pass",
            "summary_text": "MCP self-test mode=quick overall=pass",
            "counts": {"pass": 3, "warn": 0, "fail": 0, "skip": 0},
            "probes": [],
            "recommendations": [],
        }

    monkeypatch.setenv("BR_AGENT_MCP_SELFTEST_AUTOROUTE", "1")
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    monkeypatch.setattr(
        "brain_researcher.services.mcp.server.system_self_test",
        _fake_selftest,
    )

    orch = _make_orchestrator(tmp_path)
    reply = orch.handle_chat("check this MCP status for me", history=[], ctx={})

    assert calls, "expected mcp self-test to be called"
    assert calls[0]["mode"] == "quick"
    assert reply.metadata["type"] == "mcp_selftest"
    assert reply.metadata["mode"] == "quick"
    assert "overall=pass" in reply.answer


def test_chat_orchestrator_autoroutes_mcp_selftest_active(monkeypatch, tmp_path):
    calls = []

    def _fake_selftest(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "mode": kwargs.get("mode", "active"),
            "overall": "degraded",
            "summary_text": "MCP self-test mode=active overall=degraded",
            "counts": {"pass": 4, "warn": 1, "fail": 0, "skip": 0},
            "probes": [],
            "recommendations": [],
        }

    monkeypatch.setenv("BR_AGENT_MCP_SELFTEST_AUTOROUTE", "1")
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    monkeypatch.setattr(
        "brain_researcher.services.mcp.server.system_self_test",
        _fake_selftest,
    )

    orch = _make_orchestrator(tmp_path)
    reply = orch.handle_chat(
        "run full MCP self-test with KG container script probes",
        history=[],
        ctx={},
    )

    assert calls, "expected mcp self-test to be called"
    assert calls[0]["mode"] == "active"
    assert reply.metadata["type"] == "mcp_selftest"
    assert reply.metadata["mode"] == "active"


def test_chat_orchestrator_does_not_trigger_mcp_selftest_for_normal_queries(
    monkeypatch, tmp_path
):
    calls = []

    def _fake_selftest(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "summary_text": "unused"}

    monkeypatch.setenv("BR_AGENT_MCP_SELFTEST_AUTOROUTE", "1")
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    monkeypatch.setattr(
        "brain_researcher.services.mcp.server.system_self_test",
        _fake_selftest,
    )

    orch = _make_orchestrator(tmp_path)
    reply = orch.handle_chat("what is cognitive control?", history=[], ctx={})

    assert calls == []
    metadata = reply.metadata or {}
    assert metadata.get("type") != "mcp_selftest"
