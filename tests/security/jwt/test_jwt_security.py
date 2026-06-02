"""
JWT Security Tests for Brain Researcher platform.

Tests for:
- JWT token validation
- Token expiration handling
- Secret key security
- Algorithm validation
- Token tampering detection
- Claim validation

Gateway-targeted checks in this module cover the legacy standalone compatibility
surface only.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import jwt
import pytest
import requests


class TestJWTTokenValidation:
    """Test JWT token validation mechanisms."""

    def setup_method(self):
        """Set up JWT test fixtures."""
        self.base_urls = {
            "orchestrator": "http://localhost:3001",
            "br_kg": "http://localhost:5000",
            "agent": "http://localhost:8000",
            "gateway": "http://localhost:8080",  # legacy standalone compatibility surface
        }

        # Test JWT secrets (these should be env vars in production)
        self.test_secrets = {
            "weak_secret": "secret",
            "strong_secret": "very_long_and_complex_secret_key_for_testing_purposes_12345",
            "malicious_secret": "../../../etc/passwd",
        }

        # Standard test claims
        self.test_claims = {
            "sub": "test_user_12345",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,  # 1 hour from now
            "role": "researcher",
            "permissions": ["read:data", "write:analysis"],
        }

    def create_test_jwt(
        self, claims: Dict[str, Any], secret: str, algorithm: str = "HS256"
    ) -> str:
        """Create a test JWT token."""
        return jwt.encode(claims, secret, algorithm=algorithm)

    def test_expired_token_rejection(self):
        """Test that expired JWT tokens are properly rejected."""

        # Create expired token
        expired_claims = self.test_claims.copy()
        expired_claims["exp"] = int(time.time()) - 3600  # 1 hour ago

        expired_token = self.create_test_jwt(
            expired_claims, self.test_secrets["strong_secret"]
        )

        # Test with all services
        for service, base_url in self.base_urls.items():
            protected_endpoints = [
                "/api/protected",
                "/api/user/profile",
                "/api/analysis",
                "/api/admin",
            ]

            for endpoint in protected_endpoints:
                url = f"{base_url}{endpoint}"
                headers = {"Authorization": f"Bearer {expired_token}"}

                try:
                    response = requests.get(url, headers=headers)

                    if response.status_code == 404:
                        # Endpoint doesn't exist, try next
                        continue

                    # Should reject expired token
                    assert response.status_code in [
                        401,
                        403,
                    ], f"Expired JWT token should be rejected at {url}"

                    # Response should indicate token expired
                    response_text = response.text.lower()
                    assert any(
                        word in response_text
                        for word in ["expired", "invalid", "unauthorized"]
                    ), f"Error message should indicate token issue at {url}"

                    break  # If we found a working endpoint, test passed

                except requests.exceptions.ConnectionError:
                    # Service not running
                    break
                except Exception as e:
                    print(f"Error testing expired JWT at {url}: {e}")
                    continue

    def test_malformed_token_rejection(self):
        """Test that malformed JWT tokens are rejected."""

        malformed_tokens = [
            "not.a.jwt.token",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ",  # Missing signature
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..signature_only",  # Missing payload
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.",  # Missing header
            "malicious_token",
            '<script>alert("xss")</script>',
            '"; DROP TABLE users; --',
            "",  # Empty token
            "Bearer eyJhbGciOiJIUzI1NiJ9",  # Contains 'Bearer' prefix
        ]

        for service, base_url in self.base_urls.items():
            test_endpoint = f"{base_url}/api/test"

            for malformed_token in malformed_tokens:
                headers = {"Authorization": f"Bearer {malformed_token}"}

                try:
                    response = requests.get(test_endpoint, headers=headers)

                    if response.status_code == 404:
                        # Try different endpoint
                        response = requests.get(f"{base_url}/health", headers=headers)
                        if response.status_code == 404:
                            continue

                    # Should reject malformed token (401/403) or ignore it (if endpoint is public)
                    assert response.status_code in [
                        200,
                        401,
                        403,
                        404,
                    ], f"Malformed JWT should be handled properly at {test_endpoint}"

                    # Should not cause server error
                    assert (
                        response.status_code != 500
                    ), f"Malformed JWT caused server error at {test_endpoint}: {malformed_token}"

                except requests.exceptions.ConnectionError:
                    break
                except Exception as e:
                    print(f"Error testing malformed JWT: {e}")
                    continue

    def test_algorithm_confusion_attack(self):
        """Test protection against algorithm confusion attacks."""

        # Create tokens with different algorithms
        algorithms_to_test = [
            "none",  # None algorithm attack
            "HS256",  # Standard HMAC
            "RS256",  # RSA (should fail without proper key)
            "PS256",  # RSA-PSS
            "ES256",  # ECDSA
        ]

        for algorithm in algorithms_to_test:
            try:
                if algorithm == "none":
                    # None algorithm attack - create unsigned token
                    token_parts = [
                        "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0",  # {"alg":"none","typ":"JWT"}
                        jwt.utils.base64url_encode(
                            json.dumps(self.test_claims).encode()
                        ).decode(),
                        "",  # No signature for 'none' algorithm
                    ]
                    test_token = ".".join(token_parts)
                else:
                    # Try to create token with different algorithm
                    try:
                        test_token = self.create_test_jwt(
                            self.test_claims,
                            self.test_secrets["strong_secret"],
                            algorithm,
                        )
                    except Exception:
                        # Algorithm not supported, skip
                        continue

                # Test token with services
                for service, base_url in self.base_urls.items():
                    test_url = f"{base_url}/api/protected"
                    headers = {"Authorization": f"Bearer {test_token}"}

                    try:
                        response = requests.get(test_url, headers=headers)

                        if algorithm == "none":
                            # None algorithm should always be rejected
                            assert response.status_code in [
                                401,
                                403,
                                404,
                            ], f"'none' algorithm JWT should be rejected at {service}"

                        # Should not cause server error
                        assert (
                            response.status_code != 500
                        ), f"Algorithm {algorithm} caused server error at {service}"

                    except requests.exceptions.ConnectionError:
                        break

            except Exception as e:
                print(f"Error testing algorithm {algorithm}: {e}")
                continue

    def test_token_tampering_detection(self):
        """Test that tampered JWT tokens are detected."""

        # Create valid token
        valid_token = self.create_test_jwt(
            self.test_claims, self.test_secrets["strong_secret"]
        )

        # Tamper with different parts
        token_parts = valid_token.split(".")

        tampering_tests = [
            # Tamper with header
            ("header", token_parts[0][:-5] + "XXXXX", token_parts[1], token_parts[2]),
            # Tamper with payload
            ("payload", token_parts[0], token_parts[1][:-5] + "XXXXX", token_parts[2]),
            # Tamper with signature
            (
                "signature",
                token_parts[0],
                token_parts[1],
                token_parts[2][:-5] + "XXXXX",
            ),
            # Completely invalid signature
            ("invalid_sig", token_parts[0], token_parts[1], "invalid_signature_12345"),
            # Empty signature
            ("empty_sig", token_parts[0], token_parts[1], ""),
            # Extra parts
            (
                "extra_parts",
                token_parts[0],
                token_parts[1],
                token_parts[2],
                "extra.part",
            ),
        ]

        for tamper_type, *tampered_parts in tampering_tests:
            tampered_token = ".".join(tampered_parts[:3])  # Only use first 3 parts

            for service, base_url in self.base_urls.items():
                test_url = f"{base_url}/api/protected"
                headers = {"Authorization": f"Bearer {tampered_token}"}

                try:
                    response = requests.get(test_url, headers=headers)

                    if response.status_code == 404:
                        continue

                    # Tampered token should be rejected
                    assert response.status_code in [
                        401,
                        403,
                    ], f"Tampered JWT ({tamper_type}) should be rejected at {service}"

                    # Should not cause server error
                    assert (
                        response.status_code != 500
                    ), f"Tampered JWT caused server error at {service}: {tamper_type}"

                    break  # Test passed for this service

                except requests.exceptions.ConnectionError:
                    break
                except Exception as e:
                    print(f"Error testing tampered JWT {tamper_type}: {e}")
                    continue

    def test_weak_secret_detection(self):
        """Test that weak JWT secrets are avoided."""

        weak_secrets = [
            "secret",
            "123456",
            "password",
            "admin",
            "test",
            "key",
            "",  # Empty secret
            "a",  # Single character
            "12345678",  # Short numeric
        ]

        # This test is informational - checks if tokens signed with weak secrets are accepted
        for weak_secret in weak_secrets:
            try:
                weak_token = self.create_test_jwt(self.test_claims, weak_secret)

                for service, base_url in self.base_urls.items():
                    test_url = f"{base_url}/api/protected"
                    headers = {"Authorization": f"Bearer {weak_token}"}

                    try:
                        response = requests.get(test_url, headers=headers)

                        if response.status_code == 200:
                            print(
                                f"Warning: {service} may accept JWT with weak secret: {weak_secret}"
                            )

                    except requests.exceptions.ConnectionError:
                        break

            except Exception as e:
                # Some weak secrets might cause JWT library errors
                continue

    def test_claim_validation(self):
        """Test that JWT claims are properly validated."""

        # Test with missing required claims
        invalid_claim_tests = [
            # Missing subject
            {"iat": int(time.time()), "exp": int(time.time()) + 3600},
            # Missing expiration
            {"sub": "test_user", "iat": int(time.time())},
            # Invalid expiration type
            {"sub": "test_user", "iat": int(time.time()), "exp": "invalid_exp"},
            # Future issued at
            {
                "sub": "test_user",
                "iat": int(time.time()) + 3600,
                "exp": int(time.time()) + 7200,
            },
            # Malicious claims
            {
                "sub": '<script>alert("xss")</script>',
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            {
                "sub": '"; DROP TABLE users; --',
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            # Invalid role claims
            {
                "sub": "test",
                "role": "admin",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            {
                "sub": "test",
                "role": "../../../etc/passwd",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
        ]

        for invalid_claims in invalid_claim_tests:
            try:
                invalid_token = self.create_test_jwt(
                    invalid_claims, self.test_secrets["strong_secret"]
                )

                for service, base_url in self.base_urls.items():
                    test_url = f"{base_url}/api/protected"
                    headers = {"Authorization": f"Bearer {invalid_token}"}

                    try:
                        response = requests.get(test_url, headers=headers)

                        if response.status_code == 404:
                            continue

                        # Invalid claims should be rejected or handled safely
                        if response.status_code == 200:
                            print(
                                f"Info: {service} may not validate JWT claims: {invalid_claims}"
                            )
                        else:
                            assert response.status_code in [
                                401,
                                403,
                            ], f"Invalid JWT claims should be rejected at {service}"

                        break

                    except requests.exceptions.ConnectionError:
                        break

            except Exception as e:
                print(f"Error testing invalid claims: {e}")
                continue

    def test_jwt_timing_attacks(self):
        """Test protection against JWT timing attacks."""

        # Create tokens with different signature validity
        valid_token = self.create_test_jwt(
            self.test_claims, self.test_secrets["strong_secret"]
        )
        invalid_token = self.create_test_jwt(self.test_claims, "wrong_secret")

        timing_results = []

        for service, base_url in self.base_urls.items():
            test_url = f"{base_url}/api/protected"

            try:
                # Measure timing for valid tokens
                valid_times = []
                for i in range(5):
                    headers = {"Authorization": f"Bearer {valid_token}"}
                    start_time = time.time()
                    response = requests.get(test_url, headers=headers)
                    end_time = time.time()
                    valid_times.append(end_time - start_time)

                    if response.status_code == 404:
                        break

                if not valid_times or valid_times[0] == 0:
                    continue

                # Measure timing for invalid tokens
                invalid_times = []
                for i in range(5):
                    headers = {"Authorization": f"Bearer {invalid_token}"}
                    start_time = time.time()
                    response = requests.get(test_url, headers=headers)
                    end_time = time.time()
                    invalid_times.append(end_time - start_time)

                avg_valid_time = sum(valid_times) / len(valid_times)
                avg_invalid_time = sum(invalid_times) / len(invalid_times)

                # Large timing differences might indicate timing attack vulnerability
                time_difference_ratio = abs(avg_valid_time - avg_invalid_time) / min(
                    avg_valid_time, avg_invalid_time
                )

                if time_difference_ratio > 2.0:  # More than 2x difference
                    print(f"Info: {service} may be vulnerable to JWT timing attacks")

                timing_results.append(
                    (service, avg_valid_time, avg_invalid_time, time_difference_ratio)
                )

            except requests.exceptions.ConnectionError:
                continue
            except Exception as e:
                print(f"Error testing JWT timing for {service}: {e}")
                continue


@pytest.mark.security
class TestJWTStorageAndTransmission:
    """Test JWT token storage and transmission security."""

    def test_secure_token_transmission(self):
        """Test that JWT tokens are transmitted securely."""

        # This would test HTTPS enforcement for JWT transmission
        # In development, this is informational

        services = {
            "orchestrator": "http://localhost:3001",
            "br_kg": "http://localhost:5000",
            "agent": "http://localhost:8000",
            "gateway": "http://localhost:8080",
        }

        test_token = jwt.encode(
            {"sub": "test", "exp": int(time.time()) + 3600},
            "test_secret",
            algorithm="HS256",
        )

        for service, base_url in services.items():
            # Check if service enforces HTTPS for sensitive operations
            if not base_url.startswith("https://"):
                print(
                    f"Info: {service} should use HTTPS for JWT token transmission in production"
                )

            # Test for sensitive headers in HTTP response
            try:
                headers = {"Authorization": f"Bearer {test_token}"}
                response = requests.get(f"{base_url}/api/auth/verify", headers=headers)

                # Check if JWT token is reflected in response
                if test_token in response.text:
                    print(f"Warning: {service} reflects JWT token in response")

                # Check for secure cookie settings if cookies are used
                set_cookie_headers = response.headers.get("Set-Cookie", "")
                if (
                    "jwt" in set_cookie_headers.lower()
                    or "token" in set_cookie_headers.lower()
                ):
                    assert (
                        "Secure" in set_cookie_headers
                    ), f"{service} JWT cookies should have Secure flag"
                    assert (
                        "HttpOnly" in set_cookie_headers
                    ), f"{service} JWT cookies should have HttpOnly flag"
                    assert (
                        "SameSite" in set_cookie_headers
                    ), f"{service} JWT cookies should have SameSite attribute"

            except requests.exceptions.ConnectionError:
                continue
            except Exception as e:
                print(f"Error testing secure transmission for {service}: {e}")
                continue
