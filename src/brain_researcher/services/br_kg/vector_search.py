"""
Vector Search Integration for BR-KG
Implements KG-016: Vector Search Integration

This module provides semantic search capabilities using embeddings
and FAISS for efficient similarity search.
"""

import os
import json
import pickle
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading
import time

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from sklearn.preprocessing import normalize

from brain_researcher.services.br_kg.text_v1 import create_text_v1_representation

# Import NICLIP components
try:
    from brain_researcher.services.br_kg.niclip import (
        EmbeddingConfig,
        NICLIPEmbeddingService
    )
    NICLIP_AVAILABLE = True
except ImportError:
    NICLIP_AVAILABLE = False
    logger.warning("NICLIP not available. Using sentence-transformers only.")

logger = logging.getLogger(__name__)


class VectorSearchMode(Enum):
    """Vector search modes."""
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    DOT_PRODUCT = "dot_product"


@dataclass
class VectorSearchConfig:
    """Configuration for vector search."""
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    index_type: str = "IndexFlatIP"  # Inner product for cosine similarity
    dimension: int = 384  # Model output dimension
    batch_size: int = 32
    cache_dir: str = "data/br-kg/vector_cache"
    enable_gpu: bool = False
    max_sequence_length: int = 512
    normalize_embeddings: bool = True

    # Index parameters
    nprobe: int = 10  # Number of clusters to search (for IVF indexes)
    nlist: int = 100  # Number of clusters (for IVF indexes)

    # NICLIP configuration
    use_niclip: bool = False
    niclip_data_path: str = "/app/data/niclip/data"
    niclip_model: str = "BrainGPT-7B-v0.2"
    niclip_section: str = "abstract"

    # Cache settings
    enable_cache: bool = True
    cache_ttl: int = 3600  # Cache TTL in seconds
    max_cache_size: int = 10000  # Maximum cache entries


@dataclass
class VectorSearchResult:
    """Vector search result item."""
    node_id: str
    node_type: str
    score: float
    metadata: Dict[str, Any]
    text: str
    distance: float
    rank: int = 0


