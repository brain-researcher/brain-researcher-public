"""
Authentication Endpoints for Brain Researcher (auth_endpoints router).

This router provides session introspection, user profile, settings, and
health-check endpoints.  User storage is delegated to the unified
``UserStore`` (see ``user_store.py``).

The legacy file-based store (/tmp/brain_researcher_users.json) is removed;
all reads/writes go through UserStore.
"""

import logging
import os
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

try:
    import jwt
except ImportError:
    from jose import jwt  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

try:
    from ...shared.jwt_secret import resolve_shared_jwt_secret
except ImportError:
    from brain_researcher.services.shared.jwt_secret import resolve_shared_jwt_secret


SECRET_KEY = resolve_shared_jwt_secret(
    env_names=("JWT_SECRET_KEY", "NEXTAUTH_SECRET", "JWT_SECRET"),
)
if not SECRET_KEY:
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("ENVIRONMENT") == "development":
        SECRET_KEY = secrets.token_urlsafe(32)
    else:
        raise RuntimeError("JWT_SECRET_KEY must be set for orchestrator auth endpoints")
JWT_ALGORITHM = "HS256"

# Unified user store (supports both package and direct import)
try:
    from ..user_store import user_store as _user_store
except ImportError:
    from user_store import user_store as _user_store

try:
    from ..mcp_token_store import mcp_token_store
except ImportError:
    from mcp_token_store import mcp_token_store  # type: ignore

try:
    from .credits import grant_initial_account_credits_for_account
except ImportError:
    grant_initial_account_credits_for_account = None  # type: ignore


async def _grant_initial_account_credits(user_id: str, source: str) -> None:
    if grant_initial_account_credits_for_account is None:
        return
    try:
        grant_initial_account_credits_for_account(
            "default",
            user_id,
            source=source,
        )
    except Exception as exc:
        logger.warning(
            "Initial account credit grant failed for user %s (%s): %s",
            user_id,
            source,
            exc,
        )


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    return auth_header.replace("Bearer ", "")


def _decode_auth_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception as jwt_err:
        msg = str(jwt_err).lower()
        if "expired" in msg:
            raise HTTPException(status_code=401, detail="Token expired") from jwt_err
        raise HTTPException(status_code=401, detail="Invalid token") from jwt_err


async def _resolve_authenticated_user(request: Request) -> tuple[Any, dict[str, Any]]:
    token = _extract_bearer_token(request)
    payload = _decode_auth_token(token)
    user_id = payload.get("sub") or payload.get("user_id")
    email = payload.get("email")

    user = None
    if user_id:
        user = await _user_store.get_by_id(user_id)

    # OAuth/legacy sessions may carry a valid email but a non-orchestrator `sub`.
    # Fall back to email lookup so authenticated users can still access self-service endpoints.
    if not user and email:
        user = await _user_store.get_by_email(str(email))

    if not user_id and not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user, payload


def _is_admin_role(role: Any) -> bool:
    role_value = role.value if hasattr(role, "value") else str(role)
    return str(role_value).lower() == "admin"


def _serialize_user_summary(user: Any) -> dict[str, Any]:
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    preferences = dict(getattr(user, "preferences", {}) or {})
    reset_required = bool(preferences.get("must_reset_password"))
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": role_value,
        "is_active": user.is_active,
        "auth_provider": user.auth_provider,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "password_reset_required": reset_required,
    }


class AdminSetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)
    clear_reset_flag: bool = True


class AdminForceResetRequest(BaseModel):
    reason: str = Field(default="password_recovery", min_length=1, max_length=200)


class CreateMcpTokenRequest(BaseModel):
    expires_at: str | None = None


@router.get("/session")
async def get_session(request: Request):
    """Get current user session from JWT token."""
    try:
        user, _payload = await _resolve_authenticated_user(request)

        return {
            "authenticated": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.full_name,
                "image": user.picture,
                "provider": user.auth_provider,
                "roles": [
                    user.role.value if hasattr(user.role, "value") else user.role
                ],
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session error: {e}")
        return {"authenticated": False}


@router.post("/logout")
async def logout():
    """Handle user logout (stateless JWT – client removes token)."""
    return {"success": True, "message": "Logged out successfully"}


@router.get("/users/me")
async def get_current_user(request: Request):
    """Get current user profile."""
    user, _payload = await _resolve_authenticated_user(request)
    return _serialize_user_summary(user)


@router.put("/users/me/settings")
async def update_user_settings(request: Request, settings: dict[str, Any]):
    """Update user settings/preferences."""
    user, _payload = await _resolve_authenticated_user(request)

    user.preferences.update(settings)
    await _user_store.save(user)
    return {"success": True, "settings": user.preferences}


@router.get("/mcp-tokens")
async def list_mcp_tokens(request: Request):
    """List MCP token metadata for the authenticated user."""
    user, _payload = await _resolve_authenticated_user(request)
    try:
        tokens = await mcp_token_store.list_user_tokens(user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"tokens": tokens, "count": len(tokens)}


@router.post("/mcp-tokens")
async def create_mcp_token(
    request: Request,
    payload: CreateMcpTokenRequest | None = None,
):
    """Create or rotate the authenticated user's MCP token."""
    user, _jwt_payload = await _resolve_authenticated_user(request)
    try:
        token, metadata = await mcp_token_store.create_or_rotate_token(
            user.id,
            expires_at=payload.expires_at if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"token": token, "metadata": metadata}


@router.get("/mcp-tokens/verify")
async def verify_mcp_token(
    request: Request,
    x_mcp_token: str | None = Header(default=None),
):
    """Return MCP token backend status; optionally verify a supplied token."""
    user, _jwt_payload = await _resolve_authenticated_user(request)

    if x_mcp_token:
        verification = await mcp_token_store.verify_token(
            x_mcp_token,
            update_last_used=False,
        )
        if verification is None:
            raise HTTPException(status_code=401, detail="Invalid MCP token")
        return {
            "valid": True,
            "kid": verification.kid,
            "user_id": verification.user_id,
            "last_used_at": verification.last_used_at,
        }

    status = await mcp_token_store.status(user.id)
    return status


@router.delete("/mcp-tokens/{kid}")
async def revoke_mcp_token(kid: str, request: Request):
    """Revoke the authenticated user's MCP token by key id."""
    user, _jwt_payload = await _resolve_authenticated_user(request)
    try:
        revoked = await mcp_token_store.revoke_user_token(user.id, kid)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not revoked:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"success": True, "kid": kid}


