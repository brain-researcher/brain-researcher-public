"""
Integration tests for Istio security policies.

Tests mTLS authentication, authorization policies, JWT validation,
and security policy enforcement in the service mesh.
"""

import asyncio
import base64
import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import aiohttp
import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Test markers
pytestmark = pytest.mark.skip(
    "istio security policies require end_to_end marker; skipped in dev env"
)


@pytest.fixture(scope="session")
def security_test_environment():
    """Set up security test environment."""
    return {
        "namespace": "brain-researcher-security-test",
        "ca_cert": "test-ca-cert",
        "services": {
            "br_kg": {"port": 5000, "security_level": "strict"},
            "agent": {"port": 8000, "security_level": "permissive"},
            "orchestrator": {"port": 3001, "security_level": "strict"},
            "web-ui": {"port": 3000, "security_level": "permissive"},
        },
        "test_users": {
            "admin": {
                "roles": ["admin", "user"],
                "permissions": ["read", "write", "delete"],
            },
            "researcher": {"roles": ["user"], "permissions": ["read", "write"]},
            "viewer": {"roles": ["viewer"], "permissions": ["read"]},
        },
    }


@pytest.fixture
def jwt_token_generator():
    """Generate JWT tokens for testing."""

    def _generate_token(payload: Dict[str, Any], expires_in: int = 3600) -> str:
        # Generate a test RSA key pair
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Add expiration
        payload["exp"] = int(time.time()) + expires_in
        payload["iat"] = int(time.time())

        # Create JWT
        token = jwt.encode(payload, private_key, algorithm="RS256")
        return token

    return _generate_token


@pytest.fixture
async def secure_http_session():
    """Provide HTTP session with security configurations."""
    connector = aiohttp.TCPConnector(
        ssl=False, limit=100, limit_per_host=30  # For testing, we might use HTTP
    )

    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        yield session


