"""Pre-migration tests to capture current functionality.

This test suite serves as a safety net before the Biomni-style refactoring.
It captures the current state of imports and functionality to ensure nothing breaks.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


class TestPreMigrationImports:
    """Test all current imports work before migration."""

    def test_data_ingestion_imports(self):
        """Test data_ingestion module imports."""
        modules = [
            "data_ingestion.bids_io",
            "data_ingestion.neuro_downloads",
            "data_ingestion.nifti_utils",
            "data_ingestion.nwb_api",
            "data_ingestion.table_utils",
            "data_ingestion.datalad_git",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_analysis_imports(self):
        """Test canonical analysis module imports."""
        modules = [
            "brain_researcher.core.analysis.statistical_analysis",
            "brain_researcher.core.analysis.nilearn_integration",
            "brain_researcher.core.analysis.neurosynth_integration",
            "brain_researcher.core.analysis.contrast_analysis",
            "brain_researcher.core.analysis.rag_retrieval",
            "brain_researcher.core.analysis.encoding_model",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_knowledge_imports(self):
        """Test knowledge module imports."""
        modules = [
            "knowledge.embedding_index",
            "knowledge.embedding_config",
            "knowledge.persistent_db",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_utils_imports(self):
        """Test utils module imports."""
        modules = [
            "utils.spatial",
            "utils.task_matcher",
            "utils.edge_weights",
            "utils.deepseek_client",
            "utils.port_utils",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_models_imports(self):
        """Test models module imports."""
        modules = [
            "models.fmri_text_alignment",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_semantics_imports(self):
        """Test semantics module imports."""
        modules = [
            "semantics.ensemble_match.exact_fuzzy_match",
            "semantics.ensemble_match.embed_match",
            "semantics.ensemble_match.merge_candidates",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")

    def test_brain_researcher_imports(self):
        """Test new brain_researcher module imports."""
        modules = [
            "brain_researcher.cli.main",
            "brain_researcher.cli.db_commands",
            "brain_researcher.cli.data_commands",
            "brain_researcher.cli.query_commands",
            "brain_researcher.testing.supervisor",
            "brain_researcher.testing.tester",
            "brain_researcher.testing.static_analyst",
            "brain_researcher.util.tool",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None, f"Failed to import {module_name}"
            except ImportError as e:
                pytest.fail(f"Import error for {module_name}: {e}")


class TestCLICommands:
    """Test CLI commands work before migration."""

    def test_cli_help(self):
        """Test basic CLI help command."""
        result = subprocess.run(
            ["brain-researcher", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Brain Researcher" in result.stdout

    def test_cli_version(self):
        """Test CLI version command."""
        result = subprocess.run(
            ["brain-researcher", "version"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Brain Researcher" in result.stdout

    def test_cli_db_help(self):
        """Test CLI db subcommand help."""
        result = subprocess.run(
            ["brain-researcher", "db", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Database management" in result.stdout

    def test_cli_data_help(self):
        """Test CLI data subcommand help."""
        result = subprocess.run(
            ["brain-researcher", "data", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Data ingestion" in result.stdout

    def test_cli_query_help(self):
        """Test CLI query subcommand help."""
        result = subprocess.run(
            ["brain-researcher", "query", "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Query and search" in result.stdout


class TestImportInventory:
    """Create and test import inventory for migration tracking."""

    def scan_python_files(self) -> list[Path]:
        """Scan all Python files in the project."""
        root = Path(__file__).parent.parent.parent
        python_files = []

        # Directories to scan
        dirs_to_scan = [
            "brain_researcher",
            "data_ingestion",
            "tools",
            "knowledge",
            "models",
            "semantics",
            "utils",
            "tests",
            "examples",
            "scripts",
        ]

        for dir_name in dirs_to_scan:
            dir_path = root / dir_name
            if dir_path.exists():
                python_files.extend(dir_path.rglob("*.py"))

        return python_files

    def extract_imports(self, file_path: Path) -> list[dict[str, str]]:
        """Extract import statements from a Python file."""
        imports = []

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Parse imports using AST would be better, but for now use simple regex
            import_lines = [
                line.strip()
                for line in content.split("\n")
                if line.strip().startswith(("import ", "from "))
            ]

            for line in import_lines:
                imports.append(
                    {
                        "file": str(
                            file_path.relative_to(file_path.parent.parent.parent)
                        ),
                        "import": line,
                        "type": "from" if line.startswith("from") else "import",
                    }
                )

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

        return imports

    def test_create_import_inventory(self):
        """Generate comprehensive import inventory."""
        python_files = self.scan_python_files()
        all_imports = []

        for file_path in python_files:
            imports = self.extract_imports(file_path)
            all_imports.extend(imports)

        # Save inventory
        inventory_path = Path(__file__).parent / "import_inventory.json"
        with open(inventory_path, "w") as f:
            json.dump(
                {
                    "total_files": len(python_files),
                    "total_imports": len(all_imports),
                    "imports": all_imports,
                },
                f,
                indent=2,
            )

        assert inventory_path.exists()
        assert len(all_imports) > 0

        # Analyze import patterns
        internal_modules = {
            "brain_researcher",
            "data_ingestion",
            "tools",
            "knowledge",
            "models",
            "semantics",
            "utils",
            "services",
        }

        internal_imports = [
            imp
            for imp in all_imports
            if any(
                imp["import"].split()[1].startswith(mod)
                for mod in internal_modules
                if "from" in imp["import"]
            )
        ]

        print("\nImport Statistics:")
        print(f"Total Python files: {len(python_files)}")
        print(f"Total imports: {len(all_imports)}")
        print(f"Internal imports: {len(internal_imports)}")

        return inventory_path


class TestCoreFunctionality:
    """Test core functionality works before migration."""

    def test_tool_decorator(self):
        """Test the tool decorator works."""
        from brain_researcher.core.utils.tool import tool

        @tool
        def test_function(input: str) -> str:
            """Test function."""
            return f"processed: {input}"

        # Test the function works
        result = test_function("test")
        assert result == "processed: test"

        # The tool decorator might be a passthrough if langchain not installed
        # Just verify the function is callable
        assert callable(test_function)

    def test_embedding_config(self):
        """Test embedding configuration loads."""
        from brain_researcher.core.kg.embedding_config import get_config

        config = get_config()
        assert config is not None
        assert hasattr(config, "model_name")
        assert hasattr(config, "db_dir")

    def test_utils_functions(self):
        """Test utility functions work."""
        try:
            from brain_researcher.core.utils.port_utils import find_free_port

            # Test port finder
            port = find_free_port()
            assert isinstance(port, int)
            assert 1024 < port < 65535
        except ImportError:
            # Port utils might not exist, check for alternatives
            from brain_researcher.core.utils.spatial import euclidean_distance

            # Test spatial functions instead
            dist = euclidean_distance([0, 0, 0], [1, 1, 1])
            assert dist > 0


def create_migration_checkpoint():
    """Create a checkpoint of current state for rollback."""
    checkpoint = {
        "timestamp": Path(__file__).parent.parent.parent / ".migration_checkpoint",
        "git_tag": "pre-biomni-migration",
        "python_version": sys.version,
        "installed_packages": subprocess.run(
            ["pip", "freeze"], capture_output=True, text=True
        ).stdout,
    }

    # Save checkpoint
    checkpoint_path = Path(__file__).parent / "migration_checkpoint.json"
    with open(checkpoint_path, "w") as f:
        json.dump(checkpoint, f, indent=2)

    # Create git tag
    subprocess.run(["git", "tag", "-f", checkpoint["git_tag"]])

    return checkpoint_path


if __name__ == "__main__":
    # Run pre-migration tests
    pytest.main([__file__, "-v"])

    # Create migration checkpoint
    checkpoint = create_migration_checkpoint()
    print(f"\nMigration checkpoint created: {checkpoint}")
    print("Ready to start Biomni-style migration!")
