"""Hybrid search engine combining text, vector, and graph traversal.

This module provides a comprehensive search system that integrates:
- Full-text search with BM25 scoring
- Vector similarity search using embeddings
- Graph traversal for relationship-based discovery
- Multi-modal fusion scoring
- Intelligent query understanding and routing
"""

import json
import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np

from .advanced_vector_search import (
    AdvancedVectorSearchEngine,
    SearchResult,
    SearchResultType,
)

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    """Search modes for different query types."""

    AUTO = "auto"  # Automatically choose best mode
    TEXT = "text"  # Pure text search
    VECTOR = "vector"  # Pure vector search
    GRAPH = "graph"  # Graph traversal
    HYBRID = "hybrid"  # Text + Vector
    MULTIMODAL = "multimodal"  # Text + Vector + Graph


class QueryType(str, Enum):
    """Types of queries detected from user input."""

    CONCEPT = "concept"
    TASK = "task"
    REGION = "region"
    COORDINATE = "coordinate"
    PUBLICATION = "publication"
    RELATIONSHIP = "relationship"
    COMPARISON = "comparison"
    DEFINITION = "definition"


@dataclass
class QueryAnalysis:
    """Analysis of user query to determine search strategy."""

    query_type: QueryType
    search_mode: SearchMode
    entities: List[str]
    coordinates: Optional[Tuple[float, float, float]]
    relationships: List[str]
    filters: Dict[str, Any]
    confidence: float
    reasoning: str


@dataclass
class ScoredResult:
    """Result with multiple scoring components."""

    result: SearchResult
    text_score: float = 0.0
    vector_score: float = 0.0
    graph_score: float = 0.0
    combined_score: float = 0.0
    score_explanation: str = ""


