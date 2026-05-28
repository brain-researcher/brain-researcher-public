"""Redis-backed MCP token store for orchestrator auth endpoints."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from brain_researcher.services.shared.mcp_tokens import (
    compute_digest,
    format_token,
    isoformat_z,
    load_pepper,
    parse_iso_datetime,
    parse_token,
    redis_token_key,
    redis_user_key,
    utc_now,
)

logger = logging.getLogger(__name__)

TOKEN_PEPPER = load_pepper(os.getenv("BR_MCP_TOKEN_PEPPER"))
TOKEN_PEPPER_VERSION = (
    os.getenv("BR_MCP_TOKEN_PEPPER_VERSION") or "v1"
).strip() or "v1"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LAST_USED_WRITE_INTERVAL_SECONDS = max(
    10, int(os.getenv("BR_MCP_LAST_USED_WRITE_INTERVAL_SECONDS", "300"))
)

_redis_client = None
_redis_last_connect_attempt = 0.0
_redis_connect_error_logged = False


def _redis_retry_interval_seconds() -> float:
    raw = os.getenv("BR_MCP_TOKEN_REDIS_RETRY_SECONDS", "5")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 5.0


async def _mark_redis_unavailable(exc: Exception, context: str) -> None:
    global _redis_client, _redis_connect_error_logged, _redis_last_connect_attempt
    client = _redis_client
    _redis_client = None
    _redis_last_connect_attempt = 0.0
    _redis_connect_error_logged = True
    logger.warning("McpTokenStore: Redis %s (%s)", context, exc)
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def _get_redis():
    global _redis_client, _redis_connect_error_logged, _redis_last_connect_attempt
    if _redis_client is not None:
        return _redis_client

    now = time.monotonic()
    if now - _redis_last_connect_attempt < _redis_retry_interval_seconds():
        return None
    _redis_last_connect_attempt = now

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        await client.ping()
        _redis_client = client
        _redis_connect_error_logged = False
        logger.info("McpTokenStore: Redis connected at %s", REDIS_URL)
    except Exception as exc:
        if not _redis_connect_error_logged:
            logger.warning("McpTokenStore: Redis unavailable (%s)", exc)
            _redis_connect_error_logged = True
        _redis_client = None
    return _redis_client


def _require_token_pepper() -> bytes:
    if TOKEN_PEPPER is None:
        raise RuntimeError("BR_MCP_TOKEN_PEPPER is required for MCP token issuance")
    return TOKEN_PEPPER


def _to_bool(raw: Any, default: bool = True) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _sanitize_user_token_prefix(user_id: str) -> str:
    cleaned = "".join(ch for ch in user_id.lower() if ch.isalnum() or ch in {"_", "-"})
    return (cleaned[:24] or "user").strip("-_") or "user"


def _new_kid(user_id: str) -> str:
    base = _sanitize_user_token_prefix(user_id)
    ts = int(time.time())
    suffix = secrets.token_hex(4)
    return f"{base}_{ts}_{suffix}"


def _to_public_record(record: dict[str, Any]) -> dict[str, Any]:
    kid = str(record.get("kid") or "")
    return {
        "kid": kid,
        "user_id": str(record.get("user_id") or ""),
        "enabled": _to_bool(record.get("enabled"), default=True),
        "created_at": record.get("created_at"),
        "last_used_at": record.get("last_used_at"),
        "revoked_at": record.get("revoked_at"),
        "expires_at": record.get("expires_at"),
        "pepper_version": record.get("pepper_version"),
        "token_preview": f"brk_{kid}.<hidden>" if kid else None,
    }


@dataclass(frozen=True)
class TokenVerification:
    user_id: str
    kid: str
    last_used_at: str | None


class McpTokenStore:
    async def _require_redis(self):
        redis_client = await _get_redis()
        if redis_client is None:
            raise RuntimeError("Redis is unavailable for MCP token operations")
        return redis_client

    async def list_user_tokens(self, user_id: str) -> list[dict[str, Any]]:
        redis_client = await self._require_redis()
        user_key = redis_user_key(user_id)
        kid = await redis_client.get(user_key)
        if not kid:
            return []

        record = await redis_client.hgetall(redis_token_key(kid))
        if not record:
            await redis_client.delete(user_key)
            return []

        return [_to_public_record(record)]

    async def create_or_rotate_token(
        self,
        user_id: str,
        *,
        expires_at: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        redis_client = await self._require_redis()
        pepper = _require_token_pepper()
        now = utc_now()
        expires = parse_iso_datetime(expires_at) if expires_at else None
        if expires is not None and expires <= now:
            raise ValueError("expires_at must be in the future")

        secret = secrets.token_urlsafe(48)
        kid = _new_kid(user_id)
        digest = compute_digest(pepper, secret)

        token_key = redis_token_key(kid)
        user_key = redis_user_key(user_id)
        created_at = isoformat_z(now)
        payload = {
            "kid": kid,
            "user_id": user_id,
            "digest": digest,
            "enabled": "1",
            "created_at": created_at,
            "last_used_at": "",
            "revoked_at": "",
            "expires_at": isoformat_z(expires) if expires else "",
            "pepper_version": TOKEN_PEPPER_VERSION,
        }

        previous_kid = await redis_client.get(user_key)
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.hset(token_key, mapping=payload)
            pipe.set(user_key, kid)
            await pipe.execute()

        if previous_kid and previous_kid != kid:
            previous_key = redis_token_key(previous_kid)
            await redis_client.hset(
                previous_key,
                mapping={"enabled": "0", "revoked_at": created_at},
            )

        token_value = format_token(kid, secret)
        return token_value, _to_public_record(payload)

    async def revoke_user_token(self, user_id: str, kid: str) -> bool:
        redis_client = await self._require_redis()
        token_key = redis_token_key(kid)
        record = await redis_client.hgetall(token_key)
        if not record:
            return False
        if str(record.get("user_id") or "") != user_id:
            return False

        now_iso = isoformat_z(utc_now())
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.hset(token_key, mapping={"enabled": "0", "revoked_at": now_iso})
            pipe.delete(redis_user_key(user_id))
            await pipe.execute()
        return True

    async def verify_token(
        self,
        token: str,
        *,
        update_last_used: bool = True,
    ) -> TokenVerification | None:
        parsed = parse_token(token)
        if not parsed or TOKEN_PEPPER is None:
            return None
        kid, secret = parsed

        redis_client = await _get_redis()
        if redis_client is None:
            return None

        record = await redis_client.hgetall(redis_token_key(kid))
        if not record:
            return None

        if not _to_bool(record.get("enabled"), default=True):
            return None

        user_id = str(record.get("user_id") or "").strip()
        if not user_id:
            return None

        expires_at = parse_iso_datetime(record.get("expires_at"))
        if expires_at is not None and utc_now() >= expires_at:
            return None

        pepper_version = str(record.get("pepper_version") or "").strip()
        if pepper_version and pepper_version != TOKEN_PEPPER_VERSION:
            return None

        digest = compute_digest(TOKEN_PEPPER, secret)
        if not hmac.compare_digest(
            digest,
            str(record.get("digest") or "").strip().lower(),
        ):
            return None

        last_used_at = str(record.get("last_used_at") or "").strip() or None
        if update_last_used:
            now = utc_now()
            should_write = True
            if last_used_at:
                try:
                    last_dt = parse_iso_datetime(last_used_at)
                except ValueError:
                    last_dt = None
                if (
                    last_dt is not None
                    and now - last_dt < timedelta(seconds=LAST_USED_WRITE_INTERVAL_SECONDS)
                ):
                    should_write = False
            if should_write:
                last_used_at = isoformat_z(now)
                await redis_client.hset(
                    redis_token_key(kid),
                    mapping={"last_used_at": last_used_at},
                )

        return TokenVerification(user_id=user_id, kid=kid, last_used_at=last_used_at)

    async def status(self, user_id: str) -> dict[str, Any]:
        redis_client = await _get_redis()
        if redis_client is None:
            return {
                "backend": "redis",
                "redis_available": False,
                "pepper_configured": TOKEN_PEPPER is not None,
                "has_active_token": False,
            }
        kid = await redis_client.get(redis_user_key(user_id))
        return {
            "backend": "redis",
            "redis_available": True,
            "pepper_configured": TOKEN_PEPPER is not None,
            "has_active_token": bool(kid),
        }


mcp_token_store = McpTokenStore()
