from __future__ import annotations

from brain_researcher.services.orchestrator.endpoints import credits
from brain_researcher.services.orchestrator.endpoints.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    CreditsStore,
)


def test_workflow_credits_are_scoped_by_workspace_and_user(tmp_path) -> None:
    store = CreditsStore(str(tmp_path / "credits.sqlite"))

    user_a_grant = store.grant(
        "ws",
        "user-a",
        amount_milli=3_000,
        idempotency_key="monthly-seed",
        metadata={"source": "test"},
    )
    user_b_grant = store.grant(
        "ws",
        "user-b",
        amount_milli=1_000,
        idempotency_key="monthly-seed",
        metadata={"source": "test"},
    )
    other_workspace_grant = store.grant(
        "other-ws",
        "user-a",
        amount_milli=5_000,
        idempotency_key="monthly-seed",
        metadata={"source": "test"},
    )

    assert user_a_grant["idempotent"] is False
    assert user_b_grant["idempotent"] is False
    assert other_workspace_grant["idempotent"] is False

    duplicate_user_a_grant = store.grant(
        "ws",
        "user-a",
        amount_milli=3_000,
        idempotency_key="monthly-seed",
        metadata={"source": "test"},
    )
    assert duplicate_user_a_grant["idempotent"] is True
    assert duplicate_user_a_grant["balance_milli"] == 3_000

    reservation = store.reserve(
        "ws",
        "user-a",
        amount_milli=1_200,
        idempotency_key="workflow-run-1",
        metadata={"source": "test"},
        ttl_seconds=60,
    )
    duplicate_reservation = store.reserve(
        "ws",
        "user-a",
        amount_milli=1_200,
        idempotency_key="workflow-run-1",
        metadata={"source": "test"},
        ttl_seconds=60,
    )
    assert reservation["balance_milli"] == 1_800
    assert duplicate_reservation["reservation_id"] == reservation["reservation_id"]
    assert duplicate_reservation["balance_milli"] == 1_800

    release = store.release(
        reservation["reservation_id"],
        idempotency_key="workflow-run-1-release",
        metadata={"reason": "test"},
    )
    duplicate_release = store.release(
        reservation["reservation_id"],
        idempotency_key="workflow-run-1-release",
        metadata={"reason": "test"},
    )
    assert release["balance_milli"] == 3_000
    assert duplicate_release["idempotent"] is True
    assert duplicate_release["balance_milli"] == 3_000

    assert store.get_balance("ws", "user-a")["balance_milli"] == 3_000
    assert store.get_balance("ws", "user-b")["balance_milli"] == 1_000
    assert store.get_balance("other-ws", "user-a")["balance_milli"] == 5_000

    user_a_ledger = store.list_ledger("ws", "user-a", cursor=None, limit=20)["items"]
    user_b_ledger = store.list_ledger("ws", "user-b", cursor=None, limit=20)["items"]
    other_workspace_ledger = store.list_ledger(
        "other-ws", "user-a", cursor=None, limit=20
    )["items"]

    assert {entry["user_id"] for entry in user_a_ledger} == {"user-a"}
    assert {entry["workspace_id"] for entry in user_a_ledger} == {"ws"}
    assert {entry["event_type"] for entry in user_a_ledger} == {
        "grant",
        "reserve",
        "release",
    }
    assert [entry["event_type"] for entry in user_b_ledger] == ["grant"]
    assert [entry["event_type"] for entry in other_workspace_ledger] == ["grant"]


def test_workflow_monthly_top_up_is_idempotent_and_account_scoped(tmp_path) -> None:
    store = CreditsStore(str(tmp_path / "credits.sqlite"))

    first_a = store.top_up_workflow_monthly_allowance(
        "ws", "user-a", month="2026-05"
    )
    first_b = store.top_up_workflow_monthly_allowance(
        "ws", "user-b", month="2026-05"
    )
    repeated_a = store.top_up_workflow_monthly_allowance(
        "ws", "user-a", month="2026-05"
    )

    assert first_a["amount_milli"] == 10_000
    assert first_b["amount_milli"] == 10_000
    assert repeated_a["idempotent"] is True
    assert repeated_a["balance_milli"] == 10_000

    store.reserve(
        "ws",
        "user-a",
        amount_milli=1_000,
        idempotency_key="user-a-run",
        metadata={"source": "test"},
        ttl_seconds=60,
    )
    repeated_after_spend = store.top_up_workflow_monthly_allowance(
        "ws", "user-a", month="2026-05"
    )
    next_month = store.top_up_workflow_monthly_allowance(
        "ws", "user-a", month="2026-06"
    )

    assert repeated_after_spend["idempotent"] is True
    assert repeated_after_spend["balance_milli"] == 9_000
    assert next_month["amount_milli"] == 1_000
    assert next_month["balance_milli"] == 10_000
    assert store.get_balance("ws", "user-b")["balance_milli"] == 10_000


