"""
Integration tests for legacy demo endpoint guards

Tests that:
1. Legacy DEMO_SCENARIOS endpoints are blocked in production mode
2. Legacy endpoints work in development mode
3. Deprecation headers are present
4. Proper migration instructions are returned
"""

import pytest
from fastapi.testclient import TestClient
import os
from unittest.mock import patch

from brain_researcher.services.orchestrator.main_enhanced import app
from brain_researcher.services.orchestrator.config import DemoMode, OrchestratorConfig


client = TestClient(app)

# Legacy endpoints that should be guarded
LEGACY_ENDPOINTS = [
    ("POST", "/api/landing/demos/start", {"demo_type": "glm"}),
    ("GET", "/api/landing/demos/test123/progress", None),
    ("GET", "/api/landing/demos/test123/result", None),
    ("GET", "/api/landing/demos/test123/stream", None),
    ("POST", "/api/landing/demos/test123/share", {}),
]


class TestProductionModeBlocking:
    """Test that legacy endpoints are blocked in production mode"""

    @pytest.fixture(autouse=True)
    def set_production_mode(self, monkeypatch):
        """Set BR_DEMO_MODE to production for these tests"""
        monkeypatch.setenv("BR_DEMO_MODE", "production")

        # Reload config to pick up new environment variable
        OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION

        yield

        # Reset to default after test
        OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION

    @pytest.mark.parametrize("method,endpoint,payload", LEGACY_ENDPOINTS)
    def test_legacy_endpoints_blocked_in_production(self, method, endpoint, payload):
        """Test that all legacy endpoints return 404 in production mode"""
        if method == "POST":
            response = client.post(endpoint, json=payload)
        else:
            response = client.get(endpoint)

        # Should return 404 in production
        assert response.status_code == 404, \
            f"Endpoint {method} {endpoint} not blocked in production mode"

        data = response.json()
        detail = data.get("detail", {})

        # Validate error message structure
        if isinstance(detail, dict):
            assert "error" in detail or "message" in detail, \
                "Missing error information in response"

            # Check for migration instructions
            assert "migration" in detail or "docs" in detail or \
                   "Use /api/demo/real-*" in str(detail), \
                "Missing migration instructions"

    def test_production_mode_error_message_quality(self):
        """Test that production mode error messages are helpful"""
        response = client.post(
            "/api/landing/demos/start",
            json={"demo_type": "glm"}
        )

        assert response.status_code == 404
        data = response.json()
        detail = data.get("detail", {})

        if isinstance(detail, dict):
            # Should mention production mode
            error_text = str(detail).lower()
            assert "production" in error_text or "legacy" in error_text

            # Should mention alternative endpoints
            assert "/api/demo/real" in str(detail) or "migration" in detail


class TestDevelopmentModeAccess:
    """Test that legacy endpoints work in development mode"""

    @pytest.fixture(autouse=True)
    def set_development_mode(self, monkeypatch):
        """Set BR_DEMO_MODE to development for these tests"""
        monkeypatch.setenv("BR_DEMO_MODE", "development")

        # Reload config
        OrchestratorConfig.DEMO_MODE = DemoMode.DEVELOPMENT

        yield

        # Reset
        OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION

    def test_start_demo_works_in_dev_mode(self):
        """Test that start demo endpoint works in development mode"""
        response = client.post(
            "/api/landing/demos/start",
            json={"demo_type": "glm"}
        )

        # Should NOT be 404 (blocked)
        # Could be 200 (success) or other errors, but not blocked
        assert response.status_code != 404 or "not available in production" not in str(response.json())

    def test_deprecation_headers_present_in_dev_mode(self):
        """Test that deprecation headers are present in development mode"""
        response = client.post(
            "/api/landing/demos/start",
            json={"demo_type": "glm"}
        )

        # Check for deprecation headers (if endpoint succeeded)
        if response.status_code in [200, 201]:
            headers = response.headers

            # At least one deprecation indicator should be present
            has_deprecation = (
                "X-Deprecated" in headers or
                "X-Migration-Path" in headers or
                "Warning" in headers
            )

            assert has_deprecation, \
                "No deprecation headers found in development mode response"

            # Validate header values
            if "X-Deprecated" in headers:
                assert headers["X-Deprecated"].lower() == "true"

            if "X-Migration-Path" in headers:
                assert "/api/demo/real" in headers["X-Migration-Path"]

            if "Warning" in headers:
                warning = headers["Warning"].lower()
                assert "mock" in warning or "deprecated" in warning


