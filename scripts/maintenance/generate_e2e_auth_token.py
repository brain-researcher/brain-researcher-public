#!/usr/bin/env python3
"""Generate a short-lived HS256 JWT for Playwright e2e tests.

This token is intended for local or maintainer-run e2e checks where we do not
want to depend on interactive NextAuth sign-in flows. The Web UI's
`/api/analyses*` endpoints require auth and validate JWTs using
`JWT_SECRET_KEY`/`NEXTAUTH_SECRET` and (optionally) issuer/audience constraints.

Env vars:
  - JWT_SECRET_KEY or NEXTAUTH_SECRET (required)
  - E2E_JWT_SUBJECT (default: e2e-user)
  - E2E_JWT_EMAIL (default: e2e-user@example.com)
  - E2E_JWT_ROLE (default: dev)
  - E2E_JWT_ISSUER (optional)
  - E2E_JWT_AUDIENCE (optional; string or comma-separated)
  - E2E_JWT_TTL_SECONDS (default: 3600; clamped to [300, 86400])
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _parse_audience(raw: str | None) -> str | list[str] | None:
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return parts


def main() -> None:
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("NEXTAUTH_SECRET")
    if not secret:
        raise SystemExit("JWT_SECRET_KEY or NEXTAUTH_SECRET must be set")

    now = int(time.time())
    ttl = int(os.getenv("E2E_JWT_TTL_SECONDS", "3600"))
    ttl = max(300, min(ttl, 86_400))

    subject = os.getenv("E2E_JWT_SUBJECT", "e2e-user")
    email = os.getenv("E2E_JWT_EMAIL", "e2e-user@example.com")
    role = os.getenv("E2E_JWT_ROLE", "dev")
    issuer = os.getenv("E2E_JWT_ISSUER")
    audience = _parse_audience(os.getenv("E2E_JWT_AUDIENCE"))

    payload: dict[str, object] = {
        "sub": subject,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }
    if issuer:
        payload["iss"] = issuer
    if audience is not None:
        payload["aud"] = audience

    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    msg = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()

    token = f"{header_b64}.{payload_b64}.{_b64url(signature)}"
    print(token)


if __name__ == "__main__":
    main()