def test_workflow_monthly_top_up_respects_existing_grant_idempotency_key(
    tmp_path,
) -> None:
    store = CreditsStore(str(tmp_path / "credits.sqlite"))
    store.grant(
        "ws",
        "user-a",
        amount_milli=10_000,
        idempotency_key="workflow-runtime-monthly:2026-05",
        metadata={"source": "legacy-backfill"},
    )
    store.reserve(
        "ws",
        "user-a",
        amount_milli=1_000,
        idempotency_key="user-a-run-after-backfill",
        metadata={"source": "test"},
        ttl_seconds=60,
    )

    repeated = store.top_up_workflow_monthly_allowance(
        "ws", "user-a", month="2026-05"
    )

    assert repeated["idempotent"] is True
    assert repeated["balance_milli"] == 9_000


def test_initial_workflow_credit_grant_is_idempotent_and_can_be_disabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BR_CREDITS_DB", str(tmp_path / "credits.sqlite"))
    monkeypatch.setattr(credits, "_store", None)

    first = credits.grant_initial_workflow_credits_for_account(
        "default",
        "user-a",
        source="test",
    )
    second = credits.grant_initial_workflow_credits_for_account(
        "default",
        "user-a",
        source="test",
    )

    assert first["idempotent"] is False
    assert first["balance_milli"] == 10_000
    assert second["idempotent"] is True
    assert second["balance_milli"] == 10_000

    monkeypatch.setenv("BR_INITIAL_WORKFLOW_CREDITS", "0")
    disabled = credits.grant_initial_workflow_credits_for_account(
        "default",
        "user-disabled",
        source="test",
    )
    assert disabled["skipped"] is True
    assert credits._get_store().get_balance("default", "user-disabled")[
        "balance_milli"
    ] == 0


def test_initial_api_usd_credit_grant_is_idempotent_and_can_be_disabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BR_CREDITS_DB", str(tmp_path / "credits.sqlite"))
    monkeypatch.setattr(credits, "_store", None)

    first = credits.grant_initial_api_usd_credits_for_account(
        "default",
        "user-a",
        source="test",
    )
    second = credits.grant_initial_api_usd_credits_for_account(
        "default",
        "user-a",
        source="test",
    )

    assert first["idempotent"] is False
    assert first["amount_milli"] == 10_000
    assert first["balance_milli"] == 10_000
    assert second["idempotent"] is True
    assert second["balance_milli"] == 10_000
    assert (
        credits._get_store().get_bucket_balance(
            "default",
            "user-a",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
        )["balance_milli"]
        == 10_000
    )

    monkeypatch.setenv("BR_INITIAL_API_USD_CREDITS", "0")
    disabled = credits.grant_initial_api_usd_credits_for_account(
        "default",
        "user-disabled",
        source="test",
    )
    assert disabled["skipped"] is True
    assert (
        credits._get_store().get_bucket_balance(
            "default",
            "user-disabled",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
        )["balance_milli"]
        == 0
    )


def test_initial_account_credit_grant_funds_workflow_and_api_usd_buckets(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BR_CREDITS_DB", str(tmp_path / "credits.sqlite"))
    monkeypatch.setattr(credits, "_store", None)

    first = credits.grant_initial_account_credits_for_account(
        "default",
        "user-a",
        source="test",
    )
    second = credits.grant_initial_account_credits_for_account(
        "default",
        "user-a",
        source="test",
    )

    assert first["workflow_runtime"]["idempotent"] is False
    assert first["api_fee_usd"]["idempotent"] is False
    assert second["workflow_runtime"]["idempotent"] is True
    assert second["api_fee_usd"]["idempotent"] is True
    assert credits._get_store().get_balance("default", "user-a")[
        "balance_milli"
    ] == 10_000
    assert (
        credits._get_store().get_bucket_balance(
            "default",
            "user-a",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
        )["balance_milli"]
        == 10_000
    )