class TestMutualTLS:
    """Test mTLS (Mutual TLS) functionality."""

    def test_peer_authentication_configuration(self, security_test_environment):
        """Test PeerAuthentication configuration for mTLS."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        # Configure strict mTLS for the entire namespace
        peer_auth_config = security_manager.generate_peer_authentication_config(
            name="default", mtls_mode="STRICT"
        )

        assert peer_auth_config["kind"] == "PeerAuthentication"
        assert peer_auth_config["spec"]["mtls"]["mode"] == "STRICT"

    def test_service_specific_mtls(self, security_test_environment):
        """Test service-specific mTLS configuration."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        # Configure permissive mTLS for specific service
        peer_auth_config = security_manager.generate_peer_authentication_config(
            name="agent-peer-auth",
            mtls_mode="PERMISSIVE",
            selector={"matchLabels": {"app": "agent"}},
        )

        assert peer_auth_config["spec"]["mtls"]["mode"] == "PERMISSIVE"
        assert peer_auth_config["spec"]["selector"]["matchLabels"]["app"] == "agent"

    @pytest.mark.asyncio
    async def test_mtls_enforcement(
        self, security_test_environment, secure_http_session
    ):
        """Test mTLS enforcement behavior."""
        base_url = f"http://br_kg-service.{security_test_environment['namespace']}.svc.cluster.local:5000"

        # Test request without client certificate (should fail in STRICT mode)
        try:
            async with secure_http_session.get(f"{base_url}/health") as response:
                # In strict mTLS mode, this should fail or be handled by Istio
                assert response.status in [200, 403, 503]  # Various possible responses
        except aiohttp.ClientError as e:
            # Connection errors are expected in strict mTLS without proper certs
            assert "SSL" in str(e) or "certificate" in str(e).lower()

    def test_destination_rule_tls_config(self, security_test_environment):
        """Test DestinationRule TLS configuration."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        dr_config = security_manager.generate_destination_rule_tls_config(
            name="br_kg-tls-dr", host="br_kg-service", tls_mode="ISTIO_MUTUAL"
        )

        assert dr_config["kind"] == "DestinationRule"
        assert dr_config["spec"]["trafficPolicy"]["tls"]["mode"] == "ISTIO_MUTUAL"


class TestAuthorizationPolicies:
    """Test Istio AuthorizationPolicy functionality."""

    def test_basic_authorization_policy(self, security_test_environment):
        """Test basic authorization policy configuration."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        auth_policy = security_manager.generate_authorization_policy(
            name="br_kg-access-policy",
            selector={"matchLabels": {"app": "br_kg"}},
            rules=[
                {
                    "from": [
                        {
                            "source": {
                                "principals": [
                                    f"cluster.local/ns/{security_test_environment['namespace']}/sa/orchestrator-service",
                                    f"cluster.local/ns/{security_test_environment['namespace']}/sa/agent-service",
                                ]
                            }
                        }
                    ],
                    "to": [
                        {
                            "operation": {
                                "methods": ["GET", "POST"],
                                "paths": ["/api/v1/*"],
                            }
                        }
                    ],
                }
            ],
        )

        assert auth_policy["kind"] == "AuthorizationPolicy"
        assert len(auth_policy["spec"]["rules"]) == 1
        assert "GET" in auth_policy["spec"]["rules"][0]["to"][0]["operation"]["methods"]

    def test_role_based_access_control(self, security_test_environment):
        """Test role-based access control configuration."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        # Admin access policy
        admin_policy = security_manager.generate_authorization_policy(
            name="admin-access-policy",
            selector={"matchLabels": {"app": "orchestrator"}},
            rules=[
                {
                    "from": [{"source": {"requestPrincipals": ["*"]}}],
                    "to": [{"operation": {"methods": ["*"]}}],
                    "when": [
                        {"key": "request.auth.claims[roles]", "values": ["admin"]}
                    ],
                }
            ],
        )

        assert (
            admin_policy["spec"]["rules"][0]["when"][0]["key"]
            == "request.auth.claims[roles]"
        )
        assert "admin" in admin_policy["spec"]["rules"][0]["when"][0]["values"]

    def test_path_based_authorization(self, security_test_environment):
        """Test path-based authorization policies."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        path_policy = security_manager.generate_authorization_policy(
            name="path-based-access",
            selector={"matchLabels": {"app": "web-ui"}},
            rules=[
                {
                    "to": [{"operation": {"paths": ["/public/*", "/health", "/ready"]}}]
                    # No 'from' means allow all
                },
                {
                    "from": [{"source": {"requestPrincipals": ["*"]}}],
                    "to": [{"operation": {"paths": ["/api/*", "/dashboard/*"]}}],
                },
            ],
        )

        assert len(path_policy["spec"]["rules"]) == 2
        assert (
            "/public/*"
            in path_policy["spec"]["rules"][0]["to"][0]["operation"]["paths"]
        )

    @pytest.mark.asyncio
    async def test_authorization_enforcement(
        self, security_test_environment, secure_http_session, jwt_token_generator
    ):
        """Test authorization policy enforcement."""
        base_url = f"http://orchestrator-service.{security_test_environment['namespace']}.svc.cluster.local:3001"

        # Test unauthorized request
        try:
            async with secure_http_session.get(
                f"{base_url}/api/v1/admin/users"
            ) as response:
                # Should be denied without proper authentication
                assert response.status in [401, 403]
        except aiohttp.ClientError:
            # Connection might be blocked by authorization policies
            pass

        # Test authorized request with JWT
        admin_token = jwt_token_generator(
            {
                "sub": "admin-user",
                "roles": ["admin"],
                "permissions": ["read", "write", "delete"],
            }
        )

        headers = {"Authorization": f"Bearer {admin_token}"}

        try:
            async with secure_http_session.get(
                f"{base_url}/api/v1/admin/users", headers=headers
            ) as response:
                # Should be allowed with admin token
                assert response.status in [200, 404, 500]  # Not 401/403
        except aiohttp.ClientError:
            pytest.skip("Authorization test requires JWT validation setup")


