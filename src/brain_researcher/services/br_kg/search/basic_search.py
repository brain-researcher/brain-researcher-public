"""
Search functionality for BR-KG.
Implements KG-012: Basic Search Implementation
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SearchMode(Enum):
    """Search modes."""
    EXACT = "exact"
    CONTAINS = "contains"
    FUZZY = "fuzzy"
    REGEX = "regex"


@dataclass
class SearchResult:
    """Search result item."""
    node_id: str
    node_type: str
    score: float
    matched_fields: List[str]
    properties: Dict[str, Any]
    highlight: Optional[Dict[str, str]] = None


class SearchEngine:
    """Full-text search engine for BR-KG."""

    def __init__(self, db):
        """Initialize search engine with database."""
        self.db = db
        self._build_index()

    def _build_index(self):
        """Build search index from database."""
        # In a production system, this would use Elasticsearch or similar
        # For now, we'll implement in-memory indexing
        self.index = {
            "nodes": {},
            "text_index": {},
            "type_index": {}
        }

        # Index all nodes
        for node_type in ["Concept", "Task", "Region", "Dataset", "Publication"]:
            for node_id, props in self.db.find_nodes(node_type, None):
                self._index_node(node_id, node_type, props)

    def _index_node(self, node_id: str, node_type: str, properties: Dict[str, Any]):
        """Index a single node."""
        # Store node
        self.index["nodes"][node_id] = {
            "type": node_type,
            "properties": properties
        }

        # Add to type index
        if node_type not in self.index["type_index"]:
            self.index["type_index"][node_type] = []
        self.index["type_index"][node_type].append(node_id)

        # Index text fields
        text_fields = self._extract_text_fields(properties)
        for field, text in text_fields.items():
            tokens = self._tokenize(text)
            for token in tokens:
                if token not in self.index["text_index"]:
                    self.index["text_index"][token] = []
                self.index["text_index"][token].append((node_id, field))

    def _extract_text_fields(self, properties: Dict[str, Any]) -> Dict[str, str]:
        """Extract searchable text fields from properties."""
        text_fields = {}
        for key, value in properties.items():
            if isinstance(value, str):
                text_fields[key] = value
            elif isinstance(value, (int, float)):
                text_fields[key] = str(value)
        return text_fields

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for indexing."""
        # Simple tokenization - could be enhanced with NLP
        text = text.lower()
        # Remove punctuation and split
        tokens = re.findall(r'\b\w+\b', text)
        return tokens

    def search(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        fields: Optional[List[str]] = None,
        mode: SearchMode = SearchMode.CONTAINS,
        limit: int = 100,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """
        Search for nodes matching query.

        Args:
            query: Search query string
            node_types: Filter by node types
            fields: Search only specific fields
            mode: Search mode (exact, contains, fuzzy, regex)
            limit: Maximum results
            min_score: Minimum relevance score

        Returns:
            List of search results sorted by relevance
        """
        results = []
        query_lower = query.lower()
        query_tokens = self._tokenize(query)

        # Search based on mode
        if mode == SearchMode.EXACT:
            results = self._search_exact(query_lower, node_types, fields)
        elif mode == SearchMode.CONTAINS:
            results = self._search_contains(query_lower, node_types, fields)
        elif mode == SearchMode.FUZZY:
            results = self._search_fuzzy(query_tokens, node_types, fields)
        elif mode == SearchMode.REGEX:
            results = self._search_regex(query, node_types, fields)

        # Filter by minimum score
        results = [r for r in results if r.score >= min_score]

        # Sort by score (descending)
        results.sort(key=lambda x: x.score, reverse=True)

        # Apply limit
        return results[:limit]

    def _search_exact(
        self,
        query: str,
        node_types: Optional[List[str]],
        fields: Optional[List[str]]
    ) -> List[SearchResult]:
        """Exact match search."""
        results = []

        for node_id, node_data in self.index["nodes"].items():
            # Filter by node type
            if node_types and node_data["type"] not in node_types:
                continue

            matched_fields = []
            for field, value in node_data["properties"].items():
                # Filter by fields
                if fields and field not in fields:
                    continue

                if isinstance(value, str) and value.lower() == query:
                    matched_fields.append(field)

            if matched_fields:
                results.append(SearchResult(
                    node_id=node_id,
                    node_type=node_data["type"],
                    score=1.0,
                    matched_fields=matched_fields,
                    properties=node_data["properties"]
                ))

        return results

    def _search_contains(
        self,
        query: str,
        node_types: Optional[List[str]],
        fields: Optional[List[str]]
    ) -> List[SearchResult]:
        """Contains search (substring matching)."""
        results = []

        for node_id, node_data in self.index["nodes"].items():
            # Filter by node type
            if node_types and node_data["type"] not in node_types:
                continue

            matched_fields = []
            total_score = 0.0

            for field, value in node_data["properties"].items():
                # Filter by fields
                if fields and field not in fields:
                    continue

                if isinstance(value, str):
                    value_lower = value.lower()
                    if query in value_lower:
                        matched_fields.append(field)
                        # Score based on position and frequency
                        position_score = 1.0 - (value_lower.index(query) / len(value_lower))
                        frequency_score = value_lower.count(query) / len(value_lower.split())
                        field_score = (position_score + frequency_score) / 2

                        # Boost score for certain fields
                        if field in ["name", "title"]:
                            field_score *= 2.0
                        elif field in ["id", "pmid", "accession"]:
                            field_score *= 1.5

                        total_score += field_score

            if matched_fields:
                results.append(SearchResult(
                    node_id=node_id,
                    node_type=node_data["type"],
                    score=min(total_score, 1.0),
                    matched_fields=matched_fields,
                    properties=node_data["properties"],
                    highlight=self._generate_highlights(
                        node_data["properties"],
                        matched_fields,
                        query
                    )
                ))

        return results

    def _search_fuzzy(
        self,
        query_tokens: List[str],
        node_types: Optional[List[str]],
        fields: Optional[List[str]]
    ) -> List[SearchResult]:
        """Fuzzy search using token matching."""
        results = {}

        # Find nodes containing query tokens
        for token in query_tokens:
            if token in self.index["text_index"]:
                for node_id, field in self.index["text_index"][token]:
                    if node_id not in results:
                        results[node_id] = {
                            "matched_fields": set(),
                            "score": 0.0
                        }
                    results[node_id]["matched_fields"].add(field)
                    results[node_id]["score"] += 1.0 / len(query_tokens)

        # Convert to SearchResult objects
        search_results = []
        for node_id, match_data in results.items():
            node_data = self.index["nodes"][node_id]

            # Filter by node type
            if node_types and node_data["type"] not in node_types:
                continue

            # Filter by fields
            if fields:
                match_data["matched_fields"] &= set(fields)
                if not match_data["matched_fields"]:
                    continue

            search_results.append(SearchResult(
                node_id=node_id,
                node_type=node_data["type"],
                score=match_data["score"],
                matched_fields=list(match_data["matched_fields"]),
                properties=node_data["properties"]
            ))

        return search_results

    def _search_regex(
        self,
        pattern: str,
        node_types: Optional[List[str]],
        fields: Optional[List[str]]
    ) -> List[SearchResult]:
        """Regular expression search."""
        results = []

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            logger.error(f"Invalid regex pattern: {pattern}")
            return results

        for node_id, node_data in self.index["nodes"].items():
            # Filter by node type
            if node_types and node_data["type"] not in node_types:
                continue

            matched_fields = []
            for field, value in node_data["properties"].items():
                # Filter by fields
                if fields and field not in fields:
                    continue

                if isinstance(value, str) and regex.search(value):
                    matched_fields.append(field)

            if matched_fields:
                results.append(SearchResult(
                    node_id=node_id,
                    node_type=node_data["type"],
                    score=0.8,  # Fixed score for regex matches
                    matched_fields=matched_fields,
                    properties=node_data["properties"]
                ))

        return results

    def _generate_highlights(
        self,
        properties: Dict[str, Any],
        matched_fields: List[str],
        query: str
    ) -> Dict[str, str]:
        """Generate highlighted snippets for matched fields."""
        highlights = {}

        for field in matched_fields:
            value = properties.get(field, "")
            if isinstance(value, str):
                # Simple highlighting with markers
                highlighted = value.replace(
                    query,
                    f"<mark>{query}</mark>",
                    1  # Only highlight first occurrence
                )
                highlights[field] = highlighted

        return highlights

    def suggest(
        self,
        prefix: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[str]:
        """
        Generate search suggestions based on prefix.

        Args:
            prefix: Search prefix
            node_types: Filter by node types
            limit: Maximum suggestions

        Returns:
            List of suggested search terms
        """
        suggestions = set()
        prefix_lower = prefix.lower()

        # Find matching tokens
        for token in self.index["text_index"]:
            if token.startswith(prefix_lower):
                # Get nodes containing this token
                for node_id, _ in self.index["text_index"][token]:
                    node_data = self.index["nodes"][node_id]

                    # Filter by node type
                    if node_types and node_data["type"] not in node_types:
                        continue

                    # Add name/title as suggestion
                    for field in ["name", "title"]:
                        if field in node_data["properties"]:
                            suggestions.add(node_data["properties"][field])

        # Sort and limit
        sorted_suggestions = sorted(suggestions)[:limit]
        return sorted_suggestions

    def get_statistics(self) -> Dict[str, Any]:
        """Get search index statistics."""
        stats = {
            "total_nodes": len(self.index["nodes"]),
            "total_tokens": len(self.index["text_index"]),
            "nodes_by_type": {},
            "avg_tokens_per_node": 0
        }

        # Count by type
        for node_type, node_ids in self.index["type_index"].items():
            stats["nodes_by_type"][node_type] = len(node_ids)

        # Calculate average tokens
        total_tokens = sum(
            len(nodes) for nodes in self.index["text_index"].values()
        )
        if stats["total_nodes"] > 0:
            stats["avg_tokens_per_node"] = total_tokens / stats["total_nodes"]

        return stats

    def rebuild_index(self):
        """Rebuild the search index."""
        logger.info("Rebuilding search index...")
        self._build_index()
        logger.info(f"Index rebuilt: {self.get_statistics()}")


# GraphQL integration
def add_search_to_schema(schema_builder):
    """Add search queries to GraphQL schema."""
    import strawberry

    @strawberry.type
    class SearchResultType:
        node_id: str
        node_type: str
        score: float
        matched_fields: List[str]
        properties: str  # JSON string

    @schema_builder.query
    @strawberry.field
    def search(
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[SearchResultType]:
        """Search across all nodes."""
        import json

        from brain_researcher.services.br_kg.db.bootstrap import get_db

        db = get_db()
        engine = SearchEngine(db)

        results = engine.search(
            query,
            node_types=node_types,
            limit=limit
        )

        return [
            SearchResultType(
                node_id=r.node_id,
                node_type=r.node_type,
                score=r.score,
                matched_fields=r.matched_fields,
                properties=json.dumps(r.properties)
            )
            for r in results
        ]

    @schema_builder.query
    @strawberry.field
    def search_suggestions(
        prefix: str,
        limit: int = 10
    ) -> List[str]:
        """Get search suggestions."""
        from brain_researcher.services.br_kg.db.bootstrap import get_db

        db = get_db()
        engine = SearchEngine(db)

        return engine.suggest(prefix, limit=limit)