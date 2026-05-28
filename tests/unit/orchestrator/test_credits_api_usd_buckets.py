from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints import credits
from brain_researcher.services.orchestrator.endpoints.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    CreditsStore,
)


def _store(tmp_path) -> CreditsStore:
    return CreditsStore(str(tmp_path / "credits.sqlite"))


def _api_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BR_CREDITS_DB", str(tmp_path / "api-credits.sqlite"))
    monkeypatch.setattr(credits, "_store", None)
    app = FastAPI()
    app.include_router(credits.router)
    return TestClient(app)


def test_api_usd_bucket_is_isolated_from_legacy_workflow_credits(tmp_path) -> None:
    store = _store(tmp_path)

    store.grant(
        "ws",
        "user",
        amount_milli=5_000,
        idempotency_key="workflow-grant",
        metadata={"source": "test"},
    )
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=2_000,
        idempotency_key="api-grant",
        metadata={"source": "test"},
    )

    assert store.get_balance("ws", "user")["balance_milli"] == 5_000
    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 2_000
    )

    store.debit_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=750,
        idempotency_key="api-debit",
        metadata={},
    )

    assert store.get_balance("ws", "user")["balance_milli"] == 5_000
    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 1_250
    )


def test_monthly_api_top_up_is_idempotent_and_tops_up_to_cap(tmp_path) -> None:
    store = _store(tmp_path)

    first = store.top_up_api_monthly_allowance("ws", "user", month="2026-05")
    second = store.top_up_api_monthly_allowance("ws", "user", month="2026-05")

    assert first["amount_milli"] == 10_000
    assert first["balance_milli"] == 10_000
    assert first["idempotent"] is False
    assert second["amount_milli"] == 10_000
    assert second["balance_milli"] == 10_000
    assert second["idempotent"] is True

    store.debit_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=3_000,
        idempotency_key="spend-before-next-month",
        metadata={},
    )
    repeated_same_month = store.top_up_api_monthly_allowance(
        "ws", "user", month="2026-05"
    )
    next_month = store.top_up_api_monthly_allowance("ws", "user", month="2026-06")

    assert repeated_same_month["idempotent"] is True
    assert repeated_same_month["balance_milli"] == 7_000
    assert next_month["amount_milli"] == 3_000
    assert next_month["balance_milli"] == 10_000


def test_monthly_api_top_up_does_not_exceed_cap(tmp_path) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=12_000,
        idempotency_key="seed-over-cap",
        metadata={},
    )

    result = store.top_up_api_monthly_allowance("ws", "user", month="2026-05")

    assert result["entry_id"] is not None
    assert result["amount_milli"] == 0
    assert result["balance_milli"] == 12_000

    store.debit_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=5_000,
        idempotency_key="spend-after-zero-top-up",
        metadata={},
    )
    repeated = store.top_up_api_monthly_allowance("ws", "user", month="2026-05")
    assert repeated["idempotent"] is True
    assert repeated["balance_milli"] == 7_000


def test_api_usd_monthly_allowance_and_debit_are_account_scoped(tmp_path) -> None:
    store = _store(tmp_path)

    user_a_top_up = store.top_up_api_monthly_allowance("ws", "user-a", month="2026-05")
    user_b_top_up = store.top_up_api_monthly_allowance("ws", "user-b", month="2026-05")
    store.debit_bucket(
        "ws",
        "user-a",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=2_500,
        idempotency_key="user-a-api-spend",
        metadata={"source": "smoke"},
    )
    repeated_user_b = store.top_up_api_monthly_allowance(
        "ws", "user-b", month="2026-05"
    )

    assert user_a_top_up["amount_milli"] == 10_000
    assert user_b_top_up["amount_milli"] == 10_000
    assert repeated_user_b["idempotent"] is True
    assert (
        store.get_bucket_balance(
            "ws", "user-a", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 7_500
    )
    assert (
        store.get_bucket_balance(
            "ws", "user-b", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 10_000
    )


def test_api_usd_debit_and_reservation_are_direct_bucket_only_operations(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=10_000,
        idempotency_key="seed-api",
        metadata={},
    )

    debit = store.debit_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=2_500,
        idempotency_key="debit-1",
        metadata={},
    )
    duplicate_debit = store.debit_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=2_500,
        idempotency_key="debit-1",
        metadata={},
    )

    assert debit["balance_milli"] == 7_500
    assert duplicate_debit["balance_milli"] == 7_500
    assert duplicate_debit["idempotent"] is True

    reservation = store.reserve_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_250,
        idempotency_key="reserve-1",
        metadata={},
        ttl_seconds=60,
    )
    duplicate_reservation = store.reserve_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_250,
        idempotency_key="reserve-1",
        metadata={},
        ttl_seconds=60,
    )

    assert reservation["balance_milli"] == 6_250
    assert duplicate_reservation["reservation_id"] == reservation["reservation_id"]
    assert duplicate_reservation["balance_milli"] == 6_250
    assert duplicate_reservation["idempotent"] is True
    assert store.get_balance("ws", "user")["balance_milli"] == 0

    with pytest.raises(ValueError, match="insufficient_credits"):
        store.debit_bucket(
            "ws",
            "user",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=9_000,
            idempotency_key="too-much",
            metadata={},
        )


