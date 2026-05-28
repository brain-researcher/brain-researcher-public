from __future__ import annotations

import uuid

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.agent.api_fee_debit import ApiFeeDebitResult


class _FakeRouter:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []

    def route_chat(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return LLMChatResult(
            text=self.text,
            metadata=LLMRouteMetadata(
                provider="openai",
                model="gpt-4o",
                route="primary",
                transport="sdk",
                usage={"prompt_tokens": 12, "completion_tokens": 7},
                credential="managed_openai",
                bill_to="managed:budget-tool-off",
                estimated_cost=0.001,
                latency_ms=123,
            ),
        )


def test_agent_act_tool_mode_off_uses_plain_llm_and_preserves_api_fee_debit(
    monkeypatch, tmp_path
):
    from brain_researcher.config.run_artifacts import reset_recorder_config
    from brain_researcher.services.agent import web_service
    from brain_researcher.services.agent.agent_core import agent_act_core

    monkeypatch.delenv("LLM_ONLY_FALLBACK", raising=False)
    monkeypatch.delenv("DISABLE_TOOL_DISCOVERY", raising=False)
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-4o")
    reset_recorder_config()

    def fail_get_agent():
        raise AssertionError("tool_mode=off must not discover agent tools")

    monkeypatch.setattr(web_service, "get_agent", fail_get_agent)

    fake_router = _FakeRouter("Plain chat response, not JSON.")
    billing_router = web_service._ApiFeeDebitingRouter(fake_router)
    captured = {}

    def fake_call(
        metadata,
        provider_call,
        *,
        identity,
        idempotency_key,
        usage_tracker,
        credits_store=None,
        reservation_ttl_seconds=None,
    ):
        captured["identity"] = identity
        captured["idempotency_key"] = idempotency_key
        result = provider_call()
        result.metadata.api_fee_debit = ApiFeeDebitResult(
            status="debited", amount_milli=5
        ).__dict__
        return result

    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )

    identity = web_service.ApiFeeDebitIdentity(
        workspace_id=str(uuid.uuid4()),
        user_id="user-tool-off",
    )
    token = web_service._API_FEE_DEBIT_CONTEXT.set(
        {
            "identity": identity,
            "budget_id": "budget-tool-off",
            "call_prefix": "act",
            "run_id": "run-tool-off",
            "counter": 0,
        }
    )
    try:
        result = agent_act_core(
            {
                "query": "hello plain chat",
                "session_id": "sess-tool-off",
                "tool_mode": "off",
                "budget_ms": 2000,
            },
            trace_id="trace-tool-off",
            run_id="run-tool-off",
            llm_router=billing_router,
        )
    finally:
        web_service._API_FEE_DEBIT_CONTEXT.reset(token)
        reset_recorder_config()

    assert "error" not in result
    assert result["message"]["content"] == "Plain chat response, not JSON."
    assert result["tool_calls"] == []
    assert result["artifacts"] == []
    assert fake_router.calls == [
        (
            ("hello plain chat",),
            {"model_hint": "gpt-4o", "budget_id": "budget-tool-off"},
        )
    ]
    assert captured["identity"] == identity
    assert captured["idempotency_key"] == "llm-api-fee:run-tool-off:act:1"

    execution = result["runCard"]["execution"]
    assert execution["tool_mode"] == "off"
    assert execution["provider"] == "openai"
    assert execution["model"] == "gpt-4o"
    assert execution["route"] == "primary"
    assert execution["transport"] == "sdk"
    assert execution["credential"] == "managed_openai"
    assert execution["bill_to"] == "managed:budget-tool-off"
    assert execution["usage"] == {"prompt_tokens": 12, "completion_tokens": 7}
    assert execution["api_fee_debit"]["status"] == "debited"
