from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from brain_researcher.services.orchestrator.endpoints.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    CreditsStore,
)
from scripts.billing import monthly_api_credit_allowance as allowance_script


@pytest.mark.asyncio
async def test_monthly_api_credit_allowance_dry_run_does_not_write(
    tmp_path, monkeypatch
):
    store = CreditsStore(str(tmp_path / "credits.sqlite"))

    async def fake_list_all():
        return [
            SimpleNamespace(
                id="user_active", email="active@example.org", is_active=True
            ),
            SimpleNamespace(
                id="user_inactive", email="inactive@example.org", is_active=False
            ),
        ]

    monkeypatch.setattr(allowance_script, "_get_store", lambda: store)
    monkeypatch.setattr(
        allowance_script.UserStore, "list_all", staticmethod(fake_list_all)
    )

    summary = await allowance_script.run_allowance(
        month="2026-05",
        workspace_id="default",
        allowance=10.0,
        cap=10.0,
        apply=False,
    )

    assert summary["dry_run"] is True
    assert summary["total_users"] == 1
    assert summary["total_amount"] == 10.0
    assert (
        store.get_bucket_balance(
            "default", "user_active", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


@pytest.mark.asyncio
async def test_monthly_api_credit_allowance_dry_run_reports_separate_accounts(
    tmp_path, monkeypatch
):
    store = CreditsStore(str(tmp_path / "credits.sqlite"))
    store.bucket_grant(
        "default",
        "user_with_spend",
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=6_000,
        idempotency_key="seed-user-with-spend",
        metadata={"source": "test"},
    )

    async def fake_list_all():
        return [
            SimpleNamespace(
                id="user_with_spend",
                email="with-spend@example.org",
                is_active=True,
            ),
            SimpleNamespace(id="user_empty", email="empty@example.org", is_active=True),
        ]

    monkeypatch.setattr(allowance_script, "_get_store", lambda: store)
    monkeypatch.setattr(
        allowance_script.UserStore, "list_all", staticmethod(fake_list_all)
    )

    summary = await allowance_script.run_allowance(
        month="2026-05",
        workspace_id="default",
        allowance=10.0,
        cap=10.0,
        apply=False,
    )

    by_user = {row["user_id"]: row for row in summary["results"]}
    assert summary["dry_run"] is True
    assert summary["total_users"] == 2
    assert summary["total_amount"] == 14.0
    assert by_user["user_with_spend"]["amount_milli"] == 4_000
    assert by_user["user_with_spend"]["balance_milli"] == 6_000
    assert by_user["user_empty"]["amount_milli"] == 10_000
    assert by_user["user_empty"]["balance_milli"] == 0
    assert (
        store.get_bucket_balance(
            "default",
            "user_with_spend",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
        )["balance_milli"]
        == 6_000
    )
    assert (
        store.get_bucket_balance(
            "default",
            "user_empty",
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
        )["balance_milli"]
        == 0
    )


def test_monthly_api_credit_allowance_cli_defaults_to_dry_run_json(
    tmp_path, monkeypatch, capsys
):
    store = CreditsStore(str(tmp_path / "credits.sqlite"))

    async def fake_list_all():
        return [
            SimpleNamespace(id="user_cli", email="cli@example.org", is_active=True),
        ]

    monkeypatch.setattr(allowance_script, "_get_store", lambda: store)
    monkeypatch.setattr(
        allowance_script.UserStore, "list_all", staticmethod(fake_list_all)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "monthly_api_credit_allowance.py",
            "--month",
            "2026-05",
            "--workspace-id",
            "default",
        ],
    )

    assert allowance_script.main() == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["results"] == [
        {
            "amount": 10.0,
            "amount_milli": 10_000,
            "balance": 0.0,
            "balance_milli": 0,
            "bucket": API_USD_BUCKET,
            "currency": API_USD_CURRENCY,
            "dry_run": True,
            "email": "cli@example.org",
            "user_id": "user_cli",
            "workspace_id": "default",
        }
    ]
    assert (
        store.get_bucket_balance(
            "default", "user_cli", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 0
    )


@pytest.mark.asyncio
async def test_monthly_api_credit_allowance_apply_is_idempotent(tmp_path, monkeypatch):
    store = CreditsStore(str(tmp_path / "credits.sqlite"))

    async def fake_list_all():
        return [
            SimpleNamespace(
                id="user_active", email="active@example.org", is_active=True
            )
        ]

    monkeypatch.setattr(allowance_script, "_get_store", lambda: store)
    monkeypatch.setattr(
        allowance_script.UserStore, "list_all", staticmethod(fake_list_all)
    )

    first = await allowance_script.run_allowance(
        month="2026-05",
        workspace_id="default",
        allowance=10.0,
        cap=10.0,
        apply=True,
    )
    second = await allowance_script.run_allowance(
        month="2026-05",
        workspace_id="default",
        allowance=10.0,
        cap=10.0,
        apply=True,
    )

    assert first["results"][0]["amount_milli"] == 10_000
    assert second["results"][0]["idempotent"] is True
    assert (
        store.get_bucket_balance(
            "default", "user_active", bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
        )["balance_milli"]
        == 10_000
    )
