"""Signed POR token helpers (HMAC) for plan-of-record execution authorization.

The orchestrator issues a signed token when committing a Plan-of-Record (POR).
The agent verifies that token before executing /agent/run_plan.

Token format:
    por_v1.<payload_b64>.<sig_b64>

Where payload JSON includes:
    - plan_id (str)
    - version (int)
    - iat (int unix seconds)
    - exp (int unix seconds)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional


POR_TOKEN_PREFIX = "por_v1"


@dataclass(frozen=True)
class PorTokenClaims:
    plan_id: str
    version: int
    iat: int
    exp: int


def is_signed_por_token(token: str) -> bool:
    return isinstance(token, str) and token.startswith(f"{POR_TOKEN_PREFIX}.")


def get_por_token_secret() -> Optional[str]:
    return (
        os.getenv("BR_POR_TOKEN_SECRET")
        or os.getenv("POR_TOKEN_SECRET")
        or os.getenv("BRAIN_RESEARCHER_POR_TOKEN_SECRET")
    )


def por_token_ttl_seconds() -> int:
    raw = os.getenv("BR_POR_TOKEN_TTL_SECONDS")
    if raw is None:
        return 30 * 24 * 60 * 60  # 30 days
    try:
        ttl = int(raw)
    except ValueError:
        return 30 * 24 * 60 * 60
    return max(60, ttl)


def por_token_enforced() -> bool:
    raw = os.getenv("BR_POR_TOKEN_ENFORCE")
    if raw is not None:
        return raw.lower() == "true"
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
    return env in {"prod", "production"}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(secret: str, payload_b64: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def issue_por_token(
    *,
    plan_id: str,
    version: int,
    secret: str,
    ttl_seconds: int,
    now: Optional[int] = None,
) -> str:
    issued_at = int(time.time() if now is None else now)
    exp = issued_at + max(60, int(ttl_seconds))
    payload = {"plan_id": plan_id, "version": int(version), "iat": issued_at, "exp": exp}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig_b64 = _sign(secret, payload_b64)
    return f"{POR_TOKEN_PREFIX}.{payload_b64}.{sig_b64}"


def verify_por_token(
    *,
    token: str,
    plan_id: str,
    version: int,
    secret: str,
    now: Optional[int] = None,
) -> PorTokenClaims:
    if not is_signed_por_token(token):
        raise ValueError("POR token is not signed (expected por_v1.*)")

    parts = token.split(".", 2)
    if len(parts) != 3:
        raise ValueError("POR token has invalid format")
    _, payload_b64, sig_b64 = parts

    expected_sig = _sign(secret, payload_b64)
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise ValueError("POR token signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("POR token payload is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("POR token payload is not an object")

    token_plan_id = payload.get("plan_id")
    token_version = payload.get("version")
    iat = payload.get("iat")
    exp = payload.get("exp")

    if token_plan_id != plan_id or int(token_version) != int(version):
        raise ValueError("POR token does not match plan_id/version")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise ValueError("POR token timestamps invalid")

    now_ts = int(time.time() if now is None else now)
    if exp < now_ts:
        raise ValueError("POR token expired")

    return PorTokenClaims(plan_id=str(token_plan_id), version=int(token_version), iat=iat, exp=exp)


def issue_por_token_from_env(*, plan_id: str, version: int) -> str:
    secret = get_por_token_secret()
    if not secret:
        if por_token_enforced():
            raise RuntimeError("BR_POR_TOKEN_SECRET is required when POR tokens are enforced")
        # Fallback: unsigned token (dev only)
        return _b64url_encode(os.urandom(18))
    return issue_por_token(
        plan_id=plan_id,
        version=version,
        secret=secret,
        ttl_seconds=por_token_ttl_seconds(),
    )


def verify_por_token_from_env(*, token: str, plan_id: str, version: int) -> Optional[PorTokenClaims]:
    secret = get_por_token_secret()
    if not secret:
        if por_token_enforced():
            raise RuntimeError("BR_POR_TOKEN_SECRET is required when POR tokens are enforced")
        return None
    return verify_por_token(token=token, plan_id=plan_id, version=version, secret=secret)


__all__ = [
    "POR_TOKEN_PREFIX",
    "PorTokenClaims",
    "get_por_token_secret",
    "is_signed_por_token",
    "issue_por_token",
    "issue_por_token_from_env",
    "por_token_enforced",
    "por_token_ttl_seconds",
    "verify_por_token",
    "verify_por_token_from_env",
]

