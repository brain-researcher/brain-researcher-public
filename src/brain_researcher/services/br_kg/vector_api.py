"""
Vector Search API endpoints for BR-KG
Implements KG-016: Vector Search Integration API layer
"""

import importlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from flask import Blueprint, jsonify, request

from brain_researcher.services.br_kg.db.bootstrap import get_db
from brain_researcher.services.br_kg.rate_limiting import rate_limit

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from brain_researcher.services.br_kg.vector_search import (
        VectorSearchConfig,
        VectorSearchEngine,
    )

# Create Blueprint
vector_bp = Blueprint('vector_api', __name__, url_prefix='/api/vector')

# Global vector engine instances keyed by use_niclip
_vector_engines: Dict[bool, Any] = {}
_vector_engine_lock = threading.Lock()


def _vector_search_classes():
    module = importlib.import_module("brain_researcher.services.br_kg.vector_search")
    return module.VectorSearchConfig, module.VectorSearchEngine


def _cache_dir_for(use_niclip: bool) -> str:
    base_dir = Path(os.environ.get("BR_KG_VECTOR_CACHE_DIR", "data/br-kg/vector_cache"))
    suffix = "niclip" if use_niclip else "sbert"
    return str(base_dir / suffix)


def get_vector_engine(use_niclip: bool = False) -> "VectorSearchEngine":
    """Get or initialize the vector search engine.

    Args:
        use_niclip: Whether to use NICLIP embeddings instead of sentence-transformers
    """
    global _vector_engines

    engine = _vector_engines.get(use_niclip)
    if engine is not None:
        return engine

    with _vector_engine_lock:
        engine = _vector_engines.get(use_niclip)
        if engine is not None:
            return engine

        logger.info(f"Initializing vector search engine (NICLIP: {use_niclip})...")
        db = get_db()
        VectorSearchConfig, VectorSearchEngine = _vector_search_classes()
        config = VectorSearchConfig(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            enable_cache=True,
            cache_dir=_cache_dir_for(use_niclip),
            normalize_embeddings=True,
            use_niclip=use_niclip,
            niclip_data_path=os.environ.get("NICLIP_DATA_PATH", "/app/data/niclip/data")
        )
        engine = VectorSearchEngine(db, config)
        _vector_engines[use_niclip] = engine
        logger.info("Vector search engine initialized")

    return engine


@vector_bp.route('/search', methods=['POST'])
@rate_limit(requests_per_minute=100, requests_per_hour=1500)
def vector_search():
    """
    Perform vector similarity search.

    Request body:
    {
        "query": "search query text",
        "node_types": ["Concept", "Task"],  // optional
        "k": 10,  // number of results (default: 10)
        "threshold": 0.5,  // minimum similarity score (default: 0.0)
        "use_niclip": false  // use NICLIP embeddings (default: false)
    }
    """
    try:
        data = request.get_json()

        if not data or 'query' not in data:
            return jsonify({"error": "Query parameter is required"}), 400

        query = data['query']
        node_types = data.get('node_types')
        k = data.get('k', 10)
        threshold = data.get('threshold', 0.0)
        use_niclip = data.get('use_niclip', False)

        # Validate parameters
        if not isinstance(query, str) or len(query.strip()) == 0:
            return jsonify({"error": "Query must be a non-empty string"}), 400

        if k < 1 or k > 100:
            return jsonify({"error": "k must be between 1 and 100"}), 400

        if threshold < 0 or threshold > 1:
            return jsonify({"error": "threshold must be between 0 and 1"}), 400

        # Get vector engine with specified model
        engine = get_vector_engine(use_niclip=use_niclip)

        # Perform search
        start_time = time.time()
        results = engine.vector_search(
            query=query,
            node_types=node_types,
            k=k,
            threshold=threshold
        )
        search_time = time.time() - start_time

        # Format results
        response_data = {
            "query": query,
            "results": [
                {
                    "node_id": r.node_id,
                    "node_type": r.node_type,
                    "score": r.score,
                    "properties": r.metadata,
                    "text_representation": r.text[:200] + "..." if len(r.text) > 200 else r.text
                }
                for r in results
            ],
            "count": len(results),
            "search_time_ms": round(search_time * 1000, 2)
        }

        stats = engine.get_embedding_stats()
        updated_at = None
        if node_types and isinstance(node_types, list) and len(node_types) == 1:
            updated_at = stats.get("indices", {}).get(node_types[0], {}).get("updated_at")
        else:
            updated_at = {
                nt: info.get("updated_at")
                for nt, info in (stats.get("indices") or {}).items()
            }
        response_data.update(
            {
                "index_version": stats.get("index_version"),
                "model": stats.get("model"),
                "dimension": stats.get("dimension"),
                "template_version": stats.get("template_version"),
                "updated_at": updated_at,
            }
        )

        return jsonify(response_data), 200

    except Exception as e:
        logger.exception("Vector search error")
        msg = str(e) or repr(e)
        return jsonify({"error": msg}), 500


