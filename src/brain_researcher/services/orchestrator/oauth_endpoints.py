"""OAuth Authentication Endpoints for Brain Researcher"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from .auth_utils import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
)
from .magic_link import MagicLinkRequest, MagicLinkService
from .models import TokenResponse, User, UserRole
from .oauth_config import OAuthConfig, OAuthProvider

try:
    from .user_store import user_store as _user_store
except ImportError:
    from user_store import user_store as _user_store

try:
    from .endpoints.credits import grant_initial_account_credits_for_account
except ImportError:
    grant_initial_account_credits_for_account = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])

# Initialize Redis for OAuth state storage
redis_client = None
try:
    import redis.asyncio as redis

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = redis.from_url(redis_url, decode_responses=True)
    logger.info(f"Redis client initialized: {redis_url}")
except Exception as e:
    logger.warning(f"Redis not available, using in-memory storage: {e}")
    redis_client = None

# Initialize services
oauth_config = OAuthConfig()
magic_link_service = MagicLinkService()

# Fallback in-memory storage for OAuth state (when Redis unavailable)
oauth_states: Dict[str, Dict[str, Any]] = {}

# User storage is now handled by the unified UserStore (user_store.py).
# The local `users_db` dict is removed; all reads/writes go through _user_store.


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


@router.get("/{provider}/authorize")
async def oauth_authorize(provider: str, request: Request):
    """Initiate OAuth flow for a provider"""

    if provider not in ["google", "microsoft", "github"]:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    config = oauth_config.get_provider_config(provider)
    if not config:
        raise HTTPException(
            status_code=400, detail=f"Provider {provider} not configured"
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    state_data = {
        "provider": provider,
        "timestamp": datetime.utcnow().isoformat(),
        "redirect_uri": oauth_config.get_redirect_uri(provider),
    }

    # Store state in Redis (with 15 min TTL) or fallback to in-memory
    if redis_client:
        try:
            await redis_client.setex(
                f"oauth_state:{state}", 900, json.dumps(state_data)  # 15 minutes TTL
            )
            logger.info(f"OAuth state stored in Redis: {state[:10]}...")
        except Exception as e:
            logger.error(f"Redis error, falling back to in-memory: {e}")
            oauth_states[state] = state_data
    else:
        oauth_states[state] = state_data

    # Build authorization URL
    params = {
        "client_id": config["client_id"],
        "redirect_uri": oauth_config.get_redirect_uri(provider),
        "response_type": config.get("response_type", "code"),
        "scope": " ".join(config["scopes"]),
        "state": state,
    }

    # Add provider-specific parameters
    if provider == "google":
        params["access_type"] = config.get("access_type", "offline")
        params["prompt"] = config.get("prompt", "consent")
    elif provider == "microsoft":
        params["prompt"] = config.get("prompt", "select_account")

    auth_url = f"{config['authorize_url']}?{urlencode(params)}"

    return RedirectResponse(url=auth_url)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """Handle OAuth callback from provider"""

    # Handle error responses
    if error:
        logger.error(f"OAuth error from {provider}: {error} - {error_description}")
        return RedirectResponse(url=f"/auth/error?error={error}")

    # Validate and retrieve state from Redis or in-memory
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")

    state_data = None
    if redis_client:
        try:
            state_json = await redis_client.get(f"oauth_state:{state}")
            if state_json:
                state_data = json.loads(state_json)
                await redis_client.delete(f"oauth_state:{state}")  # Delete after use
                logger.info(f"OAuth state retrieved from Redis: {state[:10]}...")
            else:
                logger.warning(f"State not found in Redis: {state[:10]}...")
        except Exception as e:
            logger.error(f"Redis error, checking in-memory: {e}")
            state_data = oauth_states.pop(state, None)
    else:
        state_data = oauth_states.pop(state, None)

    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Check state expiry (15 minutes)
    state_timestamp = datetime.fromisoformat(state_data["timestamp"])
    if datetime.utcnow() - state_timestamp > timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="State expired")

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided")

    config = oauth_config.get_provider_config(provider)
    if not config:
        raise HTTPException(
            status_code=400, detail=f"Provider {provider} not configured"
        )

    try:
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": oauth_config.get_redirect_uri(provider),
                "grant_type": "authorization_code",
            }

            # GitHub requires Accept header
            headers = {}
            if provider == "github":
                headers["Accept"] = "application/json"

            token_response = await client.post(
                config["token_url"], data=token_data, headers=headers
            )

            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.text}")
                raise HTTPException(status_code=400, detail="Token exchange failed")

            tokens = token_response.json()
            access_token = tokens.get("access_token")

            if not access_token:
                raise HTTPException(status_code=400, detail="No access token received")

            # Get user info
            headers = {"Authorization": f"Bearer {access_token}"}

            # Microsoft uses different header format
            if provider == "microsoft":
                headers = {"Authorization": f"Bearer {access_token}"}

            user_response = await client.get(config["userinfo_url"], headers=headers)

            if user_response.status_code != 200:
                logger.error(f"Failed to get user info: {user_response.text}")
                raise HTTPException(status_code=400, detail="Failed to get user info")

            user_data = user_response.json()

            # GitHub may need separate call for email
            if provider == "github" and not user_data.get("email"):
                email_response = await client.get(
                    config.get(
                        "userinfo_email_url", "https://api.github.com/user/emails"
                    ),
                    headers=headers,
                )
                if email_response.status_code == 200:
                    emails = email_response.json()
                    # Get primary verified email
                    for email_obj in emails:
                        if email_obj.get("primary") and email_obj.get("verified"):
                            user_data["email"] = email_obj["email"]
                            break

            # Parse user info into standard format
            user_info = oauth_config.parse_user_info(provider, user_data)

            # Log authenticated user info
            logger.info(
                f"OAuth user authenticated: {user_info.get('email')} (name: {user_info.get('name')}, provider: {provider})"
            )

            # Validate email domain for Microsoft
            if provider == "microsoft" and user_info.get("email"):
                if not oauth_config.validate_email_domain(user_info["email"], provider):
                    raise HTTPException(
                        status_code=403,
                        detail="Email domain not allowed. Please use your institutional email.",
                    )

            # Create or update user
            user = await create_or_update_oauth_user(provider, user_info)

            # Create JWT tokens
            access_token = create_access_token(data={"sub": user.id})
            refresh_token = create_refresh_token(data={"sub": user.id})

            # Redirect to frontend with tokens
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
            redirect_params = {"access_token": access_token, "provider": provider}
            # Only include refresh token when running in development (optional)
            if os.getenv("INCLUDE_REFRESH_TOKEN_IN_URL", "false").lower() == "true":
                redirect_params["refresh_token"] = refresh_token

            redirect_url = f"{frontend_url}/auth/callback?{urlencode(redirect_params)}"

            response = RedirectResponse(url=redirect_url)
            # Align cookie settings with primary auth endpoints
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=30 * 24 * 60 * 60,
                httponly=True,
                secure=True,
                samesite="strict",
                path="/auth/refresh",
            )

            return response

    except Exception as e:
        logger.error(f"OAuth callback error for {provider}: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.post("/callback")
async def oauth_callback_api(request: Request):
    """API endpoint for frontend to sync OAuth user (legacy, prefer /ensure-user)."""
    return await ensure_oauth_user(request)


@router.post("/ensure-user")
async def ensure_oauth_user(request: Request):
    """
    Idempotent: create or update an OAuth user in the unified UserStore.
    Called by NextAuth's signIn callback after successful OAuth.

    Request body:
        { email, name?, provider, providerAccountId?, image? }
    Response:
        { success, user_id, email, role }
    """
    try:
        data = await request.json()
        email = data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        user, created = await _user_store.upsert_oauth_user(
            email=email,
            name=data.get("name"),
            provider=data.get("provider"),
            provider_account_id=data.get("providerAccountId", ""),
            image=data.get("image"),
        )
        if created:
            await _grant_initial_account_credits(user.id, "oauth.ensure_user")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ensure-user error: {e}")
        raise HTTPException(status_code=500, detail="Failed to ensure user")


@router.post("/magic-link/send")
async def send_magic_link(request: MagicLinkRequest):
    """Send a magic link to user's email"""

    # Check rate limiting
    if not await magic_link_service.rate_limit_check(request.email):
        raise HTTPException(
            status_code=429, detail="Too many requests. Please try again in an hour."
        )

    # Send magic link
    success = await magic_link_service.send_magic_link(request.email)

    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to send magic link. Please try again."
        )

    return JSONResponse({"success": True, "message": "Magic link sent to your email"})


