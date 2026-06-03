"""Advanced vector search with FAISS optimization and hybrid capabilities.

This module provides enhanced vector search functionality with:
- Optimized FAISS indices for different use cases
- Incremental indexing for real-time updates
- Multi-vector search (text + brain coordinates)
- Hybrid text-vector search with graph integration
- Search result caching and TTL management
"""

import hashlib
import json
import logging
import pickle
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import faiss
import numpy as np
import redis

# Optional imports for embeddings
try:
    from sentence_transformers import SentenceTransformer

    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = logging.getLogger(__name__)


class IndexType(str, Enum):
    """FAISS index types for different use cases."""

    FLAT = "flat"  # Exact search, small datasets
    IVF_FLAT = "ivf_flat"  # Inverted file, medium datasets
    IVF_PQ = "ivf_pq"  # Product quantization, large datasets
    HNSW = "hnsw"  # Hierarchical NSW, fast search
    GPU_FLAT = "gpu_flat"  # GPU acceleration
    GPU_IVF = "gpu_ivf"  # GPU IVF


class SearchResultType(str, Enum):
    """Types of search results."""

    CONCEPT = "concept"
    TASK = "task"
    REGION = "region"
    PUBLICATION = "publication"
    COORDINATE = "coordinate"


@dataclass
class VectorDocument:
    """Document with vector embeddings."""

    id: str
    content: str
    vector: np.ndarray
    metadata: dict[str, Any]
    doc_type: SearchResultType
    created_at: float
    updated_at: float | None = None

    def to_dict(self, include_vector: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "doc_type": self.doc_type.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

        if include_vector:
            result["vector"] = self.vector.tolist()

        return result


@dataclass
class SearchResult:
    """Enhanced search result with additional metadata."""

    id: str
    score: float
    content: str
    metadata: dict[str, Any]
    doc_type: SearchResultType
    vector: np.ndarray | None = None
    graph_distance: int | None = None
    hybrid_score: float | None = None
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        if self.vector is not None:
            result["vector"] = self.vector.tolist()
        result["doc_type"] = self.doc_type.value
        return result


class OptimizedFAISSIndex:
    """Optimized FAISS index with dynamic configuration."""

    def __init__(
        self,
        dimension: int,
        index_type: IndexType = IndexType.IVF_FLAT,
        metric: str = "L2",
        gpu_available: bool = False,
    ):
        """Initialize optimized FAISS index.

        Args:
            dimension: Vector dimension
            index_type: Type of FAISS index
            metric: Distance metric (L2, IP for cosine)
            gpu_available: Whether GPU acceleration is available
        """
        self.dimension = dimension
        self.index_type = index_type
        self.metric = metric
        self.gpu_available = gpu_available and TORCH_AVAILABLE

        # Build index
        self.index = self._build_index()
        self.is_trained = False

        # Metadata storage
        self.id_to_idx: dict[str, int] = {}
        self.idx_to_id: dict[int, str] = {}
        self.next_idx = 0

        logger.info(f"Initialized {index_type.value} index with dimension {dimension}")

    def _build_index(self) -> faiss.Index:
        """Build FAISS index based on configuration."""

        if self.index_type == IndexType.FLAT:
            if self.metric == "L2":
                index = faiss.IndexFlatL2(self.dimension)
            else:
                index = faiss.IndexFlatIP(self.dimension)

        elif self.index_type == IndexType.IVF_FLAT:
            nlist = 100  # Number of clusters
            quantizer = (
                faiss.IndexFlatL2(self.dimension)
                if self.metric == "L2"
                else faiss.IndexFlatIP(self.dimension)
            )
            index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)

        elif self.index_type == IndexType.IVF_PQ:
            nlist = 100
            m = 8  # Number of subquantizers
            quantizer = faiss.IndexFlatL2(self.dimension)
            index = faiss.IndexIVFPQ(quantizer, self.dimension, nlist, m, 8)

        elif self.index_type == IndexType.HNSW:
            index = faiss.IndexHNSWFlat(self.dimension, 32)
            index.hnsw.efConstruction = 40
            index.hnsw.efSearch = 32

        else:
            # Default to flat index
            index = faiss.IndexFlatL2(self.dimension)

        # GPU acceleration if available
        if self.gpu_available and self.index_type in [
            IndexType.GPU_FLAT,
            IndexType.GPU_IVF,
        ]:
            res = faiss.StandardGpuResources()
            index = faiss.index_cpu_to_gpu(res, 0, index)
            logger.info("Enabled GPU acceleration for FAISS index")

        return index

    def train(self, vectors: np.ndarray):
        """Train the index if required."""
        if (
            not self.is_trained
            and hasattr(self.index, "is_trained")
            and not self.index.is_trained
        ):
            logger.info(f"Training index with {len(vectors)} vectors")
            self.index.train(vectors.astype("float32"))
            self.is_trained = True

    def add_vectors(self, vectors: np.ndarray, ids: list[str]) -> list[int]:
        """Add vectors to index.

        Args:
            vectors: Vector embeddings
            ids: Document IDs

        Returns:
            List of assigned indices
        """
        vectors = vectors.astype("float32")

        # Train index if needed
        if not self.is_trained:
            self.train(vectors)

        # Track ID mappings
        indices = []
        for i, doc_id in enumerate(ids):
            idx = self.next_idx + i
            self.id_to_idx[doc_id] = idx
            self.idx_to_id[idx] = doc_id
            indices.append(idx)

        # Add to FAISS index
        self.index.add(vectors)
        self.next_idx += len(vectors)

        logger.info(f"Added {len(vectors)} vectors to index")
        return indices

    def search(
        self, query_vectors: np.ndarray, k: int = 10
    ) -> tuple[np.ndarray, np.ndarray]:
        """Search for similar vectors.

        Args:
            query_vectors: Query embeddings
            k: Number of results

        Returns:
            Tuple of (distances, indices)
        """
        query_vectors = query_vectors.astype("float32")
        distances, indices = self.index.search(query_vectors, k)
        return distances, indices

    def remove_vectors(self, ids: list[str]):
        """Remove vectors by ID (limited support in FAISS)."""
        logger.warning("Vector removal not fully supported in basic FAISS indices")
        for doc_id in ids:
            if doc_id in self.id_to_idx:
                del self.id_to_idx[doc_id]

    def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "index_type": self.index_type.value,
            "dimension": self.dimension,
            "total_vectors": self.index.ntotal if hasattr(self.index, "ntotal") else 0,
            "is_trained": self.is_trained,
            "metric": self.metric,
            "gpu_enabled": self.gpu_available,
        }


