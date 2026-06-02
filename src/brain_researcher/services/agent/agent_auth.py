"""Lightweight auth helper for UI-facing Agent endpoints.

Design goals:
- Trust Next.js/NextAuth as primary gate, but enforce a minimal check here
  (defense-in-depth) and extract a user_id for thread/run ownership.
- Dev-friendly: allow opt-out with env flag or X-Debug-User header.
- Real JWT verification when JWT_SECRET_KEY is configured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Request

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    """Authenticated user information extracted from JWT or debug headers."""

    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    provider: Optional[str] = None
    tenant_id: str = "default"  # Multi-tenancy foundation


class AuthError(Exception):
    """Raised when authentication fails."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


_JWKS_CACHE_LOCK = threading.Lock()
_JWKS_CACHE_FETCHED_AT = 0.0
_JWKS_CACHE_KEYS_BY_KID: dict[str, dict[str, Any]] = {}
_JWKS_CACHE_TTL_SECONDS = int(os.getenv("BR_AUTH_JWKS_CACHE_TTL_SECONDS", "300"))


def _parse_csv_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_supabase_url() -> Optional[str]:
    return (
        os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        or os.getenv("SUPABASE_PROJECT_URL")
    )


def _resolve_supabase_anon_key() -> Optional[str]:
    return (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_DEFAULT_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_TOKEN")
    )


def _resolve_jwks_url() -> Optional[str]:
    explicit = (
        os.getenv("BR_AGENT_JWKS_URL")
        or os.getenv("BR_AUTH_JWKS_URL")
        or os.getenv("SUPABASE_JWKS_URL")
        or os.getenv("BR_JWKS_URL")
    )
    if explicit:
        return explicit
    supabase_url = _resolve_supabase_url()
    if supabase_url:
        return f"{supabase_url.rstrip('/')}/auth/v1/keys"
    return None


def _resolve_jwt_issuer() -> Optional[str]:
    explicit = (
        os.getenv("BR_AGENT_JWT_ISSUER")
        or os.getenv("BR_AUTH_JWT_ISSUER")
        or os.getenv("SUPABASE_JWT_ISSUER")
        or os.getenv("BR_JWT_ISSUER")
    )
    if explicit:
        return explicit
    supabase_url = _resolve_supabase_url()
    if supabase_url:
        return f"{supabase_url.rstrip('/')}/auth/v1"
    return None


def _resolve_jwt_audiences() -> list[str]:
    raw = (
        os.getenv("BR_AGENT_JWT_AUDIENCE")
        or os.getenv("BR_AUTH_JWT_AUDIENCE")
        or os.getenv("SUPABASE_JWT_AUDIENCE")
        or os.getenv("BR_JWT_AUDIENCE")
    )
    return _parse_csv_list(raw)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _get_pat_allowlist() -> tuple[set[str], set[str]]:
    tokens = set(_parse_csv_list(os.getenv("BR_PAT_TOKENS")))
    hashes = set(_parse_csv_list(os.getenv("BR_PAT_TOKEN_HASHES")))
    return tokens, hashes


def is_pat_token(token: str) -> bool:
    if not token:
        return False
    tokens, hashes = _get_pat_allowlist()
    if token in tokens:
        return True
    if hashes and _hash_token(token) in hashes:
        return True
    return False


def issue_pat_jwt(subject: str, ttl_seconds: int = 3600) -> str:
    """Issue a short-lived JWT for PAT exchange."""
    from jose import jwt as jose_jwt

    secret = get_jwt_secret()
    if not secret:
        raise AuthError(
            "missing_jwt_secret", "JWT_SECRET_KEY is required for PAT exchange"
        )

    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + int(ttl_seconds),
        "provider": "pat",
        "role": "service",
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


def pat_subject_from_token(token: str) -> str:
    return f"pat:{_hash_token(token)[:12]}"