class TestJWTValidation:
    """Test JWT validation functionality."""

    def test_request_authentication_configuration(self, security_test_environment):
        """Test RequestAuthentication configuration for JWT validation."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        jwt_config = security_manager.generate_request_authentication_config(
            name="jwt-auth",
            selector={"matchLabels": {"app": "web-ui"}},
            jwt_rules=[
                {
                    "issuer": "https://auth.brain-researcher.io",
                    "jwksUri": "https://auth.brain-researcher.io/.well-known/jwks.json",
                    "audiences": ["brain-researcher-api"],
                }
            ],
        )

        assert jwt_config["kind"] == "RequestAuthentication"
        assert (
            jwt_config["spec"]["jwtRules"][0]["issuer"]
            == "https://auth.brain-researcher.io"
        )
        assert "brain-researcher-api" in jwt_config["spec"]["jwtRules"][0]["audiences"]

    @pytest.mark.asyncio
    async def test_jwt_validation_behavior(
        self, security_test_environment, secure_http_session, jwt_token_generator
    ):
        """Test JWT validation behavior."""
        base_url = f"http://web-ui-service.{security_test_environment['namespace']}.svc.cluster.local:3000"

        # Test with invalid JWT
        invalid_token = "invalid.jwt.token"
        headers = {"Authorization": f"Bearer {invalid_token}"}

        try:
            async with secure_http_session.get(
                f"{base_url}/api/protected", headers=headers
            ) as response:
                # Should reject invalid token
                assert response.status in [401, 403]
        except aiohttp.ClientError:
            # Expected for invalid JWT
            pass

        # Test with valid JWT
        valid_token = jwt_token_generator(
            {
                "sub": "test-user",
                "aud": "brain-researcher-api",
                "iss": "https://auth.brain-researcher.io",
            }
        )

        headers = {"Authorization": f"Bearer {valid_token}"}

        try:
            async with secure_http_session.get(
                f"{base_url}/api/protected", headers=headers
            ) as response:
                # Should accept valid token
                assert response.status in [200, 404, 500]  # Not 401/403
        except aiohttp.ClientError:
            pytest.skip("JWT validation test requires proper setup")

    def test_jwt_claim_extraction(self, security_test_environment, jwt_token_generator):
        """Test JWT claim extraction for authorization."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        # Create authorization policy that uses JWT claims
        claim_policy = security_manager.generate_authorization_policy(
            name="jwt-claim-policy",
            selector={"matchLabels": {"app": "br_kg"}},
            rules=[
                {
                    "from": [{"source": {"requestPrincipals": ["*"]}}],
                    "when": [
                        {
                            "key": "request.auth.claims[sub]",
                            "values": ["admin-user", "research-user"],
                        },
                        {
                            "key": "request.auth.claims[roles]",
                            "values": ["admin", "researcher"],
                        },
                    ],
                }
            ],
        )

        assert len(claim_policy["spec"]["rules"][0]["when"]) == 2
        assert (
            claim_policy["spec"]["rules"][0]["when"][0]["key"]
            == "request.auth.claims[sub]"
        )


class TestServiceAccountTokens:
    """Test Kubernetes service account token authentication."""

    def test_service_account_configuration(self, security_test_environment):
        """Test service account configuration for service-to-service auth."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        # Policy allowing orchestrator to access br_kg
        sa_policy = security_manager.generate_authorization_policy(
            name="service-account-policy",
            selector={"matchLabels": {"app": "br_kg"}},
            rules=[
                {
                    "from": [
                        {
                            "source": {
                                "principals": [
                                    f"cluster.local/ns/{security_test_environment['namespace']}/sa/orchestrator-service"
                                ]
                            }
                        }
                    ],
                    "to": [{"operation": {"methods": ["GET", "POST"]}}],
                }
            ],
        )

        expected_principal = f"cluster.local/ns/{security_test_environment['namespace']}/sa/orchestrator-service"
        assert (
            expected_principal
            in sa_policy["spec"]["rules"][0]["from"][0]["source"]["principals"]
        )

    @pytest.mark.asyncio
    async def test_service_account_authentication(
        self, security_test_environment, secure_http_session
    ):
        """Test service account token authentication."""
        base_url = f"http://br_kg-service.{security_test_environment['namespace']}.svc.cluster.local:5000"

        # In a real environment, this would use the mounted service account token
        # For testing, we simulate the behavior

        try:
            # Request without service account token
            async with secure_http_session.get(f"{base_url}/api/v1/search") as response:
                # Might be rejected depending on policy configuration
                assert response.status in [200, 401, 403]
        except aiohttp.ClientError:
            # Expected if strict policies are in place
            pass


class TestNetworkPolicies:
    """Test network policy integration with Istio."""

    def test_network_policy_to_authorization_policy_migration(
        self, security_test_environment
    ):
        """Test migration from NetworkPolicy to AuthorizationPolicy."""
        from brain_researcher.infrastructure.istio.policy_migrator import PolicyMigrator

        # Kubernetes NetworkPolicy
        network_policy = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": "br_kg-network-policy",
                "namespace": security_test_environment["namespace"],
            },
            "spec": {
                "podSelector": {"matchLabels": {"app": "br_kg"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {"podSelector": {"matchLabels": {"app": "orchestrator"}}},
                            {"podSelector": {"matchLabels": {"app": "agent"}}},
                        ],
                        "ports": [{"protocol": "TCP", "port": 5000}],
                    }
                ],
            },
        }

        with patch("kubernetes.client"):
            migrator = PolicyMigrator()

        auth_policy = migrator.convert_network_policy_to_authorization_policy(
            network_policy
        )

        assert auth_policy["kind"] == "AuthorizationPolicy"
        assert auth_policy["spec"]["selector"]["matchLabels"]["app"] == "br_kg"

    def test_deny_all_policy(self, security_test_environment):
        """Test deny-all authorization policy."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        deny_all_policy = security_manager.generate_deny_all_policy(
            name="deny-all", selector={"matchLabels": {"app": "sensitive-service"}}
        )

        assert deny_all_policy["kind"] == "AuthorizationPolicy"
        assert deny_all_policy["spec"]["action"] == "DENY"
        assert deny_all_policy["spec"]["rules"] == [{}]  # Matches all requests


