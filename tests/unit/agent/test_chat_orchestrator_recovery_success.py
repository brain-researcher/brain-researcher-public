from types import SimpleNamespace

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.memory import ConversationMemory
from brain_researcher.services.agent.tool_router import RoutingToolView


class StubToolRouter:
    def __init__(self, rid: str):
        self.view = RoutingToolView(
            runtime_id=rid,
            name=rid,
            description="stub",
            tags=[],
        )

    def get_candidates(self, user_msg, history=None, ctx=None):
        return [self.view]


class StubLLMRouter:
    def __init__(self, selection_json: str, summary_text: str = "summary"):
        self.selection_json = selection_json
        self.summary_text = summary_text
        self.calls = 0

    def route_chat(self, prompt):
        self.calls += 1
        if "Respond ONLY" in prompt:
            return SimpleNamespace(text=self.selection_json, metadata=None)
        return SimpleNamespace(text=self.summary_text, metadata=None)


class StubRecovery:
    def __init__(self, payload):
        self.payload = payload

    async def handle_error_with_recovery(self, error, execution_context, recovery_options=None):
        return self.payload


def test_recovery_returns_success_and_metadata(tmp_path):
    selection = '{"tool":"stub.tool","params":{},"reasoning":""}'
    recovery_payload = {
        "success": True,
        "result": {"data": "ok"},
        "actions_taken": ["retry"],
    }

    orch = ChatOrchestrator(
        router=StubLLMRouter(selection, summary_text="done"),
        tool_router=StubToolRouter("stub.tool"),
        tool_registry=None,
        tool_executor=None,  # force recovery path
        error_recovery=StubRecovery(recovery_payload),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    class DummyQUR:
        def __init__(self):
            self.resolved_datasets = [type('ds', (), {'dataset_id': 'ds1'})()]
            self.kg_nodes = []
            self.ambiguities = []
            self.existing_derivatives = []

    ctx = {"thread_id": "t1", "query_understanding": DummyQUR()}
    reply = orch.handle_chat("run", history=[], ctx=ctx)

    assert reply.tool_calls
    payload = reply.tool_calls[0]["result"]
    assert payload.get("status") == "recovered"
    assert payload.get("recovery_actions")