def _fetch_jwks_keys_by_kid(jwks_url: str) -> dict[str, dict[str, Any]]:
    import urllib.error
    import urllib.request

    anon_key = _resolve_supabase_anon_key()

    candidates = [jwks_url]
    if jwks_url.rstrip("/").endswith("/auth/v1/keys"):
        base = jwks_url.rstrip("/")[: -len("/auth/v1/keys")]
        candidates.insert(0, f"{base}/auth/v1/.well-known/jwks.json")

    last_error: Exception | None = None
    body: bytes | None = None
    for candidate in candidates:
        request = urllib.request.Request(candidate, method="GET")
        if anon_key:
            request.add_header("apikey", anon_key)
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:  # nosec B310
                body = resp.read()
                break
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            last_error = exc
            continue

    if body is None:
        raise AuthError(
            "jwks_fetch_failed",
            f"Unable to fetch JWKS from {jwks_url}: {last_error}",
        )
    data = json.loads(body.decode("utf-8"))
    keys = data.get("keys")
    if not isinstance(keys, list):
        raise AuthError("jwks_missing_keys", "JWKS payload missing keys list")

    keys_by_kid: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(keys):
        if not isinstance(item, dict):
            continue
        kid = str(item.get("kid") or "").strip() or f"__idx_{i}"
        keys_by_kid[kid] = item
    return keys_by_kid


def _get_cached_jwks_keys_by_kid(jwks_url: str) -> dict[str, dict[str, Any]]:
    global _JWKS_CACHE_FETCHED_AT, _JWKS_CACHE_KEYS_BY_KID
    now = time.time()
    with _JWKS_CACHE_LOCK:
        if _JWKS_CACHE_KEYS_BY_KID and now - _JWKS_CACHE_FETCHED_AT < max(
            1, _JWKS_CACHE_TTL_SECONDS
        ):
            return _JWKS_CACHE_KEYS_BY_KID
        _JWKS_CACHE_KEYS_BY_KID = _fetch_jwks_keys_by_kid(jwks_url)
        _JWKS_CACHE_FETCHED_AT = now
        return _JWKS_CACHE_KEYS_BY_KID


def _extract_bearer_token(req: Request) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    auth = req.headers.get("Authorization") or req.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def _extract_cookie_token(req: Request) -> Optional[str]:
    """Extract JWT from NextAuth session cookies.

    NextAuth (JWT strategy) stores the signed token in either
    - `next-auth.session-token` (dev/http)
    - `__Secure-next-auth.session-token` (prod/https)
    """

    # Also support Supabase access token mirrored by the web UI.
    cookie_names = [
        "next-auth.session-token",
        "__Secure-next-auth.session-token",
        "br_access_token",
    ]
    for name in cookie_names:
        if name in req.cookies:
            return req.cookies.get(name)
    return None


def _is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _extract_workspace_id(req: Request) -> Optional[str]:
    raw = (
        req.headers.get("X-Workspace-Id")
        or req.headers.get("x-workspace-id")
        or req.headers.get("X-Workspace-ID")
        or req.cookies.get("br_workspace_id")
    )
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return str(uuid.UUID(raw))
    except Exception as exc:
        raise AuthError("invalid_workspace_id", f"Invalid workspace id: {raw}") from exc


def _allow_missing_workspace_id(user: CurrentUser) -> bool:
    """Allow missing workspace id for local/dev auth providers.

    In local credential-based flows (NextAuth credentials / internal dev users),
    workspace context may not be initialized yet. Keep production strict unless
    explicitly overridden.
    """
    if _is_truthy(os.getenv("BR_ALLOW_MISSING_WORKSPACE_ID")):
        return True

    node_env = str(os.getenv("NODE_ENV") or "").strip().lower()
    if node_env == "production":
        return False

    provider = str(user.provider or "").strip().lower()
    if provider in {"credentials", "nextauth", "internal", "orchestrator", "pat"}:
        return True

    role = str(user.role or "").strip().lower()
    return role == "dev"


