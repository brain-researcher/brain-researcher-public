"""Tests for planner preflight checks module."""

import importlib
import os
import pytest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch

from brain_researcher.services.agent.planner.preflight import (
    PreflightCheck,
    PreflightReport,
    run_preflight,
    preflight_batch,
)


# Mock ToolCapability structure for testing
@dataclass
class MockContainer:
    """Mock container specification."""
    image: str


@dataclass
class MockPython:
    """Mock Python specification."""
    module: str


@dataclass
class MockToolCapability:
    """Mock tool capability for testing."""
    id: str
    name: str
    runtime_kind: str
    container: Optional[MockContainer] = None
    python: Optional[MockPython] = None


class TestPreflightCheckDataclass:
    """Test PreflightCheck dataclass."""

    def test_preflight_check_creation(self):
        """Test that PreflightCheck can be created."""
        check = PreflightCheck("test_check", True)
        assert check.name == "test_check"
        assert check.passed is True
        assert check.detail is None

    def test_preflight_check_with_detail(self):
        """Test PreflightCheck with detail message."""
        check = PreflightCheck("test_check", False, "error detail")
        assert check.name == "test_check"
        assert check.passed is False
        assert check.detail == "error detail"


class TestPreflightReportDataclass:
    """Test PreflightReport dataclass."""

    def test_preflight_report_creation(self):
        """Test that PreflightReport can be created."""
        report = PreflightReport("tool.id", True)
        assert report.tool_id == "tool.id"
        assert report.passed is True
        assert report.checks == {}

    def test_preflight_report_with_checks(self):
        """Test PreflightReport with checks dict."""
        check1 = PreflightCheck("check1", True)
        check2 = PreflightCheck("check2", False)
        report = PreflightReport(
            "tool.id",
            False,
            checks={"check1": check1, "check2": check2}
        )
        assert report.tool_id == "tool.id"
        assert report.passed is False
        assert len(report.checks) == 2
        assert report.checks["check1"].passed is True
        assert report.checks["check2"].passed is False


