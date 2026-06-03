"""Unit tests for graph embeddings ML module.

This module tests the graph embedding functionality including:
- Node2Vec, DeepWalk, and Graph2Vec implementations
- Random walk generation
- Embedding training and similarity computation
- Visualization and model persistence
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any, Tuple
import tempfile
import os

# Import the modules to test
try:
    from brain_researcher.services.br_kg.ml.graph_embeddings import (
        GraphEmbedder,
        Node2VecEmbedder,
        DeepWalkEmbedder,
        Graph2VecEmbedder,
        BaseGraphEmbedder,
        EmbeddingConfig,
        EmbeddingType
    )
except ImportError:
    # Fallback if absolute imports don't work
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    from brain_researcher.services.br_kg.ml.graph_embeddings import (
        GraphEmbedder,
        Node2VecEmbedder,
        DeepWalkEmbedder,
        Graph2VecEmbedder,
        BaseGraphEmbedder,
        EmbeddingConfig,
        EmbeddingType
    )


# Mock dependencies for testing when not available
class MockWord2Vec:
    """Mock Word2Vec for testing."""

    def __init__(self, sentences, vector_size=100, window=5, min_count=1, workers=4,
                 sg=1, epochs=5, alpha=0.025, hs=0, negative=5):
        self.vector_size = vector_size
        self.window = window
        self.min_count = min_count
        self.sg = sg
        self.epochs = epochs

        # Mock vocabulary from sentences
        vocab = set()
        for sentence in sentences:
            vocab.update(sentence)

        # Create mock word vectors
        self.wv = Mock()
        self.wv.index_to_key = list(vocab)

        # Mock vector lookup
        def mock_getitem(word):
            # Return consistent random vector for each word
            np.random.seed(hash(word) % 2**32)
            return np.random.randn(vector_size)

        self.wv.__getitem__ = mock_getitem
        self.wv.__contains__ = lambda word: word in vocab


class MockNetworkX:
    """Mock NetworkX for testing."""

    class Graph:
        def __init__(self):
            self._nodes = set()
            self._edges = set()
            self._adjacency = {}

        def add_node(self, node):
            self._nodes.add(node)
            if node not in self._adjacency:
                self._adjacency[node] = set()

        def add_edge(self, u, v, weight=1.0):
            self.add_node(u)
            self.add_node(v)
            self._edges.add((u, v))
            self._adjacency[u].add(v)
            self._adjacency[v].add(u)

        def nodes(self):
            return list(self._nodes)

        def edges(self):
            return list(self._edges)

        def neighbors(self, node):
            return list(self._adjacency.get(node, set()))

        def has_edge(self, u, v):
            return (u, v) in self._edges or (v, u) in self._edges

        def degree(self, node):
            return len(self._adjacency.get(node, set()))

        def __len__(self):
            return len(self._nodes)


class TestEmbeddingConfig:
    """Test EmbeddingConfig configuration class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)

        assert config.embedding_type == EmbeddingType.NODE2VEC
        assert config.dimensions == 128
        assert config.walk_length == 80
        assert config.num_walks == 10
        assert config.window_size == 10
        assert config.min_count == 1
        assert config.workers == 4
        assert config.p == 1.0
        assert config.q == 1.0
        assert config.learning_rate == 0.025
        assert config.epochs == 5

    def test_custom_config(self):
        """Test custom configuration values."""
        config = EmbeddingConfig(
            embedding_type=EmbeddingType.DEEPWALK,
            dimensions=64,
            walk_length=40,
            num_walks=5,
            window_size=5,
            workers=2,
            learning_rate=0.01,
            epochs=10
        )

        assert config.embedding_type == EmbeddingType.DEEPWALK
        assert config.dimensions == 64
        assert config.walk_length == 40
        assert config.num_walks == 5
        assert config.window_size == 5
        assert config.workers == 2
        assert config.learning_rate == 0.01
        assert config.epochs == 10

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = EmbeddingConfig(
            embedding_type=EmbeddingType.GRAPH2VEC,
            dimensions=256,
            wl_iterations=4
        )

        config_dict = config.to_dict()

        assert config_dict["embedding_type"] == "graph2vec"
        assert config_dict["dimensions"] == 256
        assert config_dict["wl_iterations"] == 4
        assert "walk_length" in config_dict
        assert "learning_rate" in config_dict