class VectorIndexManager:
    """Manages FAISS vector indexes for different node types."""

    def __init__(self, config: VectorSearchConfig, skip_load: bool = False):
        """Initialize vector index manager.

        Args:
            config: Vector search configuration
            skip_load: If True, skip loading existing indices (e.g., for NICLIP with different dimensions)
        """
        self.config = config
        self.indices: Dict[str, faiss.Index] = {}
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}
        self.embeddings_cache: Dict[str, np.ndarray] = {}
        self.lock = threading.Lock()

        # Create cache directory
        Path(config.cache_dir).mkdir(parents=True, exist_ok=True)

        # Load existing indices unless skipped (e.g., for NICLIP)
        if not skip_load:
            self._load_indices()

    def create_index(self, node_type: str, dimension: int = None) -> faiss.Index:
        """Create a new FAISS index for a node type."""
        dim = dimension or self.config.dimension

        if self.config.index_type == "IndexFlatIP":
            # Inner product (for cosine similarity with normalized vectors)
            index = faiss.IndexFlatIP(dim)
        elif self.config.index_type == "IndexFlatL2":
            # L2 distance (Euclidean)
            index = faiss.IndexFlatL2(dim)
        elif self.config.index_type == "IndexIVFFlat":
            # IVF index for larger datasets
            quantizer = faiss.IndexFlatIP(dim)
            index = faiss.IndexIVFFlat(quantizer, dim, self.config.nlist)
        elif self.config.index_type == "IndexHNSWFlat":
            # HNSW for fast approximate search
            index = faiss.IndexHNSWFlat(dim, 32)
        else:
            raise ValueError(f"Unknown index type: {self.config.index_type}")

        # Enable GPU if available and configured
        if self.config.enable_gpu and faiss.get_num_gpus() > 0:
            index = faiss.index_cpu_to_gpu(faiss.StandardGpuResources(), 0, index)

        return index

    def add_embeddings(self, node_type: str, embeddings: np.ndarray,
                       metadata: List[Dict[str, Any]]):
        """Add embeddings to index for a node type."""
        with self.lock:
            if node_type not in self.indices:
                self.indices[node_type] = self.create_index(node_type, embeddings.shape[1])
                self.metadata[node_type] = []

            # Normalize if configured (for cosine similarity)
            if self.config.normalize_embeddings:
                embeddings = normalize(embeddings, norm='l2', axis=1)

            # Train index if needed (for IVF indexes)
            if hasattr(self.indices[node_type], 'is_trained'):
                if not self.indices[node_type].is_trained:
                    self.indices[node_type].train(embeddings)

            # Add to index
            self.indices[node_type].add(embeddings)
            self.metadata[node_type].extend(metadata)

    def search(self, node_type: str, query_embedding: np.ndarray,
              k: int = 10) -> Tuple[np.ndarray, np.ndarray]:
        """Search for similar vectors in index."""
        if node_type not in self.indices:
            return np.array([]), np.array([])

        with self.lock:
            # Normalize query if configured
            if self.config.normalize_embeddings:
                query_embedding = normalize(query_embedding.reshape(1, -1), norm='l2', axis=1)
            else:
                query_embedding = query_embedding.reshape(1, -1)

            # Search
            distances, indices = self.indices[node_type].search(query_embedding, k)

            return distances[0], indices[0]

    def save_index(self, node_type: str):
        """Save index to disk."""
        if node_type not in self.indices:
            return

        index_path = Path(self.config.cache_dir) / f"{node_type}_index.faiss"
        metadata_path = Path(self.config.cache_dir) / f"{node_type}_metadata.pkl"

        with self.lock:
            # Save FAISS index
            faiss.write_index(self.indices[node_type], str(index_path))

            # Save metadata
            with open(metadata_path, 'wb') as f:
                pickle.dump(self.metadata[node_type], f)

    def load_index(self, node_type: str) -> bool:
        """Load index from disk."""
        index_path = Path(self.config.cache_dir) / f"{node_type}_index.faiss"
        metadata_path = Path(self.config.cache_dir) / f"{node_type}_metadata.pkl"

        if not index_path.exists() or not metadata_path.exists():
            return False

        with self.lock:
            # Load FAISS index
            self.indices[node_type] = faiss.read_index(str(index_path))

            # Load metadata
            with open(metadata_path, 'rb') as f:
                self.metadata[node_type] = pickle.load(f)

        return True

    def _load_indices(self):
        """Load all existing indices from disk."""
        cache_dir = Path(self.config.cache_dir)
        if not cache_dir.exists():
            return

        for index_file in cache_dir.glob("*_index.faiss"):
            node_type = index_file.stem.replace("_index", "")
            self.load_index(node_type)
            logger.info(f"Loaded index for {node_type}")