class TestContainerImageChecks:
    """Test container image preflight checks."""

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_container_cvmfs_available(self, mock_path_cls):
        """Test that CVMFS container passes when CVMFS is mounted."""
        # Mock CVMFS root exists
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = True
        mock_path_cls.return_value = mock_cvmfs

        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        report = run_preflight(tool)
        assert report.passed is True
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is True
        assert "CVMFS accessible" in report.checks["container_image"].detail

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_container_cvmfs_not_mounted(self, mock_path_cls):
        """Test that CVMFS container fails when CVMFS is not mounted."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        # Clear cache to ensure test starts fresh
        clear_preflight_cache()

        # Mock CVMFS root does not exist
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = False
        mock_path_cls.return_value = mock_cvmfs

        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        report = run_preflight(tool, use_cache=False)  # Disable cache for consistent test
        assert report.passed is False
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is False
        assert "CVMFS not mounted" in report.checks["container_image"].detail

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_container_local_image_exists(self, mock_path_cls):
        """Test that local container image passes when file exists."""
        # Mock local image path exists
        mock_image_path = Mock()
        mock_image_path.exists.return_value = True

        def path_side_effect(path_str):
            if path_str == "/data/containers/my_tool.sif":
                return mock_image_path
            return Mock(exists=Mock(return_value=False))

        mock_path_cls.side_effect = path_side_effect

        tool = MockToolCapability(
            id="custom.tool",
            name="Custom Tool",
            runtime_kind="container",
            container=MockContainer(image="/data/containers/my_tool.sif")
        )

        report = run_preflight(tool)
        assert report.passed is True
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is True

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_container_local_image_missing(self, mock_path_cls):
        """Test that local container fails when image file missing."""
        # Mock local image path does not exist
        mock_image_path = Mock()
        mock_image_path.exists.return_value = False

        def path_side_effect(path_str):
            return mock_image_path

        mock_path_cls.side_effect = path_side_effect

        tool = MockToolCapability(
            id="custom.tool",
            name="Custom Tool",
            runtime_kind="container",
            container=MockContainer(image="/data/containers/missing.sif")
        )

        report = run_preflight(tool)
        assert report.passed is False
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is False
        assert "image not found" in report.checks["container_image"].detail

    def test_container_no_spec(self):
        """Test that container tool without spec fails check."""
        tool = MockToolCapability(
            id="broken.tool",
            name="Broken Tool",
            runtime_kind="container",
            container=None  # No container spec
        )

        report = run_preflight(tool)
        assert report.passed is False
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is False
        assert "no container spec" in report.checks["container_image"].detail

    def test_container_no_image(self):
        """Test that container spec without image fails check."""
        tool = MockToolCapability(
            id="broken.tool",
            name="Broken Tool",
            runtime_kind="container",
            container=MockContainer(image="")  # Empty image path
        )

        report = run_preflight(tool, use_cache=False)
        assert report.passed is False
        assert "container_image" in report.checks
        assert report.checks["container_image"].passed is False
        # Either "no image configured" or "no container spec" is acceptable
        assert ("no image configured" in report.checks["container_image"].detail or
                "no container spec" in report.checks["container_image"].detail)


class TestPythonImportChecks:
    """Test Python import preflight checks."""

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_python_import_success(self, mock_import):
        """Test that importable Python module passes."""
        # Mock successful import
        mock_import.return_value = Mock()

        tool = MockToolCapability(
            id="python.numpy.mean",
            name="NumPy Mean",
            runtime_kind="python",
            python=MockPython(module="numpy")
        )

        report = run_preflight(tool)
        assert report.passed is True
        assert "python_import" in report.checks
        assert report.checks["python_import"].passed is True
        mock_import.assert_called_once_with("numpy")

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_python_import_failure(self, mock_import):
        """Test that non-importable module fails check."""
        # Mock import failure
        mock_import.side_effect = ImportError("No module named 'nonexistent'")

        tool = MockToolCapability(
            id="python.nonexistent",
            name="Nonexistent Module",
            runtime_kind="python",
            python=MockPython(module="nonexistent")
        )

        report = run_preflight(tool)
        assert report.passed is False
        assert "python_import" in report.checks
        assert report.checks["python_import"].passed is False
        assert "import failed" in report.checks["python_import"].detail
        assert "nonexistent" in report.checks["python_import"].detail

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_python_import_unexpected_error(self, mock_import):
        """Test that unexpected errors are caught."""
        # Mock unexpected exception
        mock_import.side_effect = RuntimeError("Unexpected error")

        tool = MockToolCapability(
            id="python.broken",
            name="Broken Module",
            runtime_kind="python",
            python=MockPython(module="broken")
        )

        report = run_preflight(tool)
        assert report.passed is False
        assert "python_import" in report.checks
        assert report.checks["python_import"].passed is False
        assert "unexpected error" in report.checks["python_import"].detail

    def test_python_no_spec(self):
        """Test that Python tool without spec fails check."""
        tool = MockToolCapability(
            id="python.broken",
            name="Broken Python Tool",
            runtime_kind="python",
            python=None  # No Python spec
        )

        report = run_preflight(tool)
        assert report.passed is False
        assert "python_import" in report.checks
        assert report.checks["python_import"].passed is False
        assert "no python spec" in report.checks["python_import"].detail


class TestNonApplicableChecks:
    """Test that checks pass when not applicable."""

    def test_python_tool_skips_container_check(self):
        """Test that Python tool passes container check with 'not-required'."""
        tool = MockToolCapability(
            id="python.numpy.mean",
            name="NumPy Mean",
            runtime_kind="python",
            python=MockPython(module="sys")  # Built-in module
        )

        with patch("brain_researcher.services.agent.planner.preflight.importlib.import_module"):
            report = run_preflight(tool)
            assert "container_image" in report.checks
            assert report.checks["container_image"].passed is True
            assert report.checks["container_image"].detail == "not-required"

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_container_tool_skips_python_check(self, mock_path_cls):
        """Test that container tool passes Python check with 'not-required'."""
        # Mock CVMFS available
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = True
        mock_path_cls.return_value = mock_cvmfs

        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        report = run_preflight(tool)
        assert "python_import" in report.checks
        assert report.checks["python_import"].passed is True
        assert report.checks["python_import"].detail == "not-required"


class TestPreflightIntegration:
    """Test integrated preflight functionality."""

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_run_preflight_all_pass(self, mock_import):
        """Test run_preflight when all checks pass."""
        mock_import.return_value = Mock()

        tool = MockToolCapability(
            id="python.numpy.mean",
            name="NumPy Mean",
            runtime_kind="python",
            python=MockPython(module="numpy")
        )

        report = run_preflight(tool)
        assert report.tool_id == "python.numpy.mean"
        assert report.passed is True
        assert len(report.checks) == 2  # container_image, python_import
        assert all(check.passed for check in report.checks.values())

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_run_preflight_one_fail(self, mock_path_cls):
        """Test run_preflight when one check fails."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        # Clear cache
        clear_preflight_cache()

        # Mock CVMFS not mounted
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = False
        mock_path_cls.return_value = mock_cvmfs

        tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        report = run_preflight(tool, use_cache=False)
        assert report.tool_id == "fsl.bet.run"
        assert report.passed is False  # Overall report fails
        assert report.checks["container_image"].passed is False
        assert report.checks["python_import"].passed is True  # Not required

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_preflight_batch_multiple_tools(self, mock_path_cls, mock_import):
        """Test preflight_batch with multiple tools."""
        # Mock CVMFS available
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = True
        mock_path_cls.return_value = mock_cvmfs

        # Mock successful import
        mock_import.return_value = Mock()

        container_tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        python_tool = MockToolCapability(
            id="python.numpy.mean",
            name="NumPy Mean",
            runtime_kind="python",
            python=MockPython(module="numpy")
        )

        reports = preflight_batch([container_tool, python_tool])

        assert len(reports) == 2
        assert "fsl.bet.run" in reports
        assert "python.numpy.mean" in reports
        assert reports["fsl.bet.run"].passed is True
        assert reports["python.numpy.mean"].passed is True

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_preflight_batch_mixed_results(self, mock_path_cls, mock_import):
        """Test preflight_batch with some tools passing and some failing."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        # Clear cache
        clear_preflight_cache()

        # Mock CVMFS not mounted
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = False
        mock_path_cls.return_value = mock_cvmfs

        # Mock successful import
        mock_import.return_value = Mock()

        failing_tool = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(
                image="/cvmfs/neurodesk.ardc.edu.au/containers/fsl.sif"
            )
        )

        passing_tool = MockToolCapability(
            id="python.sys.version",
            name="Sys Version",
            runtime_kind="python",
            python=MockPython(module="sys")
        )

        reports = preflight_batch([failing_tool, passing_tool], use_cache=False)

        assert len(reports) == 2
        assert reports["fsl.bet.run"].passed is False
        assert reports["python.sys.version"].passed is True

    def test_preflight_batch_empty_list(self):
        """Test preflight_batch with empty tool list."""
        reports = preflight_batch([])
        assert reports == {}


class TestPreflightCaching:
    """Test PR-3 caching functionality."""

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_cache_hit_skips_checks(self, mock_import):
        """Test that cache hit skips filesystem and import checks."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        # Clear cache to start fresh
        clear_preflight_cache()

        tool = MockToolCapability(
            id="python.numpy.mean",
            name="NumPy Mean",
            runtime_kind="python",
            python=MockPython(module="numpy")
        )

        # First call - should hit import check
        mock_import.return_value = Mock()
        report1 = run_preflight(tool, use_cache=True)
        assert report1.passed is True
        assert mock_import.call_count == 1

        # Second call - should use cache, not call import
        mock_import.reset_mock()
        report2 = run_preflight(tool, use_cache=True)
        assert report2.passed is True
        assert mock_import.call_count == 0  # Cache hit, no import

        # Verify both reports have same results
        assert report1.tool_id == report2.tool_id
        assert report1.passed == report2.passed

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_cache_disabled(self, mock_import):
        """Test that use_cache=False bypasses cache."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        clear_preflight_cache()

        tool = MockToolCapability(
            id="python.pandas.df",
            name="Pandas DF",
            runtime_kind="python",
            python=MockPython(module="pandas")
        )

        mock_import.return_value = Mock()

        # First call with cache disabled
        run_preflight(tool, use_cache=False)
        assert mock_import.call_count == 1

        # Second call with cache disabled - should still run check
        mock_import.reset_mock()
        run_preflight(tool, use_cache=False)
        assert mock_import.call_count == 1  # Cache not used

    def test_cache_expires_after_ttl(self):
        """Test that cache entries expire after TTL using time manipulation."""
        from brain_researcher.services.agent.planner.cache import PreflightCache
        import time

        # Create cache with short TTL
        cache = PreflightCache(ttl_seconds=1)

        # Store value
        cache.set("test_key", {"passed": True, "data": "test"})

        # Immediate retrieval should work
        result = cache.get("test_key")
        assert result is not None
        assert result["passed"] is True

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired now
        result_expired = cache.get("test_key")
        assert result_expired is None

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_batching_deduplicates(self, mock_import):
        """Test that batch processing deduplicates identical tools."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        clear_preflight_cache()
        mock_import.return_value = Mock()

        tool = MockToolCapability(
            id="python.scipy.stats",
            name="SciPy Stats",
            runtime_kind="python",
            python=MockPython(module="scipy.stats")
        )

        # Pass same tool multiple times
        tools = [tool, tool, tool]

        reports = preflight_batch(tools, use_cache=False, concurrent=False)

        # Should only run check once due to deduplication
        assert len(reports) == 1
        assert "python.scipy.stats" in reports
        assert mock_import.call_count == 1  # Only called once despite 3 inputs

    def test_redis_fallback(self):
        """Test graceful fallback to in-memory when Redis unavailable."""
        from brain_researcher.services.agent.planner.cache import PreflightCache

        # Create cache with invalid Redis URL
        cache = PreflightCache(
            ttl_seconds=600,
            redis_url="redis://nonexistent:9999/0"
        )

        # Should fall back to memory cache
        assert cache._use_redis is False
        assert cache._memory_store is not None

        # Memory cache should work
        cache.set("test_key", {"passed": True})
        result = cache.get("test_key")
        assert result is not None
        assert result["passed"] is True

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    def test_concurrent_container_checks(self, mock_path_cls):
        """Test that batch operations run checks concurrently."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache
        from unittest.mock import call

        clear_preflight_cache()

        # Mock CVMFS available
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = True
        mock_path_cls.return_value = mock_cvmfs

        tools = [
            MockToolCapability(
                id=f"tool.{i}",
                name=f"Tool {i}",
                runtime_kind="container",
                container=MockContainer(image=f"/cvmfs/container{i}.sif")
            )
            for i in range(5)
        ]

        # Run batch with concurrency enabled
        reports = preflight_batch(
            tools,
            use_cache=False,
            concurrent=True,
            max_workers=4
        )

        # All tools should be checked
        assert len(reports) == 5
        for i in range(5):
            assert f"tool.{i}" in reports
            assert reports[f"tool.{i}"].passed is True

    def test_cache_key_stability(self):
        """Test that cache keys are stable across calls."""
        from brain_researcher.services.agent.planner.cache import (
            compute_cache_key,
            compute_tool_digest,
        )

        tool1 = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(image="/cvmfs/fsl.sif")
        )

        tool2 = MockToolCapability(
            id="fsl.bet.run",
            name="BET",
            runtime_kind="container",
            container=MockContainer(image="/cvmfs/fsl.sif")
        )

        # Same tool configuration should produce same digest
        digest1 = compute_tool_digest(tool1)
        digest2 = compute_tool_digest(tool2)
        assert digest1 == digest2

        # Cache keys should be identical
        key1 = compute_cache_key(tool1.id, digest1)
        key2 = compute_cache_key(tool2.id, digest2)
        assert key1 == key2

    def test_cache_key_changes_with_config(self):
        """Test that cache keys change when tool config changes."""
        from brain_researcher.services.agent.planner.cache import compute_tool_digest

        tool1 = MockToolCapability(
            id="python.numpy.test",
            name="NumPy Test",
            runtime_kind="python",
            python=MockPython(module="numpy")
        )

        tool2 = MockToolCapability(
            id="python.numpy.test",
            name="NumPy Test",
            runtime_kind="python",
            python=MockPython(module="scipy")  # Different module
        )

        # Different configurations should produce different digests
        digest1 = compute_tool_digest(tool1)
        digest2 = compute_tool_digest(tool2)
        assert digest1 != digest2

    def test_batch_cache_operations(self):
        """Test batch get_many and set_many operations."""
        from brain_researcher.services.agent.planner.cache import PreflightCache

        cache = PreflightCache(ttl_seconds=600)

        # Batch set
        items = {
            "key1": {"passed": True, "data": "test1"},
            "key2": {"passed": False, "data": "test2"},
            "key3": {"passed": True, "data": "test3"},
        }
        cache.set_many(items)

        # Batch get
        results = cache.get_many(["key1", "key2", "key3", "key4"])  # key4 doesn't exist

        assert results["key1"]["passed"] is True
        assert results["key2"]["passed"] is False
        assert results["key3"]["passed"] is True
        assert results["key4"] is None  # Cache miss

    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_clear_preflight_cache(self, mock_import):
        """Test clearing the global cache."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        mock_import.return_value = Mock()

        tool = MockToolCapability(
            id="python.test.module",
            name="Test Module",
            runtime_kind="python",
            python=MockPython(module="test_module")
        )

        # Run preflight to populate cache
        report1 = run_preflight(tool, use_cache=True)
        assert report1.passed is True
        assert mock_import.call_count == 1

        # Clear cache
        clear_preflight_cache()

        # Next call should re-run checks
        mock_import.reset_mock()
        report2 = run_preflight(tool, use_cache=True)
        assert report2.passed is True
        assert mock_import.call_count == 1  # Cache was cleared, check re-run

    @patch("brain_researcher.services.agent.planner.preflight.Path")
    @patch("brain_researcher.services.agent.planner.preflight.importlib.import_module")
    def test_batch_with_exceptions(self, mock_import, mock_path_cls):
        """Test that batch operations handle exceptions gracefully."""
        from brain_researcher.services.agent.planner.cache import clear_preflight_cache

        clear_preflight_cache()

        # Mock one tool to raise exception during check
        def import_side_effect(module):
            if module == "failing_module":
                raise RuntimeError("Simulated failure")
            return Mock()

        mock_import.side_effect = import_side_effect

        # Mock CVMFS available
        mock_cvmfs = Mock()
        mock_cvmfs.exists.return_value = True
        mock_path_cls.return_value = mock_cvmfs

        passing_tool = MockToolCapability(
            id="python.passing",
            name="Passing",
            runtime_kind="python",
            python=MockPython(module="passing_module")
        )

        failing_tool = MockToolCapability(
            id="python.failing",
            name="Failing",
            runtime_kind="python",
            python=MockPython(module="failing_module")
        )

        # Batch should handle exception and continue
        reports = preflight_batch(
            [passing_tool, failing_tool],
            use_cache=False,
            concurrent=False
        )

        # Both tools should have reports
        assert len(reports) == 2
        assert reports["python.passing"].passed is True
        assert reports["python.failing"].passed is False
        # Exception should be caught in python_import check
        assert reports["python.failing"].checks["python_import"].passed is False
        assert "Simulated failure" in reports["python.failing"].checks["python_import"].detail


