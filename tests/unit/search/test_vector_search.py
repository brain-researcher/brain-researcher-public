"""Unit tests for vector search integration."""

import pytest
import numpy as np
import hashlib
from unittest.mock import Mock, patch, MagicMock
from brain_researcher.services.neurokg.search.vector_search import (
    VectorStoreType,
    SearchMode,
    SearchResult,
    FAISSVectorStore,
    VectorSearchEngine
)


class TestSearchResult:
    """Test suite for SearchResult."""
    
    def test_search_result_creation(self):
        """Test creating search result."""
        result = SearchResult(
            id="doc1",
            score=0.95,
            content="Test content",
            metadata={'type': 'test'},
            vector=np.array([1, 2, 3]),
            graph_distance=2
        )
        
        assert result.id == "doc1"
        assert result.score == 0.95
        assert result.content == "Test content"
        assert result.metadata['type'] == 'test'
        assert result.vector is not None
        assert result.graph_distance == 2


class TestFAISSVectorStore:
    """Test suite for FAISS vector store."""
    
    @pytest.fixture
    def store(self):
        """Create FAISS store."""
        return FAISSVectorStore(dimension=128, index_type="Flat")
    
    def test_store_creation(self, store):
        """Test store initialization."""
        assert store.dimension == 128
        assert store.index_type == "Flat"
        assert store.faiss_index is not None
        assert store.next_idx == 0
    
    def test_index_vectors(self, store):
        """Test indexing vectors."""
        vectors = np.random.randn(10, 128).astype('float32')
        ids = [f"doc{i}" for i in range(10)]
        metadata = [{'content': f"Content {i}"} for i in range(10)]
        
        store.index(vectors, ids, metadata)
        
        assert store.faiss_index.ntotal == 10
        assert store.next_idx == 10
        assert len(store.id_map) == 10
        assert len(store.metadata_store) == 10
    
    def test_search_vectors(self, store):
        """Test searching vectors."""
        # Index some vectors
        vectors = np.random.randn(100, 128).astype('float32')
        ids = [f"doc{i}" for i in range(100)]
        metadata = [{'content': f"Content {i}", 'type': 'test'} for i in range(100)]
        
        store.index(vectors, ids, metadata)
        
        # Search
        query = np.random.randn(128).astype('float32')
        results = store.search(query, k=5)
        
        assert len(results) <= 5
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.score > 0 for r in results)
    
    def test_search_with_filters(self, store):
        """Test searching with filters."""
        # Index vectors with different types
        vectors = np.random.randn(20, 128).astype('float32')
        ids = [f"doc{i}" for i in range(20)]
        metadata = [
            {'content': f"Content {i}", 'type': 'A' if i < 10 else 'B'} 
            for i in range(20)
        ]
        
        store.index(vectors, ids, metadata)
        
        # Search with filter
        query = np.random.randn(128).astype('float32')
        results = store.search(query, k=10, filters={'type': 'A'})
        
        # All results should be type A
        assert all(r.metadata['type'] == 'A' for r in results)
    
    def test_update_metadata(self, store):
        """Test updating metadata."""
        # Index a vector
        vectors = np.array([[1, 2, 3, 4]], dtype='float32')
        vectors = np.pad(vectors, ((0, 0), (0, 124)), 'constant')  # Pad to 128 dims
        store.index(vectors, ['doc1'], [{'content': 'Original'}])
        
        # Update metadata
        store.update('doc1', metadata={'content': 'Updated', 'new_field': 'value'})
        
        assert store.metadata_store['doc1']['content'] == 'Updated'
        assert store.metadata_store['doc1']['new_field'] == 'value'
    
    def test_different_index_types(self):
        """Test different FAISS index types."""
        # Test IVF index
        ivf_store = FAISSVectorStore(dimension=64, index_type="IVF")
        assert ivf_store.faiss_index is not None
        
        # Test HNSW index
        hnsw_store = FAISSVectorStore(dimension=64, index_type="HNSW")
        assert hnsw_store.faiss_index is not None


