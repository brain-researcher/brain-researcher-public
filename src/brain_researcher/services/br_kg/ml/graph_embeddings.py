"""Graph embedding methods - completes KG-031 Graph ML.

This module provides Node2Vec, Graph2Vec, and DeepWalk implementations
for learning distributed representations of graphs and nodes.
"""

from __future__ import annotations

import json
import logging
import pickle
import random
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    import matplotlib.pyplot as plt
    import networkx as nx
    import seaborn as sns
    from gensim.models import Word2Vec
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE

    DEPS_AVAILABLE = True
    DEPS_IMPORT_ERROR = None
except ImportError as exc:
    nx = None
    Word2Vec = None
    PCA = None
    TSNE = None
    plt = None
    sns = None
    DEPS_AVAILABLE = False
    DEPS_IMPORT_ERROR = repr(exc)

logger = logging.getLogger(__name__)


class EmbeddingType(Enum):
    """Types of graph embeddings."""

    NODE2VEC = "node2vec"
    DEEPWALK = "deepwalk"
    GRAPH2VEC = "graph2vec"


@dataclass
class EmbeddingConfig:
    """Configuration for graph embeddings."""

    embedding_type: EmbeddingType
    dimensions: int = 128
    walk_length: int = 80
    num_walks: int = 10
    window_size: int = 10
    min_count: int = 1
    workers: int = 4

    # Node2Vec specific parameters
    p: float = 1.0  # Return parameter
    q: float = 1.0  # In-out parameter

    # Graph2Vec specific parameters
    wl_iterations: int = 3  # Weisfeiler-Lehman iterations

    # Word2Vec parameters
    learning_rate: float = 0.025
    epochs: int = 5
    sg: int = 1  # Skip-gram
    hs: int = 0  # Hierarchical softmax
    negative: int = 5  # Negative sampling

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "embedding_type": self.embedding_type.value,
            "dimensions": self.dimensions,
            "walk_length": self.walk_length,
            "num_walks": self.num_walks,
            "window_size": self.window_size,
            "min_count": self.min_count,
            "workers": self.workers,
            "p": self.p,
            "q": self.q,
            "wl_iterations": self.wl_iterations,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "sg": self.sg,
            "hs": self.hs,
            "negative": self.negative,
        }