def test_api_usd_bucket_reservation_commit_is_idempotent(tmp_path) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=3_000,
        idempotency_key="seed-api-commit",
        metadata={},
    )
    reservation = store.reserve_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_200,
        idempotency_key="reserve-for-commit",
        metadata={},
        ttl_seconds=60,
    )

    commit = store.commit_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="commit-1",
        metadata={"source": "test"},
    )
    duplicate_commit = store.commit_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="commit-1",
        metadata={"source": "test"},
    )

    assert commit["status"] == "committed"
    assert commit["bucket"] == API_USD_BUCKET
    assert commit["currency"] == API_USD_CURRENCY
    assert commit["balance_milli"] == 1_800
    assert commit["idempotent"] is False
    assert duplicate_commit["status"] == "committed"
    assert duplicate_commit["balance_milli"] == 1_800
    assert duplicate_commit["idempotent"] is True
    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 1_800
    )
    assert store.get_balance("ws", "user")["balance_milli"] == 0


def test_api_usd_bucket_reservation_commit_can_refund_unused_amount(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=3_000,
        idempotency_key="seed-api-commit-refund",
        metadata={},
    )
    reservation = store.reserve_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_200,
        idempotency_key="reserve-for-commit-refund",
        metadata={},
        ttl_seconds=60,
    )

    commit = store.commit_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="commit-refund",
        metadata={"source": "test"},
        final_amount_milli=400,
    )
    duplicate_commit = store.commit_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="commit-refund",
        metadata={"source": "test"},
        final_amount_milli=400,
    )

    assert commit["status"] == "committed"
    assert commit["entry_id"]
    assert commit["amount_milli"] == 1_200
    assert commit["final_amount_milli"] == 400
    assert commit["credit_delta_milli"] == 800
    assert commit["balance_milli"] == 2_600
    assert duplicate_commit["balance_milli"] == 2_600
    assert duplicate_commit["idempotent"] is True
    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 2_600
    )


def test_api_usd_bucket_reservation_release_returns_balance_idempotently(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=3_000,
        idempotency_key="seed-api-release",
        metadata={},
    )
    reservation = store.reserve_bucket(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_200,
        idempotency_key="reserve-for-release",
        metadata={},
        ttl_seconds=60,
    )

    release = store.release_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="release-1",
        metadata={"source": "test"},
    )
    duplicate_release = store.release_bucket_reservation(
        reservation["reservation_id"],
        idempotency_key="release-1",
        metadata={"source": "test"},
    )

    assert release["status"] == "released"
    assert release["bucket"] == API_USD_BUCKET
    assert release["currency"] == API_USD_CURRENCY
    assert release["balance_milli"] == 3_000
    assert release["idempotent"] is False
    assert duplicate_release["status"] == "released"
    assert duplicate_release["balance_milli"] == 3_000
    assert duplicate_release["idempotent"] is True
    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 3_000
    )
    assert store.get_balance("ws", "user")["balance_milli"] == 0


def test_api_usd_bucket_reservation_insufficient_balance_is_unchanged(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.bucket_grant(
        "ws",
        "user",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=1_000,
        idempotency_key="seed-api-insufficient-reserve",
        metadata={},
    )

    with pytest.raises(ValueError, match="insufficient_credits"):
        store.reserve_bucket(
            "ws",
            "user",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=1_001,
            idempotency_key="reserve-too-much",
            metadata={},
            ttl_seconds=60,
        )

    assert (
        store.get_bucket_balance(
            "ws", "user", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 1_000
    )
    assert store.get_balance("ws", "user")["balance_milli"] == 0


def test_api_usd_mutation_routes_are_disabled_by_default(tmp_path, monkeypatch) -> None:
    client = _api_client(tmp_path, monkeypatch)

    top_up = client.post(
        "/api/credits/api-usd/monthly-top-up",
        json={"workspace_id": "ws", "user_id": "user"},
    )
    debit = client.post(
        "/api/credits/api-usd/debits",
        json={
            "workspace_id": "ws",
            "user_id": "user",
            "amount": 1,
            "idempotency_key": "debit-1",
        },
    )
    reservation = client.post(
        "/api/credits/api-usd/reservations",
        json={
            "workspace_id": "ws",
            "user_id": "user",
            "amount": 1,
            "idempotency_key": "reserve-1",
        },
    )

    assert top_up.status_code == 404
    assert debit.status_code == 404
    assert reservation.status_code == 404


def test_api_usd_monthly_top_up_route_requires_explicit_enable(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BR_ENABLE_API_USD_MUTATION_API", "1")
    client = _api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/credits/api-usd/monthly-top-up",
        json={"workspace_id": "ws", "user_id": "user"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bucket"] == API_USD_BUCKET
    assert payload["currency"] == API_USD_CURRENCY
    assert payload["amount_milli"] == 10_000
    assert payload["balance_milli"] == 10_000