class NICLIPAdapter:
    """Adapter to make NICLIPEmbeddingService compatible with sentence-transformer API."""

    def __init__(self, niclip_data_path: str, model_name: str = "BrainGPT-7B-v0.2",
                 section: str = "abstract"):
        """
        Initialize NICLIP adapter.

        Args:
            niclip_data_path: Path to NICLIP data directory
            model_name: NICLIP model to use
            section: Section type (abstract or body)
        """
        if not NICLIP_AVAILABLE:
            raise ImportError("NICLIP is not available. Please check installation.")

        self.config = EmbeddingConfig(
            model_name=model_name,
            section=section,
            embedding_dim=4096,  # BrainGPT embeddings are 4096-dim
            normalize=True
        )

        # Create a custom service that points directly to our data
        self.service = NICLIPEmbeddingService(niclip_data_path, self.config)
        # Override the data_root to point directly to our data folder
        self.service.data_root = Path(niclip_data_path)

        # Load vocabulary and create index
        self.vocab, self.embeddings = self.service.load_vocabulary_embeddings("cogatlas_task-names")
        self.vocab_index = self.service.create_faiss_index(self.embeddings, index_type="flat")

        # Create vocab lookup
        self.vocab_to_idx = {task.lower(): idx for idx, task in enumerate(self.vocab)}

        # Set dimension
        self.embedding_dim = self.embeddings.shape[1]

        logger.info(f"Initialized NICLIP adapter with {len(self.vocab)} vocabulary items, "
                   f"embedding dim: {self.embedding_dim}")

    def encode(self, texts: Union[str, List[str]], batch_size: int = 32,
               show_progress_bar: bool = False, convert_to_numpy: bool = True) -> np.ndarray:
        """
        Encode texts using NICLIP embeddings.

        For texts in vocabulary, returns exact embeddings.
        For unknown texts, finds most similar vocabulary item.

        Args:
            texts: Text or list of texts to encode
            batch_size: Not used, kept for API compatibility
            show_progress_bar: Not used, kept for API compatibility
            convert_to_numpy: Not used, always returns numpy (for API compatibility)

        Returns:
            Array of embeddings
        """
        single_input = isinstance(texts, str)
        if single_input:
            texts = [texts]

        embeddings = []

        for text in texts:
            text_lower = text.lower().strip()

            # Check if text is in vocabulary
            if text_lower in self.vocab_to_idx:
                idx = self.vocab_to_idx[text_lower]
                embeddings.append(self.embeddings[idx])
            else:
                # Find most similar vocabulary item using simple string matching
                # Could be enhanced with more sophisticated matching
                best_match_idx = None
                best_score = 0

                # Try partial matching
                for vocab_text, idx in self.vocab_to_idx.items():
                    if text_lower in vocab_text or vocab_text in text_lower:
                        score = len(set(text_lower.split()) & set(vocab_text.split()))
                        if score > best_score:
                            best_score = score
                            best_match_idx = idx

                if best_match_idx is not None:
                    embeddings.append(self.embeddings[best_match_idx])
                else:
                    # Return average embedding as fallback
                    embeddings.append(np.mean(self.embeddings, axis=0))

        array = np.array(embeddings, dtype=np.float32)
        if single_input:
            return array[0]
        return array

    def get_sentence_embedding_dimension(self) -> int:
        """Get embedding dimension (for compatibility)."""
        return self.embedding_dim


