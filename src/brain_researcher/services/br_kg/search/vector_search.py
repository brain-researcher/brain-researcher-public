"""Vector search integration for semantic knowledge graph queries.

Provides embedding-based search using multiple vector stores (Pinecone, Weaviate, Qdrant)
with hybrid search combining vector similarity and graph traversal.
"""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

# Vector store imports (optional dependencies)
try:
    import pinecone

    PINECONE_AVAILABLE = True
except ImportError:
    PINECONE_AVAILABLE = False

try:
    import weaviate

    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False

try:
    import qdrant_client

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer

    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

import faiss  # CPU-based fallback

logger = logging.getLogger(__name__)


class VectorStoreType(str, Enum):
    """Supported vector stores."""

    FAISS = "faiss"
    PINECONE = "pinecone"
    WEAVIATE = "weaviate"
    QDRANT = "qdrant"


class SearchMode(str, Enum):
    """Search modes."""

    VECTOR = "vector"  # Pure vector similarity
    HYBRID = "hybrid"  # Vector + keyword
    GRAPH = "graph"  # Vector + graph traversal


@dataclass
class SearchResult:
    """Search result with metadata."""

    id: str
    score: float
    content: str
    metadata: Dict[str, Any]
    vector: Optional[np.ndarray] = None
    graph_distance: Optional[int] = None


class VectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    def index(
        self, vectors: np.ndarray, ids: List[str], metadata: List[Dict[str, Any]]
    ):
        """Index vectors with metadata."""
        pass

    @abstractmethod
    def search(
        self, query_vector: np.ndarray, k: int = 10, filters: Optional[Dict] = None
    ) -> List[SearchResult]:
        """Search for similar vectors."""
        pass

    @abstractmethod
    def delete(self, ids: List[str]):
        """Delete vectors by ID."""
        pass

    @abstractmethod
    def update(
        self,
        id: str,
        vector: Optional[np.ndarray] = None,
        metadata: Optional[Dict] = None,
    ):
        """Update vector or metadata."""
        pass


