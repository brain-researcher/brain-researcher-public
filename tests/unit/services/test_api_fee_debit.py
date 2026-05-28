"""Tests for bounded platform API-fee debit helper."""

from pathlib import Path

import pytest

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.agent.api_fee_debit import (
    ApiFeeDebitIdentity,
    ApiFeeReservationError,
    call_with_platform_api_fee_reservation,
    record_usage_and_debit_platform_api_fee,
    reserve_platform_api_fee,
)
from brain_researcher.services.agent.usage_aggregator import UsageTracker
from brain_researcher.services.orchestrator.endpoints.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    CreditsStore,
)


@pytest.fixture
def credits_store(tmp_path: Path) -> CreditsStore:
    return CreditsStore(str(tmp_path / "credits.sqlite"))


def _managed_metadata(**overrides) -> LLMRouteMetadata:
    payload = {
        "provider": "openai",
        "model": "gpt-4o",
        "route": "primary",
        "transport": "sdk",
        "usage": {
            "prompt_tokens": 5000,
            "completion_tokens": 1000,
            "total_tokens": 6000,
        },
        "credential": "managed_openai",
        "bill_to": "managed:budget-123",
        "estimated_cost": 0.0225,
        "budget_id": "budget-123",
        "allocation_id": "alloc-123",
    }
    payload.update(overrides)
    return LLMRouteMetadata(**payload)


def test_managed_usage_debits_wallet_and_records_identity(credits_store, tmp_path):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    usage_tracker = UsageTracker(telemetry_dir=str(tmp_path / "telemetry"))
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-1",
        metadata={"reason": "test"},
    )

    result = record_usage_and_debit_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        usage_tracker=usage_tracker,
        credits_store=credits_store,
    )

    assert result.debited is True
    assert result.amount_milli == 23
    assert result.balance_milli == 977

    usage_summary = usage_tracker.get_usage_summary(workspace_id="ws-1")
    assert usage_summary["total_calls"] == 1
    assert usage_summary["records"][0]["workspace_id"] == "ws-1"
    assert usage_summary["records"][0]["user_id"] == "user-1"

    api_balance = credits_store.get_bucket_balance(
        "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
    )
    assert api_balance["balance_milli"] == 977
    assert credits_store.get_balance("ws-1", "user-1")["balance_milli"] == 0


def test_debit_is_idempotent_for_same_allocation(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-1",
        metadata={},
    )
    metadata = _managed_metadata()

    first = record_usage_and_debit_platform_api_fee(
        metadata,
        identity=identity,
        credits_store=credits_store,
    )
    second = record_usage_and_debit_platform_api_fee(
        metadata,
        identity=identity,
        credits_store=credits_store,
    )

    assert first.debited is True
    assert second.debited is True
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 977
    )


def test_byok_usage_is_recorded_but_not_debited(credits_store, tmp_path):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    usage_tracker = UsageTracker(telemetry_dir=str(tmp_path / "telemetry"))
    metadata = _managed_metadata(
        credential="byok_openai",
        bill_to="byok:personal",
        allocation_id="alloc-byok",
    )

    result = record_usage_and_debit_platform_api_fee(
        metadata,
        identity=identity,
        usage_tracker=usage_tracker,
        credits_store=credits_store,
    )

    assert result.status == "skipped"
    assert result.reason == "not_platform_billable"
    assert usage_tracker.get_usage_summary(workspace_id="ws-1")["total_calls"] == 1
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


def test_missing_identity_skips_debit_but_can_record_usage(tmp_path):
    usage_tracker = UsageTracker(telemetry_dir=str(tmp_path / "telemetry"))

    result = record_usage_and_debit_platform_api_fee(
        _managed_metadata(),
        identity=None,
        usage_tracker=usage_tracker,
    )

    assert result.status == "skipped"
    assert result.reason == "missing_identity"
    assert usage_tracker.get_usage_summary()["total_calls"] == 1


def test_missing_idempotency_key_skips_debit(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-1",
        metadata={},
    )

    result = record_usage_and_debit_platform_api_fee(
        _managed_metadata(allocation_id=None),
        identity=identity,
        credits_store=credits_store,
    )

    assert result.status == "skipped"
    assert result.reason == "missing_idempotency_key"
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 1000
    )


def test_insufficient_wallet_balance_reports_failed_debit(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")

    result = record_usage_and_debit_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        credits_store=credits_store,
    )

    assert result.status == "failed"
    assert result.reason == "insufficient_credits"
    assert result.amount_milli == 23
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


def test_pre_call_reservation_blocks_provider_call_when_balance_insufficient(
    credits_store,
):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    calls = {"count": 0}

    def provider_call():
        calls["count"] += 1
        return LLMChatResult(text="ok", metadata=_managed_metadata())

    with pytest.raises(ApiFeeReservationError) as exc_info:
        call_with_platform_api_fee_reservation(
            _managed_metadata(),
            provider_call,
            identity=identity,
            idempotency_key="reserve-insufficient",
            credits_store=credits_store,
        )

    assert exc_info.value.result.reason == "insufficient_credits"
    assert calls["count"] == 0
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


