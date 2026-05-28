from __future__ import annotations

import uuid

import pytest

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.agent.api_fee_debit import (
    ApiFeeDebitResult,
    ApiFeeReservationError,
    ApiFeeReservationResult,
)


def _managed_result(
    *,
    text: str = "ok",
    credential: str = "managed_openai",
    bill_to: str = "managed:budget-1",
) -> LLMChatResult:
    return LLMChatResult(
        text=text,
        metadata=LLMRouteMetadata(
            provider="openai",
            model="gpt-4o",
            route="primary",
            transport="sdk",
            usage={"prompt_tokens": 1000, "completion_tokens": 100},
            credential=credential,
            bill_to=bill_to,
            estimated_cost=0.0035,
        ),
    )


class _FakeRouter:
    def __init__(self, result_factory=_managed_result) -> None:
        self._result_factory = result_factory
        self.calls = []

    def route_chat(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result_factory()


class _EmptyRegistry:
    def __init__(self) -> None:
        self._tools = {}

    def get_all_tools(self):
        return list(self._tools.values())

    def get_tool(self, name):
        return self._tools.get(name)

    def register_tool(self, tool):
        self._tools[tool.get_tool_name()] = tool


class _EmptyAgent:
    def __init__(self) -> None:
        self.tool_registry = _EmptyRegistry()


def test_route_chat_with_api_fee_debit_uses_request_identity_and_budget(monkeypatch):
    from brain_researcher.services.agent import web_service

    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")
    fake_router = _FakeRouter()
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
        captured["metadata"] = metadata
        captured["identity"] = identity
        captured["idempotency_key"] = idempotency_key
        captured["usage_tracker"] = usage_tracker
        result = provider_call()
        result.metadata.api_fee_debit = ApiFeeDebitResult(
            status="debited", amount_milli=4
        ).__dict__
        result.metadata.api_fee_reservation = {"status": "reserved"}
        return result

    monkeypatch.setattr(web_service, "_LLM_ROUTER", fake_router)
    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )

    workspace_id = str(uuid.uuid4())
    with web_service.app.test_request_context(
        "/chat",
        method="POST",
        json={"budget_id": "budget-1"},
        headers={"X-Debug-User": "user-1", "X-Workspace-Id": workspace_id},
    ):
        result = web_service._route_chat_with_api_fee_debit(
            "hello",
            payload={"budget_id": "budget-1"},
            call_prefix="chat",
            fallback_run_id="run-1",
            model_hint="gpt-4o",
        )

    assert result.text == "ok"
    assert fake_router.calls[0][1]["budget_id"] == "budget-1"
    assert captured["identity"].workspace_id == workspace_id
    assert captured["identity"].user_id == "user-1"
    assert captured["idempotency_key"] == "llm-api-fee:run-1:chat:1"
    assert captured["metadata"].route == "preflight"
    assert result.metadata.api_fee_debit["status"] == "debited"


def test_api_fee_debit_identity_ignores_unauthenticated_payload_identity(monkeypatch):
    from brain_researcher.services.agent import web_service

    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "0")
    monkeypatch.delenv("BR_TRUST_PROXY_IDENTITY_HEADERS", raising=False)

    with web_service.app.test_request_context(
        "/chat",
        method="POST",
        json={"user_id": "victim", "workspace_id": str(uuid.uuid4())},
    ):
        identity = web_service._extract_api_fee_debit_identity(
            {"user_id": "victim", "workspace_id": str(uuid.uuid4())}
        )

    assert identity is None


def test_api_fee_debiting_router_injects_context_budget_and_debits(monkeypatch):
    from brain_researcher.services.agent import web_service

    fake_router = _FakeRouter()
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
            status="debited", amount_milli=4
        ).__dict__
        return result

    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )

    identity = web_service.ApiFeeDebitIdentity(
        workspace_id=str(uuid.uuid4()),
        user_id="user-2",
    )
    token = web_service._API_FEE_DEBIT_CONTEXT.set(
        {
            "identity": identity,
            "budget_id": "budget-2",
            "call_prefix": "chat_orchestrator",
            "run_id": "thread-1",
            "counter": 0,
        }
    )
    try:
        result = billing_router.route_chat("hello", model_hint="gpt-4o")
    finally:
        web_service._API_FEE_DEBIT_CONTEXT.reset(token)

    assert fake_router.calls[0][1]["budget_id"] == "budget-2"
    assert captured["identity"] == identity
    assert captured["idempotency_key"] == "llm-api-fee:thread-1:chat_orchestrator:1"
    assert result.metadata.api_fee_debit["status"] == "debited"


def test_api_fee_debiting_router_blocks_before_provider_when_reservation_fails(
    monkeypatch,
):
    from brain_researcher.services.agent import web_service

    fake_router = _FakeRouter()
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
        captured["metadata"] = metadata
        captured["identity"] = identity
        captured["idempotency_key"] = idempotency_key
        raise ApiFeeReservationError(
            ApiFeeReservationResult(
                status="failed",
                reason="insufficient_credits",
                workspace_id=identity.workspace_id,
                user_id=identity.user_id,
                idempotency_key=idempotency_key,
            )
        )

    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )

    identity = web_service.ApiFeeDebitIdentity(
        workspace_id=str(uuid.uuid4()),
        user_id="user-credits",
    )
    token = web_service._API_FEE_DEBIT_CONTEXT.set(
        {
            "identity": identity,
            "budget_id": "budget-low",
            "call_prefix": "act",
            "run_id": "run-low",
            "counter": 0,
        }
    )
    try:
        with pytest.raises(ApiFeeReservationError):
            billing_router.route_chat("hello", model_hint="gpt-4o")
    finally:
        web_service._API_FEE_DEBIT_CONTEXT.reset(token)

    assert fake_router.calls == []
    assert captured["identity"] == identity
    assert captured["metadata"].bill_to == "managed:budget-low"
    assert captured["idempotency_key"] == "llm-api-fee:run-low:act:1"


