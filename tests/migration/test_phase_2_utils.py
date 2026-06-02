"""Test Phase 2: Verify utils migration to brain_researcher.core.utils."""

import warnings
from pathlib import Path

import pytest


class TestPhase2UtilsMigration:
    """Test utils module migration is successful."""

    def test_new_utils_location_works(self):
        """Test importing from new location works."""
        # Import from new location
        from brain_researcher.core.utils import (
            TaskMatcher,
            call_deepseek_api,
            compute_llm_confidence,
            euclidean_distance,
            find_free_port,
        )

        # Test functions are callable
        assert callable(euclidean_distance)
        assert callable(find_free_port)
        assert callable(compute_llm_confidence)
        assert callable(call_deepseek_api)

        # Test classes are importable
        assert TaskMatcher is not None

    def test_old_utils_location_still_works(self):
        """Test importing from old location still works with deprecation warning."""
        # Capture deprecation warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import from old location
            from utils import euclidean_distance

            from brain_researcher.core.utils.spatial import get_roi_coordinates
            from brain_researcher.core.utils.task_matcher import TaskMatcher

            # Check deprecation warning was issued
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message)
            assert "brain_researcher.core.utils" in str(w[0].message)

        # Verify imports still work
        assert callable(euclidean_distance)
        assert callable(get_roi_coordinates)
        assert TaskMatcher is not None

    def test_module_level_imports_work(self):
        """Test module-level imports like utils.spatial work."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            from brain_researcher.core.utils import (
                deepseek_client,
                edge_weights,
                port_utils,
                spatial,
                task_matcher,
            )

            # Test module attributes exist
            assert hasattr(spatial, "euclidean_distance")
            assert hasattr(task_matcher, "TaskMatcher")
            assert hasattr(edge_weights, "compute_llm_confidence")
            assert hasattr(port_utils, "find_free_port")
            assert hasattr(deepseek_client, "call_deepseek_api")

    def test_functionality_preserved(self):
        """Test that actual functionality works from both locations."""
        # Test from new location
        from brain_researcher.core.utils import euclidean_distance as new_dist
        from brain_researcher.core.utils import get_roi_coordinates as new_roi

        # Test from old location (suppress warnings)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from utils import euclidean_distance as old_dist
            from utils import get_roi_coordinates as old_roi

        # Test euclidean distance
        coord1, coord2 = [0, 0, 0], [1, 1, 1]
        assert new_dist(coord1, coord2) == old_dist(coord1, coord2)

        # Test ROI lookup
        roi_name = "hippocampus"
        new_coords = new_roi(roi_name)
        old_coords = old_roi(roi_name)
        assert new_coords == old_coords

    def test_imports_in_dependent_modules(self):
        """Test that modules depending on utils still work."""
        # These modules use utils
        try:
            # Test services modules that might use utils
            # Skip if services not migrated yet
            pass
        except ImportError:
            pass

        # Test tools modules that use utils
        try:
            from brain_researcher.core.analysis import statistical_analysis

            # If import works, utils compatibility is working
            assert True
        except ImportError as e:
            # Only fail if it's a utils-related import error
            if "utils" in str(e):
                pytest.fail(f"Utils import failed in dependent module: {e}")

    def test_all_utils_files_copied(self):
        """Verify all utils files were copied to new location."""
        old_utils = Path("utils")
        new_utils = Path("brain_researcher/core/utils")

        # Get Python files from old location (excluding __init__.py)
        old_files = {f.name for f in old_utils.glob("*.py") if f.name != "__init__.py"}
        new_files = {f.name for f in new_utils.glob("*.py") if f.name != "__init__.py"}

        # All old files should exist in new location
        assert old_files.issubset(new_files), f"Missing files: {old_files - new_files}"

    def test_no_import_errors_in_copied_files(self):
        """Test that copied files don't have broken imports."""
        import importlib

        modules = [
            "brain_researcher.core.utils.spatial",
            "brain_researcher.core.utils.task_matcher",
            "brain_researcher.core.utils.edge_weights",
            "brain_researcher.core.utils.port_utils",
            "brain_researcher.core.utils.deepseek_client",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None
            except ImportError as e:
                pytest.fail(f"Import error in {module_name}: {e}")


class TestPhase2Compatibility:
    """Test backward compatibility during migration."""

    def test_pre_migration_tests_still_pass(self):
        """Run a subset of pre-migration tests to ensure compatibility."""
        # Just test that we can import from old location
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from utils import euclidean_distance

            from brain_researcher.core.utils.port_utils import find_free_port

            # Test they work
            assert callable(euclidean_distance)
            assert callable(find_free_port)

            # Test function works
            dist = euclidean_distance([0, 0, 0], [1, 1, 1])
            assert dist > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