def test_pre_call_reservation_releases_on_provider_failure(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-1",
        metadata={},
    )

    def provider_call():
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        call_with_platform_api_fee_reservation(
            _managed_metadata(),
            provider_call,
            identity=identity,
            idempotency_key="reserve-failure",
            credits_store=credits_store,
        )

    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 1000
    )


def test_pre_call_reservation_commits_actual_cost_and_refunds_surplus(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-actual-settlement",
        metadata={},
    )

    preflight_metadata = _managed_metadata(
        estimated_cost=0.10,
        allocation_id=None,
        usage={"prompt_tokens": 1000, "completion_tokens": 4096},
    )

    def provider_call():
        return LLMChatResult(text="ok", metadata=_managed_metadata())

    result = call_with_platform_api_fee_reservation(
        preflight_metadata,
        provider_call,
        identity=identity,
        idempotency_key="reserve-actual-settlement",
        credits_store=credits_store,
    )

    assert result.metadata.api_fee_debit["status"] == "debited"
    assert result.metadata.api_fee_debit["amount_milli"] == 23
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 977
    )


def test_reservation_commit_derives_cost_from_input_output_usage(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-derived-cost",
        metadata={},
    )

    preflight_metadata = _managed_metadata(
        provider="google",
        model="gemini-2.5-flash",
        credential="managed_gemini",
        bill_to="managed:budget-123",
        estimated_cost=0.01,
        allocation_id=None,
        usage={"prompt_tokens": 1000, "completion_tokens": 4096},
    )
    actual_metadata = _managed_metadata(
        provider="google",
        model="gemini-2.5-flash",
        credential="managed_gemini",
        bill_to="managed:budget-123",
        estimated_cost=0.0,
        usage={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
    )

    result = call_with_platform_api_fee_reservation(
        preflight_metadata,
        lambda: LLMChatResult(text="ok", metadata=actual_metadata),
        identity=identity,
        idempotency_key="reserve-derived-cost",
        credits_store=credits_store,
    )

    assert result.metadata.api_fee_debit["status"] == "debited"
    assert result.metadata.api_fee_debit["amount_milli"] == 1
    assert result.metadata.api_fee_debit["cost_usd"] != "0"
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 999
    )


@pytest.mark.parametrize(
    "metadata",
    [
        _managed_metadata(
            credential="byok_openai",
            bill_to="byok:personal",
            allocation_id="alloc-byok",
        ),
        _managed_metadata(
            provider="google",
            credential="local_gemini",
            bill_to="local_oauth",
            allocation_id="alloc-local",
        ),
    ],
)
def test_pre_call_reservation_skips_byok_and_local_oauth_routes(
    credits_store,
    metadata,
):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    calls = {"count": 0}

    def provider_call():
        calls["count"] += 1
        return LLMChatResult(text="ok", metadata=metadata)

    result = call_with_platform_api_fee_reservation(
        metadata,
        provider_call,
        identity=identity,
        idempotency_key="reserve-exempt",
        credits_store=credits_store,
    )

    assert result.text == "ok"
    assert calls["count"] == 1
    assert result.metadata.api_fee_reservation["status"] == "skipped"
    assert result.metadata.api_fee_debit["status"] == "skipped"
    assert result.metadata.api_fee_debit["reason"] == "not_platform_billable"
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


def test_pre_call_reservation_is_idempotent_for_same_key(credits_store):
    identity = ApiFeeDebitIdentity(workspace_id="ws-1", user_id="user-1")
    credits_store.bucket_grant(
        identity.workspace_id,
        identity.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1000,
        idempotency_key="grant-1",
        metadata={},
    )

    first = reserve_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        idempotency_key="reserve-idempotent",
        credits_store=credits_store,
    )
    second = reserve_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        idempotency_key="reserve-idempotent",
        credits_store=credits_store,
    )

    assert first.status == "reserved"
    assert second.status == "reserved"
    assert second.idempotent is True
    assert second.reservation_id == first.reservation_id
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 977
    )

    first_commit = record_usage_and_debit_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        idempotency_key="reserve-idempotent",
        credits_store=credits_store,
        reservation=first,
    )
    second_commit = record_usage_and_debit_platform_api_fee(
        _managed_metadata(),
        identity=identity,
        idempotency_key="reserve-idempotent",
        credits_store=credits_store,
        reservation=first,
    )

    assert first_commit.status == "debited"
    assert second_commit.status == "debited"
    assert (
        credits_store.get_bucket_balance(
            "ws-1", "user-1", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 977
    )