class QueryAnalyzer:
    """Analyzes queries to determine optimal search strategy."""

    def __init__(self):
        """Initialize query analyzer with patterns and rules."""

        # Coordinate pattern
        self.coord_pattern = re.compile(
            r"(?:mni|coordinates?|position)\s*[:\-]?\s*"
            r"(?:x?\s*[=:]?\s*)?(-?\d+(?:\.\d+)?)\s*[,\s]+"
            r"(?:y?\s*[=:]?\s*)?(-?\d+(?:\.\d+)?)\s*[,\s]+"
            r"(?:z?\s*[=:]?\s*)?(-?\d+(?:\.\d+)?)",
            re.IGNORECASE,
        )

        # Query type indicators
        self.query_indicators = {
            QueryType.CONCEPT: [
                "concept",
                "cognitive",
                "mental",
                "process",
                "function",
                "attention",
                "memory",
                "language",
                "executive",
                "emotion",
            ],
            QueryType.TASK: [
                "task",
                "experiment",
                "paradigm",
                "protocol",
                "study",
                "test",
                "assessment",
                "trial",
                "condition",
            ],
            QueryType.REGION: [
                "region",
                "area",
                "cortex",
                "lobe",
                "gyrus",
                "sulcus",
                "brain",
                "neural",
                "anatomical",
                "structure",
            ],
            QueryType.PUBLICATION: [
                "paper",
                "study",
                "research",
                "article",
                "publication",
                "author",
                "journal",
                "doi",
                "pmid",
            ],
            QueryType.RELATIONSHIP: [
                "relationship",
                "connection",
                "link",
                "association",
                "correlation",
                "interaction",
                "network",
                "pathway",
            ],
            QueryType.COMPARISON: [
                "compare",
                "difference",
                "similarity",
                "versus",
                "vs",
                "contrast",
                "between",
                "among",
                "relative",
            ],
            QueryType.DEFINITION: [
                "what is",
                "define",
                "definition",
                "meaning",
                "explain",
                "describe",
                "overview",
                "about",
            ],
        }

        # Search mode preferences by query type
        self.mode_preferences = {
            QueryType.CONCEPT: SearchMode.HYBRID,
            QueryType.TASK: SearchMode.VECTOR,
            QueryType.REGION: SearchMode.MULTIMODAL,
            QueryType.COORDINATE: SearchMode.GRAPH,
            QueryType.PUBLICATION: SearchMode.TEXT,
            QueryType.RELATIONSHIP: SearchMode.GRAPH,
            QueryType.COMPARISON: SearchMode.MULTIMODAL,
            QueryType.DEFINITION: SearchMode.VECTOR,
        }

    def analyze_query(self, query: str) -> QueryAnalysis:
        """Analyze query to determine search strategy.

        Args:
            query: User query string

        Returns:
            Query analysis with recommendations
        """
        query_lower = query.lower()

        # Extract coordinates if present
        coordinates = self._extract_coordinates(query)

        # Determine query type
        query_type = self._classify_query_type(query_lower)

        # Extract entities (simplified)
        entities = self._extract_entities(query)

        # Extract relationships
        relationships = self._extract_relationships(query_lower)

        # Determine search mode
        if coordinates:
            search_mode = SearchMode.GRAPH
            confidence = 0.9
        else:
            search_mode = self.mode_preferences.get(query_type, SearchMode.AUTO)
            confidence = self._calculate_confidence(query_lower, query_type)

        # Generate filters
        filters = self._generate_filters(query_lower, query_type)

        # Generate reasoning
        reasoning = self._generate_reasoning(
            query_type, search_mode, coordinates, entities
        )

        return QueryAnalysis(
            query_type=query_type,
            search_mode=search_mode,
            entities=entities,
            coordinates=coordinates,
            relationships=relationships,
            filters=filters,
            confidence=confidence,
            reasoning=reasoning,
        )

    def _extract_coordinates(self, query: str) -> Optional[Tuple[float, float, float]]:
        """Extract MNI coordinates from query."""
        match = self.coord_pattern.search(query)
        if match:
            try:
                x, y, z = map(float, match.groups())
                return (x, y, z)
            except ValueError:
                pass
        return None

    def _classify_query_type(self, query_lower: str) -> QueryType:
        """Classify query type based on content."""
        scores = defaultdict(float)

        for query_type, indicators in self.query_indicators.items():
            for indicator in indicators:
                if indicator in query_lower:
                    scores[query_type] += 1.0
                    # Boost score if indicator is at start of query
                    if query_lower.startswith(indicator):
                        scores[query_type] += 0.5

        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]

        # Default classification
        return QueryType.CONCEPT

    def _extract_entities(self, query: str) -> List[str]:
        """Extract potential entities from query."""
        # Simple entity extraction (would use NER in production)
        entities = []

        # Look for capitalized words (potential proper nouns)
        words = query.split()
        for word in words:
            if word[0].isupper() and len(word) > 2:
                entities.append(word)

        # Look for quoted strings
        quoted = re.findall(r'"([^"]*)"', query)
        entities.extend(quoted)

        return entities

    def _extract_relationships(self, query_lower: str) -> List[str]:
        """Extract relationship types from query."""
        relationships = []

        relation_patterns = {
            "activates": ["activates", "activation", "active"],
            "inhibits": ["inhibits", "inhibition", "suppresses"],
            "correlates": ["correlates", "correlation", "associated"],
            "measures": ["measures", "assesses", "evaluates"],
            "located_in": ["located", "in", "within", "part of"],
        }

        for relation, patterns in relation_patterns.items():
            if any(pattern in query_lower for pattern in patterns):
                relationships.append(relation)

        return relationships

    def _calculate_confidence(self, query_lower: str, query_type: QueryType) -> float:
        """Calculate confidence in query classification."""
        # Simple confidence based on indicator matches
        indicators = self.query_indicators.get(query_type, [])
        matches = sum(1 for indicator in indicators if indicator in query_lower)

        if matches == 0:
            return 0.3  # Low confidence
        elif matches == 1:
            return 0.6  # Medium confidence
        else:
            return 0.9  # High confidence

    def _generate_filters(
        self, query_lower: str, query_type: QueryType
    ) -> Dict[str, Any]:
        """Generate search filters based on query."""
        filters = {}

        # Type-based filters
        if query_type != QueryType.RELATIONSHIP:
            filters["doc_types"] = [SearchResultType(query_type.value)]

        # Year filters
        year_match = re.search(r"\b(19|20)\d{2}\b", query_lower)
        if year_match:
            filters["year"] = int(year_match.group())

        return filters

    def _generate_reasoning(
        self,
        query_type: QueryType,
        search_mode: SearchMode,
        coordinates: Optional[Tuple],
        entities: List[str],
    ) -> str:
        """Generate human-readable reasoning for search strategy."""
        reasoning_parts = []

        reasoning_parts.append(f"Detected query type: {query_type.value}")

        if coordinates:
            reasoning_parts.append(
                f"Found coordinates {coordinates}, using spatial search"
            )

        if entities:
            reasoning_parts.append(f"Identified entities: {', '.join(entities[:3])}")

        reasoning_parts.append(f"Recommended search mode: {search_mode.value}")

        return ". ".join(reasoning_parts)