class TestVectorSearchEngine:
    """Test suite for vector search engine."""
    
    @pytest.fixture
    def engine(self):
        """Create search engine."""
        with patch('brain_researcher.services.neurokg.search.vector_search.TRANSFORMERS_AVAILABLE', False):
            return VectorSearchEngine(
                store_type=VectorStoreType.FAISS,
                dimension=128
            )
    
    def test_engine_creation(self, engine):
        """Test engine initialization."""
        assert engine.store_type == VectorStoreType.FAISS
        assert engine.dimension == 128
        assert isinstance(engine.store, FAISSVectorStore)
        assert isinstance(engine.embedding_cache, dict)
    
    def test_embed_text_single(self, engine):
        """Test embedding single text."""
        text = "Test document"
        embedding = engine.embed_text(text)
        
        assert embedding.shape == (1, 128)
        cache_key = hashlib.md5(text.encode()).hexdigest()
        assert cache_key in engine.embedding_cache  # Check caching
    
    def test_embed_text_batch(self, engine):
        """Test embedding multiple texts."""
        texts = ["Document 1", "Document 2", "Document 3"]
        embeddings = engine.embed_text(texts)
        
        assert embeddings.shape == (3, 128)
    
    def test_index_documents(self, engine):
        """Test indexing documents."""
        documents = [
            {'id': 'doc1', 'content': 'First document about neurons'},
            {'id': 'doc2', 'content': 'Second document about synapses'},
            {'id': 'doc3', 'content': 'Third document about brain regions'}
        ]
        
        engine.index_documents(documents)
        
        assert engine.store.faiss_index.ntotal == 3
    
    def test_search_vector_mode(self, engine):
        """Test pure vector search."""
        # Index documents
        documents = [
            {'id': f'doc{i}', 'content': f'Document {i} content'}
            for i in range(20)
        ]
        engine.index_documents(documents)
        
        # Search
        results = engine.search(
            query="test query",
            k=5,
            mode=SearchMode.VECTOR
        )
        
        assert len(results) <= 5
        assert all(isinstance(r, SearchResult) for r in results)
    
    def test_search_hybrid_mode(self, engine):
        """Test hybrid search."""
        # Index documents
        documents = [
            {'id': 'doc1', 'content': 'neural networks and deep learning'},
            {'id': 'doc2', 'content': 'convolutional neural networks'},
            {'id': 'doc3', 'content': 'recurrent networks and LSTM'},
            {'id': 'doc4', 'content': 'transformer architectures'}
        ]
        engine.index_documents(documents)
        
        # Hybrid search
        results = engine.search(
            query="neural networks",
            k=3,
            mode=SearchMode.HYBRID
        )
        
        assert len(results) <= 3
        # Hybrid mode should boost keyword overlaps enough that we return at least one matching doc.
        assert any("neural" in r.content for r in results)
    
    def test_search_with_filters(self, engine):
        """Test search with metadata filters."""
        # Index documents with categories
        documents = [
            {'id': 'doc1', 'content': 'Brain imaging', 'category': 'imaging'},
            {'id': 'doc2', 'content': 'fMRI analysis', 'category': 'imaging'},
            {'id': 'doc3', 'content': 'Gene expression', 'category': 'genomics'},
            {'id': 'doc4', 'content': 'Protein synthesis', 'category': 'proteomics'}
        ]
        engine.index_documents(documents)
        
        # Search with filter
        results = engine.search(
            query="analysis",
            k=10,
            filters={'category': 'imaging'}
        )
        
        # Should only return imaging documents
        assert all(r.metadata.get('category') == 'imaging' for r in results)
    
    def test_search_with_rerank(self, engine):
        """Test search with reranking."""
        # Index documents
        documents = [
            {'id': f'doc{i}', 'content': f'Document {i} ' + 'word ' * (i * 10)}
            for i in range(10)
        ]
        engine.index_documents(documents)
        
        # Search with reranking
        results = engine.search(
            query="test",
            k=5,
            rerank=True
        )
        
        assert len(results) <= 5
        # Check that scores were modified by reranking
        assert all(r.score > 0 for r in results)
    
    def test_update_document(self, engine):
        """Test updating document."""
        # Index initial document
        engine.index_documents([{'id': 'doc1', 'content': 'Original content'}])
        
        # Update document
        engine.update_document(
            'doc1',
            content='Updated content',
            metadata={'version': 2}
        )
        
        # Search for updated content
        results = engine.search('Updated', k=1)
        if results:
            assert 'Updated' in results[0].content or results[0].metadata.get('version') == 2
    
    def test_delete_documents(self, engine):
        """Test deleting documents."""
        # Index documents
        documents = [
            {'id': f'doc{i}', 'content': f'Content {i}'}
            for i in range(5)
        ]
        engine.index_documents(documents)
        
        initial_count = engine.store.faiss_index.ntotal
        
        # Delete documents (note: basic FAISS doesn't support delete)
        engine.delete_documents(['doc1', 'doc2'])
        
        # For FAISS, count remains same but metadata could be cleared
        assert engine.store.faiss_index.ntotal == initial_count  # FAISS limitation
    
    def test_get_statistics(self, engine):
        """Test getting engine statistics."""
        # Index some documents
        documents = [
            {'id': f'doc{i}', 'content': f'Content {i}'}
            for i in range(10)
        ]
        engine.index_documents(documents)
        
        # Perform some searches to populate cache
        engine.search('test1', k=5)
        engine.search('test2', k=5)
        
        stats = engine.get_statistics()
        
        assert stats['store_type'] == VectorStoreType.FAISS.value
        assert stats['dimension'] == 128
        assert stats['cache_size'] >= 2
        assert stats['indexed_vectors'] == 10
        assert stats['index_type'] == 'Flat'
    
    def test_embedding_cache(self, engine):
        """Test embedding cache functionality."""
        text = "Cached text"
        
        # First embedding
        emb1 = engine.embed_text(text)
        cache_size1 = len(engine.embedding_cache)
        
        # Second embedding (should use cache)
        emb2 = engine.embed_text(text)
        cache_size2 = len(engine.embedding_cache)
        
        assert cache_size1 == cache_size2  # No new cache entry
        assert np.array_equal(emb1, emb2)  # Same embedding


class TestPineconeIntegration:
    """Test suite for Pinecone integration (mocked)."""
    
    @patch('brain_researcher.services.neurokg.search.vector_search.PINECONE_AVAILABLE', True)
    @patch('brain_researcher.services.neurokg.search.vector_search.pinecone', create=True)
    def test_pinecone_store_creation(self, mock_pinecone):
        """Test Pinecone store initialization."""
        from brain_researcher.services.neurokg.search.vector_search import PineconeVectorStore
        
        mock_pinecone.list_indexes.return_value = []
        mock_pinecone.Index.return_value = MagicMock()
        
        store = PineconeVectorStore(
            api_key="test_key",
            environment="test_env",
            index_name="test_index",
            dimension=768
        )
        
        mock_pinecone.init.assert_called_once_with(
            api_key="test_key",
            environment="test_env"
        )
        mock_pinecone.create_index.assert_called_once()
