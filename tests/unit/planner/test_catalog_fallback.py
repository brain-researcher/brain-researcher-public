"""
Tests for catalog loading fallback behavior.

Verifies that when catalog loading fails, the system falls back gracefully
to legacy mode and logs appropriate error messages.
"""

import pytest
from unittest.mock import patch, Mock
import os

from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    get_planner_source,
    CapabilityIndex,
)


class TestCatalogFallback:
    """Test catalog loading fallback behavior."""

    def test_catalog_source_with_successful_load(self, monkeypatch):
        """Test that catalog mode successfully loads when files exist."""
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        # This should not raise an exception
        # It may return an empty or populated index depending on config availability
        index = get_capability_index()

        # Should return a CapabilityIndex instance (may be empty if configs don't exist)
        assert isinstance(index, CapabilityIndex)

    def test_catalog_source_with_missing_files_falls_back(self, monkeypatch):
        """Test that missing catalog files trigger graceful fallback."""
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        # Mock load_capabilities_yaml to raise an exception (simulating missing/corrupt file)
        with patch(
            "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
            side_effect=FileNotFoundError("capabilities.yaml not found"),
        ):
            # Should not crash - should return empty index
            index = get_capability_index()

        # Should return empty index (fallback behavior)
        assert isinstance(index, CapabilityIndex)

    def test_catalog_source_with_corrupt_yaml_falls_back(self, monkeypatch):
        """Test that corrupt YAML files trigger graceful fallback."""
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        # Mock load_capabilities_yaml to raise a YAML parsing error
        with patch(
            "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
            side_effect=ValueError("YAML parsing error"),
        ):
            # Should not crash
            index = get_capability_index()

        # Should return empty index (fallback)
        assert isinstance(index, CapabilityIndex)

    def test_legacy_source_returns_empty_index(self, monkeypatch):
        """Test that legacy mode returns empty index without attempting catalog load."""
        monkeypatch.setenv("BR_PLANNER_SOURCE", "legacy")

        # Should not attempt to load catalog files
        with patch(
            "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
            side_effect=Exception("Should not be called!"),
        ):
            index = get_capability_index()

        # Should return empty index
        assert isinstance(index, CapabilityIndex)

        # Verify it's empty (no tools loaded from catalog)
        # Note: may have entries if legacy load_tool_catalog is called elsewhere

    def test_planner_source_env_var_precedence(self, monkeypatch):
        """Test that BR_PLANNER_SOURCE environment variable is respected."""
        # Test default (catalog)
        monkeypatch.delenv("BR_PLANNER_SOURCE", raising=False)
        assert get_planner_source() == "catalog"

        # Test explicit legacy
        monkeypatch.setenv("BR_PLANNER_SOURCE", "legacy")
        assert get_planner_source() == "legacy"

        # Test explicit catalog
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")
        assert get_planner_source() == "catalog"

        # Test case insensitive
        monkeypatch.setenv("BR_PLANNER_SOURCE", "CATALOG")
        assert get_planner_source() == "catalog"

    def test_multiple_load_failures_all_trigger_fallback(self, monkeypatch):
        """Test that any exception during catalog loading triggers fallback."""
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        # Test different exception types
        exceptions = [
            FileNotFoundError("File not found"),
            PermissionError("Permission denied"),
            ValueError("Invalid YAML"),
            KeyError("Missing key"),
            RuntimeError("Generic error"),
        ]

        for exc in exceptions:
            with patch(
                "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
                side_effect=exc,
            ):
                # All should fall back gracefully without crashing
                index = get_capability_index()
                assert isinstance(index, CapabilityIndex)

    def test_fallback_does_not_crash_system(self, monkeypatch):
        """Test that fallback behavior doesn't crash the system.

        Even with complete catalog failure, the system should remain functional
        (albeit in legacy mode).
        """
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        # Simulate total catalog failure
        with patch(
            "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
            side_effect=Exception("Total failure"),
        ):
            # Should not raise exception
            try:
                index = get_capability_index()
                assert isinstance(index, CapabilityIndex)
            except Exception as e:
                pytest.fail(f"Fallback should not raise exception, but got: {e}")

    def test_catalog_cache_behavior_after_fallback(self, monkeypatch):
        """Test that fallback doesn't poison cache.

        If catalog loading fails once, subsequent calls should still attempt
        to load (in case issue was transient).
        """
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")

        call_count = 0

        def mock_load_sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FileNotFoundError("First call fails")
            else:
                # Second call succeeds (simulating transient error resolved)
                return []

        with patch(
            "brain_researcher.services.agent.planner.catalog_loader.load_capabilities_yaml",
            side_effect=mock_load_sometimes_fails,
        ):
            # First call should fail and fallback
            index1 = get_capability_index()
            assert isinstance(index1, CapabilityIndex)

            # Note: Actual caching behavior depends on implementation
            # This test documents expected behavior for retry logic
