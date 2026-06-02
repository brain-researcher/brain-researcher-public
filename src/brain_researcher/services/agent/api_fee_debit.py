"""Bounded platform API-fee recording and credit-wallet debit helper.

This module intentionally does not infer identity from the LLM router. Callers
must pass wallet identity from an authenticated service layer after provider
usage is known.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Protocol, TypeVar

from brain_researcher.services.agent.cost_calculator import calculate_cost
from brain_researcher.services.agent.router import LLMRouteMetadata
from brain_researcher.services.agent.usage_aggregator import UsageTracker
from brain_researcher.services.shared.credits import (
    API_USD_BUCKET,
    API_USD_CURRENCY,
    _get_store,
)


class CreditsWalletStore(Protocol):
    def debit_bucket(
        self,
        workspace_id: str,
        user_id: str,
        *,
        bucket: str,
        currency: str,
        amount_milli: int,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def reserve_bucket(
        self,
        workspace_id: str,
        user_id: str,
        *,
        bucket: str,
        currency: str,
        amount_milli: int,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        ttl_seconds: int | None,
    ) -> dict[str, Any]: ...

    def commit_bucket_reservation(
        self,
        reservation_id: str,
        *,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        final_amount_milli: int | None = None,
    ) -> dict[str, Any]: ...

    def release_bucket_reservation(
        self,
        reservation_id: str,
        *,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]: ...


_T = TypeVar("_T")


@dataclass(frozen=True)
class ApiFeeDebitIdentity:
    """Wallet identity required before debiting platform API fees."""

    workspace_id: str
    user_id: str


@dataclass(frozen=True)
class ApiFeeDebitResult:
    """Outcome of a platform API-fee debit attempt."""

    status: str
    reason: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    amount_milli: int = 0
    cost_usd: str | None = None
    idempotency_key: str | None = None
    entry_id: str | None = None
    reservation_id: str | None = None
    balance_milli: int | None = None

    @property
    def debited(self) -> bool:
        return self.status == "debited"


@dataclass(frozen=True)
class ApiFeeReservationResult:
    """Outcome of a pre-call platform API-fee reservation attempt."""

    status: str
    reason: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    amount_milli: int = 0
    cost_usd: str | None = None
    idempotency_key: str | None = None
    reservation_id: str | None = None
    balance_milli: int | None = None
    idempotent: bool = False

    @property
    def reserved(self) -> bool:
        return self.status == "reserved" and bool(self.reservation_id)


class ApiFeeReservationError(RuntimeError):
    """Raised when a managed provider call must be blocked before invocation."""

    def __init__(self, result: ApiFeeReservationResult):
        self.result = result
        reason = result.reason or result.status
        super().__init__(reason)


def _decimal_from_float(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _credits_per_usd() -> Decimal:
    raw = os.getenv("BR_PLATFORM_API_FEE_CREDITS_PER_USD", "1")
    value = _decimal_from_float(raw)
    if value <= 0:
        return Decimal("1")
    return value


def _usage_token_count(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            try:
                return max(0, int(float(value)))
            except (TypeError, ValueError):
                continue
    return 0


def _usage_for_cost(metadata: LLMRouteMetadata) -> dict[str, int]:
    usage = metadata.usage or {}
    prompt_tokens = _usage_token_count(usage, "prompt_tokens", "input_tokens")
    completion_tokens = _usage_token_count(
        usage,
        "completion_tokens",
        "output_tokens",
        "candidates_token_count",
    )
    total_tokens = _usage_token_count(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _cost_usd_from_metadata(metadata: LLMRouteMetadata) -> Decimal:
    explicit = _decimal_from_float(metadata.estimated_cost)
    if explicit > 0:
        return explicit

    usage = _usage_for_cost(metadata)
    if usage["prompt_tokens"] <= 0 and usage["completion_tokens"] <= 0:
        return explicit

    cost = calculate_cost(
        metadata.provider or "",
        metadata.model or "",
        usage,
        bill_to=metadata.bill_to,
    )
    derived = _decimal_from_float(cost.get("total_cost"))
    return derived if derived > 0 else explicit


def _milli_credits_for_cost(cost_usd: Decimal) -> int:
    if cost_usd <= 0:
        return 0
    amount = cost_usd * _credits_per_usd() * Decimal("1000")
    amount_milli = int(amount.to_integral_value(rounding=ROUND_CEILING))
    return max(1, amount_milli)


def _is_platform_billable(metadata: LLMRouteMetadata) -> bool:
    bill_to = (metadata.bill_to or "").strip().lower()
    credential = (metadata.credential or "").strip().lower()
    return (
        bill_to == "managed"
        or bill_to.startswith("managed:")
        or credential.startswith("managed")
    )


def _default_idempotency_key(
    metadata: LLMRouteMetadata, explicit: str | None
) -> str | None:
    if explicit:
        return explicit
    if metadata.allocation_id:
        return f"llm-api-fee:{metadata.allocation_id}"
    return None


def _ledger_metadata(metadata: LLMRouteMetadata, cost_usd: Decimal) -> dict[str, Any]:
    return {
        "kind": "llm_platform_api_fee",
        "bucket": API_USD_BUCKET,
        "currency": API_USD_CURRENCY,
        "provider": metadata.provider,
        "model": metadata.model,
        "bill_to": metadata.bill_to,
        "credential": metadata.credential,
        "route": metadata.route,
        "transport": metadata.transport,
        "fallback_reason": metadata.fallback_reason,
        "usage": metadata.usage or {},
        "estimated_cost_usd": str(cost_usd),
        "credits_per_usd": str(_credits_per_usd()),
        "budget_id": metadata.budget_id,
        "allocation_id": metadata.allocation_id,
    }


def _reservation_ttl_seconds(explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    raw = os.getenv("BR_PLATFORM_API_FEE_RESERVATION_TTL_SECONDS", "600")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 600
    return value if value > 0 else None


def _reservation_ledger_metadata(
    metadata: LLMRouteMetadata,
    cost_usd: Decimal,
    *,
    event: str,
    reservation: ApiFeeReservationResult | None = None,
) -> dict[str, Any]:
    ledger_metadata = _ledger_metadata(metadata, cost_usd)
    ledger_metadata["reservation_event"] = event
    if reservation is not None:
        ledger_metadata["reservation_id"] = reservation.reservation_id
        ledger_metadata["reserved_amount_milli"] = reservation.amount_milli
        ledger_metadata["reserved_cost_usd"] = reservation.cost_usd
    return ledger_metadata


def _store_result_to_reservation(
    result: dict[str, Any],
    *,
    identity: ApiFeeDebitIdentity,
    cost_usd: Decimal,
    idempotency_key: str | None,
) -> ApiFeeReservationResult:
    status = str(result.get("status") or "reserved")
    reservation_id = str(result.get("reservation_id") or "") or None
    amount_milli = int(result.get("amount_milli") or 0)
    if status != "reserved":
        return ApiFeeReservationResult(
            status="failed",
            reason=f"reservation_not_available:{status}",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=amount_milli,
            cost_usd=str(cost_usd),
            idempotency_key=idempotency_key,
            reservation_id=reservation_id,
            balance_milli=(
                int(result["balance_milli"])
                if result.get("balance_milli") is not None
                else None
            ),
            idempotent=bool(result.get("idempotent")),
        )
    return ApiFeeReservationResult(
        status="reserved",
        workspace_id=identity.workspace_id,
        user_id=identity.user_id,
        amount_milli=amount_milli,
        cost_usd=str(cost_usd),
        idempotency_key=idempotency_key,
        reservation_id=reservation_id,
        balance_milli=(
            int(result["balance_milli"])
            if result.get("balance_milli") is not None
            else None
        ),
        idempotent=bool(result.get("idempotent")),
    )


def reserve_platform_api_fee(
    metadata: LLMRouteMetadata,
    *,
    identity: ApiFeeDebitIdentity | None,
    idempotency_key: str | None = None,
    credits_store: CreditsWalletStore | None = None,
    reservation_ttl_seconds: int | None = None,
) -> ApiFeeReservationResult:
    """Reserve API-fee USD before a platform-managed provider invocation.

    Managed routes fail closed when identity, a stable idempotency key, or
    balance is missing. BYOK and local OAuth routes are explicitly exempt.
    """

    if not _is_platform_billable(metadata):
        return ApiFeeReservationResult(status="skipped", reason="not_platform_billable")

    if identity is None or not identity.workspace_id or not identity.user_id:
        return ApiFeeReservationResult(status="failed", reason="missing_identity")

    cost_usd = _cost_usd_from_metadata(metadata)
    amount_milli = _milli_credits_for_cost(cost_usd)
    if amount_milli <= 0:
        return ApiFeeReservationResult(
            status="skipped",
            reason="zero_cost",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            cost_usd=str(cost_usd),
        )

    stable_idempotency_key = _default_idempotency_key(metadata, idempotency_key)
    if not stable_idempotency_key:
        return ApiFeeReservationResult(
            status="failed",
            reason="missing_idempotency_key",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=amount_milli,
            cost_usd=str(cost_usd),
        )

    store: CreditsWalletStore = credits_store or _get_store()
    ledger_metadata = _reservation_ledger_metadata(
        metadata,
        cost_usd,
        event="reserve",
    )
    try:
        reservation = store.reserve_bucket(
            identity.workspace_id,
            identity.user_id,
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=amount_milli,
            idempotency_key=stable_idempotency_key,
            metadata=ledger_metadata,
            ttl_seconds=_reservation_ttl_seconds(reservation_ttl_seconds),
        )
    except ValueError as exc:
        return ApiFeeReservationResult(
            status="failed",
            reason=str(exc),
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=amount_milli,
            cost_usd=str(cost_usd),
            idempotency_key=stable_idempotency_key,
        )
    return _store_result_to_reservation(
        reservation,
        identity=identity,
        cost_usd=cost_usd,
        idempotency_key=stable_idempotency_key,
    )


def _update_bucket_reservation_with_current_store(
    store: CreditsWalletStore,
    reservation_id: str,
    *,
    next_status: str,
    event_type: str,
    credit_delta_milli: int,
    final_amount_milli: int | None = None,
    metadata: dict[str, Any] | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Compatibility path for CreditsStore before bucket commit/release helpers.

    Newer stores should provide commit_bucket_reservation and
    release_bucket_reservation. This fallback is deliberately isolated here.
    """

    lock = getattr(store, "_lock", None)
    connect = getattr(store, "_connect", None)
    get_account = getattr(store, "_get_bucket_account_row", None)
    insert_ledger = getattr(store, "_insert_bucket_ledger", None)
    if lock is None or not callable(connect) or not callable(get_account):
        raise AttributeError("credits store does not support bucket reservations")
    if not callable(insert_ledger):
        raise AttributeError("credits store does not support bucket ledger updates")

    with lock:
        conn = connect()
        try:
            row = conn.execute(
                """
                SELECT reservation_id, workspace_id, user_id, bucket, currency,
                       amount_milli, status, created_at, updated_at, expires_at
                FROM credit_bucket_reservations
                WHERE reservation_id = ?
                LIMIT 1
                """,
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise KeyError("reservation_not_found")

            current_status = str(row["status"])
            workspace_id = str(row["workspace_id"])
            user_id = str(row["user_id"])
            bucket = str(row["bucket"])
            currency = str(row["currency"])
            amount_milli = int(row["amount_milli"])

            if current_status == next_status:
                account = get_account(conn, workspace_id, user_id, bucket, currency)
                return {
                    "reservation_id": reservation_id,
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "bucket": bucket,
                    "currency": currency,
                    "status": current_status,
                    "amount_milli": amount_milli,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "expires_at": row["expires_at"],
                    "balance_milli": int(account["balance_milli"]),
                    "idempotent": True,
                }

            if current_status != "reserved":
                raise ValueError(f"reservation_not_reserved:{current_status}")

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE credit_bucket_reservations
                SET status = ?, updated_at = ?, metadata_json = ?
                WHERE reservation_id = ?
                """,
                (
                    next_status,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=True),
                    reservation_id,
                ),
            )

            account = get_account(conn, workspace_id, user_id, bucket, currency)
            effective_delta_milli = int(credit_delta_milli)
            normalized_final_amount_milli: int | None = None
            if final_amount_milli is not None:
                normalized_final_amount_milli = max(0, int(final_amount_milli))
                effective_delta_milli = amount_milli - normalized_final_amount_milli
            next_balance = int(account["balance_milli"]) + effective_delta_milli
            if next_balance < 0:
                raise ValueError("insufficient_credits")
            if effective_delta_milli:
                conn.execute(
                    """
                    UPDATE credit_bucket_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                    """,
                    (next_balance, now, workspace_id, user_id, bucket, currency),
                )

            entry_id = insert_ledger(
                conn,
                workspace_id=workspace_id,
                user_id=user_id,
                bucket=bucket,
                currency=currency,
                event_type=event_type,
                amount_milli=effective_delta_milli,
                balance_after_milli=next_balance,
                reservation_id=reservation_id,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
            conn.commit()

            return {
                "entry_id": entry_id,
                "reservation_id": reservation_id,
                "workspace_id": workspace_id,
                "user_id": user_id,
                "bucket": bucket,
                "currency": currency,
                "status": next_status,
                "amount_milli": amount_milli,
                "final_amount_milli": normalized_final_amount_milli,
                "credit_delta_milli": effective_delta_milli,
                "created_at": row["created_at"],
                "updated_at": now,
                "expires_at": row["expires_at"],
                "balance_milli": next_balance,
                "idempotent": False,
            }
        finally:
            conn.close()


def _commit_bucket_reservation(
    store: CreditsWalletStore,
    reservation: ApiFeeReservationResult,
    *,
    idempotency_key: str | None,
    metadata: dict[str, Any] | None,
    final_amount_milli: int | None = None,
) -> dict[str, Any]:
    if not reservation.reservation_id:
        raise ValueError("missing_reservation_id")
    method = getattr(store, "commit_bucket_reservation", None)
    if callable(method):
        try:
            return method(
                reservation.reservation_id,
                idempotency_key=idempotency_key,
                metadata=metadata,
                final_amount_milli=final_amount_milli,
            )
        except TypeError:
            if final_amount_milli is None:
                raise
    return _update_bucket_reservation_with_current_store(
        store,
        reservation.reservation_id,
        next_status="committed",
        event_type="commit",
        credit_delta_milli=0,
        final_amount_milli=final_amount_milli,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


def _release_bucket_reservation(
    store: CreditsWalletStore,
    reservation: ApiFeeReservationResult,
    *,
    idempotency_key: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not reservation.reservation_id:
        raise ValueError("missing_reservation_id")
    method = getattr(store, "release_bucket_reservation", None)
    if callable(method):
        return method(
            reservation.reservation_id,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
    return _update_bucket_reservation_with_current_store(
        store,
        reservation.reservation_id,
        next_status="released",
        event_type="release",
        credit_delta_milli=reservation.amount_milli,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


def release_platform_api_fee_reservation(
    reservation: ApiFeeReservationResult,
    *,
    metadata: LLMRouteMetadata,
    credits_store: CreditsWalletStore | None = None,
    idempotency_key: str | None = None,
) -> ApiFeeReservationResult:
    """Release a pre-call reservation without recording a provider debit."""

    if not reservation.reserved:
        return reservation

    store: CreditsWalletStore = credits_store or _get_store()
    cost_usd = _cost_usd_from_metadata(metadata)
    stable_idempotency_key = idempotency_key or reservation.idempotency_key
    ledger_metadata = _reservation_ledger_metadata(
        metadata,
        cost_usd,
        event="release",
        reservation=reservation,
    )
    try:
        release = _release_bucket_reservation(
            store,
            reservation,
            idempotency_key=stable_idempotency_key,
            metadata=ledger_metadata,
        )
    except (KeyError, ValueError, AttributeError) as exc:
        return ApiFeeReservationResult(
            status="failed",
            reason=str(exc),
            workspace_id=reservation.workspace_id,
            user_id=reservation.user_id,
            amount_milli=reservation.amount_milli,
            cost_usd=reservation.cost_usd,
            idempotency_key=stable_idempotency_key,
            reservation_id=reservation.reservation_id,
        )

    return ApiFeeReservationResult(
        status="released",
        workspace_id=reservation.workspace_id,
        user_id=reservation.user_id,
        amount_milli=int(release.get("amount_milli") or reservation.amount_milli),
        cost_usd=reservation.cost_usd,
        idempotency_key=stable_idempotency_key,
        reservation_id=reservation.reservation_id,
        balance_milli=(
            int(release["balance_milli"])
            if release.get("balance_milli") is not None
            else None
        ),
        idempotent=bool(release.get("idempotent")),
    )


def record_usage_and_debit_platform_api_fee(
    metadata: LLMRouteMetadata,
    *,
    identity: ApiFeeDebitIdentity | None,
    idempotency_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    credits_store: CreditsWalletStore | None = None,
    reservation: ApiFeeReservationResult | None = None,
) -> ApiFeeDebitResult:
    """Record provider usage and debit platform API fees from a credits wallet.

    The debit path is intentionally narrow:
    - usage is recorded with the provided identity when a tracker is supplied;
    - wallet debit requires workspace/user identity;
    - wallet debit requires a stable idempotency key or router allocation id;
    - BYOK and local OAuth routes are not debited.
    """

    if usage_tracker is not None:
        usage_tracker.record_usage(
            metadata,
            workspace_id=identity.workspace_id if identity else None,
            user_id=identity.user_id if identity else None,
        )

    if reservation is not None and reservation.status == "failed":
        return ApiFeeDebitResult(
            status="failed",
            reason=reservation.reason,
            workspace_id=reservation.workspace_id,
            user_id=reservation.user_id,
            amount_milli=reservation.amount_milli,
            cost_usd=reservation.cost_usd,
            idempotency_key=reservation.idempotency_key,
            reservation_id=reservation.reservation_id,
            balance_milli=reservation.balance_milli,
        )

    if identity is None or not identity.workspace_id or not identity.user_id:
        return ApiFeeDebitResult(status="skipped", reason="missing_identity")

    if reservation is not None and reservation.reserved:
        cost_usd = _cost_usd_from_metadata(metadata)
        stable_idempotency_key = idempotency_key or reservation.idempotency_key
        store: CreditsWalletStore = credits_store or _get_store()
        if not _is_platform_billable(metadata):
            release_platform_api_fee_reservation(
                reservation,
                metadata=metadata,
                credits_store=store,
                idempotency_key=stable_idempotency_key,
            )
            return ApiFeeDebitResult(
                status="skipped",
                reason="not_platform_billable",
                workspace_id=identity.workspace_id,
                user_id=identity.user_id,
                amount_milli=reservation.amount_milli,
                cost_usd=str(cost_usd),
                idempotency_key=stable_idempotency_key,
                reservation_id=reservation.reservation_id,
            )

        if _milli_credits_for_cost(cost_usd) <= 0:
            release_platform_api_fee_reservation(
                reservation,
                metadata=metadata,
                credits_store=store,
                idempotency_key=stable_idempotency_key,
            )
            return ApiFeeDebitResult(
                status="skipped",
                reason="zero_cost",
                workspace_id=identity.workspace_id,
                user_id=identity.user_id,
                amount_milli=reservation.amount_milli,
                cost_usd=str(cost_usd),
                idempotency_key=stable_idempotency_key,
                reservation_id=reservation.reservation_id,
            )

        ledger_metadata = _reservation_ledger_metadata(
            metadata,
            cost_usd,
            event="commit",
            reservation=reservation,
        )
        final_amount_milli = _milli_credits_for_cost(cost_usd)
        try:
            commit = _commit_bucket_reservation(
                store,
                reservation,
                idempotency_key=stable_idempotency_key,
                metadata=ledger_metadata,
                final_amount_milli=final_amount_milli,
            )
        except (KeyError, ValueError, AttributeError) as exc:
            return ApiFeeDebitResult(
                status="failed",
                reason=str(exc),
                workspace_id=identity.workspace_id,
                user_id=identity.user_id,
                amount_milli=final_amount_milli,
                cost_usd=str(cost_usd),
                idempotency_key=stable_idempotency_key,
                reservation_id=reservation.reservation_id,
            )
        return ApiFeeDebitResult(
            status="debited",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=final_amount_milli,
            cost_usd=str(cost_usd),
            idempotency_key=stable_idempotency_key,
            entry_id=str(commit.get("entry_id") or ""),
            reservation_id=reservation.reservation_id,
            balance_milli=(
                int(commit["balance_milli"])
                if commit.get("balance_milli") is not None
                else None
            ),
        )

    if not _is_platform_billable(metadata):
        return ApiFeeDebitResult(
            status="skipped",
            reason="not_platform_billable",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
        )

    cost_usd = _cost_usd_from_metadata(metadata)
    amount_milli = _milli_credits_for_cost(cost_usd)
    if amount_milli <= 0:
        return ApiFeeDebitResult(
            status="skipped",
            reason="zero_cost",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            cost_usd=str(cost_usd),
        )

    stable_idempotency_key = _default_idempotency_key(metadata, idempotency_key)
    if not stable_idempotency_key:
        return ApiFeeDebitResult(
            status="skipped",
            reason="missing_idempotency_key",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=amount_milli,
            cost_usd=str(cost_usd),
        )

    store: CreditsWalletStore = credits_store or _get_store()
    ledger_metadata = _ledger_metadata(metadata, cost_usd)
    try:
        debit = store.debit_bucket(
            identity.workspace_id,
            identity.user_id,
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=amount_milli,
            idempotency_key=stable_idempotency_key,
            metadata=ledger_metadata,
        )
    except ValueError as exc:
        return ApiFeeDebitResult(
            status="failed",
            reason=str(exc),
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            amount_milli=amount_milli,
            cost_usd=str(cost_usd),
            idempotency_key=stable_idempotency_key,
        )
    return ApiFeeDebitResult(
        status="debited",
        workspace_id=identity.workspace_id,
        user_id=identity.user_id,
        amount_milli=amount_milli,
        cost_usd=str(cost_usd),
        idempotency_key=stable_idempotency_key,
        entry_id=str(debit.get("entry_id") or ""),
        balance_milli=int(debit["balance_milli"]),
    )


def call_with_platform_api_fee_reservation(
    metadata: LLMRouteMetadata,
    provider_call: Callable[[], _T],
    *,
    identity: ApiFeeDebitIdentity | None,
    idempotency_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    credits_store: CreditsWalletStore | None = None,
    reservation_ttl_seconds: int | None = None,
) -> _T:
    """Run a provider call behind a pre-call API-fee USD reservation.

    The callback is not invoked when a platform-managed route cannot reserve
    enough API-fee USD. On provider failure, any reservation made by this helper
    is released before the original exception is re-raised.
    """

    reservation = reserve_platform_api_fee(
        metadata,
        identity=identity,
        idempotency_key=idempotency_key,
        credits_store=credits_store,
        reservation_ttl_seconds=reservation_ttl_seconds,
    )
    if reservation.status == "failed":
        raise ApiFeeReservationError(reservation)

    try:
        result = provider_call()
    except Exception:
        if reservation.reserved:
            release_platform_api_fee_reservation(
                reservation,
                metadata=metadata,
                credits_store=credits_store,
                idempotency_key=reservation.idempotency_key,
            )
        raise

    result_metadata = getattr(result, "metadata", metadata)
    if not isinstance(result_metadata, LLMRouteMetadata):
        result_metadata = metadata
    debit_result = record_usage_and_debit_platform_api_fee(
        result_metadata,
        identity=identity,
        idempotency_key=idempotency_key or reservation.idempotency_key,
        usage_tracker=usage_tracker,
        credits_store=credits_store,
        reservation=reservation if reservation.reserved else None,
    )
    if isinstance(getattr(result, "metadata", None), LLMRouteMetadata):
        result.metadata.api_fee_reservation = reservation.__dict__
        result.metadata.api_fee_debit = debit_result.__dict__
    return result


__all__ = [
    "ApiFeeDebitIdentity",
    "ApiFeeDebitResult",
    "ApiFeeReservationError",
    "ApiFeeReservationResult",
    "call_with_platform_api_fee_reservation",
    "release_platform_api_fee_reservation",
    "record_usage_and_debit_platform_api_fee",
    "reserve_platform_api_fee",
]