class BM25Scorer:
    """BM25 scoring for text search."""

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        """Initialize BM25 scorer.

        Args:
            k1: Term frequency saturation parameter
            b: Length normalization parameter
        """
        self.k1 = k1
        self.b = b
        self.doc_freqs = defaultdict(int)
        self.doc_lengths = {}
        self.avg_doc_length = 0.0
        self.corpus_size = 0

    def index_documents(self, documents: Dict[str, str]):
        """Index documents for BM25 scoring.

        Args:
            documents: Dict of doc_id -> content
        """
        self.corpus_size = len(documents)
        total_length = 0

        # Calculate document frequencies
        for doc_id, content in documents.items():
            tokens = self._tokenize(content)
            self.doc_lengths[doc_id] = len(tokens)
            total_length += len(tokens)

            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] += 1

        self.avg_doc_length = (
            total_length / self.corpus_size if self.corpus_size > 0 else 0
        )

    def score(self, query: str, doc_id: str, doc_content: str) -> float:
        """Calculate BM25 score for query-document pair.

        Args:
            query: Search query
            doc_id: Document ID
            doc_content: Document content

        Returns:
            BM25 score
        """
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(doc_content)
        doc_length = len(doc_tokens)

        # Count term frequencies in document
        term_freqs = defaultdict(int)
        for token in doc_tokens:
            term_freqs[token] += 1

        score = 0.0
        for term in query_tokens:
            if term not in term_freqs:
                continue

            # Term frequency component
            tf = term_freqs[term]
            tf_component = (tf * (self.k1 + 1)) / (
                tf
                + self.k1 * (1 - self.b + self.b * (doc_length / self.avg_doc_length))
            )

            # Inverse document frequency component
            doc_freq = self.doc_freqs.get(term, 0)
            if doc_freq > 0:
                idf = math.log((self.corpus_size - doc_freq + 0.5) / (doc_freq + 0.5))
            else:
                idf = 0.0

            score += idf * tf_component

        return score

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        # Remove punctuation and convert to lowercase
        text = re.sub(r"[^\w\s]", " ", text.lower())
        return text.split()


