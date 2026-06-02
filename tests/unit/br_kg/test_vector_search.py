"""
Test suite for vector search functionality
Tests KG-016: Vector Search Integration
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

from brain_researcher.services.br_kg.vector_search import (
    VectorIndexManager,
    VectorSearchConfig,
    VectorSearchEngine,
    VectorSearchResult,
)


class TestVectorIndexManager:
    """Test the VectorIndexManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = VectorSearchConfig(
            cache_dir=self.temp_dir,
            dimension=384,
            index_type="IndexFlatIP",
            normalize_embeddings=True,
        )
        self.manager = VectorIndexManager(self.config)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_index(self):
        """Test creating different types of indices."""
        # Test Flat IP index
        index = self.manager.create_index("test_type", 384)
        assert index is not None
        assert index.d == 384

        # Test with different dimension
        index2 = self.manager.create_index("test_type2", 512)
        assert index2.d == 512

    def test_add_embeddings(self):
        """Test adding embeddings to index."""
        # Create test embeddings
        embeddings = np.random.randn(10, 384).astype("float32")
        metadata = [{"id": i, "text": f"test_{i}"} for i in range(10)]

        # Add to index
        self.manager.add_embeddings("test_type", embeddings, metadata)

        # Verify
        assert "test_type" in self.manager.indices
        assert self.manager.indices["test_type"].ntotal == 10
        assert len(self.manager.metadata["test_type"]) == 10

    def test_search(self):
        """Test searching in index."""
        # Add test data
        embeddings = np.random.randn(10, 384).astype("float32")
        metadata = [{"id": i} for i in range(10)]
        self.manager.add_embeddings("test_type", embeddings, metadata)

        # Search
        query = np.random.randn(384).astype("float32")
        distances, indices = self.manager.search("test_type", query, k=5)

        assert len(distances) == 5
        assert len(indices) == 5
        assert all(i >= 0 and i < 10 for i in indices)

    def test_save_and_load_index(self):
        """Test saving and loading indices."""
        # Add test data
        embeddings = np.random.randn(5, 384).astype("float32")
        metadata = [{"id": i} for i in range(5)]
        self.manager.add_embeddings("test_type", embeddings, metadata)

        # Save
        self.manager.save_index("test_type")

        # Create new manager and load
        new_manager = VectorIndexManager(self.config)
        success = new_manager.load_index("test_type")

        assert success
        assert "test_type" in new_manager.indices
        assert new_manager.indices["test_type"].ntotal == 5


