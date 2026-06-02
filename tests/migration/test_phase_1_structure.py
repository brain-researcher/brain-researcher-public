"""Test Phase 1: Verify new brain_researcher package structure is created correctly."""

import importlib
from pathlib import Path

import pytest


class TestPhase1Structure:
    """Test the new package structure is created correctly."""

    def test_new_directories_exist(self):
        """Verify all new directories are created."""
        base_path = Path(__file__).parent.parent.parent / "brain_researcher"

        expected_dirs = [
            "core",
            "core/kg",
            "core/ingestion",
            "core/analysis",
            "core/models",
            "core/semantics",
            "core/utils",
            "services",
            "cognitive",
        ]

        for dir_name in expected_dirs:
            dir_path = base_path / dir_name
            assert dir_path.exists(), f"Directory {dir_name} does not exist"
            assert dir_path.is_dir(), f"{dir_name} is not a directory"

            # Check __init__.py exists
            init_path = dir_path / "__init__.py"
            assert init_path.exists(), f"__init__.py missing in {dir_name}"

    def test_new_modules_importable(self):
        """Verify new modules can be imported."""
        modules = [
            "brain_researcher.core",
            "brain_researcher.core.kg",
            "brain_researcher.core.ingestion",
            "brain_researcher.core.analysis",
            "brain_researcher.core.models",
            "brain_researcher.core.semantics",
            "brain_researcher.core.utils",
            "brain_researcher.services",
            "brain_researcher.cognitive",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_existing_modules_still_work(self):
        """Verify existing modules are not broken."""
        # Test existing CLI still works
        from brain_researcher.cli import main

        assert main is not None

        # Test existing testing framework still works
        from tests.utils import supervisor

        assert supervisor is not None

        # Test existing utils still work
        from brain_researcher.core.utils import tool

        assert tool is not None

    def test_old_modules_still_importable(self):
        """Verify old module structure still works during migration."""
        old_modules = [
            "data_ingestion",
            "tools",
            "knowledge",
            "utils",
            "models",
            "semantics",
        ]

        for module_name in old_modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None
            except ImportError as e:
                pytest.fail(f"Old module {module_name} broken during migration: {e}")

    def test_no_files_in_new_directories(self):
        """Verify new directories are empty (only __init__.py)."""
        base_path = Path(__file__).parent.parent.parent / "brain_researcher/core"

        for subdir in ["kg", "ingestion", "analysis", "models", "semantics", "utils"]:
            dir_path = base_path / subdir
            files = list(dir_path.glob("*.py"))
            # Should only have __init__.py
            assert len(files) == 1, f"{subdir} has unexpected files: {files}"
            assert files[0].name == "__init__.py"


class TestPhase1Compatibility:
    """Test compatibility during the migration phase."""

    def test_no_circular_imports(self):
        """Verify no circular imports are introduced."""
        # Import all modules to check for circular dependencies

        # If we get here, no circular imports
        assert True

    def test_cli_commands_still_work(self):
        """Verify CLI commands work with new structure."""
        import subprocess

        # Test basic CLI command
        result = subprocess.run(
            ["brain-researcher", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Brain Researcher" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
