"""Signed share token helpers (HMAC) for analysis bundle sharing.

Token format:
    share_v1.<payload_b64>.<sig_b64>

Payload JSON includes:
    - analysis_id (str)
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
from typing import Optional


SHARE_TOKEN_PREFIX = "share_v1"


@dataclass(frozen=True)
class ShareTokenClaims:
    analysis_id: str
    iat: int
    exp: int


def is_signed_share_token(token: str) -> bool:
    return isinstance(token, str) and token.startswith(f"{SHARE_TOKEN_PREFIX}.")


def share_token_enforced() -> bool:
    raw = os.getenv("BR_SHARE_TOKEN_ENFORCE")
    if raw is not None:
        return raw.lower() == "true"
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
    return env in {"prod", "production"}


def get_share_token_secret() -> Optional[str]:
    secret = (
        os.getenv("BR_SHARE_TOKEN_SECRET")
        or os.getenv("SHARE_TOKEN_SECRET")
        or os.getenv("BRAIN_RESEARCHER_SHARE_TOKEN_SECRET")
        or os.getenv("JWT_SECRET_KEY")
        or os.getenv("JWT_SECRET")
    )
    if secret:
        return secret
    if share_token_enforced():
        return None
    # Dev/test fallback only.
    return "br-insecure-test-secret"


def share_token_ttl_seconds() -> int:
    raw = os.getenv("BR_SHARE_TOKEN_TTL_SECONDS")
    if raw is None:
        return 7 * 24 * 60 * 60  # 7 days
    try:
        ttl = int(raw)
    except ValueError:
        return 7 * 24 * 60 * 60
    return max(60, ttl)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(secret: str, payload_b64: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64url_encode(digest)


def issue_share_token(
    *,
    analysis_id: str,
    secret: str,
    ttl_seconds: int,
    now: Optional[int] = None,
) -> tuple[str, ShareTokenClaims]:
    issued_at = int(time.time() if now is None else now)
    exp = issued_at + max(60, int(ttl_seconds))
    payload = {"analysis_id": str(analysis_id), "iat": issued_at, "exp": exp}
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    sig_b64 = _sign(secret, payload_b64)
    token = f"{SHARE_TOKEN_PREFIX}.{payload_b64}.{sig_b64}"
    return token, ShareTokenClaims(analysis_id=str(analysis_id), iat=issued_at, exp=exp)


def verify_share_token(
    *,
    token: str,
    secret: str,
    now: Optional[int] = None,
) -> ShareTokenClaims:
    if not is_signed_share_token(token):
        raise ValueError("Share token is not signed (expected share_v1.*)")

    parts = token.split(".", 2)
    if len(parts) != 3:
        raise ValueError("Share token has invalid format")
    _, payload_b64, sig_b64 = parts

    expected_sig = _sign(secret, payload_b64)
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise ValueError("Share token signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Share token payload is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Share token payload is not an object")

    analysis_id = payload.get("analysis_id")
    iat = payload.get("iat")
    exp = payload.get("exp")

    if not isinstance(analysis_id, str) or not analysis_id:
        raise ValueError("Share token missing analysis_id")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise ValueError("Share token timestamps invalid")

    now_ts = int(time.time() if now is None else now)
    if exp < now_ts:
        raise ValueError("Share token expired")

    return ShareTokenClaims(analysis_id=analysis_id, iat=iat, exp=exp)


def issue_share_token_from_env(
    *,
    analysis_id: str,
    ttl_seconds: Optional[int] = None,
    now: Optional[int] = None,
) -> tuple[str, ShareTokenClaims]:
    secret = get_share_token_secret()
    if not secret:
        raise RuntimeError(
            "BR_SHARE_TOKEN_SECRET is required when share tokens are enforced"
        )
    return issue_share_token(
        analysis_id=analysis_id,
        secret=secret,
        ttl_seconds=share_token_ttl_seconds() if ttl_seconds is None else ttl_seconds,
        now=now,
    )


def verify_share_token_from_env(
    *,
    token: str,
    now: Optional[int] = None,
) -> ShareTokenClaims:
    secret = get_share_token_secret()
    if not secret:
        raise RuntimeError(
            "BR_SHARE_TOKEN_SECRET is required when share tokens are enforced"
        )
    return verify_share_token(token=token, secret=secret, now=now)


__all__ = [
    "SHARE_TOKEN_PREFIX",
    "ShareTokenClaims",
    "get_share_token_secret",
    "is_signed_share_token",
    "issue_share_token",
    "issue_share_token_from_env",
    "share_token_enforced",
    "share_token_ttl_seconds",
    "verify_share_token",
    "verify_share_token_from_env",
]
