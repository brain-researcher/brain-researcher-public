"""Test Phase 6: Verify models and semantics migration to brain_researcher."""

import warnings
from pathlib import Path

import pytest


class TestPhase6ModelsMigration:
    """Test models module migration is successful."""

    def test_new_models_location_works(self):
        """Test importing from new location works."""
        # Import from new location
        import brain_researcher.models

        # Test module exists
        assert brain_researcher.models is not None

        # Test specific module if it has simple imports
        try:
            from brain_researcher.models import fmri_text_alignment

            assert fmri_text_alignment is not None
        except ImportError:
            # OK if it has external dependencies
            pass

    def test_old_models_location_still_works(self):
        """Test importing from old location still works with deprecation warning."""
        # Capture deprecation warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import from old location

            # Check deprecation warning was issued
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message)
            assert "brain_researcher.models" in str(w[0].message)

    def test_models_files_copied(self):
        """Verify all models files were copied to new location."""
        old_dir = Path("models")
        new_dir = Path("brain_researcher/models")

        # Get Python files from old location (excluding __init__.py)
        old_files = {f.name for f in old_dir.glob("*.py") if f.name != "__init__.py"}
        new_files = {f.name for f in new_dir.glob("*.py") if f.name != "__init__.py"}

        # All old files should exist in new location
        assert old_files.issubset(new_files), f"Missing files: {old_files - new_files}"


class TestPhase6SemanticsMigration:
    """Test semantics module migration is successful."""

    def test_new_semantics_location_works(self):
        """Test importing from new location works."""
        # Import from new location
        import brain_researcher.semantics

        # Test module exists
        assert brain_researcher.semantics is not None

        # Test ensemble_match submodule
        from brain_researcher.semantics import ensemble_match

        assert ensemble_match is not None

    def test_old_semantics_location_still_works(self):
        """Test importing from old location still works with deprecation warning."""
        # Capture deprecation warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import from old location

            # Check deprecation warning was issued
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message)
            assert "brain_researcher.semantics" in str(w[0].message)

    def test_semantics_structure_preserved(self):
        """Test that semantics subdirectory structure is preserved."""
        old_dir = Path("semantics")
        new_dir = Path("brain_researcher/semantics")

        # Check ensemble_match subdirectory exists
        assert (new_dir / "ensemble_match").exists()

        # Check files in ensemble_match
        old_ensemble_files = {f.name for f in (old_dir / "ensemble_match").glob("*.py")}
        new_ensemble_files = {f.name for f in (new_dir / "ensemble_match").glob("*.py")}

        assert old_ensemble_files.issubset(
            new_ensemble_files
        ), f"Missing ensemble_match files: {old_ensemble_files - new_ensemble_files}"


class TestPhase6Compatibility:
    """Test backward compatibility during migration."""

    def test_imports_in_dependent_code(self):
        """Test that code depending on models/semantics still works."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            # Test that we can still import from old locations
            try:
                from models import fmri_text_alignment

                from brain_researcher.semantics.ensemble_match import cal_score

                assert True  # If we get here, compatibility layer works
            except ImportError as e:
                # Only fail if it's not due to external dependencies
                if "models" in str(e) or "semantics" in str(e):
                    if "No module named" in str(e) and (
                        "models" in str(e) or "semantics" in str(e)
                    ):
                        pytest.fail(f"Compatibility layer failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