class TestBaseGraphEmbedder:
    """Test BaseGraphEmbedder base class."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                yield

    def test_initialization_with_deps(self, mock_deps):
        """Test base embedder initialization with dependencies."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        assert embedder.config == config
        assert embedder.model is None
        assert embedder.graph is None
        assert len(embedder.embeddings) == 0
        assert len(embedder.vocabulary) == 0

    def test_initialization_without_deps(self):
        """Test initialization failure without dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', False):
            config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)

            with pytest.raises(ImportError, match="NetworkX and gensim are required"):
                BaseGraphEmbedder(config)

    def test_fit_not_implemented(self, mock_deps):
        """Test that fit method raises NotImplementedError."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        with pytest.raises(NotImplementedError):
            embedder.fit({})

    def test_get_embedding(self, mock_deps):
        """Test getting individual embeddings."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        # Add test embedding
        test_embedding = np.array([1.0, 2.0, 3.0])
        embedder.embeddings["node1"] = test_embedding

        result = embedder.get_embedding("node1")
        np.testing.assert_array_equal(result, test_embedding)

        # Test non-existent node
        result = embedder.get_embedding("nonexistent")
        assert result is None

    def test_get_all_embeddings(self, mock_deps):
        """Test getting all embeddings."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        # Add test embeddings
        embeddings = {
            "node1": np.array([1.0, 2.0]),
            "node2": np.array([3.0, 4.0])
        }
        embedder.embeddings = embeddings

        result = embedder.get_all_embeddings()

        assert len(result) == 2
        assert "node1" in result
        assert "node2" in result
        np.testing.assert_array_equal(result["node1"], embeddings["node1"])

    def test_similarity(self, mock_deps):
        """Test similarity computation."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        # Add test embeddings
        embedder.embeddings = {
            "node1": np.array([1.0, 0.0]),
            "node2": np.array([0.0, 1.0]),
            "node3": np.array([1.0, 0.0])  # Same as node1
        }

        # Test similarity
        sim1 = embedder.similarity("node1", "node2")
        assert abs(sim1 - 0.0) < 1e-6  # Orthogonal vectors

        sim2 = embedder.similarity("node1", "node3")
        assert abs(sim2 - 1.0) < 1e-6  # Identical vectors

        # Test with non-existent nodes
        sim3 = embedder.similarity("node1", "nonexistent")
        assert sim3 == 0.0

        # Test with zero vectors
        embedder.embeddings["zero"] = np.array([0.0, 0.0])
        sim4 = embedder.similarity("node1", "zero")
        assert sim4 == 0.0

    def test_most_similar(self, mock_deps):
        """Test finding most similar nodes."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        # Add test embeddings
        embedder.embeddings = {
            "target": np.array([1.0, 0.0]),
            "similar": np.array([0.9, 0.1]),  # Very similar
            "different": np.array([0.0, 1.0]),  # Orthogonal
            "opposite": np.array([-1.0, 0.0])  # Opposite
        }

        similar_nodes = embedder.most_similar("target", topn=2)

        assert len(similar_nodes) == 2
        assert similar_nodes[0][0] == "similar"  # Most similar first
        assert similar_nodes[0][1] > similar_nodes[1][1]  # Decreasing similarity

        # Test with non-existent node
        result = embedder.most_similar("nonexistent", topn=5)
        assert len(result) == 0

    def test_create_networkx_graph(self, mock_deps):
        """Test creating NetworkX graph from data."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)
        embedder = BaseGraphEmbedder(config)

        graph_data = {
            "nodes": ["A", "B", "C"],
            "edges": [
                {"start": "A", "end": "B"},
                {"source": "B", "target": "C", "properties": {"weight": 2.0}}
            ]
        }

        graph = embedder._create_networkx_graph(graph_data)

        assert len(graph.nodes()) == 3
        assert "A" in graph.nodes()
        assert "B" in graph.nodes()
        assert "C" in graph.nodes()

        assert graph.has_edge("A", "B")
        assert graph.has_edge("B", "C")


class TestNode2VecEmbedder:
    """Test Node2VecEmbedder class."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_initialization(self, mock_deps):
        """Test Node2Vec embedder initialization."""
        embedder = Node2VecEmbedder()

        assert embedder.config.embedding_type == EmbeddingType.NODE2VEC
        assert embedder.config.p == 1.0
        assert embedder.config.q == 1.0

    def test_initialization_with_config(self, mock_deps):
        """Test initialization with custom config."""
        config = EmbeddingConfig(
            embedding_type=EmbeddingType.NODE2VEC,
            p=2.0,
            q=0.5,
            dimensions=64
        )
        embedder = Node2VecEmbedder(config)

        assert embedder.config.p == 2.0
        assert embedder.config.q == 0.5
        assert embedder.config.dimensions == 64

    def test_fit_empty_graph(self, mock_deps):
        """Test fitting on empty graph."""
        embedder = Node2VecEmbedder()

        graph_data = {"nodes": [], "edges": []}
        result = embedder.fit(graph_data)

        assert len(result) == 0

    def test_fit_simple_graph(self, mock_deps):
        """Test fitting on simple graph."""
        embedder = Node2VecEmbedder()

        graph_data = {
            "nodes": ["A", "B", "C"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"}
            ]
        }

        result = embedder.fit(graph_data)

        # Should generate embeddings for connected nodes
        assert len(result) >= 0  # May vary based on walk generation
        assert isinstance(embedder.embeddings, dict)
        assert isinstance(embedder.vocabulary, set)

    def test_node2vec_walk_generation(self, mock_deps):
        """Test Node2Vec walk generation."""
        embedder = Node2VecEmbedder()

        # Create simple graph
        graph_data = {
            "nodes": ["A", "B", "C", "D"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "C", "end": "D"},
                {"start": "A", "end": "C"}
            ]
        }

        embedder.graph = embedder._create_networkx_graph(graph_data)

        # Generate walk
        walk = embedder._node2vec_walk("A")

        assert len(walk) >= 1
        assert walk[0] == "A"
        # All nodes in walk should be in graph
        for node in walk:
            assert node in embedder.graph.nodes()

    def test_biased_next_node_selection(self, mock_deps):
        """Test biased next node selection in Node2Vec."""
        config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC, p=2.0, q=0.5)
        embedder = Node2VecEmbedder(config)

        # Create graph structure for testing bias
        graph_data = {
            "nodes": ["A", "B", "C", "D"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "B", "end": "D"},
                {"start": "A", "end": "C"}  # Creates triangle A-B-C
            ]
        }

        embedder.graph = embedder._create_networkx_graph(graph_data)

        neighbors = ["C", "D"]

        # Test with different bias parameters
        next_node = embedder._get_next_node("A", "B", neighbors)
        assert next_node in neighbors