class BaseGraphEmbedder:
    """Base class for graph embedding methods."""

    def __init__(self, config: EmbeddingConfig):
        """Initialize embedder.

        Args:
            config: Embedding configuration
        """
        if not DEPS_AVAILABLE:
            raise ImportError("NetworkX and gensim are required for graph embeddings")

        self.config = config
        self.model = None
        self.graph = None
        self.embeddings = {}
        self.vocabulary = set()

    def fit(self, graph_data: Dict[str, Any]) -> Dict[str, np.ndarray]:
        """Fit embedding model on graph data.

        Args:
            graph_data: Graph structure with nodes and edges

        Returns:
            Dictionary of embeddings {node_id: embedding_vector}
        """
        raise NotImplementedError("Subclasses must implement fit method")

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        """Get embedding for a specific node.

        Args:
            node_id: Node identifier

        Returns:
            Embedding vector or None if not found
        """
        return self.embeddings.get(node_id)

    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all node embeddings."""
        return self.embeddings.copy()

    def similarity(self, node1: str, node2: str) -> float:
        """Calculate similarity between two nodes.

        Args:
            node1: First node ID
            node2: Second node ID

        Returns:
            Cosine similarity score
        """
        emb1 = self.get_embedding(node1)
        emb2 = self.get_embedding(node2)

        if emb1 is None or emb2 is None:
            return 0.0

        # Cosine similarity
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return np.dot(emb1, emb2) / (norm1 * norm2)

    def most_similar(self, node_id: str, topn: int = 10) -> List[Tuple[str, float]]:
        """Find most similar nodes.

        Args:
            node_id: Reference node ID
            topn: Number of similar nodes to return

        Returns:
            List of (node_id, similarity_score) tuples
        """
        if node_id not in self.embeddings:
            return []

        similarities = []
        target_emb = self.embeddings[node_id]

        for other_id, other_emb in self.embeddings.items():
            if other_id != node_id:
                sim = self.similarity(node_id, other_id)
                similarities.append((other_id, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:topn]

    def save_embeddings(self, filepath: str):
        """Save embeddings to file.

        Args:
            filepath: Output file path
        """
        save_data = {
            "embeddings": self.embeddings,
            "config": self.config.to_dict(),
            "vocabulary": list(self.vocabulary),
        }

        with open(filepath, "wb") as f:
            pickle.dump(save_data, f)

        logger.info(f"Saved embeddings to {filepath}")

    def load_embeddings(self, filepath: str):
        """Load embeddings from file.

        Args:
            filepath: Input file path
        """
        with open(filepath, "rb") as f:
            save_data = pickle.load(f)

        self.embeddings = save_data["embeddings"]
        self.vocabulary = set(save_data.get("vocabulary", []))

        # Restore config
        config_dict = save_data["config"]
        self.config = EmbeddingConfig(
            embedding_type=EmbeddingType(config_dict["embedding_type"]),
            **{k: v for k, v in config_dict.items() if k != "embedding_type"},
        )

        logger.info(f"Loaded embeddings from {filepath}")

    def _create_networkx_graph(self, graph_data: Dict[str, Any]) -> nx.Graph:
        """Create NetworkX graph from graph data.

        Args:
            graph_data: Graph structure

        Returns:
            NetworkX graph
        """
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        # Create graph
        graph = nx.Graph()

        # Add nodes
        for node_id in nodes:
            graph.add_node(str(node_id))

        # Add edges
        for edge in edges:
            src = str(edge.get("start") or edge.get("source"))
            dst = str(edge.get("end") or edge.get("target"))
            weight = edge.get("properties", {}).get("weight", 1.0)

            if src in nodes and dst in nodes:
                graph.add_edge(src, dst, weight=weight)

        return graph


class Node2VecEmbedder(BaseGraphEmbedder):
    """Node2Vec graph embedding implementation."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """Initialize Node2Vec embedder.

        Args:
            config: Embedding configuration
        """
        if config is None:
            config = EmbeddingConfig(embedding_type=EmbeddingType.NODE2VEC)

        super().__init__(config)

    def fit(self, graph_data: Dict[str, Any]) -> Dict[str, np.ndarray]:
        """Fit Node2Vec model.

        Args:
            graph_data: Graph structure

        Returns:
            Node embeddings
        """
        # Create NetworkX graph
        self.graph = self._create_networkx_graph(graph_data)

        if len(self.graph.nodes()) == 0:
            logger.warning("Empty graph provided")
            return {}

        # Generate walks
        walks = self._generate_walks()

        if not walks:
            logger.warning("No walks generated")
            return {}

        # Train Word2Vec model
        self.model = Word2Vec(
            walks,
            vector_size=self.config.dimensions,
            window=self.config.window_size,
            min_count=self.config.min_count,
            sg=self.config.sg,
            workers=self.config.workers,
            epochs=self.config.epochs,
            alpha=self.config.learning_rate,
            hs=self.config.hs,
            negative=self.config.negative,
        )

        # Extract embeddings
        self.embeddings = {}
        self.vocabulary = set(self.model.wv.index_to_key)

        for node_id in self.graph.nodes():
            if str(node_id) in self.vocabulary:
                self.embeddings[str(node_id)] = self.model.wv[str(node_id)]

        logger.info(f"Generated Node2Vec embeddings for {len(self.embeddings)} nodes")
        return self.embeddings

    def _generate_walks(self) -> List[List[str]]:
        """Generate random walks using Node2Vec strategy."""
        walks = []

        for _ in range(self.config.num_walks):
            for node in self.graph.nodes():
                walk = self._node2vec_walk(node)
                if len(walk) > 1:
                    walks.append([str(n) for n in walk])

        return walks

    def _node2vec_walk(self, start_node: str) -> List[str]:
        """Generate a single Node2Vec walk.

        Args:
            start_node: Starting node

        Returns:
            Walk as list of node IDs
        """
        walk = [start_node]

        while len(walk) < self.config.walk_length:
            current = walk[-1]
            neighbors = list(self.graph.neighbors(current))

            if not neighbors:
                break

            if len(walk) == 1:
                # First step - uniform random
                next_node = random.choice(neighbors)
            else:
                # Node2Vec biased walk
                prev = walk[-2]
                next_node = self._get_next_node(prev, current, neighbors)

            walk.append(next_node)

        return walk

    def _get_next_node(self, prev: str, current: str, neighbors: List[str]) -> str:
        """Get next node using Node2Vec bias.

        Args:
            prev: Previous node
            current: Current node
            neighbors: Neighbor nodes

        Returns:
            Next node to visit
        """
        weights = []

        for neighbor in neighbors:
            if neighbor == prev:
                # Return to previous node
                weight = 1.0 / self.config.p
            elif self.graph.has_edge(neighbor, prev):
                # Stay local (BFS-like)
                weight = 1.0
            else:
                # Explore further (DFS-like)
                weight = 1.0 / self.config.q

            weights.append(weight)

        # Weighted random selection
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(neighbors)

        normalized_weights = [w / total_weight for w in weights]
        return np.random.choice(neighbors, p=normalized_weights)


class DeepWalkEmbedder(BaseGraphEmbedder):
    """DeepWalk graph embedding implementation."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """Initialize DeepWalk embedder.

        Args:
            config: Embedding configuration
        """
        if config is None:
            config = EmbeddingConfig(embedding_type=EmbeddingType.DEEPWALK)

        super().__init__(config)

    def fit(self, graph_data: Dict[str, Any]) -> Dict[str, np.ndarray]:
        """Fit DeepWalk model.

        Args:
            graph_data: Graph structure

        Returns:
            Node embeddings
        """
        # Create NetworkX graph
        self.graph = self._create_networkx_graph(graph_data)

        if len(self.graph.nodes()) == 0:
            logger.warning("Empty graph provided")
            return {}

        # Generate walks
        walks = self._generate_random_walks()

        if not walks:
            logger.warning("No walks generated")
            return {}

        # Train Word2Vec model
        self.model = Word2Vec(
            walks,
            vector_size=self.config.dimensions,
            window=self.config.window_size,
            min_count=self.config.min_count,
            sg=self.config.sg,
            workers=self.config.workers,
            epochs=self.config.epochs,
            alpha=self.config.learning_rate,
            hs=self.config.hs,
            negative=self.config.negative,
        )

        # Extract embeddings
        self.embeddings = {}
        self.vocabulary = set(self.model.wv.index_to_key)

        for node_id in self.graph.nodes():
            if str(node_id) in self.vocabulary:
                self.embeddings[str(node_id)] = self.model.wv[str(node_id)]

        logger.info(f"Generated DeepWalk embeddings for {len(self.embeddings)} nodes")
        return self.embeddings

    def _generate_random_walks(self) -> List[List[str]]:
        """Generate uniform random walks."""
        walks = []

        for _ in range(self.config.num_walks):
            for node in self.graph.nodes():
                walk = self._random_walk(node)
                if len(walk) > 1:
                    walks.append([str(n) for n in walk])

        return walks

    def _random_walk(self, start_node: str) -> List[str]:
        """Generate a uniform random walk.

        Args:
            start_node: Starting node

        Returns:
            Walk as list of node IDs
        """
        walk = [start_node]

        while len(walk) < self.config.walk_length:
            current = walk[-1]
            neighbors = list(self.graph.neighbors(current))

            if not neighbors:
                break

            next_node = random.choice(neighbors)
            walk.append(next_node)

        return walk


class Graph2VecEmbedder(BaseGraphEmbedder):
    """Graph2Vec embedding for entire graphs."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """Initialize Graph2Vec embedder.

        Args:
            config: Embedding configuration
        """
        if config is None:
            config = EmbeddingConfig(embedding_type=EmbeddingType.GRAPH2VEC)

        super().__init__(config)

    def fit(
        self, graph_data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> Dict[str, np.ndarray]:
        """Fit Graph2Vec model.

        Args:
            graph_data: Single graph or list of graphs

        Returns:
            Graph embeddings
        """
        if isinstance(graph_data, dict):
            graphs = [graph_data]
        else:
            graphs = graph_data

        # Generate documents from graphs
        documents = []
        graph_ids = []

        for i, graph in enumerate(graphs):
            graph_id = graph.get("graph_id", f"graph_{i}")
            graph_ids.append(graph_id)

            # Create NetworkX graph
            nx_graph = self._create_networkx_graph(graph)

            # Generate Weisfeiler-Lehman subtree patterns
            patterns = self._wl_patterns(nx_graph)
            documents.append(patterns)

        if not documents:
            logger.warning("No documents generated")
            return {}

        # Train Word2Vec on patterns
        self.model = Word2Vec(
            documents,
            vector_size=self.config.dimensions,
            window=self.config.window_size,
            min_count=self.config.min_count,
            sg=self.config.sg,
            workers=self.config.workers,
            epochs=self.config.epochs,
            alpha=self.config.learning_rate,
            hs=self.config.hs,
            negative=self.config.negative,
        )

        # Generate graph embeddings by averaging pattern embeddings
        self.embeddings = {}
        self.vocabulary = set(self.model.wv.index_to_key)

        for i, (graph_id, patterns) in enumerate(zip(graph_ids, documents)):
            if patterns:
                # Average embeddings of patterns in this graph
                pattern_embeddings = []
                for pattern in patterns:
                    if pattern in self.vocabulary:
                        pattern_embeddings.append(self.model.wv[pattern])

                if pattern_embeddings:
                    graph_embedding = np.mean(pattern_embeddings, axis=0)
                    self.embeddings[graph_id] = graph_embedding

        logger.info(f"Generated Graph2Vec embeddings for {len(self.embeddings)} graphs")
        return self.embeddings

    def _wl_patterns(self, graph: nx.Graph) -> List[str]:
        """Generate Weisfeiler-Lehman subtree patterns.

        Args:
            graph: NetworkX graph

        Returns:
            List of pattern strings
        """
        if len(graph.nodes()) == 0:
            return []

        # Initialize node labels with degree
        node_labels = {node: str(graph.degree(node)) for node in graph.nodes()}
        patterns = []

        for iteration in range(self.config.wl_iterations):
            # Collect current labels as patterns
            patterns.extend(node_labels.values())

            # Update labels based on neighborhood
            new_labels = {}

            for node in graph.nodes():
                # Get neighbor labels
                neighbor_labels = [
                    node_labels[neighbor] for neighbor in graph.neighbors(node)
                ]
                neighbor_labels.sort()

                # Create new label by combining current and neighbor labels
                combined = node_labels[node] + "_" + "_".join(neighbor_labels)
                new_labels[node] = str(
                    hash(combined) % 10000
                )  # Hash to keep manageable

            node_labels = new_labels

        # Add final iteration labels
        patterns.extend(node_labels.values())

        return patterns


class GraphEmbedder:
    """High-level interface for graph embeddings."""

    def __init__(
        self, embedding_type: EmbeddingType, config: Optional[EmbeddingConfig] = None
    ):
        """Initialize graph embedder.

        Args:
            embedding_type: Type of embedding to use
            config: Embedding configuration
        """
        self.embedding_type = embedding_type
        self.config = config or EmbeddingConfig(embedding_type=embedding_type)

        # Create embedder
        if embedding_type == EmbeddingType.NODE2VEC:
            self.embedder = Node2VecEmbedder(self.config)
        elif embedding_type == EmbeddingType.DEEPWALK:
            self.embedder = DeepWalkEmbedder(self.config)
        elif embedding_type == EmbeddingType.GRAPH2VEC:
            self.embedder = Graph2VecEmbedder(self.config)
        else:
            raise ValueError(f"Unsupported embedding type: {embedding_type}")

    def fit(
        self, graph_data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> Dict[str, np.ndarray]:
        """Fit embedding model."""
        return self.embedder.fit(graph_data)

    def get_embedding(self, entity_id: str) -> Optional[np.ndarray]:
        """Get embedding for entity."""
        return self.embedder.get_embedding(entity_id)

    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all embeddings."""
        return self.embedder.get_all_embeddings()

    def similarity(self, entity1: str, entity2: str) -> float:
        """Calculate similarity between entities."""
        return self.embedder.similarity(entity1, entity2)

    def most_similar(self, entity_id: str, topn: int = 10) -> List[Tuple[str, float]]:
        """Find most similar entities."""
        return self.embedder.most_similar(entity_id, topn)

    def visualize_embeddings(
        self,
        method: str = "tsne",
        perplexity: int = 30,
        n_components: int = 2,
        figsize: Tuple[int, int] = (12, 8),
        sample_size: Optional[int] = None,
    ) -> Optional[Any]:
        """Visualize embeddings in 2D space.

        Args:
            method: Dimensionality reduction method ("tsne" or "pca")
            perplexity: t-SNE perplexity parameter
            n_components: Number of components
            figsize: Figure size
            sample_size: Number of nodes to sample for visualization

        Returns:
            Matplotlib figure
        """
        if plt is None:
            logger.warning("Matplotlib not available for visualization")
            return None

        embeddings = self.get_all_embeddings()
        if not embeddings:
            logger.warning("No embeddings to visualize")
            return None

        # Sample if too many embeddings
        if sample_size and len(embeddings) > sample_size:
            sampled_keys = random.sample(list(embeddings.keys()), sample_size)
            embeddings = {k: embeddings[k] for k in sampled_keys}

        # Prepare data
        entity_ids = list(embeddings.keys())
        embedding_matrix = np.array(list(embeddings.values()))

        # Dimensionality reduction
        if method.lower() == "tsne":
            if TSNE is None:
                logger.warning("scikit-learn not available for t-SNE")
                return None
            reducer = TSNE(
                n_components=n_components, perplexity=perplexity, random_state=42
            )
        elif method.lower() == "pca":
            if PCA is None:
                logger.warning("scikit-learn not available for PCA")
                return None
            reducer = PCA(n_components=n_components, random_state=42)
        else:
            raise ValueError(f"Unsupported reduction method: {method}")

        reduced_embeddings = reducer.fit_transform(embedding_matrix)

        # Create visualization
        fig, ax = plt.subplots(figsize=figsize)

        scatter = ax.scatter(
            reduced_embeddings[:, 0], reduced_embeddings[:, 1], alpha=0.7, s=50
        )

        ax.set_title(
            f"{self.embedding_type.value.title()} Embeddings ({method.upper()})"
        )
        ax.set_xlabel(f"{method.upper()} Component 1")
        ax.set_ylabel(f"{method.upper()} Component 2")

        # Optionally add labels for a subset of points
        if len(entity_ids) <= 50:  # Only label if not too many points
            for i, entity_id in enumerate(entity_ids):
                ax.annotate(
                    entity_id[:10] + ("..." if len(entity_id) > 10 else ""),
                    (reduced_embeddings[i, 0], reduced_embeddings[i, 1]),
                    xytext=(5, 5),
                    textcoords="offset points",
                    fontsize=8,
                    alpha=0.7,
                )

        plt.tight_layout()
        return fig

    def save_model(self, filepath: str):
        """Save embedding model."""
        self.embedder.save_embeddings(filepath)

    def load_model(self, filepath: str):
        """Load embedding model."""
        self.embedder.load_embeddings(filepath)

    def get_embedding_info(self) -> Dict[str, Any]:
        """Get embedding information."""
        embeddings = self.get_all_embeddings()

        if not embeddings:
            return {
                "embedding_type": self.embedding_type.value,
                "num_embeddings": 0,
                "embedding_dimension": 0,
                "config": self.config.to_dict(),
            }

        sample_embedding = next(iter(embeddings.values()))

        return {
            "embedding_type": self.embedding_type.value,
            "num_embeddings": len(embeddings),
            "embedding_dimension": len(sample_embedding),
            "vocabulary_size": len(self.embedder.vocabulary),
            "config": self.config.to_dict(),
            "sample_entities": list(embeddings.keys())[:10],
        }