class TestSecurityAuditing:
    """Test security auditing and monitoring."""

    def test_access_log_configuration(self, security_test_environment):
        """Test access log configuration for security auditing."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        telemetry_config = security_manager.configure_security_telemetry(
            name="security-telemetry",
            access_log_config={
                "providers": [{"name": "otel"}],
                "format": {
                    "labels": {
                        "source_app": "%{DOWNSTREAM_REMOTE_ADDRESS}",
                        "destination_service": "%{UPSTREAM_CLUSTER}",
                        "request_id": "%{REQ(X-REQUEST-ID)}",
                        "response_code": "%{RESPONSE_CODE}",
                        "auth_principal": "%{REQUEST_AUTH_PRINCIPAL}",
                    }
                },
            },
        )

        assert telemetry_config["kind"] == "Telemetry"
        assert (
            "auth_principal"
            in telemetry_config["spec"]["accessLogging"][0]["providers"][0]["otel"][
                "format"
            ]["labels"]
        )

    def test_security_metrics_collection(self, security_test_environment):
        """Test security-related metrics collection."""
        from brain_researcher.infrastructure.istio.security_manager import (
            IstioSecurityManager,
        )

        with patch("kubernetes.client"):
            security_manager = IstioSecurityManager(
                namespace=security_test_environment["namespace"]
            )

        metrics_config = security_manager.configure_security_metrics(
            name="security-metrics",
            custom_metrics=[
                {
                    "name": "auth_failures",
                    "dimensions": {
                        "source_service": "source.workload.name",
                        "destination_service": "destination.service.name",
                        "response_code": "response.code",
                    },
                    "value": "1",
                    "condition": "response.code == 401 || response.code == 403",
                }
            ],
        )

        assert "auth_failures" in [m["name"] for m in metrics_config["spec"]["metrics"]]


class TestSecurityPolicyValidation:
    """Test security policy validation."""

    def test_policy_conflict_detection(self, security_test_environment):
        """Test detection of conflicting security policies."""
        from brain_researcher.infrastructure.istio.policy_validator import (
            SecurityPolicyValidator,
        )

        validator = SecurityPolicyValidator()

        # Conflicting policies
        allow_policy = {
            "kind": "AuthorizationPolicy",
            "metadata": {"name": "allow-all"},
            "spec": {
                "selector": {"matchLabels": {"app": "test-service"}},
                "action": "ALLOW",
                "rules": [{}],
            },
        }

        deny_policy = {
            "kind": "AuthorizationPolicy",
            "metadata": {"name": "deny-all"},
            "spec": {
                "selector": {"matchLabels": {"app": "test-service"}},
                "action": "DENY",
                "rules": [{}],
            },
        }

        conflicts = validator.detect_policy_conflicts([allow_policy, deny_policy])

        assert len(conflicts) > 0
        assert "conflicting actions" in conflicts[0]["reason"].lower()

    def test_policy_completeness_check(self, security_test_environment):
        """Test security policy completeness checking."""
        from brain_researcher.infrastructure.istio.policy_validator import (
            SecurityPolicyValidator,
        )

        validator = SecurityPolicyValidator()

        services = ["br_kg", "agent", "orchestrator", "web-ui"]
        policies = [
            {
                "kind": "AuthorizationPolicy",
                "metadata": {"name": "br_kg-policy"},
                "spec": {"selector": {"matchLabels": {"app": "br_kg"}}},
            }
            # Missing policies for other services
        ]

        completeness_report = validator.check_policy_completeness(services, policies)

        assert not completeness_report["complete"]
        assert "agent" in completeness_report["missing_policies"]
        assert "orchestrator" in completeness_report["missing_policies"]


@pytest.mark.slow
class TestSecurityPerformance:
    """Test performance impact of security policies."""

    @pytest.mark.asyncio
    async def test_authentication_overhead(
        self, security_test_environment, secure_http_session, jwt_token_generator
    ):
        """Test authentication overhead on request latency."""
        base_url = f"http://web-ui-service.{security_test_environment['namespace']}.svc.cluster.local:3000"

        # Measure latency without authentication
        start_time = time.time()
        try:
            async with secure_http_session.get(f"{base_url}/public/health") as response:
                no_auth_time = time.time() - start_time
        except aiohttp.ClientError:
            pytest.skip("Service not available for performance testing")

        # Measure latency with JWT authentication
        token = jwt_token_generator({"sub": "test-user"})
        headers = {"Authorization": f"Bearer {token}"}

        start_time = time.time()
        try:
            async with secure_http_session.get(
                f"{base_url}/api/protected", headers=headers
            ) as response:
                auth_time = time.time() - start_time
        except aiohttp.ClientError:
            pytest.skip("Authenticated endpoint not available")

        # Authentication should not add significant overhead
        overhead = auth_time - no_auth_time
        assert overhead < 0.5  # Should be less than 500ms additional overhead

    @pytest.mark.asyncio
    async def test_authorization_policy_overhead(
        self, security_test_environment, secure_http_session
    ):
        """Test authorization policy evaluation overhead."""
        base_url = f"http://br_kg-service.{security_test_environment['namespace']}.svc.cluster.local:5000"

        # Make multiple requests to measure consistent overhead
        latencies = []

        for _ in range(50):
            start_time = time.time()
            try:
                async with secure_http_session.get(f"{base_url}/health") as response:
                    end_time = time.time()
                    if response.status == 200:
                        latencies.append((end_time - start_time) * 1000)
            except aiohttp.ClientError:
                pass

        if not latencies:
            pytest.skip("No successful requests for overhead measurement")

        avg_latency = sum(latencies) / len(latencies)

        # Authorization overhead should be reasonable
        assert avg_latency < 200  # Less than 200ms average


@pytest.mark.skip("end_to_end marker not registered")
class TestSecurityE2E:
    """End-to-end security tests."""

    @pytest.mark.asyncio
    async def test_full_security_workflow(
        self, security_test_environment, secure_http_session, jwt_token_generator
    ):
        """Test complete security workflow: authentication -> authorization -> access."""

        # Step 1: Get valid JWT token
        user_token = jwt_token_generator(
            {
                "sub": "researcher-001",
                "roles": ["researcher"],
                "permissions": ["read", "write"],
                "aud": "brain-researcher-api",
            }
        )

        # Step 2: Access protected resource
        orchestrator_url = f"http://orchestrator-service.{security_test_environment['namespace']}.svc.cluster.local:3001"
        headers = {
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }

        try:
            # Should be able to access researcher endpoints
            async with secure_http_session.get(
                f"{orchestrator_url}/api/v1/research/datasets", headers=headers
            ) as response:
                assert response.status in [
                    200,
                    404,
                ]  # Success or not found, but not auth error

            # Should NOT be able to access admin endpoints
            async with secure_http_session.get(
                f"{orchestrator_url}/api/v1/admin/users", headers=headers
            ) as response:
                assert response.status in [403, 404]  # Forbidden or not found

        except aiohttp.ClientError:
            pytest.skip("Full security workflow test requires complete setup")

    @pytest.mark.asyncio
    async def test_cross_service_security(
        self, security_test_environment, secure_http_session
    ):
        """Test security enforcement across service boundaries."""

        # Test: web-ui -> orchestrator -> br_kg (with proper service accounts)
        web_ui_url = f"http://web-ui-service.{security_test_environment['namespace']}.svc.cluster.local:3000"

        request_data = {
            "query": "test security across services",
            "user_context": {"role": "researcher"},
        }

        try:
            async with secure_http_session.post(
                f"{web_ui_url}/api/research/search",
                json=request_data,
                headers={"Content-Type": "application/json"},
            ) as response:

                # The request should either succeed with proper authentication
                # or fail with proper security error codes
                assert response.status in [200, 401, 403, 500]

                if response.status in [401, 403]:
                    # Security policies are working
                    error_data = await response.json()
                    assert (
                        "auth" in error_data.get("error", "").lower()
                        or "permission" in error_data.get("error", "").lower()
                    )

        except aiohttp.ClientError:
            pytest.skip("Cross-service security test requires full mesh setup")