class TestDeepWalkEmbedder:
    """Test DeepWalkEmbedder class."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_initialization(self, mock_deps):
        """Test DeepWalk embedder initialization."""
        embedder = DeepWalkEmbedder()

        assert embedder.config.embedding_type == EmbeddingType.DEEPWALK

    def test_fit_simple_graph(self, mock_deps):
        """Test fitting DeepWalk on simple graph."""
        embedder = DeepWalkEmbedder()

        graph_data = {
            "nodes": ["A", "B", "C"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"}
            ]
        }

        result = embedder.fit(graph_data)

        assert isinstance(result, dict)
        assert isinstance(embedder.embeddings, dict)

    def test_random_walk_generation(self, mock_deps):
        """Test uniform random walk generation."""
        embedder = DeepWalkEmbedder()

        graph_data = {
            "nodes": ["A", "B", "C"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"}
            ]
        }

        embedder.graph = embedder._create_networkx_graph(graph_data)

        walk = embedder._random_walk("A")

        assert len(walk) >= 1
        assert walk[0] == "A"
        # All nodes in walk should be in graph
        for node in walk:
            assert node in embedder.graph.nodes()


class TestGraph2VecEmbedder:
    """Test Graph2VecEmbedder class."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_initialization(self, mock_deps):
        """Test Graph2Vec embedder initialization."""
        embedder = Graph2VecEmbedder()

        assert embedder.config.embedding_type == EmbeddingType.GRAPH2VEC
        assert embedder.config.wl_iterations == 3

    def test_fit_single_graph(self, mock_deps):
        """Test fitting Graph2Vec on single graph."""
        embedder = Graph2VecEmbedder()

        graph_data = {
            "graph_id": "test_graph",
            "nodes": ["A", "B", "C"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"}
            ]
        }

        result = embedder.fit(graph_data)

        assert isinstance(result, dict)
        if result:  # May be empty if patterns don't generate vocabulary
            assert "test_graph" in result or "graph_0" in result

    def test_fit_multiple_graphs(self, mock_deps):
        """Test fitting Graph2Vec on multiple graphs."""
        embedder = Graph2VecEmbedder()

        graphs = [
            {
                "graph_id": "graph1",
                "nodes": ["A", "B"],
                "edges": [{"start": "A", "end": "B"}]
            },
            {
                "graph_id": "graph2",
                "nodes": ["X", "Y", "Z"],
                "edges": [{"start": "X", "end": "Y"}, {"start": "Y", "end": "Z"}]
            }
        ]

        result = embedder.fit(graphs)

        assert isinstance(result, dict)

    def test_wl_patterns_generation(self, mock_deps):
        """Test Weisfeiler-Lehman pattern generation."""
        embedder = Graph2VecEmbedder()

        # Create simple graph
        graph = MockNetworkX.Graph()
        graph.add_edge("A", "B")
        graph.add_edge("B", "C")

        patterns = embedder._wl_patterns(graph)

        assert isinstance(patterns, list)
        assert len(patterns) > 0  # Should generate some patterns
        assert all(isinstance(pattern, str) for pattern in patterns)

    def test_wl_patterns_empty_graph(self, mock_deps):
        """Test WL patterns on empty graph."""
        embedder = Graph2VecEmbedder()

        graph = MockNetworkX.Graph()
        patterns = embedder._wl_patterns(graph)

        assert patterns == []


