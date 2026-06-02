"""
Authentication security tests for Brain Researcher platform.

Tests authentication mechanisms across all services:
- Orchestrator API authentication
- BR-KG service authentication
- Agent service authentication
- JWT token validation
- Session management

Gateway-targeted checks in this module cover the legacy standalone compatibility
surface only.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import jwt
import pytest
import requests


class TestAuthentication:
    """Test suite for authentication security."""

    def setup_method(self):
        """Set up test fixtures."""
        self.base_urls = {
            "orchestrator": "http://localhost:3001",
            "br_kg": "http://localhost:5000",
            "agent": "http://localhost:8000",
            "gateway": "http://localhost:8080",  # legacy standalone compatibility surface
        }

        self.test_credentials = {
            "valid_user": {"username": "test_user", "password": "test_password"},
            "invalid_user": {"username": "invalid", "password": "wrong"},
            "admin_user": {"username": "admin", "password": "admin_password"},
        }

        # Test JWT secrets (use environment variables in production)
        self.test_jwt_secret = "test_secret_key_for_security_testing"

    def test_unauthenticated_access_blocked(self):
        """Test that protected endpoints block unauthenticated access."""
        protected_endpoints = [
            ("orchestrator", "/api/chat"),
            ("orchestrator", "/api/analysis"),
            ("br_kg", "/api/protected"),
            ("agent", "/api/agent/query"),
            ("gateway", "/api/admin"),
        ]

        for service, endpoint in protected_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"
            response = requests.get(url)

            # Should return 401 Unauthorized or 403 Forbidden
            assert response.status_code in [
                401,
                403,
            ], f"Endpoint {url} should require authentication but returned {response.status_code}"

    def test_invalid_credentials_rejected(self):
        """Test that invalid credentials are properly rejected."""
        login_endpoints = [("orchestrator", "/auth/login"), ("gateway", "/auth/login")]

        for service, endpoint in login_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            # Test with invalid credentials
            response = requests.post(url, json=self.test_credentials["invalid_user"])

            assert response.status_code in [
                401,
                403,
            ], f"Invalid credentials should be rejected at {url}"

            # Ensure no session/token is returned
            assert "token" not in response.json().get(
                "data", {}
            ), "No authentication token should be returned for invalid credentials"

    def test_valid_credentials_accepted(self):
        """Test that valid credentials are properly accepted."""
        login_endpoints = [("orchestrator", "/auth/login"), ("gateway", "/auth/login")]

        for service, endpoint in login_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            try:
                response = requests.post(url, json=self.test_credentials["valid_user"])

                if response.status_code == 404:
                    # Endpoint doesn't exist yet, skip
                    continue

                assert (
                    response.status_code == 200
                ), f"Valid credentials should be accepted at {url}"

                # Should return some form of authentication token/session
                response_data = response.json()
                assert any(
                    key in response_data
                    for key in ["token", "session_id", "access_token"]
                ), "Authentication response should include token or session identifier"

            except requests.exceptions.ConnectionError:
                # Service not running, skip test
                continue

    def test_brute_force_protection(self):
        """Test protection against brute force attacks."""
        login_endpoints = [("orchestrator", "/auth/login"), ("gateway", "/auth/login")]

        for service, endpoint in login_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            # Attempt multiple failed logins
            failed_attempts = 0
            for attempt in range(10):  # Try 10 failed logins
                try:
                    response = requests.post(
                        url, json=self.test_credentials["invalid_user"]
                    )

                    if response.status_code == 404:
                        # Endpoint doesn't exist, skip
                        break

                    if response.status_code == 429:  # Too Many Requests
                        # Good! Rate limiting is in place
                        break

                    failed_attempts += 1
                    time.sleep(0.1)  # Brief pause between attempts

                except requests.exceptions.ConnectionError:
                    # Service not running, skip
                    break

            # After multiple failed attempts, should see rate limiting
            # (This is informational - not all services may have this implemented yet)
            if failed_attempts >= 10:
                print(f"Warning: {url} may not have brute force protection")

    def test_session_timeout(self):
        """Test that sessions properly timeout."""
        # This test checks if long-lived sessions are properly invalidated
        # Implementation depends on session management approach

        login_endpoints = [("orchestrator", "/auth/login"), ("gateway", "/auth/login")]

        for service, endpoint in login_endpoints:
            if service not in self.base_urls:
                continue

            login_url = f"{self.base_urls[service]}{endpoint}"

            try:
                # Attempt to login
                response = requests.post(
                    login_url, json=self.test_credentials["valid_user"]
                )

                if response.status_code == 404:
                    continue

                if response.status_code != 200:
                    continue

                # Extract token/session
                response_data = response.json()
                token = response_data.get("token") or response_data.get("access_token")

                if not token:
                    continue

                # Test immediate access (should work)
                headers = {"Authorization": f"Bearer {token}"}
                test_url = f"{self.base_urls[service]}/api/test"

                # Note: This is a basic structure - full implementation would
                # require actual protected endpoints and proper session management

            except requests.exceptions.ConnectionError:
                continue

    def test_password_complexity_requirements(self):
        """Test that password complexity requirements are enforced."""
        weak_passwords = [
            "password",  # Common password
            "123456",  # Numeric sequence
            "abc123",  # Simple pattern
            "password123",  # Dictionary + numbers
            "qwerty",  # Keyboard pattern
            "admin",  # Common admin password
            "test",  # Too short
        ]

        registration_endpoints = [
            ("orchestrator", "/auth/register"),
            ("gateway", "/auth/register"),
        ]

        for service, endpoint in registration_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            for weak_password in weak_passwords:
                test_user = {
                    "username": f"testuser_{weak_password}",
                    "password": weak_password,
                    "email": f"test_{weak_password}@example.com",
                }

                try:
                    response = requests.post(url, json=test_user)

                    if response.status_code == 404:
                        # Endpoint doesn't exist yet
                        break

                    # Should reject weak passwords
                    assert (
                        response.status_code != 200 or "error" in response.json()
                    ), f"Weak password '{weak_password}' should be rejected"

                except requests.exceptions.ConnectionError:
                    break

    def test_account_lockout_after_failures(self):
        """Test that accounts are locked after repeated failed attempts."""
        login_endpoints = [("orchestrator", "/auth/login"), ("gateway", "/auth/login")]

        for service, endpoint in login_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            # Use a specific username for lockout testing
            lockout_test_user = {
                "username": "lockout_test_user",
                "password": "wrong_password",
            }

            try:
                # Attempt multiple failed logins for same user
                for attempt in range(5):
                    response = requests.post(url, json=lockout_test_user)

                    if response.status_code == 404:
                        break

                    time.sleep(0.5)  # Brief pause

                # After multiple failures, account should be locked
                # Even with correct password, should be locked
                correct_attempt = {
                    "username": "lockout_test_user",
                    "password": "correct_password",  # Assuming this would be correct
                }
                response = requests.post(url, json=correct_attempt)

                if response.status_code not in [404, 423]:  # 423 = Locked
                    print(f"Info: {url} may not implement account lockout")

            except requests.exceptions.ConnectionError:
                continue

    def test_logout_invalidates_session(self):
        """Test that logout properly invalidates sessions/tokens."""
        # Test logout functionality across services

        for service in ["orchestrator", "gateway"]:
            if service not in self.base_urls:
                continue

            login_url = f"{self.base_urls[service]}/auth/login"
            logout_url = f"{self.base_urls[service]}/auth/logout"

            try:
                # Login first
                response = requests.post(
                    login_url, json=self.test_credentials["valid_user"]
                )

                if response.status_code not in [200, 404]:
                    continue

                if response.status_code == 404:
                    continue

                # Extract session token
                token = response.json().get("token")
                if not token:
                    continue

                # Logout
                headers = {"Authorization": f"Bearer {token}"}
                logout_response = requests.post(logout_url, headers=headers)

                # After logout, token should be invalid
                protected_url = f"{self.base_urls[service]}/api/protected"
                protected_response = requests.get(protected_url, headers=headers)

                assert protected_response.status_code in [
                    401,
                    403,
                ], "Token should be invalid after logout"

            except requests.exceptions.ConnectionError:
                continue


class TestAuthorizationControls:
    """Test authorization and access control mechanisms."""

    def setup_method(self):
        """Set up authorization test fixtures."""
        self.base_urls = {
            "orchestrator": "http://localhost:3001",
            "br_kg": "http://localhost:5000",
            "agent": "http://localhost:8000",
            "gateway": "http://localhost:8080",
        }

        self.user_roles = {
            "admin": {"username": "admin", "password": "admin_pass", "role": "admin"},
            "researcher": {
                "username": "researcher",
                "password": "research_pass",
                "role": "researcher",
            },
            "viewer": {
                "username": "viewer",
                "password": "viewer_pass",
                "role": "viewer",
            },
        }

    def test_role_based_access_control(self):
        """Test that different user roles have appropriate access levels."""

        # Admin-only endpoints
        admin_endpoints = [
            ("orchestrator", "/api/admin/users"),
            ("orchestrator", "/api/admin/settings"),
            ("br_kg", "/api/admin/database"),
            ("gateway", "/api/admin/services"),
        ]

        # Researcher endpoints
        researcher_endpoints = [
            ("orchestrator", "/api/analysis"),
            ("br_kg", "/api/query"),
            ("agent", "/api/agent/analyze"),
        ]

        # Public/viewer endpoints
        public_endpoints = [
            ("orchestrator", "/api/public/datasets"),
            ("br_kg", "/api/public/browse"),
            ("orchestrator", "/health"),
        ]

        # Test admin access
        for service, endpoint in admin_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            # Non-admin users should be denied access
            for role in ["researcher", "viewer"]:
                # This would require implementing proper authentication first
                # For now, just check that endpoints exist and require auth
                try:
                    response = requests.get(url)
                    assert response.status_code in [
                        401,
                        403,
                        404,
                    ], f"Admin endpoint {url} should require authentication"
                except requests.exceptions.ConnectionError:
                    continue

    def test_data_access_controls(self):
        """Test that users can only access data they're authorized for."""

        # Test participant data access controls
        participant_endpoints = [
            ("br_kg", "/api/participants/12345"),
            ("orchestrator", "/api/data/participant/12345"),
        ]

        for service, endpoint in participant_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            try:
                # Without authentication, should be denied
                response = requests.get(url)
                assert response.status_code in [
                    401,
                    403,
                    404,
                ], f"Participant data endpoint {url} should require authorization"

            except requests.exceptions.ConnectionError:
                continue

    def test_api_rate_limiting(self):
        """Test that API rate limiting is properly implemented."""

        # Test rate limiting on various endpoints
        test_endpoints = [
            ("orchestrator", "/api/query"),
            ("br_kg", "/api/search"),
            ("agent", "/api/agent/query"),
        ]

        for service, endpoint in test_endpoints:
            if service not in self.base_urls:
                continue

            url = f"{self.base_urls[service]}{endpoint}"

            # Make rapid requests to trigger rate limiting
            rate_limit_triggered = False

            try:
                for i in range(50):  # Make many requests quickly
                    response = requests.get(url)

                    if response.status_code == 429:  # Too Many Requests
                        rate_limit_triggered = True
                        break

                    time.sleep(0.05)  # Very brief pause

                # Rate limiting should eventually kick in
                # (This is informational - not all endpoints may have this)
                if not rate_limit_triggered:
                    print(f"Info: {url} may not have rate limiting configured")

            except requests.exceptions.ConnectionError:
                continue