def _supabase_preflight(
    workspace_id: str, required_role: str, token: str
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    supabase_url = _resolve_supabase_url()
    anon_key = _resolve_supabase_anon_key()
    if not supabase_url or not anon_key:
        raise AuthError(
            "missing_supabase_config",
            "SUPABASE_URL and SUPABASE_ANON_KEY are required for workspace enforcement",
        )

    url = f"{supabase_url.rstrip('/')}/rest/v1/rpc/br_preflight"
    payload = json.dumps(
        {"p_workspace_id": workspace_id, "p_required_role": required_role}
    ).encode("utf-8")

    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("apikey", anon_key)
    request.add_header("authorization", f"Bearer {token}")
    request.add_header("content-type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # nosec B310
            body = resp.read().decode("utf-8")
            data = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        status = getattr(exc, "code", None) or 500
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        if status in {401, 403}:
            raise AuthError(
                "workspace_forbidden",
                detail or "Workspace membership/role check failed",
            ) from exc
        raise AuthError(
            "workspace_preflight_failed",
            detail or f"Supabase preflight failed (HTTP {status})",
        ) from exc
    except urllib.error.URLError as exc:
        raise AuthError(
            "workspace_preflight_failed", "Unable to reach Supabase"
        ) from exc

    if isinstance(data, list):
        data = data[0] if data else {}

    if isinstance(data, dict):
        if data.get("ok") is True:
            return data
        if isinstance(data.get("role"), str) and data.get("role"):
            return data

    raise AuthError("workspace_forbidden", "Workspace membership/role check failed")


def _apply_workspace_context(
    req: Request, user: CurrentUser, token: Optional[str]
) -> CurrentUser:
    workspace_id = _extract_workspace_id(req)
    if workspace_id:
        user.tenant_id = workspace_id

    if not _is_truthy(os.getenv("BR_ENFORCE_WORKSPACE_MEMBERSHIP")):
        return user

    if not workspace_id:
        if _allow_missing_workspace_id(user):
            logger.debug(
                "Workspace membership enforcement enabled but workspace id missing; "
                "allowing in non-production for provider=%s role=%s",
                user.provider,
                user.role,
            )
            return user
        raise AuthError(
            "missing_workspace_id",
            "x-workspace-id header or br_workspace_id cookie is required",
        )

    required_role = (
        str(os.getenv("BR_WORKSPACE_REQUIRED_ROLE") or "member").strip().lower()
    )
    if not token:
        raise AuthError(
            "missing_bearer_token",
            "Authorization header required for workspace enforcement",
        )

    preflight = _supabase_preflight(workspace_id, required_role, token)

    role = preflight.get("role")
    if isinstance(role, str) and role:
        user.role = role

    user_id = preflight.get("user_id")
    if isinstance(user_id, str) and user_id:
        user.id = user_id

    return user


def _decode_jwt(
    token: str,
    secret: Optional[str],
    algorithms: Optional[list[str]] = None,
    *,
    jwks_url: Optional[str] = None,
    issuer: Optional[str] = None,
    audiences: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Decode and verify a JWT token.

    Args:
        token: The JWT token string
        secret: The secret key for HS* verification (optional for RS*)
        algorithms: Allowed algorithms (default: inferred)
        jwks_url: Remote JWKS URL for RS* verification
        issuer: Expected issuer (iss)
        audiences: Expected audiences (aud)

    Returns:
        Decoded token payload

    Raises:
        AuthError: If token is invalid, expired, or verification fails
    """
    from jose import ExpiredSignatureError, JWTError
    from jose import jwk as jose_jwk
    from jose import jwt as jose_jwt

    try:
        header = jose_jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError("decode_error", "Failed to read JWT header") from exc

    alg = str(header.get("alg") or "").upper()
    kid = str(header.get("kid") or "").strip() or None

    if not alg:
        raise AuthError("missing_jwt_alg", "JWT header missing alg")

    allowed = {a.upper() for a in (algorithms or [])}
    if not allowed:
        if jwks_url and secret:
            allowed = {"HS256", "RS256", "ES256"}
        elif jwks_url:
            allowed = {"RS256", "ES256"}
        else:
            allowed = {"HS256"}

    if alg not in allowed:
        raise AuthError("jwt_alg_not_allowed", f"JWT alg {alg} not allowed")

    key: str
    if alg.startswith("HS"):
        secrets = []
        if secret:
            secrets.append(secret)
        for candidate in get_jwt_secret_candidates():
            if candidate and candidate not in secrets:
                secrets.append(candidate)
        if not secrets:
            raise AuthError("missing_jwt_secret", "Missing JWT secret for HS* token")
        key = secrets[0]
    else:
        if not jwks_url:
            raise AuthError("missing_jwks_url", "Missing JWKS URL for RS* token")
        keys_by_kid = _get_cached_jwks_keys_by_kid(jwks_url)
        jwk_dict = keys_by_kid.get(kid or "")
        if jwk_dict is None:
            with _JWKS_CACHE_LOCK:
                global _JWKS_CACHE_FETCHED_AT, _JWKS_CACHE_KEYS_BY_KID
                _JWKS_CACHE_KEYS_BY_KID = {}
                _JWKS_CACHE_FETCHED_AT = 0.0
            keys_by_kid = _get_cached_jwks_keys_by_kid(jwks_url)
            jwk_dict = keys_by_kid.get(kid or "")
        if jwk_dict is None:
            raise AuthError("jwks_kid_not_found", "JWT kid not found in JWKS")
        key_obj = jose_jwk.construct(jwk_dict, alg)
        key = key_obj.to_pem().decode("utf-8")

    audience: str | list[str] | None
    if audiences and len(audiences) > 1:
        audience = audiences
    elif audiences and len(audiences) == 1:
        audience = audiences[0]
    else:
        audience = None

    options = {
        "verify_aud": bool(audiences),
        "verify_iss": bool(issuer),
    }

    # NextAuth HS* session tokens typically omit `iss`/`aud`. When we verify HS*
    # tokens with the shared secret, treat signature verification as sufficient,
    # even if Supabase env vars are present (which would otherwise force iss/aud).
    if alg.startswith("HS"):
        options["verify_aud"] = False
        options["verify_iss"] = False
        audience = None
        issuer = None

    if alg.startswith("HS"):
        last_invalid: JWTError | None = None
        for candidate_secret in secrets:
            try:
                payload = jose_jwt.decode(
                    token,
                    candidate_secret,
                    algorithms=[alg],
                    audience=audience,
                    issuer=issuer or None,
                    options=options,
                )
                return payload
            except ExpiredSignatureError as exc:
                raise AuthError("token_expired", "JWT token has expired") from exc
            except JWTError as exc:
                message = str(exc).lower()
                if "signature verification failed" in message:
                    last_invalid = exc
                    continue
                if "not enough segments" in message:
                    raise AuthError("decode_error", "Failed to decode JWT") from exc
                raise AuthError("invalid_token", f"Invalid JWT token: {exc}") from exc

        raise AuthError(
            "invalid_signature",
            "JWT signature verification failed",
        ) from last_invalid

    try:
        payload = jose_jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=audience,
            issuer=issuer or None,
            options=options,
        )
        return payload
    except ExpiredSignatureError as exc:
        raise AuthError("token_expired", "JWT token has expired") from exc
    except JWTError as exc:
        message = str(exc).lower()
        if "signature verification failed" in message:
            raise AuthError(
                "invalid_signature", "JWT signature verification failed"
            ) from exc
        if "not enough segments" in message:
            raise AuthError("decode_error", "Failed to decode JWT") from exc
        raise AuthError("invalid_token", f"Invalid JWT token: {exc}") from exc


def _extract_user_from_jwt(payload: Dict[str, Any]) -> CurrentUser:
    """Extract user information from JWT payload.

    Supports common claim names from NextAuth and standard JWT:
    - sub / userId / user_id -> id
    - email
    - name / full_name
    - role
    - provider
    """
    user_id = (
        payload.get("sub")
        or payload.get("userId")
        or payload.get("user_id")
        or payload.get("id")
    )

    if not user_id:
        raise AuthError(
            "missing_user_id", "JWT payload missing user identifier (sub/userId)"
        )

    return CurrentUser(
        id=str(user_id),
        email=payload.get("email"),
        name=payload.get("name") or payload.get("full_name"),
        role=payload.get("role"),
        provider=payload.get("provider"),
        tenant_id=payload.get("tenant_id", "default"),
    )


def get_jwt_secret() -> Optional[str]:
    """Get JWT secret from environment.

    Checks multiple env vars for flexibility:
    - JWT_SECRET_KEY (preferred)
    - NEXTAUTH_SECRET (NextAuth compatibility)
    - SECRET_KEY (generic fallback)
    """

    secret = (
        os.getenv("JWT_SECRET_KEY")
        or os.getenv("NEXTAUTH_SECRET")
        or os.getenv("SECRET_KEY")
    )
    if secret:
        return secret

    # Avoid .env probing in test runs to keep expectations deterministic.
    if _is_test_env():
        return None

    return (
        _get_repo_dotenv_value("JWT_SECRET_KEY")
        or _get_repo_dotenv_value("NEXTAUTH_SECRET")
        or _get_repo_dotenv_value("SECRET_KEY")
    )


def get_jwt_secret_candidates() -> list[str]:
    """Return all plausible HS256 secrets for local/proxy interoperability."""
    candidates = [
        os.getenv("JWT_SECRET_KEY"),
        os.getenv("NEXTAUTH_SECRET"),
        os.getenv("SECRET_KEY"),
    ]

    if not _is_test_env():
        candidates.extend(
            [
                _get_repo_dotenv_value("JWT_SECRET_KEY"),
                _get_repo_dotenv_value("NEXTAUTH_SECRET"),
                _get_repo_dotenv_value("SECRET_KEY"),
            ]
        )

    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = str(candidate).strip()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return ordered


def _is_test_env() -> bool:
    """Return True only for explicit test execution contexts."""
    return bool(os.getenv("PYTEST_CURRENT_TEST") or os.getenv("BR_TESTING"))


@lru_cache(maxsize=3)
def _get_repo_dotenv_value(key: str) -> Optional[str]:
    """Best-effort lookup for <key> in the repo root dotenv files.

    This is a dev convenience so the Agent can verify NextAuth JWTs when it is
    started without sourcing dotenv files. If env vars are already set, this is
    never used.
    """
    try:
        repo_root = None
        for parent in Path(__file__).resolve().parents:
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                repo_root = parent
                break
        if repo_root is None:
            return None

        # Prefer .env.local (common for dev secrets) then fall back to .env.
        for filename in (".env.local", ".env"):
            env_path = repo_root / filename
            if not env_path.exists():
                continue

            for line in env_path.read_text(encoding="utf-8").splitlines():
                trimmed = line.strip()
                if not trimmed or trimmed.startswith("#"):
                    continue

                eq = trimmed.find("=")
                if eq <= 0:
                    continue

                k = trimmed[:eq].strip()
                if k != key:
                    continue

                v = trimmed[eq + 1 :].strip()
                if (v.startswith('"') and v.endswith('"')) or (
                    v.startswith("'") and v.endswith("'")
                ):
                    v = v[1:-1]
                return v or None
    except Exception:  # pragma: no cover - defensive
        return None

    return None


def is_dev_mode() -> bool:
    """Check if auth is disabled for development."""
    return os.getenv("DISABLE_AUTH_FOR_DEV", "0").lower() in {"1", "true", "yes"}


def get_current_user(req: Request) -> CurrentUser:
    """Resolve the current user from the request.

    Authentication flow:
    1. If DISABLE_AUTH_FOR_DEV is truthy, accept X-Debug-User or fall back to "dev-user".
    2. Extract Bearer token from Authorization header.
    3. If JWT_SECRET_KEY is set, verify token signature and extract claims.
    4. Otherwise, treat token as opaque user ID (legacy mode with warning).

    Raises:
        AuthError: If authentication fails
    """
    # Dev mode bypass
    if is_dev_mode():
        debug_user = (
            req.headers.get("X-Debug-User")
            or req.headers.get("x-debug-user")
            or "dev-user"
        )
        logger.debug(f"Dev mode: using debug user '{debug_user}'")
        return CurrentUser(id=debug_user)

    # Extract token
    token = _extract_bearer_token(req) or _extract_cookie_token(req)
    if not token:
        raise AuthError(
            "missing_bearer_token",
            "Authorization header or NextAuth session cookie required",
        )

    # Resolve verification config (HS256 shared secret + optional JWKS for RS256)
    jwt_secret = get_jwt_secret()
    jwks_url = _resolve_jwks_url()
    issuer = _resolve_jwt_issuer()
    audiences = _resolve_jwt_audiences()

    if not jwt_secret and not jwks_url:
        logger.warning(
            "JWT secret/JWKS missing; falling back to opaque token legacy mode. "
            "Set JWT_SECRET_KEY/NEXTAUTH_SECRET or SUPABASE_JWKS_URL for verification."
        )
        user = CurrentUser(id=token)
        return _apply_workspace_context(req, user, token)

    # Real JWT verification (HS256 or RS256)
    payload = _decode_jwt(
        token,
        jwt_secret,
        jwks_url=jwks_url,
        issuer=issuer,
        audiences=audiences,
    )
    user = _extract_user_from_jwt(payload)
    user = _apply_workspace_context(req, user, token)
    logger.debug(f"JWT verified for user: {user.id}")
    return user


def require_auth(req: Request) -> CurrentUser:
    """Convenience wrapper that raises AuthError with HTTP-friendly codes.

    Use this in route handlers:
        try:
            user = require_auth(request)
        except AuthError as e:
            return jsonify({"error": e.code, "detail": e.detail}), 401
    """
    return get_current_user(req)


def optional_auth(req: Request) -> Optional[CurrentUser]:
    """Get current user if authenticated, None otherwise.

    Use for routes that work both authenticated and anonymously.
    """
    try:
        return get_current_user(req)
    except AuthError:
        return None
