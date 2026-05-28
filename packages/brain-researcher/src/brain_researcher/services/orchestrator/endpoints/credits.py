"""
Credits ledger and reservation endpoints.

This module provides an internal (non-payment) credits system:
- balance + ledger queries
- internal grants
- reservation / commit / release flow for execution gating
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain_researcher.config.paths import get_data_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credits", tags=["Credits"])

WORKFLOW_RUNTIME_BUCKET = "workflow_runtime"
WORKFLOW_RUNTIME_CURRENCY = "credit"
WORKFLOW_MONTHLY_ALLOWANCE_MILLI_CREDITS = 10_000
INITIAL_WORKFLOW_ALLOWANCE_MILLI_CREDITS = 10_000
API_USD_BUCKET = "api_fee_usd"
API_USD_CURRENCY = "usd"
API_MONTHLY_ALLOWANCE_MILLI_USD = 10_000
INITIAL_API_USD_ALLOWANCE_MILLI_USD = 10_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_milli_credits(amount: float) -> int:
    return int(round(float(amount) * 1000))


def _from_milli_credits(amount_milli: int) -> float:
    return round(float(amount_milli) / 1000.0, 3)


class CreditsStore:
    """SQLite-backed credits store with transactional balance updates."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS credit_accounts (
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        balance_milli INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, user_id)
                    );

                    CREATE TABLE IF NOT EXISTS credit_ledger (
                        entry_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        amount_milli INTEGER NOT NULL,
                        balance_after_milli INTEGER NOT NULL,
                        reservation_id TEXT,
                        idempotency_key TEXT,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS credit_ledger_identity_idx
                    ON credit_ledger(workspace_id, user_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS credit_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        amount_milli INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        idempotency_key TEXT,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS credit_reservations_idempo_idx
                    ON credit_reservations(workspace_id, user_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS credit_bucket_accounts (
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        bucket TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        balance_milli INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, user_id, bucket, currency)
                    );

                    CREATE TABLE IF NOT EXISTS credit_bucket_ledger (
                        entry_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        bucket TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        amount_milli INTEGER NOT NULL,
                        balance_after_milli INTEGER NOT NULL,
                        reservation_id TEXT,
                        idempotency_key TEXT,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS credit_bucket_ledger_identity_idx
                    ON credit_bucket_ledger(workspace_id, user_id, bucket, currency, created_at DESC);

                    CREATE UNIQUE INDEX IF NOT EXISTS credit_bucket_ledger_idempo_idx
                    ON credit_bucket_ledger(workspace_id, user_id, bucket, currency, event_type, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS credit_bucket_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        bucket TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        amount_milli INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        idempotency_key TEXT,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS credit_bucket_reservations_idempo_idx
                    ON credit_bucket_reservations(workspace_id, user_id, bucket, currency, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _ensure_account(
        self, conn: sqlite3.Connection, workspace_id: str, user_id: str
    ) -> None:
        now = _utc_now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO credit_accounts (workspace_id, user_id, balance_milli, updated_at)
            VALUES (?, ?, 0, ?)
            """,
            (workspace_id, user_id, now),
        )

    def _get_account_row(
        self, conn: sqlite3.Connection, workspace_id: str, user_id: str
    ) -> sqlite3.Row:
        self._ensure_account(conn, workspace_id, user_id)
        row = conn.execute(
            """
            SELECT workspace_id, user_id, balance_milli, updated_at
            FROM credit_accounts
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("credit account missing after ensure")
        return row

    def _insert_ledger(
        self,
        conn: sqlite3.Connection,
        *,
        workspace_id: str,
        user_id: str,
        event_type: str,
        amount_milli: int,
        balance_after_milli: int,
        reservation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO credit_ledger (
              entry_id, workspace_id, user_id, event_type, amount_milli, balance_after_milli,
              reservation_id, idempotency_key, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                workspace_id,
                user_id,
                event_type,
                int(amount_milli),
                int(balance_after_milli),
                reservation_id,
                idempotency_key,
                json.dumps(metadata or {}, ensure_ascii=True),
                _utc_now_iso(),
            ),
        )
        return entry_id

    def _ensure_bucket_account(
        self,
        conn: sqlite3.Connection,
        workspace_id: str,
        user_id: str,
        bucket: str,
        currency: str,
    ) -> None:
        now = _utc_now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO credit_bucket_accounts (
              workspace_id, user_id, bucket, currency, balance_milli, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?)
            """,
            (workspace_id, user_id, bucket, currency, now),
        )

    def _get_bucket_account_row(
        self,
        conn: sqlite3.Connection,
        workspace_id: str,
        user_id: str,
        bucket: str,
        currency: str,
    ) -> sqlite3.Row:
        self._ensure_bucket_account(conn, workspace_id, user_id, bucket, currency)
        row = conn.execute(
            """
            SELECT workspace_id, user_id, bucket, currency, balance_milli, updated_at
            FROM credit_bucket_accounts
            WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
            """,
            (workspace_id, user_id, bucket, currency),
        ).fetchone()
        if row is None:
            raise RuntimeError("credit bucket account missing after ensure")
        return row

    def _insert_bucket_ledger(
        self,
        conn: sqlite3.Connection,
        *,
        workspace_id: str,
        user_id: str,
        bucket: str,
        currency: str,
        event_type: str,
        amount_milli: int,
        balance_after_milli: int,
        reservation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO credit_bucket_ledger (
              entry_id, workspace_id, user_id, bucket, currency, event_type,
              amount_milli, balance_after_milli, reservation_id, idempotency_key,
              metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                workspace_id,
                user_id,
                bucket,
                currency,
                event_type,
                int(amount_milli),
                int(balance_after_milli),
                reservation_id,
                idempotency_key,
                json.dumps(metadata or {}, ensure_ascii=True),
                _utc_now_iso(),
            ),
        )
        return entry_id

    def get_bucket_balance(
        self, workspace_id: str, user_id: str, *, bucket: str, currency: str
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = self._get_bucket_account_row(
                    conn, workspace_id, user_id, bucket, currency
                )
                return {
                    "workspace_id": row["workspace_id"],
                    "user_id": row["user_id"],
                    "bucket": row["bucket"],
                    "currency": row["currency"],
                    "balance_milli": int(row["balance_milli"]),
                    "updated_at": row["updated_at"],
                }
            finally:
                conn.close()

    def bucket_grant(
        self,
        workspace_id: str,
        user_id: str,
        *,
        bucket: str,
        currency: str,
        amount_milli: int,
        event_type: str = "grant",
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if amount_milli <= 0:
            raise ValueError("grant amount must be > 0")

        with self._lock:
            conn = self._connect()
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT entry_id
                        FROM credit_bucket_ledger
                        WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                          AND event_type = ? AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (
                            workspace_id,
                            user_id,
                            bucket,
                            currency,
                            event_type,
                            idempotency_key,
                        ),
                    ).fetchone()
                    if existing is not None:
                        balance = self._get_bucket_account_row(
                            conn, workspace_id, user_id, bucket, currency
                        )
                        return {
                            "entry_id": existing["entry_id"],
                            "idempotent": True,
                            "amount_milli": 0,
                            "balance_milli": int(balance["balance_milli"]),
                        }

                account = self._get_bucket_account_row(
                    conn, workspace_id, user_id, bucket, currency
                )
                next_balance = int(account["balance_milli"]) + int(amount_milli)
                now = _utc_now_iso()
                conn.execute(
                    """
                    UPDATE credit_bucket_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                    """,
                    (next_balance, now, workspace_id, user_id, bucket, currency),
                )
                entry_id = self._insert_bucket_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    bucket=bucket,
                    currency=currency,
                    event_type=event_type,
                    amount_milli=amount_milli,
                    balance_after_milli=next_balance,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "entry_id": entry_id,
                    "idempotent": False,
                    "amount_milli": int(amount_milli),
                    "balance_milli": next_balance,
                }
            finally:
                conn.close()

    def top_up_api_monthly_allowance(
        self,
        workspace_id: str,
        user_id: str,
        *,
        month: str,
        allowance_milli: int = API_MONTHLY_ALLOWANCE_MILLI_USD,
        cap_milli: int = API_MONTHLY_ALLOWANCE_MILLI_USD,
    ) -> Dict[str, Any]:
        if allowance_milli <= 0 or cap_milli <= 0:
            raise ValueError("allowance and cap must be > 0")
        idempotency_key = f"api-usd-monthly:{month}"
        metadata = {
            "bucket": API_USD_BUCKET,
            "currency": API_USD_CURRENCY,
            "month": month,
        }

        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    """
                    SELECT entry_id, amount_milli, balance_after_milli
                    FROM credit_bucket_ledger
                    WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                      AND event_type = 'monthly_top_up' AND idempotency_key = ?
                    LIMIT 1
                    """,
                    (
                        workspace_id,
                        user_id,
                        API_USD_BUCKET,
                        API_USD_CURRENCY,
                        idempotency_key,
                    ),
                ).fetchone()
                if existing is not None:
                    account = self._get_bucket_account_row(
                        conn, workspace_id, user_id, API_USD_BUCKET, API_USD_CURRENCY
                    )
                    return {
                        "entry_id": existing["entry_id"],
                        "idempotent": True,
                        "amount_milli": int(existing["amount_milli"]),
                        "balance_milli": int(account["balance_milli"]),
                        "bucket": API_USD_BUCKET,
                        "currency": API_USD_CURRENCY,
                    }

                account = self._get_bucket_account_row(
                    conn, workspace_id, user_id, API_USD_BUCKET, API_USD_CURRENCY
                )
                current_balance = int(account["balance_milli"])
                top_up_milli = max(
                    0, min(int(allowance_milli), int(cap_milli) - current_balance)
                )
                now = _utc_now_iso()
                next_balance = current_balance + top_up_milli
                if top_up_milli:
                    conn.execute(
                        """
                        UPDATE credit_bucket_accounts
                        SET balance_milli = ?, updated_at = ?
                        WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                        """,
                        (
                            next_balance,
                            now,
                            workspace_id,
                            user_id,
                            API_USD_BUCKET,
                            API_USD_CURRENCY,
                        ),
                    )
                entry_id = self._insert_bucket_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    bucket=API_USD_BUCKET,
                    currency=API_USD_CURRENCY,
                    event_type="monthly_top_up",
                    amount_milli=top_up_milli,
                    balance_after_milli=next_balance,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "entry_id": entry_id,
                    "idempotent": False,
                    "amount_milli": top_up_milli,
                    "balance_milli": next_balance,
                    "bucket": API_USD_BUCKET,
                    "currency": API_USD_CURRENCY,
                }
            finally:
                conn.close()

    def top_up_workflow_monthly_allowance(
        self,
        workspace_id: str,
        user_id: str,
        *,
        month: str,
        allowance_milli: int = WORKFLOW_MONTHLY_ALLOWANCE_MILLI_CREDITS,
        cap_milli: int = WORKFLOW_MONTHLY_ALLOWANCE_MILLI_CREDITS,
    ) -> Dict[str, Any]:
        if allowance_milli <= 0 or cap_milli <= 0:
            raise ValueError("allowance and cap must be > 0")
        idempotency_key = f"workflow-runtime-monthly:{month}"
        metadata = {
            "bucket": WORKFLOW_RUNTIME_BUCKET,
            "currency": WORKFLOW_RUNTIME_CURRENCY,
            "month": month,
        }

        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    """
                    SELECT entry_id, amount_milli, balance_after_milli
                    FROM credit_ledger
                    WHERE workspace_id = ? AND user_id = ? AND idempotency_key = ?
                    LIMIT 1
                    """,
                    (workspace_id, user_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    account = self._get_account_row(conn, workspace_id, user_id)
                    return {
                        "entry_id": existing["entry_id"],
                        "idempotent": True,
                        "amount_milli": int(existing["amount_milli"]),
                        "balance_milli": int(account["balance_milli"]),
                        "bucket": WORKFLOW_RUNTIME_BUCKET,
                        "currency": WORKFLOW_RUNTIME_CURRENCY,
                    }

                account = self._get_account_row(conn, workspace_id, user_id)
                current_balance = int(account["balance_milli"])
                top_up_milli = max(
                    0, min(int(allowance_milli), int(cap_milli) - current_balance)
                )
                now = _utc_now_iso()
                next_balance = current_balance + top_up_milli
                if top_up_milli:
                    conn.execute(
                        """
                        UPDATE credit_accounts
                        SET balance_milli = ?, updated_at = ?
                        WHERE workspace_id = ? AND user_id = ?
                        """,
                        (next_balance, now, workspace_id, user_id),
                    )
                entry_id = self._insert_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    event_type="monthly_top_up",
                    amount_milli=top_up_milli,
                    balance_after_milli=next_balance,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "entry_id": entry_id,
                    "idempotent": False,
                    "amount_milli": top_up_milli,
                    "balance_milli": next_balance,
                    "bucket": WORKFLOW_RUNTIME_BUCKET,
                    "currency": WORKFLOW_RUNTIME_CURRENCY,
                }
            finally:
                conn.close()

    def debit_bucket(
        self,
        workspace_id: str,
        user_id: str,
        *,
        bucket: str,
        currency: str,
        amount_milli: int,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if amount_milli <= 0:
            raise ValueError("debit amount must be > 0")

        with self._lock:
            conn = self._connect()
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT entry_id, balance_after_milli
                        FROM credit_bucket_ledger
                        WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                          AND event_type = 'debit' AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (workspace_id, user_id, bucket, currency, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        return {
                            "entry_id": existing["entry_id"],
                            "idempotent": True,
                            "amount_milli": int(amount_milli),
                            "balance_milli": int(existing["balance_after_milli"]),
                        }

                account = self._get_bucket_account_row(
                    conn, workspace_id, user_id, bucket, currency
                )
                current_balance = int(account["balance_milli"])
                if current_balance < int(amount_milli):
                    raise ValueError("insufficient_credits")
                next_balance = current_balance - int(amount_milli)
                now = _utc_now_iso()
                conn.execute(
                    """
                    UPDATE credit_bucket_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                    """,
                    (next_balance, now, workspace_id, user_id, bucket, currency),
                )
                entry_id = self._insert_bucket_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    bucket=bucket,
                    currency=currency,
                    event_type="debit",
                    amount_milli=-int(amount_milli),
                    balance_after_milli=next_balance,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "entry_id": entry_id,
                    "idempotent": False,
                    "amount_milli": int(amount_milli),
                    "balance_milli": next_balance,
                }
            finally:
                conn.close()

    def reserve_bucket(
        self,
        workspace_id: str,
        user_id: str,
        *,
        bucket: str,
        currency: str,
        amount_milli: int,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
        ttl_seconds: Optional[int],
    ) -> Dict[str, Any]:
        if amount_milli <= 0:
            raise ValueError("reservation amount must be > 0")

        with self._lock:
            conn = self._connect()
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT reservation_id, status, amount_milli, created_at, updated_at, expires_at
                        FROM credit_bucket_reservations
                        WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                          AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (workspace_id, user_id, bucket, currency, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        balance = self._get_bucket_account_row(
                            conn, workspace_id, user_id, bucket, currency
                        )
                        return {
                            "reservation_id": existing["reservation_id"],
                            "workspace_id": workspace_id,
                            "user_id": user_id,
                            "bucket": bucket,
                            "currency": currency,
                            "status": existing["status"],
                            "amount_milli": int(existing["amount_milli"]),
                            "created_at": existing["created_at"],
                            "updated_at": existing["updated_at"],
                            "expires_at": existing["expires_at"],
                            "balance_milli": int(balance["balance_milli"]),
                            "idempotent": True,
                        }

                account = self._get_bucket_account_row(
                    conn, workspace_id, user_id, bucket, currency
                )
                current_balance = int(account["balance_milli"])
                if current_balance < int(amount_milli):
                    raise ValueError("insufficient_credits")
                next_balance = current_balance - int(amount_milli)
                now = datetime.now(timezone.utc)
                now_iso = now.isoformat()
                expires_at = (
                    (now + timedelta(seconds=int(ttl_seconds))).isoformat()
                    if ttl_seconds and int(ttl_seconds) > 0
                    else None
                )
                reservation_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO credit_bucket_reservations (
                      reservation_id, workspace_id, user_id, bucket, currency, amount_milli,
                      status, idempotency_key, metadata_json, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        workspace_id,
                        user_id,
                        bucket,
                        currency,
                        int(amount_milli),
                        idempotency_key,
                        json.dumps(metadata or {}, ensure_ascii=True),
                        now_iso,
                        now_iso,
                        expires_at,
                    ),
                )
                conn.execute(
                    """
                    UPDATE credit_bucket_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                    """,
                    (next_balance, now_iso, workspace_id, user_id, bucket, currency),
                )
                entry_id = self._insert_bucket_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    bucket=bucket,
                    currency=currency,
                    event_type="reserve",
                    amount_milli=-int(amount_milli),
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
                    "status": "reserved",
                    "amount_milli": int(amount_milli),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "expires_at": expires_at,
                    "balance_milli": next_balance,
                    "idempotent": False,
                }
            finally:
                conn.close()

    def _update_bucket_reservation_status(
        self,
        reservation_id: str,
        *,
        next_status: str,
        event_type: str,
        credit_delta_milli: int,
        final_amount_milli: Optional[int] = None,
        metadata: Optional[Dict[str, Any]],
        idempotency_key: Optional[str],
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
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
                    account = self._get_bucket_account_row(
                        conn, workspace_id, user_id, bucket, currency
                    )
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

                now = _utc_now_iso()
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

                account = self._get_bucket_account_row(
                    conn, workspace_id, user_id, bucket, currency
                )
                effective_delta_milli = int(credit_delta_milli)
                normalized_final_amount_milli: Optional[int] = None
                if final_amount_milli is not None:
                    normalized_final_amount_milli = max(0, int(final_amount_milli))
                    effective_delta_milli = amount_milli - normalized_final_amount_milli
                next_balance = int(account["balance_milli"]) + effective_delta_milli
                if next_balance < 0:
                    raise ValueError("insufficient_credits")

                if effective_delta_milli != 0:
                    conn.execute(
                        """
                        UPDATE credit_bucket_accounts
                        SET balance_milli = ?, updated_at = ?
                        WHERE workspace_id = ? AND user_id = ? AND bucket = ? AND currency = ?
                        """,
                        (
                            next_balance,
                            now,
                            workspace_id,
                            user_id,
                            bucket,
                            currency,
                        ),
                    )

                entry_id = self._insert_bucket_ledger(
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

    def commit_bucket_reservation(
        self,
        reservation_id: str,
        *,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
        final_amount_milli: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._update_bucket_reservation_status(
            reservation_id,
            next_status="committed",
            event_type="commit",
            credit_delta_milli=0,
            final_amount_milli=final_amount_milli,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def release_bucket_reservation(
        self,
        reservation_id: str,
        *,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT amount_milli
                    FROM credit_bucket_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    raise KeyError("reservation_not_found")
                amount_milli = int(row["amount_milli"])
            finally:
                conn.close()

        return self._update_bucket_reservation_status(
            reservation_id,
            next_status="released",
            event_type="release",
            credit_delta_milli=amount_milli,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def get_balance(self, workspace_id: str, user_id: str) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = self._get_account_row(conn, workspace_id, user_id)
                return {
                    "workspace_id": row["workspace_id"],
                    "user_id": row["user_id"],
                    "balance_milli": int(row["balance_milli"]),
                    "updated_at": row["updated_at"],
                }
            finally:
                conn.close()

    def list_ledger(
        self, workspace_id: str, user_id: str, *, cursor: Optional[str], limit: int
    ) -> Dict[str, Any]:
        offset = 0
        if cursor:
            try:
                offset = max(0, int(cursor))
            except Exception:
                offset = 0

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT entry_id, workspace_id, user_id, event_type, amount_milli, balance_after_milli,
                           reservation_id, idempotency_key, metadata_json, created_at
                    FROM credit_ledger
                    WHERE workspace_id = ? AND user_id = ?
                    ORDER BY created_at DESC, entry_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (workspace_id, user_id, int(limit), int(offset)),
                ).fetchall()

                items: List[Dict[str, Any]] = []
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata_json"] or "{}")
                    except Exception:
                        metadata = {}
                    items.append(
                        {
                            "entry_id": row["entry_id"],
                            "workspace_id": row["workspace_id"],
                            "user_id": row["user_id"],
                            "event_type": row["event_type"],
                            "amount_milli": int(row["amount_milli"]),
                            "balance_after_milli": int(row["balance_after_milli"]),
                            "reservation_id": row["reservation_id"],
                            "idempotency_key": row["idempotency_key"],
                            "metadata": metadata,
                            "created_at": row["created_at"],
                        }
                    )

                next_cursor = (
                    str(offset + len(items)) if len(items) >= int(limit) else None
                )
                return {"items": items, "next_cursor": next_cursor}
            finally:
                conn.close()

    def grant(
        self,
        workspace_id: str,
        user_id: str,
        *,
        amount_milli: int,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if amount_milli <= 0:
            raise ValueError("grant amount must be > 0")

        with self._lock:
            conn = self._connect()
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT entry_id, balance_after_milli
                        FROM credit_ledger
                        WHERE workspace_id = ? AND user_id = ? AND event_type = 'grant' AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (workspace_id, user_id, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        balance = self.get_balance(workspace_id, user_id)
                        return {
                            "entry_id": existing["entry_id"],
                            "idempotent": True,
                            "balance_milli": balance["balance_milli"],
                        }

                row = self._get_account_row(conn, workspace_id, user_id)
                next_balance = int(row["balance_milli"]) + int(amount_milli)
                now = _utc_now_iso()
                conn.execute(
                    """
                    UPDATE credit_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ?
                    """,
                    (next_balance, now, workspace_id, user_id),
                )
                entry_id = self._insert_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    event_type="grant",
                    amount_milli=amount_milli,
                    balance_after_milli=next_balance,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "entry_id": entry_id,
                    "idempotent": False,
                    "balance_milli": next_balance,
                }
            finally:
                conn.close()

    def reserve(
        self,
        workspace_id: str,
        user_id: str,
        *,
        amount_milli: int,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
        ttl_seconds: Optional[int],
    ) -> Dict[str, Any]:
        if amount_milli <= 0:
            raise ValueError("reservation amount must be > 0")

        with self._lock:
            conn = self._connect()
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT reservation_id, status, amount_milli, created_at, updated_at, expires_at
                        FROM credit_reservations
                        WHERE workspace_id = ? AND user_id = ? AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (workspace_id, user_id, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        balance = self._get_account_row(conn, workspace_id, user_id)
                        return {
                            "reservation_id": existing["reservation_id"],
                            "status": existing["status"],
                            "amount_milli": int(existing["amount_milli"]),
                            "created_at": existing["created_at"],
                            "updated_at": existing["updated_at"],
                            "expires_at": existing["expires_at"],
                            "balance_milli": int(balance["balance_milli"]),
                            "idempotent": True,
                        }

                account = self._get_account_row(conn, workspace_id, user_id)
                current_balance = int(account["balance_milli"])
                if current_balance < int(amount_milli):
                    raise ValueError("insufficient_credits")

                next_balance = current_balance - int(amount_milli)
                now = datetime.now(timezone.utc)
                now_iso = now.isoformat()
                expires_at = (
                    (now + timedelta(seconds=int(ttl_seconds))).isoformat()
                    if ttl_seconds and int(ttl_seconds) > 0
                    else None
                )
                reservation_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO credit_reservations (
                      reservation_id, workspace_id, user_id, amount_milli, status,
                      idempotency_key, metadata_json, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        workspace_id,
                        user_id,
                        int(amount_milli),
                        idempotency_key,
                        json.dumps(metadata or {}, ensure_ascii=True),
                        now_iso,
                        now_iso,
                        expires_at,
                    ),
                )
                conn.execute(
                    """
                    UPDATE credit_accounts
                    SET balance_milli = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ?
                    """,
                    (next_balance, now_iso, workspace_id, user_id),
                )
                self._insert_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    event_type="reserve",
                    amount_milli=-int(amount_milli),
                    balance_after_milli=next_balance,
                    reservation_id=reservation_id,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()
                return {
                    "reservation_id": reservation_id,
                    "status": "reserved",
                    "amount_milli": int(amount_milli),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "expires_at": expires_at,
                    "balance_milli": next_balance,
                    "idempotent": False,
                }
            finally:
                conn.close()

    def _update_reservation_status(
        self,
        reservation_id: str,
        *,
        next_status: str,
        event_type: str,
        credit_delta_milli: int,
        metadata: Optional[Dict[str, Any]],
        idempotency_key: Optional[str],
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT reservation_id, workspace_id, user_id, amount_milli, status, created_at, updated_at, expires_at
                    FROM credit_reservations
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
                amount_milli = int(row["amount_milli"])

                if current_status == next_status:
                    account = self._get_account_row(conn, workspace_id, user_id)
                    return {
                        "reservation_id": reservation_id,
                        "workspace_id": workspace_id,
                        "user_id": user_id,
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

                now = _utc_now_iso()
                conn.execute(
                    """
                    UPDATE credit_reservations
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

                account = self._get_account_row(conn, workspace_id, user_id)
                next_balance = int(account["balance_milli"]) + int(credit_delta_milli)

                if credit_delta_milli != 0:
                    conn.execute(
                        """
                        UPDATE credit_accounts
                        SET balance_milli = ?, updated_at = ?
                        WHERE workspace_id = ? AND user_id = ?
                        """,
                        (next_balance, now, workspace_id, user_id),
                    )

                self._insert_ledger(
                    conn,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    event_type=event_type,
                    amount_milli=int(credit_delta_milli),
                    balance_after_milli=next_balance,
                    reservation_id=reservation_id,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                conn.commit()

                return {
                    "reservation_id": reservation_id,
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "status": next_status,
                    "amount_milli": amount_milli,
                    "created_at": row["created_at"],
                    "updated_at": now,
                    "expires_at": row["expires_at"],
                    "balance_milli": next_balance,
                    "idempotent": False,
                }
            finally:
                conn.close()

    def commit(
        self,
        reservation_id: str,
        *,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self._update_reservation_status(
            reservation_id,
            next_status="committed",
            event_type="commit",
            credit_delta_milli=0,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def release(
        self,
        reservation_id: str,
        *,
        idempotency_key: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT amount_milli FROM credit_reservations WHERE reservation_id = ? LIMIT 1",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    raise KeyError("reservation_not_found")
                amount_milli = int(row["amount_milli"])
            finally:
                conn.close()

        return self._update_reservation_status(
            reservation_id,
            next_status="released",
            event_type="release",
            credit_delta_milli=amount_milli,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )


_store: Optional[CreditsStore] = None
_store_lock = threading.Lock()


def _get_store() -> CreditsStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            path = os.getenv("BR_CREDITS_DB") or str(
                get_data_root() / "orchestrator" / "credits.sqlite"
            )
            _store = CreditsStore(path)
    return _store


def _resolve_identity(
    request: Request, workspace_id: Optional[str], user_id: Optional[str]
) -> Tuple[str, str]:
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
    reservation_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class CreditsLedgerResponse(BaseModel):
    items: List[CreditsLedgerEntryResponse]
    next_cursor: Optional[str] = None


class CreditsGrantRequest(BaseModel):
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    amount: float = Field(..., gt=0)
    idempotency_key: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreditsReservationRequest(BaseModel):
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    amount: float = Field(..., gt=0)
    idempotency_key: Optional[str] = None
    ttl_seconds: Optional[int] = Field(default=1800, ge=60, le=86400)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreditsReservationActionRequest(BaseModel):
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    expires_at: Optional[str] = None
    idempotent: bool = False


class ApiUsdMonthlyTopUpRequest(BaseModel):
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    allowance: float = Field(default=10.0, gt=0)
    cap: float = Field(default=10.0, gt=0)


class ApiUsdDebitRequest(BaseModel):
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    amount: float = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    entry_id: Optional[str] = None
    idempotent: bool = False


class BucketCreditsReservationResponse(CreditsReservationResponse):
    bucket: str
    currency: str


def _to_balance_response(payload: Dict[str, Any]) -> CreditsBalanceResponse:
    return CreditsBalanceResponse(
        workspace_id=str(payload["workspace_id"]),
        user_id=str(payload["user_id"]),
        balance=_from_milli_credits(int(payload["balance_milli"])),
        balance_milli=int(payload["balance_milli"]),
        updated_at=str(payload["updated_at"]),
    )


def _to_bucket_balance_response(
    payload: Dict[str, Any],
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


def _to_reservation_response(payload: Dict[str, Any]) -> CreditsReservationResponse:
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
    payload: Dict[str, Any],
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


def _initial_workflow_credit_amount_milli() -> int:
    raw = os.getenv("BR_INITIAL_WORKFLOW_CREDITS")
    if raw is None or not raw.strip():
        return INITIAL_WORKFLOW_ALLOWANCE_MILLI_CREDITS
    try:
        return _to_milli_credits(float(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid BR_INITIAL_WORKFLOW_CREDITS=%r; using default", raw)
        return INITIAL_WORKFLOW_ALLOWANCE_MILLI_CREDITS


def _initial_api_usd_credit_amount_milli() -> int:
    raw = os.getenv("BR_INITIAL_API_USD_CREDITS")
    if raw is None or not raw.strip():
        return INITIAL_API_USD_ALLOWANCE_MILLI_USD
    try:
        return _to_milli_credits(float(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid BR_INITIAL_API_USD_CREDITS=%r; using default", raw)
        return INITIAL_API_USD_ALLOWANCE_MILLI_USD


def grant_initial_workflow_credits_for_account(
    workspace_id: str,
    user_id: str,
    *,
    source: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ws = (workspace_id or "").strip() or "default"
    user = (user_id or "").strip()
    if not user:
        raise ValueError("user_id is required")

    amount_milli = _initial_workflow_credit_amount_milli()
    if amount_milli <= 0:
        return {
            "skipped": True,
            "reason": "initial_workflow_credits_disabled",
            "workspace_id": ws,
            "user_id": user,
            "amount_milli": 0,
        }

    grant_metadata = {
        "source": source,
        "bucket": WORKFLOW_RUNTIME_BUCKET,
        "currency": WORKFLOW_RUNTIME_CURRENCY,
    }
    grant_metadata.update(metadata or {})
    return _get_store().grant(
        ws,
        user,
        amount_milli=amount_milli,
        idempotency_key="initial-workflow-credits:v1",
        metadata=grant_metadata,
    )


def grant_initial_api_usd_credits_for_account(
    workspace_id: str,
    user_id: str,
    *,
    source: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ws = (workspace_id or "").strip() or "default"
    user = (user_id or "").strip()
    if not user:
        raise ValueError("user_id is required")

    amount_milli = _initial_api_usd_credit_amount_milli()
    if amount_milli <= 0:
        return {
            "skipped": True,
            "reason": "initial_api_usd_credits_disabled",
            "workspace_id": ws,
            "user_id": user,
            "amount_milli": 0,
            "bucket": API_USD_BUCKET,
            "currency": API_USD_CURRENCY,
        }

    grant_metadata = {
        "source": source,
        "bucket": API_USD_BUCKET,
        "currency": API_USD_CURRENCY,
    }
    grant_metadata.update(metadata or {})
    return _get_store().bucket_grant(
        ws,
        user,
        bucket=API_USD_BUCKET,
        currency=API_USD_CURRENCY,
        amount_milli=amount_milli,
        idempotency_key="initial-api-usd-credits:v1",
        metadata=grant_metadata,
    )


def grant_initial_account_credits_for_account(
    workspace_id: str,
    user_id: str,
    *,
    source: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "workspace_id": (workspace_id or "").strip() or "default",
        "user_id": (user_id or "").strip(),
        "workflow_runtime": grant_initial_workflow_credits_for_account(
            workspace_id,
            user_id,
            source=source,
            metadata=metadata,
        ),
        "api_fee_usd": grant_initial_api_usd_credits_for_account(
            workspace_id,
            user_id,
            source=source,
            metadata=metadata,
        ),
    }


@router.get("/balance", response_model=CreditsBalanceResponse)
async def credits_balance(
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
):
    ws, user = _resolve_identity(request, workspace_id, user_id)
    payload = _get_store().get_balance(ws, user)
    return _to_balance_response(payload)


@router.get("/ledger", response_model=CreditsLedgerResponse)
async def credits_ledger(
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
):
    ws, user = _resolve_identity(request, workspace_id, user_id)
    payload = _get_store().list_ledger(ws, user, cursor=cursor, limit=limit)
    items: List[CreditsLedgerEntryResponse] = []
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
    workspace_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
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
