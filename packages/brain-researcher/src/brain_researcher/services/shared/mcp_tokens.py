"""Shared helpers for Brain Researcher MCP API keys."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

UTC = timezone.utc

TOKEN_PREFIX = "brk_"


def token_redis_prefix() -> str:
    raw = (os.getenv("BR_MCP_TOKEN_REDIS_PREFIX") or "mcp_token").strip()
    return raw or "mcp_token"


def redis_token_key(kid: str) -> str:
    return f"{token_redis_prefix()}:kid:{kid}"


def redis_user_key(user_id: str) -> str:
    return f"{token_redis_prefix()}:user:{user_id}"


def load_pepper(raw: str | None) -> bytes | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("BR_MCP_TOKEN_PEPPER must be valid hex") from exc


def compute_digest(pepper: bytes, secret: str) -> str:
    return hmac.new(pepper, secret.encode("utf-8"), hashlib.sha256).hexdigest()


def format_token(kid: str, secret: str) -> str:
    return f"{TOKEN_PREFIX}{kid}.{secret}"


def parse_token(token: str | None) -> tuple[str, str] | None:
    value = (token or "").strip()
    if not value or len(value) > 1024:
        return None
    if not value.startswith(TOKEN_PREFIX):
        return None

    body = value[len(TOKEN_PREFIX) :]
    if "." not in body:
        return None
    key_id, secret = body.split(".", 1)
    key_id = key_id.strip()
    secret = secret.strip()
    if not key_id or not secret:
        return None
    if len(key_id) > 128 or len(secret) > 512:
        return None
    return key_id, secret


def parse_iso_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp value: {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_z(value: datetime) -> str:
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")