class VectorSearchEngine:
    """Enhanced search engine with vector similarity search."""

    def __init__(self, db, config: Optional[VectorSearchConfig] = None):
        """Initialize vector search engine."""
        self.db = db
        self.config = config or VectorSearchConfig()
        self.index_version = os.environ.get("BR_KG_VECTOR_INDEX_VERSION", "kg_text_v1")
        self.template_version = os.environ.get("BR_KG_VECTOR_TEMPLATE_VERSION", "node_text_v1")
        self.index_updated_at: Dict[str, str] = {}

        # Initialize embedding model
        if self.config.use_niclip and NICLIP_AVAILABLE:
            logger.info(f"Loading NICLIP model: {self.config.niclip_model}")
            self.model = NICLIPAdapter(
                niclip_data_path=self.config.niclip_data_path,
                model_name=self.config.niclip_model,
                section=self.config.niclip_section
            )
            # Update dimension for NICLIP
            self.config.dimension = self.model.embedding_dim
        else:
            if self.config.use_niclip and not NICLIP_AVAILABLE:
                logger.warning("NICLIP requested but not available, falling back to sentence-transformers")
            logger.info(f"Loading embedding model: {self.config.model_name}")
            self.model = SentenceTransformer(
                self.config.model_name,
                device='cuda' if self.config.enable_gpu else 'cpu'
            )
            self.model.max_seq_length = self.config.max_sequence_length

        # Initialize index manager (skip loading existing indices for NICLIP due to dimension mismatch)
        self.index_manager = VectorIndexManager(self.config, skip_load=self.config.use_niclip)

        # Cache for embeddings
        self.embedding_cache: Dict[str, np.ndarray] = {}
        self.cache_timestamps: Dict[str, float] = {}

        # For NICLIP, always rebuild indices (different dimensions)
        # For sentence-transformers, load cached indices if available (but validate dimensions)
        if self.config.use_niclip:
            logger.info("NICLIP mode: rebuilding indices with 4096 dimensions")
            self._build_indices()
        else:
            if self.index_manager.indices:
                for idx in self.index_manager.indices.values():
                    if getattr(idx, "d", None) != self.config.dimension:
                        logger.warning(
                            "Cached index dimension mismatch (expected %s). Rebuilding indices.",
                            self.config.dimension,
                        )
                        self.index_manager.indices = {}
                        self.index_manager.metadata = {}
                        self._build_indices()
                        break
            if not self.index_manager.indices:
                self._build_indices()

    def _build_indices(self):
        """Build vector indices from database."""
        logger.info("Building vector indices from database...")

        node_types = [
            "Task",
            "TaskDef",
            "TaskSpec",
            "Concept",
            "Construct",
            "Tool",
            "ToolFamily",
            "Dataset",
        ]
        if os.environ.get("BR_KG_VECTOR_INCLUDE_REGION", "0").lower() in {"1", "true", "yes", "on"}:
            node_types.append("Region")
        if os.environ.get("BR_KG_VECTOR_INCLUDE_PUBLICATION", "0").lower() in {"1", "true", "yes", "on"}:
            node_types.append("Publication")

        for node_type in node_types:
            embeddings_list = []
            metadata_list = []
            texts = []

            # Fetch nodes from database
            nodes = self.db.find_nodes(node_type, None)

            for node_id, properties in nodes:
                # Create text representation for embedding
                text = self._create_text_representation(node_type, properties)
                texts.append(text)

                # Store metadata
                metadata_list.append({
                    "node_id": node_id,
                    "node_type": node_type,
                    "properties": properties,
                    "text": text
                })

            if texts:
                # Generate embeddings in batches
                embeddings = self._generate_embeddings_batch(texts)

                # Add to index
                self.index_manager.add_embeddings(node_type, embeddings, metadata_list)

                # Save index
                self.index_manager.save_index(node_type)
                self.index_updated_at[node_type] = datetime.now(timezone.utc).isoformat()

                logger.info(f"Indexed {len(texts)} {node_type} nodes")

    def _create_text_representation(self, node_type: str,
                                   properties: Dict[str, Any]) -> str:
        """Create text representation of node for embedding."""
        return create_text_v1_representation(node_type, properties)

    def _index_updated_at_for(self, node_type: str) -> Optional[str]:
        if node_type in self.index_updated_at:
            return self.index_updated_at[node_type]
        index_path = Path(self.config.cache_dir) / f"{node_type}_index.faiss"
        if index_path.exists():
            return datetime.fromtimestamp(index_path.stat().st_mtime, tz=timezone.utc).isoformat()
        return None

    def _generate_embeddings_batch(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for a batch of texts."""
        embeddings = []

        # Process in batches
        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i:i + self.config.batch_size]
            batch_embeddings = self.model.encode(
                batch,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            embeddings.append(batch_embeddings)

        return np.vstack(embeddings) if embeddings else np.array([])

    def generate_embedding(self, text: str, use_cache: bool = True) -> np.ndarray:
        """Generate embedding for a single text."""
        # Check cache
        if use_cache and self.config.enable_cache:
            if text in self.embedding_cache:
                # Check if cache is still valid
                if time.time() - self.cache_timestamps.get(text, 0) < self.config.cache_ttl:
                    return self.embedding_cache[text]

        # Generate embedding
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            show_progress_bar=False
        )

        # Update cache
        if self.config.enable_cache:
            # Manage cache size
            if len(self.embedding_cache) >= self.config.max_cache_size:
                # Remove oldest entries
                oldest_keys = sorted(self.cache_timestamps.keys(),
                                   key=lambda k: self.cache_timestamps[k])[:100]
                for key in oldest_keys:
                    del self.embedding_cache[key]
                    del self.cache_timestamps[key]

            self.embedding_cache[text] = embedding
            self.cache_timestamps[text] = time.time()

        return embedding

    def vector_search(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        k: int = 10,
        threshold: float = 0.0
    ) -> List[VectorSearchResult]:
        """
        Perform vector similarity search.

        Args:
            query: Search query text
            node_types: List of node types to search (None = all)
            k: Number of results to return
            threshold: Minimum similarity threshold

        Returns:
            List of VectorSearchResult objects
        """
        # Generate query embedding
        query_embedding = self.generate_embedding(query)

        # Determine which node types to search
        if node_types is None:
            node_types = list(self.index_manager.indices.keys())

        all_results = []

        for node_type in node_types:
            if node_type not in self.index_manager.indices:
                continue

            # Search in index
            distances, indices = self.index_manager.search(
                node_type, query_embedding, k
            )

            # Convert to results
            for i, (dist, idx) in enumerate(zip(distances, indices)):
                if idx == -1:  # FAISS returns -1 for no match
                    continue

                # Check threshold
                similarity = float(dist)  # For cosine similarity with normalized vectors
                if similarity < threshold:
                    continue

                # Get metadata
                metadata = self.index_manager.metadata[node_type][idx]

                result = VectorSearchResult(
                    node_id=metadata["node_id"],
                    node_type=node_type,
                    score=similarity,
                    metadata=metadata["properties"],
                    text=metadata["text"],
                    distance=float(dist),
                    rank=i
                )
                all_results.append(result)

        # Sort by score (descending)
        all_results.sort(key=lambda x: x.score, reverse=True)

        # Re-rank and limit
        for i, result in enumerate(all_results[:k]):
            result.rank = i

        return all_results[:k]

    def hybrid_search(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        k: int = 10,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining vector and text search.

        Args:
            query: Search query
            node_types: Node types to search
            k: Number of results
            vector_weight: Weight for vector search scores
            text_weight: Weight for text search scores
            threshold: Minimum score threshold

        Returns:
            Combined search results
        """
        # Import the text search engine
        from .search import SearchEngine, SearchMode

        # Perform vector search
        vector_results = self.vector_search(query, node_types, k * 2, threshold)

        # Perform text search
        text_engine = SearchEngine(self.db)
        text_results = text_engine.search(
            query, node_types, SearchMode.FUZZY, k * 2
        )

        # Combine results
        combined_scores = {}
        result_data = {}

        # Add vector search results
        for result in vector_results:
            key = f"{result.node_type}:{result.node_id}"
            combined_scores[key] = result.score * vector_weight
            result_data[key] = {
                "node_id": result.node_id,
                "node_type": result.node_type,
                "properties": result.metadata,
                "vector_score": result.score,
                "text_score": 0.0,
                "combined_score": 0.0,
                "text": result.text
            }

        # Add text search results
        for result in text_results:
            key = f"{result.node_type}:{result.node_id}"
            text_score = result.score / 100.0  # Normalize to 0-1

            if key in combined_scores:
                combined_scores[key] += text_score * text_weight
                result_data[key]["text_score"] = text_score
            else:
                combined_scores[key] = text_score * text_weight
                result_data[key] = {
                    "node_id": result.node_id,
                    "node_type": result.node_type,
                    "properties": result.properties,
                    "vector_score": 0.0,
                    "text_score": text_score,
                    "combined_score": 0.0,
                    "text": ""
                }

        # Update combined scores
        for key in combined_scores:
            result_data[key]["combined_score"] = combined_scores[key]

        # Sort by combined score
        sorted_results = sorted(
            result_data.values(),
            key=lambda x: x["combined_score"],
            reverse=True
        )

        # Filter by threshold and limit
        filtered_results = [
            r for r in sorted_results
            if r["combined_score"] >= threshold
        ][:k]

        return filtered_results

    def find_similar_nodes(
        self,
        node_id: str,
        node_type: str,
        k: int = 10,
        include_self: bool = False
    ) -> List[VectorSearchResult]:
        """
        Find nodes similar to a given node.

        Args:
            node_id: ID of the reference node
            node_type: Type of the reference node
            k: Number of similar nodes to return
            include_self: Whether to include the reference node

        Returns:
            List of similar nodes
        """
        # Get node properties
        properties = self.db.get_node(node_type, node_id)
        if not properties:
            return []

        # Create text representation
        text = self._create_text_representation(node_type, properties)

        # Generate embedding
        embedding = self.generate_embedding(text)

        # Search for similar nodes
        results = []
        for search_type in [node_type]:  # Can expand to search across types
            distances, indices = self.index_manager.search(
                search_type, embedding, k + 1
            )

            for dist, idx in zip(distances, indices):
                if idx == -1:
                    continue

                metadata = self.index_manager.metadata[search_type][idx]

                # Skip self unless requested
                if not include_self and metadata["node_id"] == node_id:
                    continue

                result = VectorSearchResult(
                    node_id=metadata["node_id"],
                    node_type=search_type,
                    score=float(dist),
                    metadata=metadata["properties"],
                    text=metadata["text"],
                    distance=float(dist)
                )
                results.append(result)

        # Sort and limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:k]

    def update_node_embedding(self, node_id: str, node_type: str):
        """Update embedding for a specific node."""
        # Get node properties
        properties = self.db.get_node(node_type, node_id)
        if not properties:
            return

        # Create text representation
        text = self._create_text_representation(node_type, properties)

        # Generate embedding
        embedding = self.generate_embedding(text, use_cache=False)

        # Update in index (would need to implement index update logic)
        # For now, we'll rebuild the index for that type
        logger.info(f"Updating embedding for {node_type}:{node_id}")

        # This is a simplified approach - in production, you'd want
        # to update the specific vector in the index
        self._rebuild_index_for_type(node_type)

    def _rebuild_index_for_type(self, node_type: str):
        """Rebuild index for a specific node type."""
        embeddings_list = []
        metadata_list = []
        texts = []

        # Fetch all nodes of this type
        nodes = self.db.find_nodes(node_type, None)

        for node_id, properties in nodes:
            text = self._create_text_representation(node_type, properties)
            texts.append(text)
            metadata_list.append({
                "node_id": node_id,
                "node_type": node_type,
                "properties": properties,
                "text": text
            })

        if texts:
            # Generate embeddings
            embeddings = self._generate_embeddings_batch(texts)

            # Clear old index
            if node_type in self.index_manager.indices:
                del self.index_manager.indices[node_type]
                del self.index_manager.metadata[node_type]

            # Add to new index
            self.index_manager.add_embeddings(node_type, embeddings, metadata_list)

            # Save index
            self.index_manager.save_index(node_type)

            logger.info(f"Rebuilt index for {node_type} with {len(texts)} nodes")

    def get_embedding_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector indices."""
        stats = {
            "model": self.config.model_name,
            "dimension": self.config.dimension,
            "index_version": self.index_version,
            "template_version": self.template_version,
            "indices": {}
        }

        for node_type, index in self.index_manager.indices.items():
            stats["indices"][node_type] = {
                "num_vectors": index.ntotal,
                "index_type": type(index).__name__,
                "is_trained": getattr(index, 'is_trained', True),
                "updated_at": self._index_updated_at_for(node_type),
            }

        stats["cache"] = {
            "enabled": self.config.enable_cache,
            "size": len(self.embedding_cache),
            "max_size": self.config.max_cache_size,
            "ttl": self.config.cache_ttl
        }

        return stats
