from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from brain_researcher.services.agent import web_service


class _FakeActAgent:
    def __init__(self, *, model: str, provider_family: str, reply: str = "ok") -> None:
        self.llm = SimpleNamespace(model=model)
        self._provider_family_name = provider_family
        self._reply = reply
        self.last_context = None

    def _llm_provider_family(self) -> str:
        return self._provider_family_name

    def run(self, query, complexity=None, context=None):
        self.last_context = context
        return {"messages": [AIMessage(content=self._reply, tool_calls=[])]}

    def get_last_ai_message(self, state):
        return self._reply


def test_act_llm_run_card_uses_runtime_coding_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-2.5-flash")
    fake_agent = _FakeActAgent(
        model="models/gemini-2.5-pro",
        provider_family="gemini",
        reply="runtime coding model",
    )
    monkeypatch.setattr(
        web_service,
        "_get_cached_act_llm_agent",
        lambda *, tool_mode, coding_bias: fake_agent,
    )

    client = web_service.app.test_client()
    response = client.post(
        "/act_llm",
        json={"query": "write code", "codingMode": True, "tool_mode": "auto"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    execution = payload["runCard"]["execution"]
    assert execution["model"] == "gemini-2.5-pro"
    assert execution["provider"] == "gemini"
    assert execution["coding_mode"] is True


def test_act_llm_run_card_prefers_runtime_deepseek_metadata(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-2.5-flash")
    fake_agent = _FakeActAgent(
        model="deepseek-chat",
        provider_family="openai",
        reply="runtime deepseek model",
    )
    monkeypatch.setattr(
        web_service,
        "_get_cached_act_llm_agent",
        lambda *, tool_mode, coding_bias: fake_agent,
    )

    client = web_service.app.test_client()
    response = client.post("/act_llm", json={"query": "hello", "tool_mode": "auto"})

    assert response.status_code == 200
    payload = response.get_json()
    execution = payload["runCard"]["execution"]
    assert execution["model"] == "deepseek-chat"
    assert execution["provider"] == "deepseek"


def test_act_llm_normalizes_resume_checkpoint_context(monkeypatch):
    fake_agent = _FakeActAgent(
        model="models/gemini-2.5-pro",
        provider_family="gemini",
        reply="checkpointed",
    )
    monkeypatch.setattr(
        web_service,
        "_get_cached_act_llm_agent",
        lambda *, tool_mode, coding_bias: fake_agent,
    )

    client = web_service.app.test_client()
    response = client.post(
        "/act_llm",
        json={
            "query": "resume this analysis",
            "tool_mode": "auto",
            "session_id": "thread-123",
            "checkpoint_id": "ckpt-123",
        },
    )

    assert response.status_code == 200
    assert fake_agent.last_context == {
        "thread_id": "thread-123",
        "resume_checkpoint_id": "ckpt-123",
    }