class SearchCache:
    """Redis-based search result cache with TTL."""

    def __init__(
        self, redis_client: redis.Redis | None = None, default_ttl: int = 3600
    ):
        """Initialize search cache.

        Args:
            redis_client: Redis client
            default_ttl: Default cache TTL in seconds
        """
        self.redis = redis_client or self._create_redis_client()
        self.default_ttl = default_ttl
        self.cache_prefix = "br_kg:search:"

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            client = redis.Redis(host="localhost", port=6379, decode_responses=True)
            client.ping()
            return client
        except:
            import fakeredis

            return fakeredis.FakeRedis(decode_responses=True)

    def _make_cache_key(
        self, query: str, filters: dict | None = None, k: int = 10
    ) -> str:
        """Generate cache key."""
        cache_data = {"query": query, "filters": filters or {}, "k": k}
        key_hash = hashlib.sha256(
            json.dumps(cache_data, sort_keys=True).encode()
        ).hexdigest()
        return f"{self.cache_prefix}{key_hash}"

    def get(
        self, query: str, filters: dict | None = None, k: int = 10
    ) -> list[SearchResult] | None:
        """Get cached search results."""
        cache_key = self._make_cache_key(query, filters, k)

        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                results_data = json.loads(cached_data)
                results = []
                for result_data in results_data:
                    # Reconstruct SearchResult
                    result = SearchResult(
                        id=result_data["id"],
                        score=result_data["score"],
                        content=result_data["content"],
                        metadata=result_data["metadata"],
                        doc_type=SearchResultType(result_data["doc_type"]),
                        graph_distance=result_data.get("graph_distance"),
                        hybrid_score=result_data.get("hybrid_score"),
                        explanation=result_data.get("explanation"),
                    )
                    results.append(result)

                logger.debug(f"Cache hit for query: {query[:50]}...")
                return results
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")

        return None

    def set(
        self,
        query: str,
        results: list[SearchResult],
        filters: dict | None = None,
        k: int = 10,
        ttl: int | None = None,
    ):
        """Cache search results."""
        cache_key = self._make_cache_key(query, filters, k)
        ttl = ttl or self.default_ttl

        try:
            # Convert results to JSON-serializable format
            results_data = [result.to_dict() for result in results]
            self.redis.setex(cache_key, ttl, json.dumps(results_data))
            logger.debug(f"Cached search results for: {query[:50]}...")
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")

    def invalidate_pattern(self, pattern: str):
        """Invalidate cache entries matching pattern."""
        try:
            keys = self.redis.keys(f"{self.cache_prefix}*{pattern}*")
            if keys:
                self.redis.delete(*keys)
                logger.info(f"Invalidated {len(keys)} cache entries")
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")