class TestCatalogPythonToolPreflight:
    """Test preflight for catalog Python tools."""

    @patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"})
    def test_catalog_python_tool_preflight_ok(self, monkeypatch):
        """Test that a catalog python tool passes preflight with default (catalog) planner source."""
        from brain_researcher.services.agent.planner.catalog_loader import (
            get_tool_by_id,
            get_capability_index,
        )
        from brain_researcher.services.agent.planner.preflight import run_preflight

        # Clear cache to ensure fresh load
        get_capability_index.cache_clear()

        # Ensure BR_PLANNER_SOURCE is set to catalog (default)
        monkeypatch.delenv("BR_PLANNER_SOURCE", raising=False)
        # Default should be catalog mode
        os.environ["BR_PLANNER_SOURCE"] = "catalog"

        # Get a catalog Python tool (nilearn_connectivity_matrix should exist)
        tool = get_tool_by_id("python.nilearn_connectivity_matrix.run")
        
        # If tool doesn't exist, skip test (catalog may not be fully set up)
        if tool is None:
            pytest.skip("Catalog tool python.nilearn_connectivity_matrix.run not found")

        # Run preflight
        result = run_preflight(tool, use_cache=False)

        # Verify preflight passed
        assert result.passed is True, \
            f"Preflight should pass for catalog python tool, got passed={result.passed}"

        # Verify runtime metadata is included
        assert result.runtime_kind == "python", \
            f"runtime_kind should be 'python', got: {result.runtime_kind}"
        assert result.python_module is not None, \
            "python_module should be set for python tools"
        assert result.python_function is not None, \
            "python_function should be set for python tools"

        print(f"✓ Catalog python tool preflight passed")
        print(f"  Tool ID: {tool.id}")
        print(f"  Runtime kind: {result.runtime_kind}")
        print(f"  Python module: {result.python_module}")
        print(f"  Python function: {result.python_function}")