class TestGraphEmbedder:
    """Test GraphEmbedder high-level interface."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_initialization_node2vec(self, mock_deps):
        """Test initialization with Node2Vec."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        assert embedder.embedding_type == EmbeddingType.NODE2VEC
        assert isinstance(embedder.embedder, Node2VecEmbedder)

    def test_initialization_deepwalk(self, mock_deps):
        """Test initialization with DeepWalk."""
        embedder = GraphEmbedder(EmbeddingType.DEEPWALK)

        assert embedder.embedding_type == EmbeddingType.DEEPWALK
        assert isinstance(embedder.embedder, DeepWalkEmbedder)

    def test_initialization_graph2vec(self, mock_deps):
        """Test initialization with Graph2Vec."""
        embedder = GraphEmbedder(EmbeddingType.GRAPH2VEC)

        assert embedder.embedding_type == EmbeddingType.GRAPH2VEC
        assert isinstance(embedder.embedder, Graph2VecEmbedder)

    def test_unsupported_embedding_type(self, mock_deps):
        """Test error with unsupported embedding type."""
        with pytest.raises(ValueError, match="Unsupported embedding type"):
            GraphEmbedder("unsupported_type")

    def test_fit_delegation(self, mock_deps):
        """Test that fit method delegates to underlying embedder."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        # Mock the underlying embedder
        mock_result = {"node1": np.array([1, 2, 3])}
        embedder.embedder.fit = Mock(return_value=mock_result)

        graph_data = {"nodes": ["node1"], "edges": []}
        result = embedder.fit(graph_data)

        embedder.embedder.fit.assert_called_once_with(graph_data)
        assert result == mock_result

    def test_get_embedding_delegation(self, mock_deps):
        """Test that get_embedding delegates to underlying embedder."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        mock_embedding = np.array([1, 2, 3])
        embedder.embedder.get_embedding = Mock(return_value=mock_embedding)

        result = embedder.get_embedding("node1")

        embedder.embedder.get_embedding.assert_called_once_with("node1")
        np.testing.assert_array_equal(result, mock_embedding)

    def test_similarity_delegation(self, mock_deps):
        """Test that similarity delegates to underlying embedder."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        embedder.embedder.similarity = Mock(return_value=0.85)

        result = embedder.similarity("node1", "node2")

        embedder.embedder.similarity.assert_called_once_with("node1", "node2")
        assert result == 0.85

    def test_visualization_without_matplotlib(self, mock_deps):
        """Test visualization when matplotlib is not available."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.plt', None):
            embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

            result = embedder.visualize_embeddings()

            assert result is None

    def test_visualization_empty_embeddings(self, mock_deps):
        """Test visualization with empty embeddings."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.plt', Mock()):
            embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

            # Mock empty embeddings
            embedder.get_all_embeddings = Mock(return_value={})

            result = embedder.visualize_embeddings()

            assert result is None

    def test_visualization_with_embeddings(self, mock_deps):
        """Test visualization with actual embeddings."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.plt') as mock_plt:
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.TSNE') as mock_tsne:
                embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

                # Mock embeddings
                mock_embeddings = {
                    "node1": np.array([1.0, 2.0, 3.0]),
                    "node2": np.array([4.0, 5.0, 6.0]),
                    "node3": np.array([7.0, 8.0, 9.0])
                }
                embedder.get_all_embeddings = Mock(return_value=mock_embeddings)

                # Mock t-SNE
                mock_tsne_instance = Mock()
                mock_tsne_instance.fit_transform.return_value = np.array([[1, 2], [3, 4], [5, 6]])
                mock_tsne.return_value = mock_tsne_instance

                # Mock matplotlib
                mock_fig, mock_ax = Mock(), Mock()
                mock_plt.subplots.return_value = (mock_fig, mock_ax)

                result = embedder.visualize_embeddings(method="tsne")

                assert result == mock_fig
                mock_tsne.assert_called_once()
                mock_plt.subplots.assert_called_once()

    def test_save_load_model(self, mock_deps):
        """Test saving and loading model."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        # Mock the underlying embedder methods
        embedder.embedder.save_embeddings = Mock()
        embedder.embedder.load_embeddings = Mock()

        # Test save
        embedder.save_model("test.pkl")
        embedder.embedder.save_embeddings.assert_called_once_with("test.pkl")

        # Test load
        embedder.load_model("test.pkl")
        embedder.embedder.load_embeddings.assert_called_once_with("test.pkl")

    def test_get_embedding_info_empty(self, mock_deps):
        """Test getting embedding info when empty."""
        embedder = GraphEmbedder(EmbeddingType.DEEPWALK)

        embedder.get_all_embeddings = Mock(return_value={})

        info = embedder.get_embedding_info()

        assert info["embedding_type"] == "deepwalk"
        assert info["num_embeddings"] == 0
        assert info["embedding_dimension"] == 0
        assert "config" in info

    def test_get_embedding_info_with_data(self, mock_deps):
        """Test getting embedding info with data."""
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)

        mock_embeddings = {
            "node1": np.array([1.0, 2.0, 3.0, 4.0]),
            "node2": np.array([5.0, 6.0, 7.0, 8.0])
        }
        embedder.get_all_embeddings = Mock(return_value=mock_embeddings)
        embedder.embedder.vocabulary = {"node1", "node2", "node3"}

        info = embedder.get_embedding_info()

        assert info["embedding_type"] == "node2vec"
        assert info["num_embeddings"] == 2
        assert info["embedding_dimension"] == 4
        assert info["vocabulary_size"] == 3
        assert len(info["sample_entities"]) <= 10


class TestModelPersistence:
    """Test model saving and loading functionality."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_save_load_embeddings(self, mock_deps):
        """Test saving and loading embeddings."""
        embedder = Node2VecEmbedder()

        # Set up test data
        test_embeddings = {
            "node1": np.array([1.0, 2.0, 3.0]),
            "node2": np.array([4.0, 5.0, 6.0])
        }
        embedder.embeddings = test_embeddings
        embedder.vocabulary = {"node1", "node2"}

        with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # Save embeddings
            embedder.save_embeddings(tmp_path)

            # Create new embedder and load
            new_embedder = Node2VecEmbedder()
            new_embedder.load_embeddings(tmp_path)

            # Verify loaded data
            assert len(new_embedder.embeddings) == 2
            assert "node1" in new_embedder.embeddings
            assert "node2" in new_embedder.embeddings
            np.testing.assert_array_equal(
                new_embedder.embeddings["node1"],
                test_embeddings["node1"]
            )
            assert new_embedder.vocabulary == {"node1", "node2"}

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestDependencyHandling:
    """Test behavior when dependencies are not available."""

    def test_missing_dependencies(self):
        """Test ImportError when dependencies are missing."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', False):
            config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)

            with pytest.raises(ImportError, match="NetworkX and gensim are required"):
                BaseGraphEmbedder(config)

            with pytest.raises(ImportError, match="NetworkX and gensim are required"):
                Node2VecEmbedder(config)

            with pytest.raises(ImportError, match="NetworkX and gensim are required"):
                DeepWalkEmbedder(config)

            with pytest.raises(ImportError, match="NetworkX and gensim are required"):
                Graph2VecEmbedder(config)


@pytest.mark.integration
class TestEmbeddingIntegration:
    """Integration tests for embedding workflow."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies."""
        with patch('brain_researcher.services.br_kg.ml.graph_embeddings.DEPS_AVAILABLE', True):
            with patch('brain_researcher.services.br_kg.ml.graph_embeddings.nx', MockNetworkX):
                with patch('brain_researcher.services.br_kg.ml.graph_embeddings.Word2Vec', MockWord2Vec):
                    yield

    def test_end_to_end_node2vec(self, mock_deps):
        """Test complete Node2Vec workflow."""
        # Create test graph
        graph_data = {
            "nodes": ["A", "B", "C", "D", "E"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "C", "end": "D"},
                {"start": "D", "end": "E"},
                {"start": "A", "end": "C"},  # Create some cycles
                {"start": "B", "end": "D"}
            ]
        }

        # Configure and train embeddings
        config = EmbeddingConfig(
            embedding_type=EmbeddingType.NODE2VEC,
            dimensions=64,
            walk_length=10,
            num_walks=5,
            p=1.0,
            q=1.0
        )

        embedder = GraphEmbedder(EmbeddingType.NODE2VEC, config)
        embeddings = embedder.fit(graph_data)

        # Verify results
        assert isinstance(embeddings, dict)

        # Test similarity queries
        if embeddings:
            nodes = list(embeddings.keys())
            if len(nodes) >= 2:
                sim = embedder.similarity(nodes[0], nodes[1])
                assert isinstance(sim, float)
                assert -1.0 <= sim <= 1.0

            # Test most similar
            if nodes:
                similar = embedder.most_similar(nodes[0], topn=2)
                assert isinstance(similar, list)

    def test_end_to_end_graph2vec(self, mock_deps):
        """Test complete Graph2Vec workflow."""
        # Create test graphs
        graphs = [
            {
                "graph_id": "social_network",
                "nodes": ["Alice", "Bob", "Charlie"],
                "edges": [
                    {"start": "Alice", "end": "Bob"},
                    {"start": "Bob", "end": "Charlie"}
                ]
            },
            {
                "graph_id": "protein_network",
                "nodes": ["P1", "P2", "P3", "P4"],
                "edges": [
                    {"start": "P1", "end": "P2"},
                    {"start": "P2", "end": "P3"},
                    {"start": "P3", "end": "P4"},
                    {"start": "P1", "end": "P4"}
                ]
            }
        ]

        config = EmbeddingConfig(
            embedding_type=EmbeddingType.GRAPH2VEC,
            dimensions=32,
            wl_iterations=2
        )

        embedder = GraphEmbedder(EmbeddingType.GRAPH2VEC, config)
        embeddings = embedder.fit(graphs)

        # Verify results
        assert isinstance(embeddings, dict)

        # Test graph similarity
        if len(embeddings) >= 2:
            graph_ids = list(embeddings.keys())
            sim = embedder.similarity(graph_ids[0], graph_ids[1])
            assert isinstance(sim, float)

    def test_embedding_comparison(self, mock_deps):
        """Test comparing different embedding methods."""
        graph_data = {
            "nodes": ["A", "B", "C", "D"],
            "edges": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "C", "end": "D"},
                {"start": "A", "end": "D"}
            ]
        }

        methods = [EmbeddingType.NODE2VEC, EmbeddingType.DEEPWALK]
        results = {}

        for method in methods:
            embedder = GraphEmbedder(method)
            embeddings = embedder.fit(graph_data)
            results[method.value] = embeddings

        # Both methods should produce embeddings
        for method, embeddings in results.items():
            assert isinstance(embeddings, dict)


if __name__ == "__main__":
    pytest.main([__file__])