def test_agent_act_endpoint_uses_authenticated_billing_context(monkeypatch):
    from flask import g

    from brain_researcher.services.agent import agent_core, web_service

    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")
    fake_router = _FakeRouter()
    monkeypatch.setattr(
        web_service,
        "_BILLING_LLM_ROUTER",
        web_service._ApiFeeDebitingRouter(fake_router),
    )

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
            status="debited", amount_milli=4
        ).__dict__
        return result

    def fake_agent_act_core(payload, *, trace_id=None, run_id=None, llm_router=None):
        assert run_id == "run-act-1"
        plan_result = llm_router.route_chat("act planning", model_hint="gpt-4o")
        return {
            "message": {"role": "assistant", "content": plan_result.text},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {
                "execution": {
                    "api_fee_debit": plan_result.metadata.api_fee_debit,
                }
            },
            "session_id": payload.get("session_id"),
        }

    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )
    monkeypatch.setattr(agent_core, "agent_act_core", fake_agent_act_core)

    workspace_id = str(uuid.uuid4())
    with web_service.app.test_request_context(
        "/act",
        method="POST",
        json={
            "query": "plan this",
            "session_id": "sess-act",
            "budget_id": "budget-act",
        },
        headers={"X-Debug-User": "user-act", "X-Workspace-Id": workspace_id},
    ):
        g.client_run_id = "run-act-1"
        response = web_service.agent_act.__wrapped__()

    body = response.get_json()
    assert body["runCard"]["execution"]["api_fee_debit"]["status"] == "debited"
    assert fake_router.calls[0][1]["budget_id"] == "budget-act"
    assert captured["identity"].workspace_id == workspace_id
    assert captured["identity"].user_id == "user-act"
    assert captured["idempotency_key"] == "llm-api-fee:run-act-1:act:1"


def test_agent_act_core_uses_injected_billing_router_for_planning(
    monkeypatch, tmp_path
):
    from brain_researcher.config.run_artifacts import reset_recorder_config
    from brain_researcher.services.agent import web_service
    from brain_researcher.services.agent.agent_core import agent_act_core

    monkeypatch.delenv("LLM_ONLY_FALLBACK", raising=False)
    monkeypatch.delenv("DISABLE_TOOL_DISCOVERY", raising=False)
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    reset_recorder_config()

    monkeypatch.setattr(web_service, "get_agent", lambda: _EmptyAgent())
    fake_router = _FakeRouter(
        lambda: _managed_result(
            text='{"tool": "none", "params": {}, "reasoning": "no tool needed"}'
        )
    )
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
            status="debited", amount_milli=4
        ).__dict__
        return result

    monkeypatch.setattr(
        web_service,
        "call_with_platform_api_fee_reservation",
        fake_call,
    )

    identity = web_service.ApiFeeDebitIdentity(
        workspace_id=str(uuid.uuid4()),
        user_id="user-act-core",
    )
    token = web_service._API_FEE_DEBIT_CONTEXT.set(
        {
            "identity": identity,
            "budget_id": "budget-act-core",
            "call_prefix": "act",
            "run_id": "run-act-core",
            "counter": 0,
        }
    )
    try:
        result = agent_act_core(
            {"query": "plan only", "session_id": "sess-act-core", "budget_ms": 2000},
            trace_id="trace-act-core",
            run_id="run-act-core",
            llm_router=billing_router,
        )
    finally:
        web_service._API_FEE_DEBIT_CONTEXT.reset(token)

    assert "error" not in result
    assert fake_router.calls[0][1]["budget_id"] == "budget-act-core"
    assert captured["identity"] == identity
    assert captured["idempotency_key"] == "llm-api-fee:run-act-core:act:1"
    assert result["runCard"]["execution"]["api_fee_debit"]["status"] == "debited"


@pytest.mark.parametrize(
    ("credential", "bill_to"),
    [
        ("byok_openai", "byok:personal"),
        ("local_gemini", "local_oauth"),
    ],
)
def test_act_billing_router_skips_byok_and_local_oauth_debit(
    monkeypatch, credential, bill_to
):
    from brain_researcher.services.agent import api_fee_debit, web_service

    fake_router = _FakeRouter(
        lambda: _managed_result(credential=credential, bill_to=bill_to)
    )
    billing_router = web_service._ApiFeeDebitingRouter(fake_router)

    def fail_get_store():
        raise AssertionError("BYOK/local OAuth routes must not debit credits")

    monkeypatch.setattr(api_fee_debit, "_get_store", fail_get_store)

    identity = web_service.ApiFeeDebitIdentity(
        workspace_id=str(uuid.uuid4()),
        user_id="user-byok",
    )
    token = web_service._API_FEE_DEBIT_CONTEXT.set(
        {
            "identity": identity,
            "call_prefix": "act",
            "run_id": "run-non-platform",
            "counter": 0,
        }
    )
    try:
        result = billing_router.route_chat("act planning", model_hint="gpt-4o")
    finally:
        web_service._API_FEE_DEBIT_CONTEXT.reset(token)

    assert "budget_id" not in fake_router.calls[0][1]
    assert result.metadata.api_fee_debit["status"] == "skipped"
    assert result.metadata.api_fee_debit["reason"] == "not_platform_billable"
