import json
from types import SimpleNamespace

from brain_researcher.services.agent.chat_orchestrator import (
    ChatOrchestrator,
    ToolPlan,
)
from brain_researcher.services.agent.memory import ConversationMemory
from brain_researcher.services.agent.resolution_memory import get_pending_decisions
from brain_researcher.services.agent.subagents.contracts import CriticVerdict
from brain_researcher.services.agent.tool_router import RoutingToolView


class StubRouter:
    def __init__(self, selection_json: str, summary_text: str = "done"):
        self.selection_json = selection_json
        self.summary_text = summary_text

    def route_chat(self, prompt):
        # Return selection on first call, summary on second (naive but fine for tests)
        if "Respond ONLY with JSON" in prompt:
            return SimpleNamespace(text=self.selection_json, metadata=None)
        return SimpleNamespace(text=self.summary_text, metadata=None)


class StubToolRouter:
    def __init__(self, runtime_id: str = "foo"):
        self.runtime_id = runtime_id
        self.view = RoutingToolView(
            runtime_id=runtime_id,
            name=runtime_id,
            description="stub",
            tags=[],
        )

    def get_candidates(self, user_msg, history=None, ctx=None):
        return [self.view]


class DummyQUR:
    def __init__(self, ambiguities=None, resolved_datasets=None):
        self.ambiguities = ambiguities or []
        self.resolved_datasets = resolved_datasets or []
        self.kg_nodes = []
        self.existing_derivatives = []


class StubRegistry:
    def __init__(self, runtime_id="foo"):
        self.runtime_id = runtime_id

    def get_runtime_tool(self, tool_id):
        if tool_id == self.runtime_id:
            return object()
        return None

    def get_all_tools(self):
        class _T:
            def __init__(self, name):
                self._name = name

            def get_tool_name(self):
                return self._name

            def get_tool_description(self):
                return "stub tool"

        return [_T(self.runtime_id)]


class StubRecovery:
    def __init__(self, payload):
        self.payload = payload

    async def handle_error_with_recovery(self, error, execution_context, recovery_options=None):
        return self.payload


def test_clarification_from_ambiguities(tmp_path):
    selection = json.dumps({"tool": "foo", "params": {}, "reasoning": "need dataset"})
    orchestrator = ChatOrchestrator(
        router=StubRouter(selection),
        tool_router=StubToolRouter("foo"),
        tool_registry=StubRegistry("foo"),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    reply = orchestrator.handle_chat(
        "run glm",
        history=[],
        ctx={"query_understanding": DummyQUR(["Which dataset id?"]), "thread_id": "t1"},
    )

    assert reply.metadata.get("type") == "clarification"
    assert "dataset" in reply.answer.lower()
    assert reply.tool_calls == []


def test_clarification_from_multiple_ambiguities_is_sequential(tmp_path):
    selection = json.dumps({"tool": "foo", "params": {}, "reasoning": "need dataset"})
    orchestrator = ChatOrchestrator(
        router=StubRouter(selection),
        tool_router=StubToolRouter("foo"),
        tool_registry=StubRegistry("foo"),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )
    ctx = {
        "query_understanding": DummyQUR(["Which dataset id?", "Which contrast?"]),
        "thread_id": "t-sequential",
    }

    reply = orchestrator.handle_chat("run glm", history=[], ctx=ctx)

    assert reply.metadata.get("type") == "clarification"
    assert reply.metadata.get("questions") == ["Which dataset id?"]
    assert reply.answer == "Which dataset id?"
    assert [item["question"] for item in get_pending_decisions(ctx)] == [
        "Which dataset id?",
        "Which contrast?",
    ]


def test_maybe_clarify_queues_one_question_at_a_time(tmp_path):
    orchestrator = ChatOrchestrator(
        router=StubRouter(json.dumps({"tool": "foo", "params": {}, "reasoning": ""})),
        tool_router=StubToolRouter("foo"),
        tool_registry=StubRegistry("foo"),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )
    ctx = {
        "query_understanding": DummyQUR(["Which dataset id?", "Which contrast?"]),
        "thread_id": "t-maybe-clarify",
    }

    reply = orchestrator._maybe_clarify(
        "run glm",
        ToolPlan(tool="no_tool", params={}, reasoning="need info"),
        ctx,
        "",
    )

    assert reply is not None
    assert reply.metadata.get("questions") == ["Which dataset id?"]
    assert [item["question"] for item in get_pending_decisions(ctx)] == [
        "Which dataset id?",
        "Which contrast?",
        "What dataset or subject should I operate on?",
    ]


def test_error_recovery_clarification(tmp_path):
    selection = json.dumps({"tool": "foo", "params": {}, "reasoning": ""})
    recovery_payload = {
        "success": False,
        "clarification_needed": True,
        "question": "Provide subject id",
        "actions_taken": ["request_clarification"],
    }
    orchestrator = ChatOrchestrator(
        router=StubRouter(selection),
        tool_router=StubToolRouter("foo"),
        tool_registry=StubRegistry("foo"),
        tool_executor=None,  # force error path
        error_recovery=StubRecovery(recovery_payload),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    ctx = {
        "thread_id": "t1",
        "query_understanding": DummyQUR(resolved_datasets=[SimpleNamespace(dataset_id="ds1")]),
    }
    reply = orchestrator.handle_chat("run", history=[], ctx=ctx)

    assert reply.metadata.get("type") == "clarification"
    assert "subject" in reply.answer.lower() or "question" in reply.metadata.get("question", "").lower()
    assert reply.tool_calls, "tool_calls should carry recovery result"


def test_plan_gate_block_falls_back_to_no_tool(monkeypatch, tmp_path):
    class StubPlanCriticRouter:
        def review_plan(self, **kwargs):
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason="blocked_for_test",
            )

    monkeypatch.setenv("BR_AGENT_MULTIAGENT_ENABLED", "1")
    monkeypatch.setenv("BR_AGENT_CRITIC_PLAN_GATE", "1")

    selection = json.dumps({"tool": "foo", "params": {}, "reasoning": ""})
    orchestrator = ChatOrchestrator(
        router=StubRouter(selection, summary_text="fallback answer"),
        tool_router=StubToolRouter("foo"),
        tool_registry=StubRegistry("foo"),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )
    orchestrator._multiagent_router = StubPlanCriticRouter()

    reply = orchestrator.handle_chat("run tool", history=[], ctx={"thread_id": "t1"})

    assert reply.answer == "fallback answer"
    assert reply.tool_calls == []
    assert reply.metadata["critic_plan_verdict"]["decision"] == "block"
