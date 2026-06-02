"""Test Phase 3: Verify knowledge migration to brain_researcher.core.kg."""

import warnings
from pathlib import Path

import pytest


class TestPhase3KnowledgeMigration:
    """Test knowledge module migration is successful."""

    def test_new_kg_location_works(self):
        """Test importing from new location works."""
        # Import from new location
        from brain_researcher.core.kg import (
            EmbeddingConfig,
            EmbeddingIndex,
            EmbeddingMetrics,
            PersistentKnowledgeBase,
            get_config,
        )

        # Test classes are importable
        assert EmbeddingIndex is not None
        assert EmbeddingConfig is not None
        assert PersistentKnowledgeBase is not None
        assert EmbeddingMetrics is not None

        # Test functions are callable
        assert callable(get_config)

        # Test we can create instances
        config = EmbeddingConfig()
        assert config.model_name == "all-MiniLM-L6-v2"
        assert config.db_dir == "brain_researcher/core/kg/db"

    def test_old_knowledge_location_still_works(self):
        """Test importing from old location still works with deprecation warning."""
        # Capture deprecation warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import from old location
            from knowledge import EmbeddingConfig, EmbeddingIndex

            from brain_researcher.core.kg.embedding_config import get_config

            # Check deprecation warning was issued
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message)
            assert "brain_researcher.core.kg" in str(w[0].message)

        # Verify imports still work
        assert EmbeddingIndex is not None
        assert EmbeddingConfig is not None
        assert callable(get_config)

    def test_module_level_imports_work(self):
        """Test module-level imports like knowledge.embedding_index work."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            from brain_researcher.core.kg import (
                embedding_config,
                embedding_index,
                embedding_metrics,
                persistent_db,
            )

            # Test module attributes exist (via compatibility layer)
            assert hasattr(embedding_index, "EmbeddingIndex")
            assert hasattr(embedding_config, "EmbeddingConfig")
            assert hasattr(persistent_db, "PersistentEmbeddingDB") or hasattr(
                persistent_db, "PersistentKnowledgeBase"
            )
            assert hasattr(embedding_metrics, "EmbeddingMetrics") or hasattr(
                embedding_metrics, "EmbeddingMetricsCollector"
            )

    def test_config_functionality_preserved(self):
        """Test that configuration works from both locations."""
        # Test from new location
        from brain_researcher.core.kg import get_config as new_get_config

        # Test from old location (suppress warnings)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from knowledge import get_config as old_get_config

        # Both should return valid configs
        new_cfg = new_get_config()
        old_cfg = old_get_config()

        assert new_cfg.model_name == old_cfg.model_name
        assert new_cfg.shard_size == old_cfg.shard_size

    def test_all_kg_files_copied(self):
        """Verify all knowledge files were copied to new location."""
        old_kg = Path("knowledge")
        new_kg = Path("brain_researcher/core/kg")

        # Get Python files from old location (excluding __init__.py)
        old_files = {f.name for f in old_kg.glob("*.py") if f.name != "__init__.py"}
        new_files = {f.name for f in new_kg.glob("*.py") if f.name != "__init__.py"}

        # All old files should exist in new location
        assert old_files.issubset(new_files), f"Missing files: {old_files - new_files}"

        # Check data files too
        old_data_files = {f.name for f in old_kg.glob("*.json")} | {
            f.name for f in old_kg.glob("*.md")
        }
        new_data_files = {f.name for f in new_kg.glob("*.json")} | {
            f.name for f in new_kg.glob("*.md")
        }

        assert old_data_files.issubset(
            new_data_files
        ), f"Missing data files: {old_data_files - new_data_files}"

    def test_db_directory_copied(self):
        """Test that db directory and contents were copied."""
        new_db = Path("brain_researcher/core/kg/db")

        assert new_db.exists(), "db directory not copied"
        assert new_db.is_dir(), "db is not a directory"

        # Check some expected files exist
        expected_files = [
            "faiss_index.bin",
            "index_mapping.json",
            "pubmed_last_run.txt",
        ]
        for filename in expected_files:
            file_path = new_db / filename
            assert file_path.exists(), f"Missing db file: {filename}"

    def test_no_import_errors_in_copied_files(self):
        """Test that copied files don't have broken imports."""
        import importlib

        modules = [
            "brain_researcher.core.kg.embedding_index",
            "brain_researcher.core.kg.embedding_config",
            "brain_researcher.core.kg.persistent_db",
            "brain_researcher.core.kg.embedding_metrics",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                assert module is not None
            except ImportError as e:
                # Allow imports of optional dependencies to fail
                if "faiss" in str(e) or "prometheus_client" in str(e):
                    continue
                pytest.fail(f"Import error in {module_name}: {e}")

    def test_embedding_config_paths_updated(self):
        """Test that paths in config are updated to new location."""
        from brain_researcher.core.kg import EmbeddingConfig

        config = EmbeddingConfig()
        assert "brain_researcher/core/kg" in config.db_dir
        assert "knowledge/db" not in config.db_dir


class TestPhase3Compatibility:
    """Test backward compatibility during migration."""

    def test_imports_in_dependent_modules(self):
        """Test that modules depending on knowledge still work."""
        # Test if any tools use knowledge module
        try:
            # These might use knowledge module
            from brain_researcher.core.analysis import rag_retrieval

            # If import works, compatibility layer is working
            assert True
        except ImportError as e:
            # Only fail if it's a knowledge-related import error
            if "knowledge" in str(e):
                pytest.fail(f"Knowledge import failed in dependent module: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
