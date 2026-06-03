"""
Unified UserStore for the Orchestrator service.

Single source of truth for user records, backed by Redis.
All auth modules (main_enhanced, oauth_endpoints, auth_endpoints) MUST use
this module instead of local dicts or file-based storage.

Redis key layout:
    user:{user_id}          -> JSON-serialised User dict
    user_email:{email}      -> user_id  (email -> id index)
    user_username:{username} -> user_id  (username -> id index)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependency with main_enhanced
_User = None
_UserRole = None


def _ensure_models():
    """Lazy-import User and UserRole to break circular imports."""
    global _User, _UserRole
    if _User is None:
        from .models import User, UserRole

        _User = User
        _UserRole = UserRole


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

_redis_client = None
_redis_last_connect_attempt = 0.0
_redis_connect_error_logged = False


def _get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_redis_retry_interval_seconds() -> float:
    raw = os.getenv("BR_USERSTORE_REDIS_RETRY_SECONDS", "5")
    try:
        value = float(raw)
        return max(0.5, value)
    except ValueError:
        return 5.0


async def _mark_redis_unavailable(exc: Exception, context: str) -> None:
    """Drop the current Redis client so later calls can reconnect."""
    global _redis_client, _redis_connect_error_logged, _redis_last_connect_attempt
    client = _redis_client
    _redis_client = None
    _redis_last_connect_attempt = 0.0
    _redis_connect_error_logged = True
    logger.warning("UserStore: Redis %s (%s), falling back to in-memory", context, exc)
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def _get_redis():
    """Return a connected async Redis client, or None when unavailable."""
    global _redis_client, _redis_connect_error_logged, _redis_last_connect_attempt
    if _redis_client is not None:
        return _redis_client

    now = time.monotonic()
    retry_interval = _get_redis_retry_interval_seconds()
    if now - _redis_last_connect_attempt < retry_interval:
        return None

    _redis_last_connect_attempt = now
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            _get_redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        # Quick connectivity check
        await client.ping()
        _redis_client = client
        _redis_connect_error_logged = False
        logger.info("UserStore: Redis connected at %s", _get_redis_url())
    except Exception as exc:
        # Avoid flooding logs when Redis is temporarily unavailable.
        if not _redis_connect_error_logged:
            logger.warning(
                "UserStore: Redis unavailable (%s), falling back to in-memory", exc
            )
            _redis_connect_error_logged = True
        else:
            logger.debug("UserStore: Redis still unavailable (%s)", exc)
        _redis_client = None
    return _redis_client


# ---------------------------------------------------------------------------
# In-memory fallback (used when Redis is unreachable)
# ---------------------------------------------------------------------------

_mem_users: dict[str, dict[str, Any]] = {}
_mem_email_idx: dict[str, str] = {}
_mem_username_idx: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _user_to_dict(user) -> dict[str, Any]:
    """Serialise a User model to a plain dict for storage."""
    data = user.model_dump(mode="json")
    # User.hashed_password is excluded from public model dumps by design,
    # but internal credential storage must persist it.
    hashed_password = getattr(user, "hashed_password", None)
    if hashed_password:
        data["hashed_password"] = hashed_password
    return data


def _dict_to_user(data: dict[str, Any]):
    """Deserialise a dict back into a User model."""
    _ensure_models()
    return _User.model_validate(data)


def _generate_user_id() -> str:
    return f"user_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class UserStore:
    """Async user store backed by Redis with in-memory fallback."""

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @staticmethod
    async def get_by_id(user_id: str):
        """Look up a user by their orchestrator ID. Returns User or None."""
        _ensure_models()
        r = await _get_redis()
        if r:
            try:
                raw = await r.get(f"user:{user_id}")
                if raw:
                    return _dict_to_user(json.loads(raw))
                return None
            except Exception as exc:
                await _mark_redis_unavailable(exc, "get_by_id failed")
        # Fallback
        data = _mem_users.get(user_id)
        return _dict_to_user(data) if data else None

    @staticmethod
    async def get_by_email(email: str):
        """Look up a user by email. Returns User or None."""
        _ensure_models()
        email_lower = email.lower()
        r = await _get_redis()
        if r:
            try:
                user_id = await r.get(f"user_email:{email_lower}")
                if user_id:
                    return await UserStore.get_by_id(user_id)
                return None
            except Exception as exc:
                await _mark_redis_unavailable(exc, "get_by_email failed")
        # Fallback
        user_id = _mem_email_idx.get(email_lower)
        if user_id:
            data = _mem_users.get(user_id)
            return _dict_to_user(data) if data else None
        return None

    @staticmethod
    async def get_by_username(username: str):
        """Look up a user by username. Returns User or None."""
        _ensure_models()
        r = await _get_redis()
        if r:
            try:
                user_id = await r.get(f"user_username:{username}")
                if user_id:
                    return await UserStore.get_by_id(user_id)
                return None
            except Exception as exc:
                await _mark_redis_unavailable(exc, "get_by_username failed")
        # Fallback
        user_id = _mem_username_idx.get(username)
        if user_id:
            data = _mem_users.get(user_id)
            return _dict_to_user(data) if data else None
        return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    async def _persist(user) -> None:
        """Write a User to both Redis and in-memory fallback."""
        data = _user_to_dict(user)
        email_lower = user.email.lower()

        # Always update in-memory (serves as a hot cache / fallback)
        _mem_users[user.id] = data
        _mem_email_idx[email_lower] = user.id
        if user.username:
            _mem_username_idx[user.username] = user.id

        r = await _get_redis()
        if r:
            try:
                await r.set(f"user:{user.id}", json.dumps(data, default=str))
                await r.set(f"user_email:{email_lower}", user.id)
                if user.username:
                    await r.set(f"user_username:{user.username}", user.id)
            except Exception as exc:
                await _mark_redis_unavailable(exc, "write failed")

    @staticmethod
    async def upsert_oauth_user(
        email: str,
        name: str | None = None,
        provider: str | None = None,
        provider_account_id: str | None = None,
        image: str | None = None,
    ):
        """
        Idempotent create-or-update for OAuth users.
        Returns (User, created: bool).
        """
        _ensure_models()
        existing = await UserStore.get_by_email(email)
        if existing:
            # Update mutable fields
            changed = False
            if name and name != existing.full_name:
                existing.full_name = name
                changed = True
            if provider and provider != existing.auth_provider:
                existing.auth_provider = provider
                changed = True
            if (
                provider_account_id
                and provider_account_id != existing.provider_account_id
            ):
                existing.provider_account_id = provider_account_id
                changed = True
            if image and image != existing.picture:
                existing.picture = image
                changed = True
            existing.last_login = datetime.utcnow()
            if changed or True:  # always persist to update last_login
                await UserStore._persist(existing)
            return existing, False

        # Create new user
        user_id = _generate_user_id()
        # Derive username from email, sanitise to match User.username pattern ^[a-zA-Z0-9_]+$
        import re

        raw_stem = email.split("@")[0]
        username = re.sub(r"[^a-zA-Z0-9_]", "_", raw_stem) or "user"
        # Enforce min length (3)
        if len(username) < 3:
            username = f"{username}_user"
        # Ensure username uniqueness by appending random suffix if needed
        if await UserStore.get_by_username(username):
            username = f"{username}_{secrets.token_hex(3)}"

        user = _User(
            id=user_id,
            username=username,
            email=email,
            full_name=name or username,
            role=_UserRole.RESEARCHER,
            is_active=True,
            created_at=datetime.utcnow(),
            last_login=datetime.utcnow(),
            auth_provider=provider,
            provider_account_id=provider_account_id,
            picture=image,
        )
        await UserStore._persist(user)
        logger.info(
            "UserStore: created OAuth user %s (%s via %s)", user_id, email, provider
        )
        return user, True

    @staticmethod
    async def create_credential_user(
        username: str,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        role=None,
        user_id: str | None = None,
        **extra_fields,
    ):
        """
        Create a credential-based user.  Raises ValueError on duplicate email/username.
        """
        _ensure_models()
        if role is None:
            role = _UserRole.RESEARCHER

        if await UserStore.get_by_email(email):
            raise ValueError(f"Email already registered: {email}")
        if await UserStore.get_by_username(username):
            raise ValueError(f"Username already exists: {username}")

        uid = user_id or _generate_user_id()
        user = _User(
            id=uid,
            username=username,
            email=email,
            full_name=full_name or username,
            role=role,
            is_active=True,
            created_at=datetime.utcnow(),
            hashed_password=hashed_password,
            auth_provider="password",
            **extra_fields,
        )
        await UserStore._persist(user)
        logger.info("UserStore: created credential user %s (%s)", uid, email)
        return user

    @staticmethod
    async def update_last_login(user_id: str) -> None:
        user = await UserStore.get_by_id(user_id)
        if user:
            user.last_login = datetime.utcnow()
            await UserStore._persist(user)

    @staticmethod
    async def set_password_hash(
        user_id: str,
        hashed_password: str,
        *,
        clear_reset_flag: bool = True,
    ):
        """Set/replace a user's password hash and persist changes."""
        user = await UserStore.get_by_id(user_id)
        if user is None:
            return None

        user.hashed_password = hashed_password
        user.auth_provider = "password"
        if clear_reset_flag:
            preferences = dict(user.preferences or {})
            preferences.pop("must_reset_password", None)
            preferences.pop("password_reset", None)
            user.preferences = preferences

        await UserStore._persist(user)
        logger.info("UserStore: updated password hash for %s", user_id)
        return user

    @staticmethod
    async def mark_password_reset_required(
        user_id: str,
        *,
        reason: str = "password_recovery",
    ):
        """Mark a user account as requiring password reset."""
        user = await UserStore.get_by_id(user_id)
        if user is None:
            return None

        preferences = dict(user.preferences or {})
        preferences["must_reset_password"] = True
        preferences["password_reset"] = {
            "required": True,
            "reason": reason,
            "updated_at": datetime.utcnow().isoformat(),
        }
        user.preferences = preferences
        await UserStore._persist(user)
        return user

    @staticmethod
    async def list_password_users_missing_hash() -> list:
        """List password-auth users that currently have no stored password hash."""
        users = await UserStore.list_all()
        missing = []
        for user in users:
            provider = str(getattr(user, "auth_provider", "") or "").lower()
            if provider == "password" and not getattr(user, "hashed_password", None):
                missing.append(user)
        return missing

    @staticmethod
    async def save(user) -> None:
        """Persist an already-constructed User object."""
        await UserStore._persist(user)

    @staticmethod
    async def list_all() -> list:
        """Return all users (for admin/debug). Prefer get_by_* for normal lookups."""
        _ensure_models()
        r = await _get_redis()
        if r:
            try:
                keys = []
                async for key in r.scan_iter(match="user:user_*"):
                    keys.append(key)
                users = []
                for key in keys:
                    raw = await r.get(key)
                    if raw:
                        users.append(_dict_to_user(json.loads(raw)))
                return users
            except Exception as exc:
                await _mark_redis_unavailable(exc, "list_all failed")
        return [_dict_to_user(d) for d in _mem_users.values()]


# Module-level singleton
user_store = UserStore()
