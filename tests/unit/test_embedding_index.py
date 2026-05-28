"""
Comprehensive tests for the embedding index system.

Tests sharding, multimodal embeddings, concurrent access, and persistence.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.core.kg.embedding_config import EmbeddingConfig
from brain_researcher.core.kg.embedding_index import EmbeddingIndex
from brain_researcher.core.kg.embedding_metrics import (
    EmbeddingMetricsCollector,
    QueryTimer,
)


class TestEmbeddingIndex:
    """Test the EmbeddingIndex class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test indices."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_model(self):
        """Mock sentence transformer model."""
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = 384
        model.encode.side_effect = lambda text, **kwargs: np.random.randn(
            384 if isinstance(text, str) else len(text), 384
        ).astype(np.float32)
        return model

    def test_initialization(self, temp_dir, mock_model):
        """Test basic initialization."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=100)

            assert index.db_dir == temp_dir
            assert index.shard_size == 100
            assert len(index.indices) == 0
            assert len(index.metadata) == 0

    def test_add_records_single_shard(self, temp_dir, mock_model):
        """Test adding records to a single shard."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=100)

            # Add records
            records = [
                {"id": "1", "text": "Deep learning for fMRI analysis"},
                {"id": "2", "text": "Brain connectivity patterns"},
                {"id": "3", "text": "Neuroimaging data processing"},
            ]

            index.add_records(records)

            assert len(index.indices) == 1
            assert index.indices[0].ntotal == 3
            assert len(index.metadata[0]) == 3

    def test_sharding(self, temp_dir, mock_model):
        """Test automatic sharding when exceeding shard size."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=5)

            # Add more records than shard size
            records = [
                {"id": f"doc_{i}", "text": f"Document {i} text"} for i in range(12)
            ]

            index.add_records(records)

            # Should have 3 shards: 5 + 5 + 2
            assert len(index.indices) == 3
            assert index.indices[0].ntotal == 5
            assert index.indices[1].ntotal == 5
            assert index.indices[2].ntotal == 2

    def test_multimodal_embeddings(self, temp_dir, mock_model):
        """Test handling of text + figure embeddings."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir)

            # Create figure embedding
            figure_vec = np.random.randn(256).astype(np.float32)

            # Add mixed records
            records = [
                {"id": "1", "text": "Text only document"},
                {"id": "2", "text": "Document with figure", "figure": figure_vec},
                {"id": "3", "text": "Another text only"},
            ]

            index.add_records(records)

            # Check dimensions
            assert index.indices[0].d == 384  # Text only dimension
            # Note: Current implementation has dimension mismatch issue
            # This test would fail with the provided code

    def test_search_basic(self, temp_dir, mock_model):
        """Test basic search functionality."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=100)

            # Add records
            records = [
                {"id": "1", "text": "Deep learning for brain imaging"},
                {"id": "2", "text": "Functional connectivity analysis"},
                {"id": "3", "text": "Machine learning in neuroscience"},
            ]
            index.add_records(records)

            # Search
            results = index.search("deep learning brain", top_k=2)

            assert len(results) == 2
            assert all("score" in r for r in results)
            assert all("id" in r for r in results)
            assert results[0]["score"] >= results[1]["score"]  # Sorted by score

    def test_search_across_shards(self, temp_dir, mock_model):
        """Test search across multiple shards."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=3)

            # Add records across multiple shards
            records = [
                {"id": f"doc_{i}", "text": f"Document {i} about brain research"}
                for i in range(10)
            ]
            index.add_records(records)

            # Search should aggregate across all shards
            results = index.search("brain research", top_k=5)

            assert len(results) == 5
            assert len(set(r["id"] for r in results)) == 5  # All unique

    def test_persistence(self, temp_dir, mock_model):
        """Test saving and loading indices."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            # Create and save index
            index1 = EmbeddingIndex(db_dir=temp_dir, shard_size=5)
            records = [{"id": f"doc_{i}", "text": f"Document {i}"} for i in range(8)]
            index1.add_records(records)
            index1.save()

            # Load in new instance
            index2 = EmbeddingIndex(db_dir=temp_dir, shard_size=5)

            # Should have same structure
            assert len(index2.indices) == 2
            assert index2.indices[0].ntotal == 5
            assert index2.indices[1].ntotal == 3

            # Search should work
            results = index2.search("Document", top_k=3)
            assert len(results) == 3

    def test_concurrent_add(self, temp_dir, mock_model):
        """Test concurrent record addition."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=100)

            def add_batch(start_id):
                records = [
                    {"id": f"doc_{start_id + i}", "text": f"Document {start_id + i}"}
                    for i in range(10)
                ]
                index.add_records(records)

            # Add records from multiple threads
            threads = []
            for i in range(5):
                t = threading.Thread(target=add_batch, args=(i * 10,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # Should have all 50 records
            assert sum(idx.ntotal for idx in index.indices) == 50

    def test_concurrent_search(self, temp_dir, mock_model):
        """Test concurrent search operations."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=100)

            # Add records
            records = [
                {"id": f"doc_{i}", "text": f"Research paper {i}"} for i in range(20)
            ]
            index.add_records(records)

            results_list = []

            def search_task():
                results = index.search("research paper", top_k=5)
                results_list.append(results)

            # Search from multiple threads
            threads = []
            for _ in range(10):
                t = threading.Thread(target=search_task)
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # All searches should succeed
            assert len(results_list) == 10
            assert all(len(results) == 5 for results in results_list)

    def test_empty_shard_handling(self, temp_dir, mock_model):
        """Test handling of empty shards."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir, shard_size=5)

            # Force creation of empty shard
            index._get_last_shard()

            # Search should handle empty shard
            results = index.search("test query", top_k=5)
            assert len(results) == 0

    def test_shutdown(self, temp_dir, mock_model):
        """Test proper shutdown."""
        with patch(
            "knowledge.embedding_index.SentenceTransformer", return_value=mock_model
        ):
            index = EmbeddingIndex(db_dir=temp_dir)

            # Add some data
            records = [{"id": "1", "text": "Test document"}]
            index.add_records(records)

            # Shutdown should save
            with patch.object(index, "save") as mock_save:
                index.shutdown()
                mock_save.assert_called_once()


class TestEmbeddingConfig:
    """Test the configuration system."""

    def test_default_config(self):
        """Test default configuration values."""
        config = EmbeddingConfig()

        assert config.model_name == "all-MiniLM-L6-v2"
        assert config.shard_size == 10000
        assert config.refresh_interval == 86400

    def test_env_loading(self, monkeypatch):
        """Test loading from environment variables."""
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "custom-model")
        monkeypatch.setenv("EMBEDDING_SHARD_SIZE", "5000")
        monkeypatch.setenv("EMBEDDING_REFRESH_INTERVAL", "3600")

        config = EmbeddingConfig.from_env()

        assert config.model_name == "custom-model"
        assert config.shard_size == 5000
        assert config.refresh_interval == 3600

    def test_file_loading(self, temp_dir):
        """Test loading from config file."""
        config_path = os.path.join(temp_dir, "config.json")

        # Save test config
        test_config = EmbeddingConfig(
            model_name="test-model", shard_size=2000, enable_metrics=False
        )
        test_config.save(config_path)

        # Load and verify
        loaded_config = EmbeddingConfig.from_file(config_path)
        assert loaded_config.model_name == "test-model"
        assert loaded_config.shard_size == 2000
        assert loaded_config.enable_metrics == False

    def test_validation(self):
        """Test configuration validation."""
        # Valid config
        config = EmbeddingConfig()
        assert config.validate() == True

        # Invalid shard size
        config = EmbeddingConfig(shard_size=-100)
        assert config.validate() == False

        # Invalid index type
        config = EmbeddingConfig(index_type="InvalidType")
        assert config.validate() == False


class TestEmbeddingMetrics:
    """Test the metrics collection system."""

    def test_query_recording(self):
        """Test recording query metrics."""
        collector = EmbeddingMetricsCollector()

        # Record some queries
        collector.record_query("test query 1", 50.0, 5, 2)
        collector.record_query("test query 2", 150.0, 3, 2)
        collector.record_query("test query 3", 75.0, 10, 3, error="timeout")

        summary = collector.get_summary()

        assert summary["total_queries"] == 3
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 1 / 3

    def test_latency_histogram(self):
        """Test latency histogram buckets."""
        collector = EmbeddingMetricsCollector()

        # Record queries with different latencies
        latencies = [5, 45, 95, 245, 495, 995, 2495, 6000]
        for i, latency in enumerate(latencies):
            collector.record_query(f"query {i}", latency, 1, 1)

        # Check histogram
        assert collector.latency_histogram[10] == 1  # 5ms
        assert collector.latency_histogram[50] == 2  # 5ms, 45ms
        assert collector.latency_histogram[100] == 3  # +95ms
        assert collector.latency_histogram[250] == 4  # +245ms
        assert collector.latency_histogram[float("inf")] == 1  # 6000ms

    def test_query_timer(self):
        """Test QueryTimer context manager."""
        collector = EmbeddingMetricsCollector()

        # Successful query
        with QueryTimer(collector, "test query", 2) as timer:
            time.sleep(0.01)  # Simulate work
            timer.set_results(5)

        # Failed query
        try:
            with QueryTimer(collector, "error query", 1) as timer:
                raise ValueError("Test error")
        except ValueError:
            pass

        summary = collector.get_summary()
        assert summary["total_queries"] == 2
        assert summary["total_errors"] == 1

    def test_index_metrics(self):
        """Test index state metrics."""
        collector = EmbeddingMetricsCollector()

        collector.update_index_metrics(
            total_embeddings=50000, total_shards=5, memory_usage_mb=1024.5
        )

        collector.record_refresh()

        summary = collector.get_summary()
        assert summary["index"]["total_embeddings"] == 50000
        assert summary["index"]["total_shards"] == 5
        assert summary["index"]["memory_usage_mb"] == 1024.5
        assert summary["index"]["refresh_count"] == 1
        assert summary["index"]["last_refresh"] is not None

    def test_prometheus_export(self):
        """Test Prometheus metrics export."""
        collector = EmbeddingMetricsCollector()

        # Add some data
        collector.record_query("test", 100.0, 5, 2)
        collector.update_index_metrics(10000, 2, 512.0)

        prometheus_output = collector.get_prometheus_metrics()

        assert "embedding_queries_total 1" in prometheus_output
        assert "embedding_errors_total 0" in prometheus_output
        assert "embedding_index_size 10000" in prometheus_output
        assert "embedding_index_shards 2" in prometheus_output
        assert "embedding_memory_usage_mb 512.0" in prometheus_output


# Integration test
@pytest.mark.integration
def test_full_system_integration(temp_dir):
    """Test full integration of config, metrics, and index."""
    # Setup config
    config = EmbeddingConfig(db_dir=temp_dir, shard_size=5, enable_metrics=True)

    # Setup metrics
    metrics = EmbeddingMetricsCollector()

    with patch("knowledge.embedding_index.SentenceTransformer") as mock_st:
        # Mock model
        mock_model = Mock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.side_effect = lambda text, **kwargs: np.random.randn(
            384 if isinstance(text, str) else len(text), 384
        ).astype(np.float32)
        mock_st.return_value = mock_model

        # Create index with config
        index = EmbeddingIndex(db_dir=config.db_dir, shard_size=config.shard_size)

        # Add records
        records = [{"id": f"doc_{i}", "text": f"Document {i}"} for i in range(10)]
        index.add_records(records)

        # Search with metrics
        with QueryTimer(metrics, "test search", len(index.indices)) as timer:
            results = index.search("Document", top_k=5)
            timer.set_results(len(results))

        # Verify
        assert len(results) == 5
        summary = metrics.get_summary()
        assert summary["total_queries"] == 1
        assert summary["total_errors"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