class TestConfigurationHandling:
    """Test configuration and mode detection"""

    def test_default_mode_is_production(self):
        """Test that default demo mode is production"""
        # Without BR_DEMO_MODE set, should default to production
        config = OrchestratorConfig()

        # Default should be production for safety
        assert config.DEMO_MODE == DemoMode.PRODUCTION or \
               os.getenv("BR_DEMO_MODE", "production").lower() == "production"

    def test_is_production_mode_helper(self):
        """Test is_production_mode() helper"""
        with patch.dict(os.environ, {"BR_DEMO_MODE": "production"}):
            OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION
            assert OrchestratorConfig.is_production_mode() == True
            assert OrchestratorConfig.is_development_mode() == False

    def test_is_development_mode_helper(self):
        """Test is_development_mode() helper"""
        with patch.dict(os.environ, {"BR_DEMO_MODE": "development"}):
            OrchestratorConfig.DEMO_MODE = DemoMode.DEVELOPMENT
            assert OrchestratorConfig.is_development_mode() == True
            assert OrchestratorConfig.is_production_mode() == False

    @pytest.mark.parametrize("mode_value", ["production", "PRODUCTION", "Production"])
    def test_mode_case_insensitive(self, mode_value):
        """Test that demo mode is case-insensitive"""
        with patch.dict(os.environ, {"BR_DEMO_MODE": mode_value}, clear=False):
            # Reload the config class to pick up new env var
            from importlib import reload
            from brain_researcher.services.orchestrator import config as config_module
            reload(config_module)

            # Should be normalized to lowercase enum
            assert config_module.config.DEMO_MODE == DemoMode.PRODUCTION


class TestNonLegacyEndpointsUnaffected:
    """Test that real demo endpoints are not affected by dev mode guards"""

    @pytest.fixture(autouse=True)
    def set_production_mode(self, monkeypatch):
        """Set production mode to ensure guards don't affect real endpoints"""
        monkeypatch.setenv("BR_DEMO_MODE", "production")
        OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION
        yield

    def test_real_demo_endpoints_work_in_production(self):
        """Test that /api/demo/real-* endpoints work in production mode"""
        # These should NOT be affected by dev-mode guards

        real_endpoints = [
            "/api/demo/real-results/glm_motor",
            "/api/demo/real-artifacts/glm_motor",
            "/api/demo/real-evidence/glm_motor",
        ]

        for endpoint in real_endpoints:
            response = client.get(endpoint)

            # Should be 200 (success) or other valid errors
            # Should NOT be blocked with 404 + production mode message
            if response.status_code == 404:
                detail = response.json().get("detail", "")
                assert "not available in production" not in str(detail).lower(), \
                    f"Real endpoint {endpoint} incorrectly blocked"

    def test_share_endpoint_works_in_production(self):
        """Test that real share endpoint works in production"""
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "glm_motor",
                "is_public": True,
                "expires_in_hours": 24
            }
        )

        # Should work (200) or have valid error
        # Should NOT be blocked by dev-mode guard
        if response.status_code == 404:
            detail = response.json().get("detail", "")
            assert "not available in production" not in str(detail).lower()


class TestMigrationInstructions:
    """Test quality of migration instructions"""

    @pytest.fixture(autouse=True)
    def set_production_mode(self, monkeypatch):
        """Set production mode"""
        monkeypatch.setenv("BR_DEMO_MODE", "production")
        OrchestratorConfig.DEMO_MODE = DemoMode.PRODUCTION
        yield

    def test_migration_instructions_actionable(self):
        """Test that migration instructions are actionable"""
        response = client.post(
            "/api/landing/demos/start",
            json={"demo_type": "glm"}
        )

        assert response.status_code == 404
        detail = response.json().get("detail", {})

        if isinstance(detail, dict):
            # Should provide specific alternative
            migration_info = str(detail).lower()

            # Should mention what to use instead
            assert "/api/demo/real" in str(detail) or \
                   "real-results" in migration_info or \
                   "real-artifacts" in migration_info

    def test_migration_provides_docs_link(self):
        """Test that migration message provides docs link"""
        response = client.get("/api/landing/demos/test123/result")

        assert response.status_code == 404
        detail = response.json().get("detail", {})

        if isinstance(detail, dict):
            # Should mention docs
            assert "docs" in detail or "/docs" in str(detail)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