@vector_bp.route('/hybrid', methods=['POST'])
@rate_limit(requests_per_minute=80, requests_per_hour=1200)
def hybrid_search():
    """
    Perform hybrid search combining vector and text search.

    Request body:
    {
        "query": "search query",
        "node_types": ["Concept", "Task"],  // optional
        "k": 10,  // number of results
        "vector_weight": 0.7,  // weight for vector search (0-1)
        "text_weight": 0.3,  // weight for text search (0-1)
        "threshold": 0.0,  // minimum combined score
        "use_niclip": false  // use NICLIP embeddings (default: false)
    }
    """
    try:
        data = request.get_json()

        if not data or 'query' not in data:
            return jsonify({"error": "Query parameter is required"}), 400

        query = data['query']
        node_types = data.get('node_types')
        k = data.get('k', 10)
        vector_weight = data.get('vector_weight', 0.7)
        text_weight = data.get('text_weight', 0.3)
        threshold = data.get('threshold', 0.0)
        use_niclip = data.get('use_niclip', False)

        # Validate weights
        if vector_weight + text_weight > 1.001:  # Allow small floating point error
            return jsonify({"error": "vector_weight + text_weight must not exceed 1.0"}), 400

        # Get vector engine with specified model
        engine = get_vector_engine(use_niclip=use_niclip)

        # Perform hybrid search
        start_time = time.time()
        results = engine.hybrid_search(
            query=query,
            node_types=node_types,
            k=k,
            vector_weight=vector_weight,
            text_weight=text_weight,
            threshold=threshold
        )
        search_time = time.time() - start_time

        # Format results
        response_data = {
            "query": query,
            "results": results,
            "count": len(results),
            "search_time_ms": round(search_time * 1000, 2),
            "search_config": {
                "vector_weight": vector_weight,
                "text_weight": text_weight,
                "threshold": threshold
            }
        }

        stats = engine.get_embedding_stats()
        updated_at = None
        if node_types and isinstance(node_types, list) and len(node_types) == 1:
            updated_at = stats.get("indices", {}).get(node_types[0], {}).get("updated_at")
        else:
            updated_at = {
                nt: info.get("updated_at")
                for nt, info in (stats.get("indices") or {}).items()
            }
        response_data.update(
            {
                "index_version": stats.get("index_version"),
                "model": stats.get("model"),
                "dimension": stats.get("dimension"),
                "template_version": stats.get("template_version"),
                "updated_at": updated_at,
            }
        )

        return jsonify(response_data), 200

    except Exception as e:
        logger.exception("Hybrid search error")
        msg = str(e) or repr(e)
        return jsonify({"error": msg}), 500


@vector_bp.route('/similar/<node_type>/<node_id>', methods=['GET'])
@rate_limit(requests_per_minute=100, requests_per_hour=1500)
def find_similar_nodes(node_type: str, node_id: str):
    """
    Find nodes similar to a given node.

    Query parameters:
    - k: number of similar nodes to return (default: 10)
    - include_self: whether to include the reference node (default: false)
    - use_niclip: whether to use NICLIP embeddings (default: false)
    """
    try:
        k = request.args.get('k', 10, type=int)
        include_self = request.args.get('include_self', 'false').lower() == 'true'
        use_niclip = request.args.get('use_niclip', 'false').lower() == 'true'

        # Validate parameters
        if k < 1 or k > 50:
            return jsonify({"error": "k must be between 1 and 50"}), 400

        # Get vector engine with specified model
        engine = get_vector_engine(use_niclip=use_niclip)

        # Find similar nodes
        start_time = time.time()
        results = engine.find_similar_nodes(
            node_id=node_id,
            node_type=node_type,
            k=k,
            include_self=include_self
        )
        search_time = time.time() - start_time

        if not results:
            return jsonify({"error": f"Node {node_type}:{node_id} not found"}), 404

        # Format results
        response_data = {
            "reference_node": {
                "node_id": node_id,
                "node_type": node_type
            },
            "similar_nodes": [
                {
                    "node_id": r.node_id,
                    "node_type": r.node_type,
                    "similarity_score": r.score,
                    "properties": r.metadata
                }
                for r in results
            ],
            "count": len(results),
            "search_time_ms": round(search_time * 1000, 2)
        }

        stats = engine.get_embedding_stats()
        response_data.update(
            {
                "index_version": stats.get("index_version"),
                "model": stats.get("model"),
                "dimension": stats.get("dimension"),
                "template_version": stats.get("template_version"),
                "updated_at": stats.get("indices", {}).get(node_type, {}).get("updated_at"),
            }
        )

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Similar nodes search error: {e}")
        return jsonify({"error": str(e)}), 500


