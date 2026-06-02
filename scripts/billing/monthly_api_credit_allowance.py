#!/usr/bin/env python3
"""Top up each active account's API-fee USD credits to a monthly cap.

Inputs:
- User list: orchestrator UserStore, normally backed by REDIS_URL.
- Credits DB: BR_CREDITS_DB, or the orchestrator default data-root SQLite path.

Usage:
  python scripts/billing/monthly_api_credit_allowance.py --month 2026-05
  python scripts/billing/monthly_api_credit_allowance.py --month 2026-05 --apply

The default mode is dry-run. Use --apply to write ledger entries.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from brain_researcher.services.orchestrator.endpoints.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    CreditsStore,
    _from_milli_credits,
    _get_store,
    _to_milli_credits,
)
from brain_researcher.services.orchestrator.user_store import UserStore


@dataclass(frozen=True)
class AllowanceTarget:
    workspace_id: str
    user_id: str
    email: str | None


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _active_user_targets(users: list[Any], workspace_id: str) -> list[AllowanceTarget]:
    targets: list[AllowanceTarget] = []
    for user in users:
        if not bool(getattr(user, "is_active", True)):
            continue
        user_id = str(getattr(user, "id", "") or "").strip()
        if not user_id:
            continue
        email = getattr(user, "email", None)
        targets.append(
            AllowanceTarget(
                workspace_id=workspace_id,
                user_id=user_id,
                email=str(email) if email else None,
            )
        )
    return targets


def _preview_top_up(
    store: CreditsStore,
    target: AllowanceTarget,
    *,
    allowance_milli: int,
    cap_milli: int,
) -> dict[str, Any]:
    balance = store.get_bucket_balance(
        target.workspace_id,
        target.user_id,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
    )
    current = int(balance["balance_milli"])
    top_up = max(0, min(allowance_milli, cap_milli - current))
    return {
        "workspace_id": target.workspace_id,
        "user_id": target.user_id,
        "email": target.email,
        "bucket": API_USD_BUCKET,
        "currency": API_USD_CURRENCY,
        "dry_run": True,
        "amount": _from_milli_credits(top_up),
        "amount_milli": top_up,
        "balance": _from_milli_credits(current),
        "balance_milli": current,
    }


async def run_allowance(
    *,
    month: str,
    workspace_id: str,
    allowance: float,
    cap: float,
    apply: bool,
) -> dict[str, Any]:
    store = _get_store()
    users = await UserStore.list_all()
    targets = _active_user_targets(users, workspace_id)
    allowance_milli = _to_milli_credits(allowance)
    cap_milli = _to_milli_credits(cap)

    results: list[dict[str, Any]] = []
    for target in targets:
        if not apply:
            results.append(
                _preview_top_up(
                    store,
                    target,
                    allowance_milli=allowance_milli,
                    cap_milli=cap_milli,
                )
            )
            continue

        result = store.top_up_api_monthly_allowance(
            target.workspace_id,
            target.user_id,
            month=month,
            allowance_milli=allowance_milli,
            cap_milli=cap_milli,
        )
        results.append(
            {
                "workspace_id": target.workspace_id,
                "user_id": target.user_id,
                "email": target.email,
                "bucket": result["bucket"],
                "currency": result["currency"],
                "dry_run": False,
                "entry_id": result["entry_id"],
                "idempotent": result["idempotent"],
                "amount": _from_milli_credits(int(result["amount_milli"])),
                "amount_milli": int(result["amount_milli"]),
                "balance": _from_milli_credits(int(result["balance_milli"])),
                "balance_milli": int(result["balance_milli"]),
            }
        )

    return {
        "month": month,
        "workspace_id": workspace_id,
        "bucket": API_USD_BUCKET,
        "currency": API_USD_CURRENCY,
        "allowance": allowance,
        "cap": cap,
        "dry_run": not apply,
        "total_users": len(targets),
        "total_amount": round(sum(float(row["amount"]) for row in results), 3),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month", default=_current_month(), help="Allowance month, YYYY-MM."
    )
    parser.add_argument("--workspace-id", default="default")
    parser.add_argument("--allowance", type=float, default=10.0)
    parser.add_argument("--cap", type=float, default=10.0)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write top-up ledger entries. Omit for dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = asyncio.run(
        run_allowance(
            month=args.month,
            workspace_id=args.workspace_id,
            allowance=args.allowance,
            cap=args.cap,
            apply=bool(args.apply),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