class TestVectorSearchEngine:
    """Test the VectorSearchEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = VectorSearchConfig(
            cache_dir=self.temp_dir,
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            normalize_embeddings=True,
            enable_cache=True,
            max_cache_size=100,
        )

        # Mock database
        self.mock_db = Mock()
        self.mock_db.find_nodes.return_value = []
        self.mock_db.get_node.return_value = {}

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_initialization(self, mock_st):
        """Test engine initialization."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.zeros((1, 384))
        mock_st.return_value = mock_model

        engine = VectorSearchEngine(self.mock_db, self.config)

        assert engine.db == self.mock_db
        assert engine.config == self.config
        assert engine.model is not None
        mock_st.assert_called_once_with(self.config.model_name, device="cpu")

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_create_text_representation(self, mock_st):
        """Test creating text representations for different node types."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_st.return_value = mock_model

        engine = VectorSearchEngine(self.mock_db, self.config)

        # Test Concept node
        concept_props = {
            "name": "Working Memory",
            "definition": "A cognitive system",
            "description": "Temporary storage and manipulation",
        }
        text = engine._create_text_representation("Concept", concept_props)
        assert "Working Memory" in text
        assert "cognitive system" in text

        # Test Publication node
        pub_props = {
            "title": "Neural Mechanisms",
            "abstract": "This study investigates...",
            "keywords": ["fMRI", "cognition"],
        }
        text = engine._create_text_representation("Publication", pub_props)
        assert "Neural Mechanisms" in text
        assert "fMRI cognition" in text

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_generate_embedding(self, mock_st):
        """Test embedding generation with caching."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.randn(384)
        mock_st.return_value = mock_model

        engine = VectorSearchEngine(self.mock_db, self.config)

        # First call - should generate
        text = "test query"
        embedding1 = engine.generate_embedding(text)
        assert embedding1.shape == (384,)
        mock_model.encode.assert_called_once()

        # Second call - should use cache
        mock_model.encode.reset_mock()
        embedding2 = engine.generate_embedding(text)
        np.testing.assert_array_equal(embedding1, embedding2)
        mock_model.encode.assert_not_called()

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_vector_search(self, mock_st):
        """Test vector similarity search."""
        # Setup mock model
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.randn(384)
        mock_st.return_value = mock_model

        # Setup mock database with test nodes
        self.mock_db.find_nodes.return_value = [
            ("node1", {"name": "Test Node 1", "description": "Description 1"}),
            ("node2", {"name": "Test Node 2", "description": "Description 2"}),
            ("node3", {"name": "Test Node 3", "description": "Description 3"}),
        ]

        engine = VectorSearchEngine(self.mock_db, self.config)

        # Perform search
        results = engine.vector_search("test query", k=2)

        # Verify results
        assert len(results) <= 2
        for result in results:
            assert isinstance(result, VectorSearchResult)
            assert result.node_id in ["node1", "node2", "node3"]
            assert result.node_type in [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]
            assert 0 <= result.score <= 1

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    @patch("brain_researcher.services.br_kg.search.SearchEngine")
    def test_hybrid_search(self, mock_search_engine, mock_st):
        """Test hybrid search combining vector and text search."""
        # Setup mock model
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.randn(384)
        mock_st.return_value = mock_model

        # Setup mock text search
        from brain_researcher.services.br_kg.search import SearchResult

        mock_text_results = [
            SearchResult(
                node_id="node1",
                node_type="Concept",
                score=0.8,
                matched_fields=["name"],
                properties={"name": "Test"},
            )
        ]
        mock_search_engine.return_value.search.return_value = mock_text_results

        engine = VectorSearchEngine(self.mock_db, self.config)

        # Perform hybrid search
        results = engine.hybrid_search(
            "test query", k=5, vector_weight=0.7, text_weight=0.3
        )

        # Verify results structure
        assert isinstance(results, list)
        for result in results:
            assert "node_id" in result
            assert "combined_score" in result
            assert "vector_score" in result
            assert "text_score" in result

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_find_similar_nodes(self, mock_st):
        """Test finding similar nodes."""
        # Setup mock model
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.randn(384)
        mock_st.return_value = mock_model

        # Setup mock database
        self.mock_db.get_node.return_value = {
            "name": "Reference Node",
            "description": "Test description",
        }
        self.mock_db.find_nodes.return_value = [
            ("ref_node", {"name": "Reference Node"}),
            ("similar1", {"name": "Similar Node 1"}),
            ("similar2", {"name": "Similar Node 2"}),
        ]

        engine = VectorSearchEngine(self.mock_db, self.config)

        # Find similar nodes
        results = engine.find_similar_nodes(
            "ref_node", "Concept", k=2, include_self=False
        )

        # Verify results
        assert len(results) <= 2
        node_ids = [r.node_id for r in results]
        assert "ref_node" not in node_ids  # Self should be excluded

    @patch("brain_researcher.services.br_kg.vector_search.SentenceTransformer")
    def test_get_embedding_stats(self, mock_st):
        """Test getting embedding statistics."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_st.return_value = mock_model

        engine = VectorSearchEngine(self.mock_db, self.config)

        stats = engine.get_embedding_stats()

        assert "model" in stats
        assert stats["model"] == self.config.model_name
        assert "dimension" in stats
        assert stats["dimension"] == 384
        assert "indices" in stats
        assert "cache" in stats


@pytest.mark.integration
class TestVectorSearchIntegration:
    """Integration tests for vector search with real data."""

    @pytest.mark.slow
    def test_real_embedding_generation(self):
        """Test with real sentence transformer model."""
        config = VectorSearchConfig(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            cache_dir=tempfile.mkdtemp(),
        )

        mock_db = Mock()
        mock_db.find_nodes.return_value = []

        engine = VectorSearchEngine(mock_db, config)

        # Generate real embedding
        text = "Functional connectivity in resting-state fMRI"
        embedding = engine.generate_embedding(text)

        assert embedding.shape == (384,)
        assert -1 <= embedding.min() <= embedding.max() <= 1

        # Cleanup
        shutil.rmtree(config.cache_dir, ignore_errors=True)

    @pytest.mark.slow
    def test_similarity_calculation(self):
        """Test similarity calculation between embeddings."""
        config = VectorSearchConfig(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            cache_dir=tempfile.mkdtemp(),
            normalize_embeddings=True,
        )

        mock_db = Mock()
        mock_db.find_nodes.return_value = []

        engine = VectorSearchEngine(mock_db, config)

        # Generate embeddings for similar texts
        text1 = "Brain connectivity analysis using fMRI"
        text2 = "fMRI-based brain network analysis"
        text3 = "Weather forecast for tomorrow"

        emb1 = engine.generate_embedding(text1)
        emb2 = engine.generate_embedding(text2)
        emb3 = engine.generate_embedding(text3)

        # Calculate cosine similarities
        sim_12 = np.dot(emb1, emb2)
        sim_13 = np.dot(emb1, emb3)

        # Similar texts should have higher similarity
        assert sim_12 > sim_13
        assert sim_12 > 0.5  # Reasonably similar
        assert sim_13 < 0.5  # Not very similar

        # Cleanup
        shutil.rmtree(config.cache_dir, ignore_errors=True)