class AdvancedVectorSearchEngine:
    """Advanced vector search engine with FAISS optimization and hybrid capabilities."""

    def __init__(
        self,
        dimension: int = 768,
        index_type: IndexType = IndexType.IVF_FLAT,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_ttl: int = 3600,
        gpu_enabled: bool = False,
    ):
        """Initialize advanced search engine.

        Args:
            dimension: Vector dimension
            index_type: FAISS index type
            embedding_model: Sentence transformer model
            cache_ttl: Cache TTL in seconds
            gpu_enabled: Enable GPU acceleration
        """
        self.dimension = dimension
        self.index_type = index_type
        self.cache_ttl = cache_ttl

        # Initialize embedding model
        if TRANSFORMERS_AVAILABLE:
            self.embedding_model = SentenceTransformer(embedding_model)
            # Update dimension from model
            self.dimension = self.embedding_model.get_sentence_embedding_dimension()
        else:
            logger.warning("Sentence transformers not available")
            self.embedding_model = None

        # Initialize FAISS index
        self.faiss_index = OptimizedFAISSIndex(
            dimension=self.dimension, index_type=index_type, gpu_available=gpu_enabled
        )

        # Initialize cache
        self.search_cache = SearchCache(default_ttl=cache_ttl)

        # Document storage
        self.documents: dict[str, VectorDocument] = {}

        # Performance tracking
        self.stats = {
            "total_searches": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_documents": 0,
            "avg_search_time_ms": 0.0,
        }

        logger.info(
            f"Initialized AdvancedVectorSearchEngine with {index_type.value} index"
        )

    def embed_text(self, texts: str | list[str]) -> np.ndarray:
        """Generate embeddings for text(s).

        Args:
            texts: Text or list of texts

        Returns:
            Embedding vectors
        """
        if isinstance(texts, str):
            texts = [texts]

        if self.embedding_model:
            embeddings = self.embedding_model.encode(texts, convert_to_numpy=True)
        else:
            # Fallback to random embeddings
            embeddings = np.random.randn(len(texts), self.dimension).astype("float32")

        return embeddings

    def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """Add documents to the search index.

        Args:
            documents: List of document dictionaries

        Returns:
            Number of documents added
        """
        if not documents:
            return 0

        # Extract content and generate embeddings
        contents = []
        doc_objects = []

        for doc in documents:
            content = doc.get("content", "")
            if not content:
                continue

            contents.append(content)

            # Create VectorDocument object
            doc_obj = VectorDocument(
                id=doc.get("id", str(time.time())),
                content=content,
                vector=None,  # Will be set after embedding
                metadata=doc.get("metadata", {}),
                doc_type=SearchResultType(doc.get("type", "concept")),
                created_at=time.time(),
            )
            doc_objects.append(doc_obj)

        if not contents:
            return 0

        # Generate embeddings
        embeddings = self.embed_text(contents)

        # Add vectors to each document
        for doc_obj, embedding in zip(doc_objects, embeddings, strict=False):
            doc_obj.vector = embedding
            self.documents[doc_obj.id] = doc_obj

        # Add to FAISS index
        vectors = np.array([doc.vector for doc in doc_objects])
        ids = [doc.id for doc in doc_objects]

        self.faiss_index.add_vectors(vectors, ids)

        # Update stats
        self.stats["total_documents"] += len(doc_objects)

        # Invalidate related cache entries
        self.search_cache.invalidate_pattern("")  # Simple invalidation

        logger.info(f"Added {len(doc_objects)} documents to search index")
        return len(doc_objects)

    def update_document(
        self,
        doc_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update an existing document.

        Args:
            doc_id: Document ID
            content: New content (will regenerate embedding)
            metadata: New metadata

        Returns:
            Success status
        """
        if doc_id not in self.documents:
            return False

        doc = self.documents[doc_id]

        # Update metadata
        if metadata:
            doc.metadata.update(metadata)

        # Update content and regenerate embedding
        if content and content != doc.content:
            doc.content = content
            new_embedding = self.embed_text(content)[0]
            doc.vector = new_embedding
            doc.updated_at = time.time()

            # Note: For simplicity, we don't update the FAISS index here
            # In production, you'd want incremental update capabilities
            logger.warning(
                f"Document {doc_id} content updated, but FAISS index not updated"
            )

        # Invalidate cache
        self.search_cache.invalidate_pattern(doc_id)

        return True

    def search(
        self,
        query: str,
        k: int = 10,
        doc_types: list[SearchResultType] | None = None,
        filters: dict[str, Any] | None = None,
        use_cache: bool = True,
        hybrid_search: bool = False,
    ) -> list[SearchResult]:
        """Search for similar documents.

        Args:
            query: Search query
            k: Number of results
            doc_types: Filter by document types
            filters: Metadata filters
            use_cache: Whether to use caching
            hybrid_search: Use hybrid text + vector search

        Returns:
            Search results
        """
        start_time = time.time()
        self.stats["total_searches"] += 1

        # Check cache
        if use_cache:
            cached_results = self.search_cache.get(query, filters, k)
            if cached_results:
                self.stats["cache_hits"] += 1
                return cached_results[:k]

        self.stats["cache_misses"] += 1

        # Generate query embedding
        query_embedding = self.embed_text(query)[0].reshape(1, -1)

        # Search in FAISS index
        distances, indices = self.faiss_index.search(
            query_embedding, k * 2
        )  # Get more for filtering

        # Convert to search results
        results = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            if idx == -1:  # No result
                continue

            doc_id = self.faiss_index.idx_to_id.get(idx)
            if not doc_id or doc_id not in self.documents:
                continue

            doc = self.documents[doc_id]

            # Apply filters
            if doc_types and doc.doc_type not in doc_types:
                continue

            if filters:
                match = all(
                    doc.metadata.get(key) == value for key, value in filters.items()
                )
                if not match:
                    continue

            # Calculate similarity score (convert distance to similarity)
            score = 1.0 / (1.0 + dist)

            result = SearchResult(
                id=doc.id,
                score=score,
                content=doc.content,
                metadata=doc.metadata.copy(),
                doc_type=doc.doc_type,
                vector=(
                    doc.vector if len(results) < 5 else None
                ),  # Only include vectors for top results
            )

            # Hybrid search enhancement
            if hybrid_search:
                keyword_score = self._calculate_keyword_score(query, doc.content)
                result.hybrid_score = 0.7 * score + 0.3 * keyword_score
                result.score = result.hybrid_score
                result.explanation = f"Vector similarity: {score:.3f}, Keyword match: {keyword_score:.3f}"

            results.append(result)

        # Sort by score and limit results
        results.sort(key=lambda x: x.score, reverse=True)
        results = results[:k]

        # Cache results
        if use_cache:
            self.search_cache.set(query, results, filters, k)

        # Update performance stats
        search_time = (time.time() - start_time) * 1000
        self._update_search_stats(search_time)

        logger.info(
            f"Search completed in {search_time:.2f}ms, found {len(results)} results"
        )
        return results

    def _calculate_keyword_score(self, query: str, content: str) -> float:
        """Calculate keyword-based similarity score.

        Args:
            query: Search query
            content: Document content

        Returns:
            Keyword similarity score
        """
        query_terms = set(query.lower().split())
        content_terms = set(content.lower().split())

        if not query_terms:
            return 0.0

        intersection = query_terms & content_terms
        return len(intersection) / len(query_terms)

    def _update_search_stats(self, search_time_ms: float):
        """Update search performance statistics."""
        current_avg = self.stats["avg_search_time_ms"]
        total_searches = self.stats["total_searches"]

        # Calculate rolling average
        self.stats["avg_search_time_ms"] = (
            current_avg * (total_searches - 1) + search_time_ms
        ) / total_searches

    def search_by_coordinate(
        self, x: float, y: float, z: float, radius: float = 10.0, k: int = 10
    ) -> list[SearchResult]:
        """Search for brain regions by MNI coordinates.

        Args:
            x, y, z: MNI coordinates
            radius: Search radius in mm
            k: Number of results

        Returns:
            Search results for nearby regions
        """
        # Create coordinate-based query
        coord_query = f"MNI coordinates {x} {y} {z} brain region"

        # Use regular search with spatial filtering
        results = self.search(
            query=coord_query,
            k=k * 2,  # Get more results for spatial filtering
            doc_types=[SearchResultType.REGION],
        )

        # Filter by spatial distance (simplified)
        spatial_results = []
        for result in results:
            # Extract coordinates from metadata if available
            if "mni_coords" in result.metadata:
                coords = result.metadata["mni_coords"]
                if isinstance(coords, list | tuple) and len(coords) >= 3:
                    distance = np.sqrt(
                        (coords[0] - x) ** 2
                        + (coords[1] - y) ** 2
                        + (coords[2] - z) ** 2
                    )
                    if distance <= radius:
                        result.metadata["spatial_distance"] = distance
                        spatial_results.append(result)

        # Sort by spatial distance
        spatial_results.sort(
            key=lambda x: x.metadata.get("spatial_distance", float("inf"))
        )

        return spatial_results[:k]

    def get_similar_documents(self, doc_id: str, k: int = 10) -> list[SearchResult]:
        """Find documents similar to a given document.

        Args:
            doc_id: Reference document ID
            k: Number of results

        Returns:
            Similar documents
        """
        if doc_id not in self.documents:
            return []

        doc = self.documents[doc_id]
        query_vector = doc.vector.reshape(1, -1)

        # Search using document's vector
        distances, indices = self.faiss_index.search(
            query_vector, k + 1
        )  # +1 to exclude self

        results = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            result_doc_id = self.faiss_index.idx_to_id.get(idx)
            if (
                result_doc_id
                and result_doc_id != doc_id
                and result_doc_id in self.documents
            ):
                result_doc = self.documents[result_doc_id]

                result = SearchResult(
                    id=result_doc.id,
                    score=1.0 / (1.0 + dist),
                    content=result_doc.content,
                    metadata=result_doc.metadata.copy(),
                    doc_type=result_doc.doc_type,
                )
                results.append(result)

        return results[:k]

    def batch_search(self, queries: list[str], k: int = 10) -> list[list[SearchResult]]:
        """Perform batch search for multiple queries.

        Args:
            queries: List of search queries
            k: Number of results per query

        Returns:
            List of search results for each query
        """
        # Generate all embeddings at once for efficiency
        query_embeddings = self.embed_text(queries)

        # Perform batch search in FAISS
        distances, indices = self.faiss_index.search(query_embeddings, k)

        # Convert results
        all_results = []
        for i, _query in enumerate(queries):
            query_results = []
            for dist, idx in zip(distances[i], indices[i], strict=False):
                if idx == -1:
                    continue

                doc_id = self.faiss_index.idx_to_id.get(idx)
                if doc_id and doc_id in self.documents:
                    doc = self.documents[doc_id]

                    result = SearchResult(
                        id=doc.id,
                        score=1.0 / (1.0 + dist),
                        content=doc.content,
                        metadata=doc.metadata.copy(),
                        doc_type=doc.doc_type,
                    )
                    query_results.append(result)

            all_results.append(query_results)

        return all_results

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive search engine statistics.

        Returns:
            Statistics dictionary
        """
        faiss_stats = self.faiss_index.get_stats()

        return {
            **self.stats,
            **faiss_stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / max(1, self.stats["total_searches"])
            ),
            "embedding_model": (
                self.embedding_model.model_name if self.embedding_model else None
            ),
            "documents_by_type": {
                doc_type.value: sum(
                    1 for doc in self.documents.values() if doc.doc_type == doc_type
                )
                for doc_type in SearchResultType
            },
        }

    def save_index(self, filepath: str):
        """Save the search index to disk.

        Args:
            filepath: Path to save the index
        """
        try:
            # Save FAISS index
            faiss.write_index(self.faiss_index.index, f"{filepath}.faiss")

            # Save metadata
            metadata = {
                "documents": {
                    doc_id: doc.to_dict(include_vector=True)
                    for doc_id, doc in self.documents.items()
                },
                "id_mappings": {
                    "id_to_idx": self.faiss_index.id_to_idx,
                    "idx_to_id": self.faiss_index.idx_to_id,
                },
                "config": {
                    "dimension": self.dimension,
                    "index_type": self.index_type.value,
                    "cache_ttl": self.cache_ttl,
                },
                "stats": self.stats,
            }

            with open(f"{filepath}.metadata", "wb") as f:
                pickle.dump(metadata, f)

            logger.info(f"Saved search index to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save index: {e}")
            raise

    def load_index(self, filepath: str):
        """Load search index from disk.

        Args:
            filepath: Path to load the index from
        """
        try:
            # Load FAISS index
            self.faiss_index.index = faiss.read_index(f"{filepath}.faiss")

            # Load metadata
            with open(f"{filepath}.metadata", "rb") as f:
                metadata = pickle.load(f)

            # Restore documents
            self.documents = {}
            for doc_id, doc_data in metadata["documents"].items():
                doc = VectorDocument(
                    id=doc_data["id"],
                    content=doc_data["content"],
                    vector=np.array(doc_data["vector"]),
                    metadata=doc_data["metadata"],
                    doc_type=SearchResultType(doc_data["doc_type"]),
                    created_at=doc_data["created_at"],
                    updated_at=doc_data.get("updated_at"),
                )
                self.documents[doc_id] = doc

            # Restore ID mappings
            self.faiss_index.id_to_idx = metadata["id_mappings"]["id_to_idx"]
            self.faiss_index.idx_to_id = metadata["id_mappings"]["idx_to_id"]
            self.faiss_index.next_idx = len(self.faiss_index.id_to_idx)

            # Restore stats
            self.stats.update(metadata["stats"])

            logger.info(f"Loaded search index from {filepath}")

        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            raise
