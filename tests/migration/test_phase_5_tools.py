"""Test Phase 5: Verify analysis migration to brain_researcher.core.analysis."""

import warnings
from pathlib import Path

import pytest


class TestPhase5ToolsMigration:
    """Test tools module migration is successful."""

    def test_new_analysis_location_works(self):
        """Test importing from new location works."""
        # Import the analysis module
        import brain_researcher.core.analysis

        # Test that it has some expected attributes
        assert brain_researcher.core.analysis is not None
        assert hasattr(brain_researcher.core.analysis, "__all__")

        # Test importing a simple module without external deps
        from brain_researcher.core.analysis import effect_size

        assert effect_size is not None

    def test_legacy_tools_directory_removed(self):
        """Test the legacy root tools directory has been removed."""
        assert not Path("tools").exists()

    def test_module_level_imports_work(self):
        """Test module-level imports from the canonical analysis package."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ImportWarning)

            from brain_researcher.core.analysis import (
                contrast_analysis,
                encoding_model,
                neurosynth_integration,
                nilearn_integration,
                rag_retrieval,
                statistical_analysis,
            )

            assert contrast_analysis is not None
            assert encoding_model is not None
            assert neurosynth_integration is not None
            assert nilearn_integration is not None
            assert rag_retrieval is not None
            assert statistical_analysis is not None

    def test_all_tools_files_copied(self):
        """Verify all tools files were copied to new location."""
        new_dir = Path("src/brain_researcher/core/analysis")
        expected = {
            "contrast_analysis.py",
            "encoding_model.py",
            "neurosynth_integration.py",
            "nilearn_integration.py",
            "rag_retrieval.py",
            "statistical_analysis.py",
        }
        present = {f.name for f in new_dir.glob("*.py")}
        assert expected.issubset(present), f"Missing files: {expected - present}"

    def test_no_import_errors_in_copied_files(self):
        """Test that copied files don't have broken imports."""
        import importlib

        # Test a subset of key modules that don't have external dependencies
        modules = [
            "brain_researcher.core.analysis.effect_size",
            "brain_researcher.core.analysis.multiverse_convergence",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None
            except ImportError as e:
                # Allow imports of optional dependencies to fail
                optional_deps = [
                    "nilearn",
                    "nibabel",
                    "statsmodels",
                    "sklearn",
                    "scipy",
                ]
                if any(dep in str(e) for dep in optional_deps):
                    continue
                pytest.fail(f"Import error in {module_name}: {e}")


class TestPhase5Compatibility:
    """Test backward compatibility during migration."""

    def test_imports_in_dependent_modules(self):
        """Test that modules depending on analysis imports still work."""
        # Test if any modules use tools
        try:
            from brain_researcher.cli import query_commands

            assert True
        except ImportError as e:
            if "brain_researcher.core.analysis" in str(e):
                pytest.fail(f"analysis import failed in dependent module: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