class GraphTraversal:
    """Graph traversal for relationship-based search."""

    def __init__(self, neo4j_db):
        """Initialize graph traversal.

        Args:
            neo4j_db: Neo4j database connection
        """
        self.neo4j_db = neo4j_db

    def find_related_concepts(
        self, concept_id: str, max_hops: int = 2
    ) -> List[Dict[str, Any]]:
        """Find concepts related through graph traversal.

        Args:
            concept_id: Starting concept ID
            max_hops: Maximum traversal depth

        Returns:
            List of related concepts with relationship info
        """
        query = """
        MATCH (c:Concept {concept_id: $concept_id})
        CALL apoc.path.expand(c, null, null, 1, $max_hops)
        YIELD path, node
        WHERE node:Concept AND node.concept_id <> $concept_id
        WITH node, length(path) as distance,
             [rel IN relationships(path) | type(rel)] as relationship_types
        RETURN node, distance, relationship_types
        ORDER BY distance ASC
        LIMIT 50
        """

        try:
            with self.neo4j_db.session() as session:
                result = session.run(query, concept_id=concept_id, max_hops=max_hops)

                related = []
                for record in result:
                    related.append(
                        {
                            "node": dict(record["node"]),
                            "distance": record["distance"],
                            "relationship_types": record["relationship_types"],
                        }
                    )

                return related

        except Exception as e:
            logger.error(f"Graph traversal error: {e}")
            return []

    def find_shortest_path(
        self, start_id: str, end_id: str, relation_types: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Find shortest path between two nodes.

        Args:
            start_id: Starting node ID
            end_id: End node ID
            relation_types: Allowed relationship types

        Returns:
            Path information or None
        """
        rel_filter = ""
        if relation_types:
            rel_filter = f":{':'.join(relation_types)}"

        query = f"""
        MATCH (start {{concept_id: $start_id}}), (end {{concept_id: $end_id}})
        MATCH path = shortestPath((start)-[{rel_filter}*]-(end))
        RETURN path, length(path) as path_length,
               [node IN nodes(path) | node] as path_nodes,
               [rel IN relationships(path) | type(rel)] as path_relations
        """

        try:
            with self.neo4j_db.session() as session:
                result = session.run(query, start_id=start_id, end_id=end_id)
                record = result.single()

                if record:
                    return {
                        "path_length": record["path_length"],
                        "path_nodes": [dict(node) for node in record["path_nodes"]],
                        "path_relations": record["path_relations"],
                    }

        except Exception as e:
            logger.error(f"Shortest path error: {e}")

        return None

    def find_by_coordinates(
        self, x: float, y: float, z: float, radius: float = 10.0
    ) -> List[Dict[str, Any]]:
        """Find brain regions by MNI coordinates.

        Args:
            x, y, z: MNI coordinates
            radius: Search radius in mm

        Returns:
            List of nearby regions
        """
        query = """
        MATCH (r:Region)
        WHERE r.mni_x IS NOT NULL AND r.mni_y IS NOT NULL AND r.mni_z IS NOT NULL
        WITH r, sqrt(pow(r.mni_x - $x, 2) + pow(r.mni_y - $y, 2) + pow(r.mni_z - $z, 2)) as distance
        WHERE distance <= $radius
        RETURN r, distance
        ORDER BY distance ASC
        LIMIT 20
        """

        try:
            with self.neo4j_db.session() as session:
                result = session.run(query, x=x, y=y, z=z, radius=radius)

                regions = []
                for record in result:
                    regions.append(
                        {"region": dict(record["r"]), "distance": record["distance"]}
                    )

                return regions

        except Exception as e:
            logger.error(f"Coordinate search error: {e}")
            return []


class HybridSearchEngine:
    """Comprehensive hybrid search engine."""

    def __init__(
        self,
        vector_engine: AdvancedVectorSearchEngine,
        neo4j_db,
        enable_graph_traversal: bool = True,
    ):
        """Initialize hybrid search engine.

        Args:
            vector_engine: Vector search engine
            neo4j_db: Neo4j database connection
            enable_graph_traversal: Enable graph-based search
        """
        self.vector_engine = vector_engine
        self.neo4j_db = neo4j_db
        self.enable_graph_traversal = enable_graph_traversal

        # Initialize components
        self.query_analyzer = QueryAnalyzer()
        self.bm25_scorer = BM25Scorer()
        self.graph_traversal = (
            GraphTraversal(neo4j_db) if enable_graph_traversal else None
        )

        # Index documents for BM25
        self._index_documents_for_bm25()

        # Performance tracking
        self.search_stats = {
            "total_searches": 0,
            "search_mode_usage": defaultdict(int),
            "avg_response_time_ms": 0.0,
            "avg_results_returned": 0.0,
        }

        logger.info("Initialized HybridSearchEngine")

    def _index_documents_for_bm25(self):
        """Index documents for BM25 text search."""
        documents = {
            doc.id: doc.content for doc in self.vector_engine.documents.values()
        }
        self.bm25_scorer.index_documents(documents)
        logger.info(f"Indexed {len(documents)} documents for BM25 scoring")

    def search(
        self,
        query: str,
        k: int = 10,
        search_mode: Optional[SearchMode] = None,
        filters: Optional[Dict[str, Any]] = None,
        explain: bool = False,
    ) -> List[ScoredResult]:
        """Perform hybrid search.

        Args:
            query: Search query
            k: Number of results
            search_mode: Override automatic search mode selection
            filters: Additional filters
            explain: Include scoring explanations

        Returns:
            List of scored results
        """
        start_time = time.time()
        self.search_stats["total_searches"] += 1

        # Analyze query
        analysis = self.query_analyzer.analyze_query(query)

        # Override search mode if specified
        if search_mode:
            analysis.search_mode = search_mode

        # Update filters
        if filters:
            analysis.filters.update(filters)

        # Route to appropriate search method
        if analysis.search_mode == SearchMode.TEXT:
            results = self._text_search(query, k, analysis)
        elif analysis.search_mode == SearchMode.VECTOR:
            results = self._vector_search(query, k, analysis)
        elif analysis.search_mode == SearchMode.GRAPH:
            results = self._graph_search(query, k, analysis)
        elif analysis.search_mode == SearchMode.HYBRID:
            results = self._hybrid_search(query, k, analysis)
        elif analysis.search_mode == SearchMode.MULTIMODAL:
            results = self._multimodal_search(query, k, analysis)
        else:  # AUTO
            results = self._auto_search(query, k, analysis)

        # Add explanations if requested
        if explain:
            for result in results:
                result.score_explanation = self._generate_explanation(result, analysis)

        # Update statistics
        search_time = (time.time() - start_time) * 1000
        self._update_search_stats(analysis.search_mode, search_time, len(results))

        logger.info(
            f"Hybrid search completed in {search_time:.2f}ms using {analysis.search_mode.value} mode"
        )

        return results[:k]

    def _text_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Pure text search using BM25."""
        results = []

        for doc_id, doc in self.vector_engine.documents.items():
            # Apply filters
            if not self._matches_filters(doc, analysis.filters):
                continue

            # Calculate BM25 score
            text_score = self.bm25_scorer.score(query, doc_id, doc.content)

            if text_score > 0:
                search_result = SearchResult(
                    id=doc.id,
                    score=text_score,
                    content=doc.content,
                    metadata=doc.metadata.copy(),
                    doc_type=doc.doc_type,
                )

                scored_result = ScoredResult(
                    result=search_result,
                    text_score=text_score,
                    combined_score=text_score,
                )
                results.append(scored_result)

        # Sort by score
        results.sort(key=lambda x: x.combined_score, reverse=True)
        return results[:k]

    def _vector_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Pure vector search."""
        doc_types = analysis.filters.get("doc_types")

        vector_results = self.vector_engine.search(
            query=query,
            k=k,
            doc_types=doc_types,
            filters=analysis.filters,
            use_cache=True,
        )

        scored_results = []
        for result in vector_results:
            scored_result = ScoredResult(
                result=result, vector_score=result.score, combined_score=result.score
            )
            scored_results.append(scored_result)

        return scored_results

    def _graph_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Graph traversal based search."""
        if not self.graph_traversal:
            return self._vector_search(query, k, analysis)

        results = []

        # Coordinate-based search
        if analysis.coordinates:
            x, y, z = analysis.coordinates
            regions = self.graph_traversal.find_by_coordinates(x, y, z, radius=15.0)

            for region_data in regions[:k]:
                region = region_data["region"]
                distance = region_data["distance"]

                search_result = SearchResult(
                    id=region.get("region_id", str(region.get("id", ""))),
                    score=1.0 / (1.0 + distance / 10.0),  # Distance-based score
                    content=region.get("name", ""),
                    metadata={**region, "spatial_distance": distance},
                    doc_type=SearchResultType.REGION,
                )

                scored_result = ScoredResult(
                    result=search_result,
                    graph_score=search_result.score,
                    combined_score=search_result.score,
                )
                results.append(scored_result)

        else:
            # Relationship-based search (simplified)
            # In a full implementation, this would parse relationship queries
            vector_results = self._vector_search(query, k * 2, analysis)

            for i, vector_result in enumerate(vector_results[:k]):
                scored_result = ScoredResult(
                    result=vector_result.result,
                    vector_score=vector_result.vector_score,
                    graph_score=0.1,  # Small graph component
                    combined_score=vector_result.vector_score + 0.1,
                )
                results.append(scored_result)

        return results

    def _hybrid_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Hybrid text + vector search."""
        # Get vector results
        vector_results = self.vector_engine.search(
            query=query,
            k=k * 2,  # Get more for reranking
            doc_types=analysis.filters.get("doc_types"),
            filters=analysis.filters,
        )

        # Calculate combined scores
        scored_results = []
        for vector_result in vector_results:
            # Calculate text score
            text_score = self.bm25_scorer.score(
                query, vector_result.id, vector_result.content
            )

            # Combine scores (weighted average)
            combined_score = 0.6 * vector_result.score + 0.4 * text_score

            scored_result = ScoredResult(
                result=vector_result,
                text_score=text_score,
                vector_score=vector_result.score,
                combined_score=combined_score,
            )
            scored_results.append(scored_result)

        # Sort by combined score
        scored_results.sort(key=lambda x: x.combined_score, reverse=True)

        return scored_results[:k]

    def _multimodal_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Multimodal search combining text, vector, and graph."""
        # Start with hybrid search
        hybrid_results = self._hybrid_search(query, k * 2, analysis)

        # Enhance with graph information
        enhanced_results = []
        for hybrid_result in hybrid_results:
            graph_score = 0.0

            # Add graph traversal score if graph search is enabled
            if (
                self.graph_traversal
                and hybrid_result.result.doc_type == SearchResultType.CONCEPT
            ):
                # Simplified graph enhancement
                graph_score = 0.1  # Base graph score

                # Check if result has relationships
                if "relationships" in hybrid_result.result.metadata:
                    graph_score += 0.1 * len(
                        hybrid_result.result.metadata["relationships"]
                    )

            # Combine all scores
            final_score = (
                0.4 * hybrid_result.vector_score
                + 0.3 * hybrid_result.text_score
                + 0.3 * graph_score
            )

            scored_result = ScoredResult(
                result=hybrid_result.result,
                text_score=hybrid_result.text_score,
                vector_score=hybrid_result.vector_score,
                graph_score=graph_score,
                combined_score=final_score,
            )
            enhanced_results.append(scored_result)

        # Sort by final score
        enhanced_results.sort(key=lambda x: x.combined_score, reverse=True)

        return enhanced_results[:k]

    def _auto_search(
        self, query: str, k: int, analysis: QueryAnalysis
    ) -> List[ScoredResult]:
        """Automatically choose best search method."""
        # Choose method based on analysis confidence and query type
        if analysis.confidence > 0.8:
            if analysis.query_type in [QueryType.COORDINATE, QueryType.REGION]:
                return self._graph_search(query, k, analysis)
            elif analysis.query_type in [QueryType.CONCEPT, QueryType.TASK]:
                return self._hybrid_search(query, k, analysis)
            else:
                return self._vector_search(query, k, analysis)
        else:
            # Low confidence - use multimodal for robustness
            return self._multimodal_search(query, k, analysis)

    def _matches_filters(self, doc: Any, filters: Dict[str, Any]) -> bool:
        """Check if document matches filters."""
        if not filters:
            return True

        # Check document types
        if "doc_types" in filters:
            doc_types = filters["doc_types"]
            if doc.doc_type not in doc_types:
                return False

        # Check metadata filters
        for key, value in filters.items():
            if key == "doc_types":
                continue

            if key not in doc.metadata or doc.metadata[key] != value:
                return False

        return True

    def _generate_explanation(
        self, result: ScoredResult, analysis: QueryAnalysis
    ) -> str:
        """Generate human-readable explanation for result scoring."""
        explanation_parts = []

        if result.text_score > 0:
            explanation_parts.append(f"Text relevance: {result.text_score:.3f}")

        if result.vector_score > 0:
            explanation_parts.append(f"Semantic similarity: {result.vector_score:.3f}")

        if result.graph_score > 0:
            explanation_parts.append(f"Graph connectivity: {result.graph_score:.3f}")

        explanation_parts.append(f"Final score: {result.combined_score:.3f}")
        explanation_parts.append(f"Query type: {analysis.query_type.value}")

        return ". ".join(explanation_parts)

    def _update_search_stats(
        self, search_mode: SearchMode, search_time_ms: float, result_count: int
    ):
        """Update search performance statistics."""
        self.search_stats["search_mode_usage"][search_mode.value] += 1

        # Update rolling averages
        total_searches = self.search_stats["total_searches"]

        current_avg_time = self.search_stats["avg_response_time_ms"]
        self.search_stats["avg_response_time_ms"] = (
            current_avg_time * (total_searches - 1) + search_time_ms
        ) / total_searches

        current_avg_results = self.search_stats["avg_results_returned"]
        self.search_stats["avg_results_returned"] = (
            current_avg_results * (total_searches - 1) + result_count
        ) / total_searches

    def get_search_statistics(self) -> Dict[str, Any]:
        """Get comprehensive search statistics."""
        base_stats = self.vector_engine.get_statistics()

        return {
            **base_stats,
            **self.search_stats,
            "bm25_corpus_size": self.bm25_scorer.corpus_size,
            "graph_traversal_enabled": self.enable_graph_traversal,
            "query_analyzer_patterns": len(self.query_analyzer.query_indicators),
        }
