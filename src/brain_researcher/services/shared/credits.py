"""Shared credits store/runtime helpers.

This module owns the process-local SQLite credits store and internal account
credit grants. FastAPI endpoints live in ``services.orchestrator`` and import
this module; lower runtime layers import this module directly instead of the
orchestrator endpoint package.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_data_root

logger = logging.getLogger(__name__)

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
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
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
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
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
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        ttl_seconds: int | None,
    ) -> dict[str, Any]:
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
        final_amount_milli: int | None = None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
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
                normalized_final_amount_milli: int | None = None
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        final_amount_milli: int | None = None,
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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

    def get_balance(self, workspace_id: str, user_id: str) -> dict[str, Any]:
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
        self, workspace_id: str, user_id: str, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
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

                items: list[dict[str, Any]] = []
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        ttl_seconds: int | None,
    ) -> dict[str, Any]:
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
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
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


_store: CreditsStore | None = None
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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