class FAISSVectorStore(VectorStore):
    """FAISS-based vector store (CPU/GPU)."""

    def __init__(self, dimension: int = 768, index_type: str = "Flat"):
        """Initialize FAISS store.

        Args:
            dimension: Vector dimension
            index_type: Index type (Flat, IVF, HNSW)
        """
        self.dimension = dimension
        self.index_type = index_type

        # Create index based on type
        if index_type == "Flat":
            self._index = faiss.IndexFlatL2(dimension)
        elif index_type == "IVF":
            quantizer = faiss.IndexFlatL2(dimension)
            self._index = faiss.IndexIVFFlat(quantizer, dimension, 100)
            self._index.train(np.random.randn(1000, dimension).astype("float32"))
        elif index_type == "HNSW":
            self._index = faiss.IndexHNSWFlat(dimension, 32)
        else:
            self._index = faiss.IndexFlatL2(dimension)

        self.id_map: Dict[int, str] = {}
        self.metadata_store: Dict[str, Dict[str, Any]] = {}
        self.next_idx = 0

    @property
    def faiss_index(self):
        """Expose the underlying FAISS index (for tests/inspection)."""
        return self._index

    def index(
        self, vectors: np.ndarray, ids: List[str], metadata: List[Dict[str, Any]]
    ):
        """Index vectors."""
        vectors = vectors.astype("float32")

        # Add to FAISS index
        self._index.add(vectors)

        # Store ID mapping and metadata
        for i, (vec_id, meta) in enumerate(zip(ids, metadata)):
            self.id_map[self.next_idx + i] = vec_id
            self.metadata_store[vec_id] = meta

        self.next_idx += len(vectors)
        logger.info(f"Indexed {len(vectors)} vectors in FAISS")

    def search(
        self, query_vector: np.ndarray, k: int = 10, filters: Optional[Dict] = None
    ) -> List[SearchResult]:
        """Search for similar vectors."""
        query_vector = query_vector.astype("float32").reshape(1, -1)

        # Search in FAISS
        distances, indices = self._index.search(query_vector, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # No result
                continue

            vec_id = self.id_map.get(idx)
            if not vec_id:
                continue

            meta = self.metadata_store.get(vec_id, {})

            # Apply filters if provided
            if filters:
                match = all(meta.get(key) == value for key, value in filters.items())
                if not match:
                    continue

            results.append(
                SearchResult(
                    id=vec_id,
                    score=1.0 / (1.0 + dist),  # Convert distance to similarity
                    content=meta.get("content", ""),
                    metadata=meta,
                )
            )

        return results

    def delete(self, ids: List[str]):
        """Delete vectors (not supported in basic FAISS)."""
        logger.warning("Delete not supported in basic FAISS index")

    def update(
        self,
        id: str,
        vector: Optional[np.ndarray] = None,
        metadata: Optional[Dict] = None,
    ):
        """Update metadata only (vector update not supported)."""
        if metadata and id in self.metadata_store:
            self.metadata_store[id].update(metadata)


class PineconeVectorStore(VectorStore):
    """Pinecone vector store."""

    def __init__(
        self, api_key: str, environment: str, index_name: str, dimension: int = 768
    ):
        """Initialize Pinecone store."""
        if not PINECONE_AVAILABLE:
            raise ImportError("Pinecone not installed")

        pinecone.init(api_key=api_key, environment=environment)

        # Create or connect to index
        if index_name not in pinecone.list_indexes():
            pinecone.create_index(index_name, dimension=dimension, metric="cosine")

        self._index = pinecone.Index(index_name)

    def index(
        self, vectors: np.ndarray, ids: List[str], metadata: List[Dict[str, Any]]
    ):
        """Index vectors in Pinecone."""
        # Prepare batch
        batch = [
            (id, vector.tolist(), meta)
            for id, vector, meta in zip(ids, vectors, metadata)
        ]

        # Upsert to Pinecone
        self._index.upsert(batch)
        logger.info(f"Indexed {len(vectors)} vectors in Pinecone")

    def search(
        self, query_vector: np.ndarray, k: int = 10, filters: Optional[Dict] = None
    ) -> List[SearchResult]:
        """Search in Pinecone."""
        response = self._index.query(
            vector=query_vector.tolist(), top_k=k, include_metadata=True, filter=filters
        )

        results = []
        for match in response["matches"]:
            results.append(
                SearchResult(
                    id=match["id"],
                    score=match["score"],
                    content=match.get("metadata", {}).get("content", ""),
                    metadata=match.get("metadata", {}),
                )
            )

        return results

    def delete(self, ids: List[str]):
        """Delete from Pinecone."""
        self._index.delete(ids=ids)

    def update(
        self,
        id: str,
        vector: Optional[np.ndarray] = None,
        metadata: Optional[Dict] = None,
    ):
        """Update in Pinecone."""
        if vector is not None or metadata is not None:
            update_data = {"id": id}
            if vector is not None:
                update_data["values"] = vector.tolist()
            if metadata is not None:
                update_data["metadata"] = metadata
            self._index.upsert([update_data])


class VectorSearchEngine:
    """Main vector search engine with hybrid capabilities."""

    def __init__(
        self,
        store_type: VectorStoreType = VectorStoreType.FAISS,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        **store_kwargs,
    ):
        """Initialize search engine.

        Args:
            store_type: Type of vector store
            embedding_model: Model for embeddings
            **store_kwargs: Store-specific arguments
        """
        self.store_type = store_type
        self.embedding_model_name = embedding_model

        # Initialize embedding model
        if TRANSFORMERS_AVAILABLE:
            self.embedding_model = SentenceTransformer(embedding_model)
            self.dimension = self.embedding_model.get_sentence_embedding_dimension()
        else:
            logger.warning(
                "Sentence transformers not available, using random embeddings"
            )
            self.embedding_model = None
            self.dimension = store_kwargs.get("dimension", 768)

        # Initialize vector store
        if store_type == VectorStoreType.FAISS:
            self.store = FAISSVectorStore(dimension=self.dimension)
        elif store_type == VectorStoreType.PINECONE:
            self.store = PineconeVectorStore(dimension=self.dimension, **store_kwargs)
        else:
            raise ValueError(f"Unsupported store type: {store_type}")

        # Cache for embeddings
        self.embedding_cache: Dict[str, np.ndarray] = {}

    def embed_text(self, text: Union[str, List[str]]) -> np.ndarray:
        """Generate embeddings for text.

        Args:
            text: Text or list of texts

        Returns:
            Embeddings array
        """
        if isinstance(text, str):
            text = [text]

        embeddings = []
        for t in text:
            # Check cache
            cache_key = hashlib.md5(t.encode()).hexdigest()
            if cache_key in self.embedding_cache:
                embeddings.append(self.embedding_cache[cache_key])
            else:
                # Generate embedding
                if self.embedding_model:
                    emb = self.embedding_model.encode(t)
                else:
                    # Deterministic fallback embeddings (avoid flaky behavior in tests/CI).
                    seed = int(cache_key[:8], 16)
                    rng = np.random.default_rng(seed)
                    emb = rng.standard_normal(self.dimension)

                self.embedding_cache[cache_key] = emb
                embeddings.append(emb)

        return np.array(embeddings)

    def index_documents(
        self,
        documents: List[Dict[str, Any]],
        content_field: str = "content",
        id_field: str = "id",
    ):
        """Index documents in vector store.

        Args:
            documents: List of documents
            content_field: Field containing text content
            id_field: Field containing document ID
        """
        # Extract content and generate embeddings
        contents = [doc[content_field] for doc in documents]
        ids = [doc[id_field] for doc in documents]

        embeddings = self.embed_text(contents)

        # Prepare metadata
        metadata = []
        for doc in documents:
            meta = {k: v for k, v in doc.items() if k != content_field}
            meta["content"] = doc[content_field]
            metadata.append(meta)

        # Index in store
        self.store.index(embeddings, ids, metadata)

        logger.info(f"Indexed {len(documents)} documents")

    def search(
        self,
        query: str,
        k: int = 10,
        mode: SearchMode = SearchMode.VECTOR,
        filters: Optional[Dict] = None,
        rerank: bool = False,
    ) -> List[SearchResult]:
        """Search for similar documents.

        Args:
            query: Search query
            k: Number of results
            mode: Search mode
            filters: Metadata filters
            rerank: Whether to rerank results

        Returns:
            Search results
        """
        # Generate query embedding
        query_embedding = self.embed_text(query)[0]

        # Perform vector search. For HYBRID (and reranking), fetch a larger candidate
        # set so non-vector signals (keywords) can influence the top-k.
        candidate_k = k
        if mode == SearchMode.HYBRID:
            candidate_k = max(candidate_k, k * 5)
        if rerank:
            candidate_k = max(candidate_k, k * 2)
        results = self.store.search(query_embedding, k=candidate_k, filters=filters)

        if mode == SearchMode.HYBRID:
            # Combine with keyword search
            results = self._hybrid_search(query, results, k)
        elif mode == SearchMode.GRAPH:
            # Enhance with graph traversal
            results = self._graph_enhanced_search(query, results, k)

        # Rerank if requested
        if rerank:
            results = self._rerank_results(query, results, k)

        return results[:k]

    def _hybrid_search(
        self, query: str, vector_results: List[SearchResult], k: int
    ) -> List[SearchResult]:
        """Combine vector and keyword search.

        Args:
            query: Search query
            vector_results: Vector search results
            k: Number of results

        Returns:
            Combined results
        """
        # Simple keyword matching for demonstration
        query_terms = set(query.lower().split())

        for result in vector_results:
            content_terms = set(result.content.lower().split())
            keyword_score = len(query_terms & content_terms) / len(query_terms)

            # Combine scores (weighted average)
            # Give keyword overlap enough weight that HYBRID mode meaningfully differs
            # from pure vector similarity (and remains deterministic in tests).
            result.score = 0.5 * result.score + 0.5 * keyword_score

        # Sort by combined score
        vector_results.sort(key=lambda x: x.score, reverse=True)

        return vector_results

    def _graph_enhanced_search(
        self, query: str, vector_results: List[SearchResult], k: int
    ) -> List[SearchResult]:
        """Enhance search with graph traversal.

        Args:
            query: Search query
            vector_results: Initial results
            k: Number of results

        Returns:
            Enhanced results
        """
        # This would integrate with Neo4j to find related nodes
        # For now, just return vector results
        logger.info("Graph enhancement would traverse Neo4j relationships")
        return vector_results

    def _rerank_results(
        self, query: str, results: List[SearchResult], k: int
    ) -> List[SearchResult]:
        """Rerank results using cross-encoder.

        Args:
            query: Search query
            results: Initial results
            k: Number of results

        Returns:
            Reranked results
        """
        # Simple length-based reranking for demonstration
        for result in results:
            length_penalty = min(1.0, 100 / max(1, len(result.content)))
            result.score *= 1.0 + length_penalty * 0.1

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """Update document in index.

        Args:
            doc_id: Document ID
            content: New content
            metadata: New metadata
        """
        vector = None
        if content:
            vector = self.embed_text(content)[0]
            if metadata is None:
                metadata = {}
            metadata["content"] = content

        self.store.update(doc_id, vector=vector, metadata=metadata)

    def delete_documents(self, doc_ids: List[str]):
        """Delete documents from index.

        Args:
            doc_ids: Document IDs to delete
        """
        self.store.delete(doc_ids)
        logger.info(f"Deleted {len(doc_ids)} documents")

    def get_statistics(self) -> Dict[str, Any]:
        """Get search engine statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "store_type": self.store_type.value,
            "embedding_model": self.embedding_model_name,
            "dimension": self.dimension,
            "cache_size": len(self.embedding_cache),
        }

        if isinstance(self.store, FAISSVectorStore):
            stats["indexed_vectors"] = self.store.faiss_index.ntotal
            stats["index_type"] = self.store.index_type

        return stats