@router.post("/ensure-user")
async def ensure_oauth_user(request: Request):
    """
    Idempotent: create or update an OAuth user in the unified UserStore.
    Called by NextAuth's signIn callback after successful OAuth.

    Path: POST /auth/ensure-user  (under the /auth prefix, NOT /auth/oauth,
    to avoid collision with main_enhanced.py's /auth/oauth/{provider} route).

    Request body:
        { email, name?, provider, providerAccountId?, image? }
    Response:
        { success, user_id, email, role }
    """
    try:
        data = await request.json()
        email = data.get("email")
        if not email:
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "Email is required"}, status_code=400)

        user, created = await _user_store.upsert_oauth_user(
            email=email,
            name=data.get("name"),
            provider=data.get("provider"),
            provider_account_id=data.get("providerAccountId", ""),
            image=data.get("image"),
        )
        if created:
            await _grant_initial_account_credits(user.id, "auth.ensure_user")

        from fastapi.responses import JSONResponse

        return JSONResponse(
            {
                "success": True,
                "user_id": user.id,
                "email": user.email,
                "name": user.full_name,
                "role": user.role.value if hasattr(user.role, "value") else user.role,
                "provider": data.get("provider"),
                "created": created,
            }
        )

    except Exception as e:
        logger.error(f"ensure-user error: {e}")
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "Failed to ensure user"}, status_code=500)


@router.get("/admin/users")
async def list_users_for_admin(
    request: Request,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
):
    """List known users for admin operators."""
    current_user, _payload = await _resolve_authenticated_user(request)
    if not _is_admin_role(current_user.role):
        raise HTTPException(status_code=403, detail="Admin access required")

    users = await _user_store.list_all()
    if not include_inactive:
        users = [user for user in users if bool(getattr(user, "is_active", True))]

    users.sort(
        key=lambda item: (item.created_at is not None, item.created_at), reverse=True
    )
    total = len(users)
    page = users[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(page),
        "users": [_serialize_user_summary(user) for user in page],
    }


@router.post("/admin/users/{user_id}/force-password-reset")
async def force_password_reset_for_user(
    user_id: str,
    payload: AdminForceResetRequest,
    request: Request,
):
    """Mark a user account as requiring password reset."""
    current_user, _payload = await _resolve_authenticated_user(request)
    if not _is_admin_role(current_user.role):
        raise HTTPException(status_code=403, detail="Admin access required")

    if not hasattr(_user_store, "mark_password_reset_required"):
        raise HTTPException(status_code=500, detail="Password reset API unavailable")

    updated_user = await _user_store.mark_password_reset_required(
        user_id,
        reason=payload.reason,
    )
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "success": True,
        "user": _serialize_user_summary(updated_user),
        "message": "User marked for password reset",
    }


@router.post("/admin/users/{user_id}/password")
async def set_password_for_user(
    user_id: str,
    payload: AdminSetPasswordRequest,
    request: Request,
):
    """Set/replace a user's password hash."""
    current_user, _payload = await _resolve_authenticated_user(request)
    if not _is_admin_role(current_user.role):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        from ..auth_utils import hash_password
    except ImportError:
        from auth_utils import hash_password  # type: ignore

    if not hasattr(_user_store, "set_password_hash"):
        raise HTTPException(status_code=500, detail="Password update API unavailable")

    updated_user = await _user_store.set_password_hash(
        user_id,
        hash_password(payload.new_password),
        clear_reset_flag=payload.clear_reset_flag,
    )
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "success": True,
        "user": _serialize_user_summary(updated_user),
        "message": "Password updated",
    }


@router.get("/health")
async def health_check():
    """Health check endpoint for authentication service."""
    return {
        "status": "healthy",
        "service": "authentication",
        "timestamp": datetime.utcnow().isoformat(),
    }
