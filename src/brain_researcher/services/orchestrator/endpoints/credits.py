"""
Credits ledger and reservation endpoints.

This module provides an internal (non-payment) credits system:
- balance + ledger queries
- internal grants
- reservation / commit / release flow for execution gating
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain_researcher.services.shared.credits import (
    API_MONTHLY_ALLOWANCE_MILLI_USD,  # noqa: F401
    API_USD_BUCKET,
    API_USD_CURRENCY,
    INITIAL_API_USD_ALLOWANCE_MILLI_USD,  # noqa: F401
    INITIAL_WORKFLOW_ALLOWANCE_MILLI_CREDITS,  # noqa: F401
    WORKFLOW_MONTHLY_ALLOWANCE_MILLI_CREDITS,  # noqa: F401
    WORKFLOW_RUNTIME_BUCKET,  # noqa: F401
    WORKFLOW_RUNTIME_CURRENCY,  # noqa: F401
    CreditsStore,  # noqa: F401
    _from_milli_credits,
    _get_store,
    _to_milli_credits,
    grant_initial_account_credits_for_account,  # noqa: F401
    grant_initial_api_usd_credits_for_account,  # noqa: F401
    grant_initial_workflow_credits_for_account,  # noqa: F401
)

router = APIRouter(prefix="/api/credits", tags=["Credits"])


def _resolve_identity(
    request: Request, workspace_id: str | None, user_id: str | None
) -> tuple[str, str]:
    ws = (
        (workspace_id or "").strip()
        or (request.headers.get("x-workspace-id") or "").strip()
        or "default"
    )
    user = (
        (user_id or "").strip()
        or (request.headers.get("x-user-id") or "").strip()
        or "default"
    )
    return ws, user


class CreditsBalanceResponse(BaseModel):
    workspace_id: str
    user_id: str
    balance: float
    balance_milli: int
    updated_at: str


class BucketCreditsBalanceResponse(CreditsBalanceResponse):
    bucket: str
    currency: str


class CreditsLedgerEntryResponse(BaseModel):
    entry_id: str
    workspace_id: str
    user_id: str
    event_type: str
    amount: float
    amount_milli: int
    balance_after: float
    balance_after_milli: int
    reservation_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class CreditsLedgerResponse(BaseModel):
    items: list[CreditsLedgerEntryResponse]
    next_cursor: str | None = None


class CreditsGrantRequest(BaseModel):
    workspace_id: str | None = None
    user_id: str | None = None
    amount: float = Field(..., gt=0)
    idempotency_key: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreditsReservationRequest(BaseModel):
    workspace_id: str | None = None
    user_id: str | None = None
    amount: float = Field(..., gt=0)
    idempotency_key: str | None = None
    ttl_seconds: int | None = Field(default=1800, ge=60, le=86400)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreditsReservationActionRequest(BaseModel):
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreditsReservationResponse(BaseModel):
    reservation_id: str
    workspace_id: str
    user_id: str
    status: str
    amount: float
    amount_milli: int
    balance: float
    balance_milli: int
    created_at: str
    updated_at: str
    expires_at: str | None = None
    idempotent: bool = False


class ApiUsdMonthlyTopUpRequest(BaseModel):
    workspace_id: str | None = None
    user_id: str | None = None
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    allowance: float = Field(default=10.0, gt=0)
    cap: float = Field(default=10.0, gt=0)


class ApiUsdDebitRequest(BaseModel):
    workspace_id: str | None = None
    user_id: str | None = None
    amount: float = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApiUsdReservationRequest(CreditsReservationRequest):
    idempotency_key: str = Field(..., min_length=1)


class ApiUsdMutationResponse(BaseModel):
    workspace_id: str
    user_id: str
    bucket: str
    currency: str
    amount: float
    amount_milli: int
    balance: float
    balance_milli: int
    entry_id: str | None = None
    idempotent: bool = False


class BucketCreditsReservationResponse(CreditsReservationResponse):
    bucket: str
    currency: str


def _to_balance_response(payload: dict[str, Any]) -> CreditsBalanceResponse:
    return CreditsBalanceResponse(
        workspace_id=str(payload["workspace_id"]),
        user_id=str(payload["user_id"]),
        balance=_from_milli_credits(int(payload["balance_milli"])),
        balance_milli=int(payload["balance_milli"]),
        updated_at=str(payload["updated_at"]),
    )


def _to_bucket_balance_response(
    payload: dict[str, Any],
) -> BucketCreditsBalanceResponse:
    return BucketCreditsBalanceResponse(
        workspace_id=str(payload["workspace_id"]),
        user_id=str(payload["user_id"]),
        bucket=str(payload["bucket"]),
        currency=str(payload["currency"]),
        balance=_from_milli_credits(int(payload["balance_milli"])),
        balance_milli=int(payload["balance_milli"]),
        updated_at=str(payload["updated_at"]),
    )


def _to_reservation_response(payload: dict[str, Any]) -> CreditsReservationResponse:
    return CreditsReservationResponse(
        reservation_id=str(payload["reservation_id"]),
        workspace_id=str(payload["workspace_id"]),
        user_id=str(payload["user_id"]),
        status=str(payload["status"]),
        amount=_from_milli_credits(int(payload["amount_milli"])),
        amount_milli=int(payload["amount_milli"]),
        balance=_from_milli_credits(int(payload["balance_milli"])),
        balance_milli=int(payload["balance_milli"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        expires_at=payload.get("expires_at"),
        idempotent=bool(payload.get("idempotent", False)),
    )


def _to_bucket_reservation_response(
    payload: dict[str, Any],
) -> BucketCreditsReservationResponse:
    return BucketCreditsReservationResponse(
        reservation_id=str(payload["reservation_id"]),
        workspace_id=str(payload["workspace_id"]),
        user_id=str(payload["user_id"]),
        bucket=str(payload["bucket"]),
        currency=str(payload["currency"]),
        status=str(payload["status"]),
        amount=_from_milli_credits(int(payload["amount_milli"])),
        amount_milli=int(payload["amount_milli"]),
        balance=_from_milli_credits(int(payload["balance_milli"])),
        balance_milli=int(payload["balance_milli"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        expires_at=payload.get("expires_at"),
        idempotent=bool(payload.get("idempotent", False)),
    )


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _api_usd_mutation_api_enabled() -> bool:
    return os.getenv("BR_ENABLE_API_USD_MUTATION_API", "0").lower() in {
        "1",
        "true",
        "yes",
    }


def _require_api_usd_mutation_api() -> None:
    if not _api_usd_mutation_api_enabled():
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/balance", response_model=CreditsBalanceResponse)
async def credits_balance(
    request: Request,
    workspace_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
):
    ws, user = _resolve_identity(request, workspace_id, user_id)
    payload = _get_store().get_balance(ws, user)
    return _to_balance_response(payload)


@router.get("/ledger", response_model=CreditsLedgerResponse)
async def credits_ledger(
    request: Request,
    workspace_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
):
    ws, user = _resolve_identity(request, workspace_id, user_id)
    payload = _get_store().list_ledger(ws, user, cursor=cursor, limit=limit)
    items: list[CreditsLedgerEntryResponse] = []
    for item in payload["items"]:
        items.append(
            CreditsLedgerEntryResponse(
                entry_id=item["entry_id"],
                workspace_id=item["workspace_id"],
                user_id=item["user_id"],
                event_type=item["event_type"],
                amount=_from_milli_credits(item["amount_milli"]),
                amount_milli=item["amount_milli"],
                balance_after=_from_milli_credits(item["balance_after_milli"]),
                balance_after_milli=item["balance_after_milli"],
                reservation_id=item.get("reservation_id"),
                idempotency_key=item.get("idempotency_key"),
                metadata=item.get("metadata") or {},
                created_at=item["created_at"],
            )
        )
    return CreditsLedgerResponse(items=items, next_cursor=payload.get("next_cursor"))


@router.get("/api-usd/balance", response_model=BucketCreditsBalanceResponse)
async def api_usd_credits_balance(
    request: Request,
    workspace_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
):
    ws, user = _resolve_identity(request, workspace_id, user_id)
    payload = _get_store().get_bucket_balance(
        ws, user, bucket=API_USD_BUCKET, currency=API_USD_CURRENCY
    )
    return _to_bucket_balance_response(payload)


@router.post("/api-usd/monthly-top-up", response_model=ApiUsdMutationResponse)
async def api_usd_monthly_top_up(request: Request, payload: ApiUsdMonthlyTopUpRequest):
    _require_api_usd_mutation_api()
    ws, user = _resolve_identity(request, payload.workspace_id, payload.user_id)
    try:
        result = _get_store().top_up_api_monthly_allowance(
            ws,
            user,
            month=payload.month or _current_month(),
            allowance_milli=_to_milli_credits(payload.allowance),
            cap_milli=_to_milli_credits(payload.cap),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiUsdMutationResponse(
        workspace_id=ws,
        user_id=user,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        entry_id=result.get("entry_id"),
        idempotent=bool(result.get("idempotent")),
        amount=_from_milli_credits(int(result["amount_milli"])),
        amount_milli=int(result["amount_milli"]),
        balance=_from_milli_credits(int(result["balance_milli"])),
        balance_milli=int(result["balance_milli"]),
    )


@router.post("/api-usd/debits", response_model=ApiUsdMutationResponse)
async def api_usd_debit(request: Request, payload: ApiUsdDebitRequest):
    _require_api_usd_mutation_api()
    ws, user = _resolve_identity(request, payload.workspace_id, payload.user_id)
    try:
        result = _get_store().debit_bucket(
            ws,
            user,
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=_to_milli_credits(payload.amount),
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        if str(exc) == "insufficient_credits":
            raise HTTPException(status_code=402, detail="Insufficient credits") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiUsdMutationResponse(
        workspace_id=ws,
        user_id=user,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        entry_id=result.get("entry_id"),
        idempotent=bool(result.get("idempotent")),
        amount=_from_milli_credits(int(result["amount_milli"])),
        amount_milli=int(result["amount_milli"]),
        balance=_from_milli_credits(int(result["balance_milli"])),
        balance_milli=int(result["balance_milli"]),
    )


@router.post("/api-usd/reservations", response_model=BucketCreditsReservationResponse)
async def api_usd_reserve(request: Request, payload: ApiUsdReservationRequest):
    _require_api_usd_mutation_api()
    ws, user = _resolve_identity(request, payload.workspace_id, payload.user_id)
    try:
        result = _get_store().reserve_bucket(
            ws,
            user,
            bucket=API_USD_BUCKET,
            currency=API_USD_CURRENCY,
            amount_milli=_to_milli_credits(payload.amount),
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
            ttl_seconds=payload.ttl_seconds,
        )
    except ValueError as exc:
        if str(exc) == "insufficient_credits":
            raise HTTPException(status_code=402, detail="Insufficient credits") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_bucket_reservation_response(result)


@router.post("/grants")
async def credits_grant(request: Request, payload: CreditsGrantRequest):
    ws, user = _resolve_identity(request, payload.workspace_id, payload.user_id)
    metadata = dict(payload.metadata or {})
    if payload.reason:
        metadata.setdefault("reason", payload.reason)
    try:
        result = _get_store().grant(
            ws,
            user,
            amount_milli=_to_milli_credits(payload.amount),
            idempotency_key=payload.idempotency_key,
            metadata=metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    balance = _get_store().get_balance(ws, user)
    return {
        "entry_id": result["entry_id"],
        "idempotent": bool(result.get("idempotent")),
        "balance": _from_milli_credits(int(balance["balance_milli"])),
        "balance_milli": int(balance["balance_milli"]),
        "workspace_id": ws,
        "user_id": user,
    }


@router.post("/reservations", response_model=CreditsReservationResponse)
async def credits_reserve(request: Request, payload: CreditsReservationRequest):
    ws, user = _resolve_identity(request, payload.workspace_id, payload.user_id)
    try:
        result = _get_store().reserve(
            ws,
            user,
            amount_milli=_to_milli_credits(payload.amount),
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
            ttl_seconds=payload.ttl_seconds,
        )
    except ValueError as exc:
        if str(exc) == "insufficient_credits":
            raise HTTPException(status_code=402, detail="Insufficient credits") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result["workspace_id"] = ws
    result["user_id"] = user
    return _to_reservation_response(result)


@router.post(
    "/reservations/{reservation_id}/commit", response_model=CreditsReservationResponse
)
async def credits_commit(reservation_id: str, payload: CreditsReservationActionRequest):
    try:
        result = _get_store().commit(
            reservation_id,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Reservation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_reservation_response(result)


@router.post(
    "/reservations/{reservation_id}/release", response_model=CreditsReservationResponse
)
async def credits_release(
    reservation_id: str, payload: CreditsReservationActionRequest
):
    try:
        result = _get_store().release(
            reservation_id,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Reservation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_reservation_response(result)