@router.post("/magic-link/verify")
async def verify_magic_link(token: str):
    """Verify a magic link token"""

    email = await magic_link_service.verify_magic_link(token)

    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired magic link")

    # Find or create user via unified UserStore
    user, created = await _user_store.upsert_oauth_user(
        email=email,
        name=email.split("@")[0],
        provider="email",
    )
    if created:
        await _grant_initial_account_credits(user.id, "oauth.magic_link")

    # Create JWT tokens
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user,
    )


async def create_or_update_oauth_user(provider: str, user_info: Dict[str, Any]) -> User:
    """Create or update a user from OAuth provider data via unified UserStore."""

    email = user_info.get("email")
    if not email:
        raise ValueError("Email not provided by OAuth provider")

    user, created = await _user_store.upsert_oauth_user(
        email=email,
        name=user_info.get("name"),
        provider=provider,
        provider_account_id=user_info.get("provider_id"),
        image=user_info.get("picture"),
    )
    if created:
        await _grant_initial_account_credits(user.id, f"oauth.{provider}")

    # Provider-specific field updates
    changed = False
    if provider == "microsoft":
        if user_info.get("organization"):
            user.organization = user_info["organization"]
            changed = True
        if user_info.get("department"):
            user.department = user_info["department"]
            changed = True
        if user_info.get("job_title"):
            user.job_title = user_info["job_title"]
            changed = True
    elif provider == "github":
        if user_info.get("github_username"):
            user.github_username = user_info["github_username"]
            changed = True

    if changed:
        await _user_store.save(user)

    return user
