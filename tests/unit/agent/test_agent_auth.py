"""Unit tests for agent auth module."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest


class TestJWTDecoding:
    """Tests for JWT token decoding and verification."""

    @pytest.fixture
    def jwt_secret(self):
        """Standard test secret."""
        return "test-jwt-secret-key-256bits-long!"

    @pytest.fixture
    def valid_token(self, jwt_secret):
        """Create a valid JWT token."""
        import jwt

        payload = {
            "sub": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "role": "user",
            "exp": int(time.time()) + 3600,  # 1 hour from now
            "iat": int(time.time()),
        }
        return jwt.encode(payload, jwt_secret, algorithm="HS256")

    @pytest.fixture
    def expired_token(self, jwt_secret):
        """Create an expired JWT token."""
        import jwt

        payload = {
            "sub": "user-123",
            "email": "test@example.com",
            "exp": int(time.time()) - 3600,  # 1 hour ago
            "iat": int(time.time()) - 7200,
        }
        return jwt.encode(payload, jwt_secret, algorithm="HS256")

    def test_decode_jwt_valid(self, jwt_secret, valid_token):
        """Valid JWT should decode successfully."""
        from brain_researcher.services.agent.agent_auth import _decode_jwt

        payload = _decode_jwt(valid_token, jwt_secret)

        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["name"] == "Test User"

    def test_decode_jwt_expired(self, jwt_secret, expired_token):
        """Expired JWT should raise AuthError with token_expired code."""
        from brain_researcher.services.agent.agent_auth import _decode_jwt, AuthError

        with pytest.raises(AuthError) as exc_info:
            _decode_jwt(expired_token, jwt_secret)

        assert exc_info.value.code == "token_expired"
        assert "expired" in exc_info.value.detail.lower()

    def test_decode_jwt_invalid_signature(self, valid_token):
        """JWT with wrong secret should raise AuthError with invalid_signature code."""
        from brain_researcher.services.agent.agent_auth import _decode_jwt, AuthError

        with pytest.raises(AuthError) as exc_info:
            _decode_jwt(valid_token, "wrong-secret-key-different-one!")

        assert exc_info.value.code == "invalid_signature"

    def test_decode_jwt_malformed(self, jwt_secret):
        """Malformed JWT should raise AuthError with decode_error code."""
        from brain_researcher.services.agent.agent_auth import _decode_jwt, AuthError

        with pytest.raises(AuthError) as exc_info:
            _decode_jwt("not.a.valid.jwt.token", jwt_secret)

        assert exc_info.value.code in ("decode_error", "invalid_token")


class TestUserExtraction:
    """Tests for extracting user from JWT payload."""

    def test_extract_user_from_jwt_sub(self):
        """User ID should be extracted from 'sub' claim."""
        from brain_researcher.services.agent.agent_auth import _extract_user_from_jwt

        payload = {
            "sub": "user-456",
            "email": "user@test.com",
            "name": "Test User",
        }

        user = _extract_user_from_jwt(payload)

        assert user.id == "user-456"
        assert user.email == "user@test.com"
        assert user.name == "Test User"

    def test_extract_user_from_jwt_userid_field(self):
        """User ID should be extracted from 'userId' if 'sub' is missing."""
        from brain_researcher.services.agent.agent_auth import _extract_user_from_jwt

        payload = {
            "userId": "user-789",
            "email": "alt@test.com",
        }

        user = _extract_user_from_jwt(payload)
        assert user.id == "user-789"

    def test_extract_user_from_jwt_missing_id(self):
        """Missing user ID should raise AuthError."""
        from brain_researcher.services.agent.agent_auth import _extract_user_from_jwt, AuthError

        payload = {"email": "noid@test.com"}

        with pytest.raises(AuthError) as exc_info:
            _extract_user_from_jwt(payload)

        assert exc_info.value.code == "missing_user_id"


class TestBearerTokenExtraction:
    """Tests for extracting Bearer token from request headers."""

    def test_extract_bearer_token_valid(self):
        """Valid Bearer token should be extracted."""
        from brain_researcher.services.agent.agent_auth import _extract_bearer_token

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda k: "Bearer my-token-123" if k.lower() == "authorization" else None

        token = _extract_bearer_token(mock_request)
        assert token == "my-token-123"

    def test_extract_bearer_token_missing(self):
        """Missing Authorization header should return None."""
        from brain_researcher.services.agent.agent_auth import _extract_bearer_token

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        token = _extract_bearer_token(mock_request)
        assert token is None

    def test_extract_bearer_token_not_bearer(self):
        """Non-Bearer auth should return None."""
        from brain_researcher.services.agent.agent_auth import _extract_bearer_token

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "Basic dXNlcjpwYXNz"

        token = _extract_bearer_token(mock_request)
        assert token is None


class TestDevMode:
    """Tests for development mode authentication bypass."""

    def test_dev_mode_enabled(self):
        """DISABLE_AUTH_FOR_DEV=1 should enable dev mode."""
        from brain_researcher.services.agent.agent_auth import is_dev_mode

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "1"}):
            assert is_dev_mode() is True

    def test_dev_mode_disabled(self):
        """DISABLE_AUTH_FOR_DEV not set should disable dev mode."""
        from brain_researcher.services.agent.agent_auth import is_dev_mode

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "0"}, clear=True):
            assert is_dev_mode() is False

    def test_dev_mode_true_string(self):
        """DISABLE_AUTH_FOR_DEV=true should enable dev mode."""
        from brain_researcher.services.agent.agent_auth import is_dev_mode

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "true"}):
            assert is_dev_mode() is True


class TestGetCurrentUser:
    """Tests for the main get_current_user function."""

    def test_dev_mode_with_debug_header(self):
        """Dev mode should use X-Debug-User header."""
        from brain_researcher.services.agent.agent_auth import get_current_user

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda k: "debug-user-abc" if k == "X-Debug-User" else None

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "1"}):
            user = get_current_user(mock_request)

        assert user.id == "debug-user-abc"

    def test_dev_mode_default_user(self):
        """Dev mode without X-Debug-User should use 'dev-user'."""
        from brain_researcher.services.agent.agent_auth import get_current_user

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "1"}):
            user = get_current_user(mock_request)

        assert user.id == "dev-user"

    def test_missing_bearer_token(self):
        """Missing Bearer token should raise AuthError."""
        from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "0"}, clear=True):
            with pytest.raises(AuthError) as exc_info:
                get_current_user(mock_request)

        assert exc_info.value.code == "missing_bearer_token"

    def test_jwt_verification_with_secret(self):
        """With JWT_SECRET_KEY set, token should be verified."""
        import jwt
        from brain_researcher.services.agent.agent_auth import get_current_user

        secret = "test-secret-key-for-jwt-verification"
        token = jwt.encode(
            {
                "sub": "verified-user",
                "email": "verified@test.com",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda k: f"Bearer {token}" if k.lower() == "authorization" else None
        # No workspace context by default
        mock_request.cookies.get.return_value = None

        env = {"JWT_SECRET_KEY": secret, "DISABLE_AUTH_FOR_DEV": "0"}
        with patch.dict(os.environ, env, clear=True):
            user = get_current_user(mock_request)

        assert user.id == "verified-user"
        assert user.email == "verified@test.com"

    def test_jwt_verification_falls_back_to_nextauth_secret(self):
        """If JWT_SECRET_KEY mismatches, fallback secrets should still verify."""
        import jwt
        from brain_researcher.services.agent.agent_auth import get_current_user

        token_secret = "nextauth-secret-correct"
        token = jwt.encode(
            {
                "sub": "verified-user",
                "email": "verified@test.com",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            token_secret,
            algorithm="HS256",
        )

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = (
            lambda k: f"Bearer {token}" if k.lower() == "authorization" else None
        )
        mock_request.cookies.get.return_value = None

        env = {
            "JWT_SECRET_KEY": "primary-secret-wrong",
            "NEXTAUTH_SECRET": token_secret,
            "DISABLE_AUTH_FOR_DEV": "0",
        }
        with patch.dict(os.environ, env, clear=True):
            user = get_current_user(mock_request)

        assert user.id == "verified-user"
        assert user.email == "verified@test.com"

    def test_legacy_mode_without_secret(self):
        """Without JWT secret, token should be used as opaque user ID."""
        from brain_researcher.services.agent.agent_auth import get_current_user

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda k: "Bearer opaque-token-as-user-id" if k.lower() == "authorization" else None
        # No workspace context by default
        mock_request.cookies.get.return_value = None

        # Clear all JWT-related env vars
        env = {"DISABLE_AUTH_FOR_DEV": "0"}
        with patch.dict(os.environ, env, clear=True):
            # Also need to ensure the secret getters return None
            with patch("brain_researcher.services.agent.agent_auth.get_jwt_secret", return_value=None):
                user = get_current_user(mock_request)

        assert user.id == "opaque-token-as-user-id"


class TestOptionalAuth:
    """Tests for optional_auth function."""

    def test_optional_auth_with_valid_user(self):
        """optional_auth should return user when authenticated."""
        from brain_researcher.services.agent.agent_auth import optional_auth

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "1"}):
            user = optional_auth(mock_request)

        assert user is not None
        assert user.id == "dev-user"

    def test_optional_auth_returns_none_on_failure(self):
        """optional_auth should return None when auth fails."""
        from brain_researcher.services.agent.agent_auth import optional_auth

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with patch.dict(os.environ, {"DISABLE_AUTH_FOR_DEV": "0"}, clear=True):
            user = optional_auth(mock_request)

        assert user is None


class TestWorkspaceEnforcement:
    """Tests for workspace membership enforcement behavior."""

    def test_missing_workspace_allowed_for_credentials_in_dev(self):
        """Dev credentials flow should tolerate missing workspace context."""
        import jwt
        from brain_researcher.services.agent.agent_auth import get_current_user

        secret = "test-secret-key-for-workspace"
        token = jwt.encode(
            {
                "sub": "dev-user",
                "email": "dev@example.com",
                "provider": "credentials",
                "role": "dev",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = (
            lambda k: f"Bearer {token}" if k.lower() == "authorization" else None
        )
        mock_request.cookies.get.return_value = None

        env = {
            "JWT_SECRET_KEY": secret,
            "BR_ENFORCE_WORKSPACE_MEMBERSHIP": "1",
            "NODE_ENV": "development",
            "DISABLE_AUTH_FOR_DEV": "0",
        }
        with patch.dict(os.environ, env, clear=True):
            user = get_current_user(mock_request)

        assert user.id == "dev-user"
        assert user.tenant_id == "default"

    def test_missing_workspace_rejected_in_production(self):
        """Production should keep strict missing workspace rejection."""
        import jwt
        from brain_researcher.services.agent.agent_auth import AuthError, get_current_user

        secret = "test-secret-key-for-workspace"
        token = jwt.encode(
            {
                "sub": "dev-user",
                "email": "dev@example.com",
                "provider": "credentials",
                "role": "dev",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = (
            lambda k: f"Bearer {token}" if k.lower() == "authorization" else None
        )
        mock_request.cookies.get.return_value = None

        env = {
            "JWT_SECRET_KEY": secret,
            "BR_ENFORCE_WORKSPACE_MEMBERSHIP": "1",
            "NODE_ENV": "production",
            "DISABLE_AUTH_FOR_DEV": "0",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(AuthError) as exc_info:
                get_current_user(mock_request)

        assert exc_info.value.code == "missing_workspace_id"


class TestAuthError:
    """Tests for AuthError exception class."""

    def test_auth_error_with_detail(self):
        """AuthError should include code and detail."""
        from brain_researcher.services.agent.agent_auth import AuthError

        error = AuthError("test_code", "Test detail message")

        assert error.code == "test_code"
        assert error.detail == "Test detail message"
        assert "test_code" in str(error)
        assert "Test detail message" in str(error)

    def test_auth_error_without_detail(self):
        """AuthError should work without detail."""
        from brain_researcher.services.agent.agent_auth import AuthError

        error = AuthError("simple_error")

        assert error.code == "simple_error"
        assert error.detail == ""
        assert str(error) == "simple_error"


class TestJWTSecretResolution:
    """Tests for JWT secret resolution from environment."""

    def test_jwt_secret_key_preferred(self):
        """JWT_SECRET_KEY should be preferred."""
        from brain_researcher.services.agent.agent_auth import get_jwt_secret

        env = {
            "JWT_SECRET_KEY": "primary-secret",
            "NEXTAUTH_SECRET": "nextauth-secret",
            "SECRET_KEY": "generic-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            secret = get_jwt_secret()

        assert secret == "primary-secret"

    def test_nextauth_secret_fallback(self):
        """NEXTAUTH_SECRET should be used if JWT_SECRET_KEY not set."""
        from brain_researcher.services.agent.agent_auth import get_jwt_secret

        env = {
            "NEXTAUTH_SECRET": "nextauth-secret",
            "SECRET_KEY": "generic-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            secret = get_jwt_secret()

        assert secret == "nextauth-secret"

    def test_secret_key_fallback(self):
        """SECRET_KEY should be used as last resort."""
        from brain_researcher.services.agent.agent_auth import get_jwt_secret

        env = {"SECRET_KEY": "generic-secret"}
        with patch.dict(os.environ, env, clear=True):
            secret = get_jwt_secret()

        assert secret == "generic-secret"

    def test_no_secret_returns_none(self):
        """No secret configured should return None."""
        from brain_researcher.services.agent.agent_auth import get_jwt_secret

        with patch.dict(os.environ, {"BR_TESTING": "1"}, clear=True):
            secret = get_jwt_secret()

        assert secret is None