@vector_bp.route('/stats', methods=['GET'])
def get_vector_stats():
    """Get statistics about the vector search indices."""
    try:
        engine = get_vector_engine()
        stats = engine.get_embedding_stats()

        return jsonify(stats), 200

    except Exception as e:
        logger.error(f"Error getting vector stats: {e}")
        return jsonify({"error": str(e)}), 500


@vector_bp.route('/rebuild', methods=['POST'])
@rate_limit(requests_per_minute=1, requests_per_hour=5)
def rebuild_indices():
    """
    Rebuild vector search indices from database.
    This is a heavy operation and should be rate-limited.
    """
    try:
        # Check for admin auth (simplified for now)
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Authorization required"}), 401

        # Get vector engine and rebuild
        engine = get_vector_engine()

        start_time = time.time()
        engine._build_indices()
        rebuild_time = time.time() - start_time

        stats = engine.get_embedding_stats()

        return jsonify({
            "message": "Vector indices rebuilt successfully",
            "rebuild_time_seconds": round(rebuild_time, 2),
            "stats": stats
        }), 200

    except Exception as e:
        logger.error(f"Error rebuilding indices: {e}")
        return jsonify({"error": str(e)}), 500


@vector_bp.route('/embedding', methods=['POST'])
@rate_limit(requests_per_minute=50, requests_per_hour=500)
def generate_embedding():
    """
    Generate embedding for a given text.
    Useful for debugging and visualization.

    Request body:
    {
        "text": "text to embed",
        "use_niclip": false  // use NICLIP embeddings (default: false)
    }
    """
    try:
        data = request.get_json()

        if not data or 'text' not in data:
            return jsonify({"error": "Text parameter is required"}), 400

        text = data['text']
        use_niclip = data.get('use_niclip', False)

        # Get vector engine with specified model
        engine = get_vector_engine(use_niclip=use_niclip)

        # Generate embedding
        embedding = engine.generate_embedding(text, use_cache=True)

        return jsonify({
            "text": text[:100] + "..." if len(text) > 100 else text,
            "embedding_dimension": len(embedding),
            "embedding_preview": embedding[:10].tolist(),  # First 10 dimensions
            "model": engine.config.model_name
        }), 200

    except Exception as e:
        logger.exception("Error generating embedding")
        msg = str(e) or repr(e)
        return jsonify({"error": msg}), 500


# GraphQL integration
def add_vector_search_to_graphql(schema_builder):
    """Add vector search queries to GraphQL schema."""
    from typing import List, Optional

    import strawberry

    @strawberry.type
    class VectorSearchResultType:
        node_id: str
        node_type: str
        score: float
        properties: str  # JSON string
        text_representation: str

    @strawberry.type
    class SimilarNodeType:
        node_id: str
        node_type: str
        similarity_score: float
        properties: str  # JSON string

    @schema_builder.query
    @strawberry.field
    def vector_search(
        query: str,
        node_types: Optional[List[str]] = None,
        k: int = 10,
        threshold: float = 0.0
    ) -> List[VectorSearchResultType]:
        """Perform vector similarity search."""
        engine = get_vector_engine()
        results = engine.vector_search(query, node_types, k, threshold)

        import json
        return [
            VectorSearchResultType(
                node_id=r.node_id,
                node_type=r.node_type,
                score=r.score,
                properties=json.dumps(r.metadata),
                text_representation=r.text[:200] + "..." if len(r.text) > 200 else r.text
            )
            for r in results
        ]

    @schema_builder.query
    @strawberry.field
    def find_similar(
        node_id: str,
        node_type: str,
        k: int = 10,
        include_self: bool = False
    ) -> List[SimilarNodeType]:
        """Find nodes similar to a given node."""
        engine = get_vector_engine()
        results = engine.find_similar_nodes(node_id, node_type, k, include_self)

        import json
        return [
            SimilarNodeType(
                node_id=r.node_id,
                node_type=r.node_type,
                similarity_score=r.score,
                properties=json.dumps(r.metadata)
            )
            for r in results
        ]
