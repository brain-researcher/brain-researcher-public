from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.agent.api_fee_debit import ApiFeeReservationError
from brain_researcher.services.mcp import api_fee


def test_mcp_api_fee_context_derives_default_workspace_and_budget() -> None:
    token = api_fee.set_mcp_api_fee_context(
        user_id="user-1",
        request_id="request-1",
    )
    try:
        identity = api_fee.current_mcp_api_fee_identity()
        assert identity is not None
        assert identity.workspace_id == "default"
        assert identity.user_id == "user-1"
        assert api_fee.current_mcp_api_fee_budget_id() == "mcp-api-usd:default:user-1"
    finally:
        api_fee.reset_mcp_api_fee_context(token)


def test_route_chat_with_mcp_api_fee_reserves_before_managed_call(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeRouter:
        def __init__(self, *_, **__):
            pass

        def route_chat(self, prompt: str, **kwargs):
            calls["prompt"] = prompt
            calls["kwargs"] = kwargs
            return LLMChatResult(
                text='{"ok": true}',
                metadata=LLMRouteMetadata(
                    provider="google",
                    model="gemini-2.5-flash",
                    credential="managed_gemini",
                    bill_to=f"managed:{kwargs['budget_id']}",
                    estimated_cost=0.002,
                    allocation_id="allocation-1",
                ),
            )

    def fake_reserve(metadata, provider_call, **kwargs):
        calls["preflight"] = metadata
        calls["identity"] = kwargs["identity"]
        calls["idempotency_key"] = kwargs["idempotency_key"]
        result = provider_call()
        result.metadata.api_fee_reservation = {"status": "reserved"}
        result.metadata.api_fee_debit = {"status": "debited"}
        return result

    monkeypatch.setattr(api_fee, "LLMRouter", FakeRouter)
    monkeypatch.setattr(api_fee, "get_shared_managed_pool", lambda: object())
    monkeypatch.setattr(api_fee, "call_with_platform_api_fee_reservation", fake_reserve)
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-2.5-flash")

    token = api_fee.set_mcp_api_fee_context(
        workspace_id="tenant-1",
        user_id="user-1",
        request_id="request-1",
    )
    try:
        result = api_fee.route_chat_with_mcp_api_fee(
            "hello",
            call_prefix="summary:test",
            task_type="summary",
        )
    finally:
        api_fee.reset_mcp_api_fee_context(token)

    assert result.text == '{"ok": true}'
    assert calls["kwargs"] == {
        "task_type": "summary",
        "budget_id": "mcp-api-usd:tenant-1:user-1",
    }
    identity = calls["identity"]
    assert identity.workspace_id == "tenant-1"
    assert identity.user_id == "user-1"
    preflight = calls["preflight"]
    assert preflight.bill_to == "managed:mcp-api-usd:tenant-1:user-1"
    assert str(calls["idempotency_key"]).startswith(
        "llm-api-fee:mcp:request-1:summary:test:"
    )


def test_route_chat_with_mcp_api_fee_fails_closed_without_identity_when_required(
    monkeypatch,
) -> None:
    class FakeRouter:
        def __init__(self, *_, **__):
            pass

        def route_chat(self, *_, **__):  # pragma: no cover - must not be called
            raise AssertionError("provider call should be blocked before routing")

    monkeypatch.setattr(api_fee, "LLMRouter", FakeRouter)
    monkeypatch.setattr(api_fee, "get_shared_managed_pool", lambda: object())
    monkeypatch.setenv("BR_MCP_PLATFORM_API_FEE_REQUIRED", "1")

    with pytest.raises(ApiFeeReservationError) as exc_info:
        api_fee.route_chat_with_mcp_api_fee("hello")

    assert exc_info.value.result.status == "failed"
    assert exc_info.value.result.reason == "missing_identity"


def test_direct_mcp_platform_call_requires_api_usd_when_enabled(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_reserve(metadata, provider_call, **kwargs):
        observed["metadata"] = metadata
        observed["identity"] = kwargs["identity"]
        observed["idempotency_key"] = kwargs["idempotency_key"]
        return provider_call()

    monkeypatch.setattr(api_fee, "call_with_platform_api_fee_reservation", fake_reserve)
    monkeypatch.setenv("BR_MCP_PLATFORM_API_FEE_REQUIRED", "1")

    token = api_fee.set_mcp_api_fee_context(
        workspace_id="tenant-1",
        user_id="user-1",
        request_id="request-2",
    )
    try:
        result = api_fee.call_mcp_platform_api_with_fee(
            lambda: SimpleNamespace(ok=True),
            provider="google",
            model="gemini-3-flash-preview",
            call_prefix="google_deep_research",
            estimated_cost_usd=0.05,
        )
    finally:
        api_fee.reset_mcp_api_fee_context(token)

    assert result.ok is True
    metadata = observed["metadata"]
    assert metadata.bill_to == "managed:mcp-api-usd:tenant-1:user-1"
    identity = observed["identity"]
    assert identity.workspace_id == "tenant-1"
    assert identity.user_id == "user-1"
    assert str(observed["idempotency_key"]).startswith(
        "llm-api-fee:mcp:request-2:google_deep_research:"
    )


def test_api_fee_error_payload_uses_reservation_error_result() -> None:
    err = api_fee._missing_identity_error()

    payload = api_fee.api_fee_error_payload(err)

    assert payload["ok"] is False
    assert payload["error"] == "api_fee_credit_required"
    assert payload["api_fee_reservation"]["reason"] == "missing_identity"
