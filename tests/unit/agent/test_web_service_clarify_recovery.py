import os
from contextlib import contextmanager

from brain_researcher.services.agent.chat_orchestrator import ChatReply
from brain_researcher.services.agent import web_service

@contextmanager
def orchestrator_stub(reply: ChatReply):
    original = web_service._CHAT_ORCHESTRATOR
    try:
        web_service._CHAT_ORCHESTRATOR = type(
            "StubOrch",
            (),
            {"handle_chat": staticmethod(lambda *args, **kwargs: reply)},
        )()
        yield
    finally:
        web_service._CHAT_ORCHESTRATOR = original


def test_chat_orchestrator_clarification_flow():
    os.environ["BR_CHAT_ORCHESTRATOR_ENABLED"] = "1"
    reply = ChatReply(
        answer="Need clarification",
        tool_calls=[{"plan": {"tool": "stub"}, "result": {"status": "clarify"}}],
        metadata={"type": "clarification"},
    )
    with orchestrator_stub(reply):
        client = web_service.app.test_client()
        res = client.post("/api/cli", json={"argv": ["chat", "-p", "hello"]})
        assert res.status_code == 200
        data = res.get_json()
        assert data["text"] == "Need clarification"
        assert data["tool_calls"]
        assert data["metadata"]["type"] == "clarification"