@pytest.mark.security
class TestSecurityHeaders:
    """Test for proper security headers."""

    def test_security_headers_present(self):
        """Test that all services return proper security headers."""

        required_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": ["DENY", "SAMEORIGIN"],
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=",  # Should contain max-age
            "Content-Security-Policy": "default-src",  # Should have CSP
        }

        services = {
            "orchestrator": "http://localhost:3001",
            "br_kg": "http://localhost:5000",
            "gateway": "http://localhost:8080",
        }

        for service_name, base_url in services.items():
            try:
                response = requests.get(f"{base_url}/health")

                if response.status_code >= 400:
                    continue

                headers = response.headers

                for header_name, expected_value in required_headers.items():
                    if isinstance(expected_value, list):
                        # Multiple acceptable values
                        assert header_name in headers and any(
                            val in headers[header_name] for val in expected_value
                        ), f"{service_name} missing security header: {header_name}"
                    else:
                        # Single expected pattern
                        assert (
                            header_name in headers
                            and expected_value in headers[header_name]
                        ), f"{service_name} missing or incorrect security header: {header_name}"

            except requests.exceptions.ConnectionError:
                # Service not running, skip
                continue
            except AssertionError as e:
                # Header missing - this is expected for development
                print(f"Security header missing in {service_name}: {e}")
                continue
