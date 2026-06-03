"""
Query Builder Agent for Natural Language Query Processing

Constructs executable Cypher and SPARQL queries from mapped patterns.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .schema_mapper_agent import GraphPattern, MappedQuery

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """Types of executable queries"""

    CYPHER = "cypher"
    SPARQL = "sparql"
    GRAPHQL = "graphql"


@dataclass
class ExecutableQuery:
    """An executable query ready for database execution"""

    query_type: QueryType
    query_string: str
    parameters: dict[str, Any]
    fallback_query: str | None
    estimated_cost: float
    confidence_score: float
    optimizations_applied: list[str] = field(default_factory=list)


class QueryBuilderAgent:
    """
    Agent responsible for building executable queries from mapped patterns.

    Handles:
    - Cypher query construction for Neo4j
    - SPARQL query construction for RDF stores
    - Query optimization
    - Fallback query generation
    """

    def __init__(self):
        """Initialize the query builder agent"""
        self.query_templates = self._load_query_templates()

    def _load_query_templates(self) -> dict[str, str]:
        """Load query templates for common patterns"""
        return {
            "simple_match": "MATCH {pattern} WHERE {filters} RETURN {projections}",
            "aggregation": "MATCH {pattern} WHERE {filters} RETURN {aggregation}",
            "path_search": "MATCH path = {pattern} WHERE {filters} RETURN path",
            "shortest_path": "MATCH path = shortestPath({pattern}) RETURN path",
            "optional_match": "MATCH {required} OPTIONAL MATCH {optional} WHERE {filters} RETURN {projections}",
        }

    def build_query(
        self, mapped_query: MappedQuery, context: dict[str, Any] | None = None
    ) -> ExecutableQuery:
        """
        Build an executable query from mapped patterns

        Args:
            mapped_query: The mapped query with patterns and filters
            context: Optional context for query building

        Returns:
            ExecutableQuery ready for execution
        """
        # Determine query type based on backend
        query_type = self._determine_query_type(context)

        if query_type == QueryType.CYPHER:
            query_string, parameters = self._build_cypher_query(mapped_query)
            fallback = self._generate_fallback_query(mapped_query)
        elif query_type == QueryType.SPARQL:
            query_string, parameters = self._build_sparql_query(mapped_query)
            fallback = None
        else:
            raise ValueError(f"Unsupported query type: {query_type}")

        # Apply optimizations
        query_string, optimizations = self._optimize_query(
            query_string, query_type, mapped_query
        )

        # Estimate query cost
        estimated_cost = self._estimate_query_cost(mapped_query, query_string)

        # Calculate confidence
        confidence = self._calculate_confidence(
            mapped_query, optimizations, estimated_cost
        )

        return ExecutableQuery(
            query_type=query_type,
            query_string=query_string,
            parameters=parameters,
            fallback_query=fallback,
            estimated_cost=estimated_cost,
            confidence_score=confidence,
            optimizations_applied=optimizations,
        )

    def _determine_query_type(self, context: dict[str, Any] | None) -> QueryType:
        """Determine which query type to use"""
        if context and "backend" in context:
            if context["backend"] == "neo4j":
                return QueryType.CYPHER
            elif context["backend"] == "sparql":
                return QueryType.SPARQL

        # Default to Cypher for Neo4j
        return QueryType.CYPHER

    def _build_cypher_query(
        self, mapped_query: MappedQuery
    ) -> tuple[str, dict[str, Any]]:
        """Build a Cypher query for Neo4j"""
        query_parts = []
        parameters = {}
        param_counter = 0

        # Build MATCH clauses
        for pattern in mapped_query.graph_patterns:
            match_clause = self._build_match_clause(pattern, mapped_query)
            query_parts.append(match_clause)

        # Build WHERE clauses
        where_conditions = []

        # Add node filters
        for node_id, filters in mapped_query.node_filters.items():
            for filter_spec in filters:
                param_name = f"param_{param_counter}"
                param_counter += 1

                condition = self._build_filter_condition(
                    node_id, filter_spec, param_name
                )
                where_conditions.append(condition)
                parameters[param_name] = filter_spec["value"]

        # Add relationship filters
        for rel_alias, filters in mapped_query.relationship_filters.items():
            for filter_spec in filters:
                param_name = f"param_{param_counter}"
                param_counter += 1

                condition = self._build_filter_condition(
                    rel_alias, filter_spec, param_name
                )
                where_conditions.append(condition)
                parameters[param_name] = filter_spec["value"]

        # Add WHERE clause if conditions exist
        if where_conditions:
            query_parts.append("WHERE " + " AND ".join(where_conditions))

        # Build RETURN clause
        return_clause = self._build_return_clause(
            mapped_query.projections,
            mapped_query.parsed_query.intent,
            mapped_query.parsed_query.modifiers,
        )
        query_parts.append(return_clause)

        # Add modifiers (ORDER BY, LIMIT, etc.)
        modifiers = self._build_modifiers(mapped_query.parsed_query.modifiers)
        if modifiers:
            query_parts.append(modifiers)

        query_string = "\n".join(query_parts)
        return query_string, parameters

    def _build_sparql_query(
        self, mapped_query: MappedQuery
    ) -> tuple[str, dict[str, Any]]:
        """Build a SPARQL query"""
        query_parts = []

        # Prefixes
        query_parts.append(
            """
PREFIX br_kg: <https://br_kg.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX bio2rdf: <http://bio2rdf.org/>
        """.strip()
        )

        # SELECT clause
        projections = mapped_query.projections if mapped_query.projections else ["*"]
        select_vars = " ".join(
            [f"?{p}" if not p.startswith("?") else p for p in projections]
        )
        query_parts.append(f"SELECT {select_vars}")

        # WHERE clause with graph patterns
        where_patterns = []
        for pattern in mapped_query.graph_patterns:
            sparql_pattern = self._convert_to_sparql_pattern(pattern)
            where_patterns.append(sparql_pattern)

        # Add filters
        filter_conditions = []
        for constraint in mapped_query.constraints:
            filter_condition = self._build_sparql_filter(constraint)
            if filter_condition:
                filter_conditions.append(filter_condition)

        query_parts.append("WHERE {")
        query_parts.extend(["  " + p for p in where_patterns])
        if filter_conditions:
            query_parts.extend(["  FILTER(" + f + ")" for f in filter_conditions])
        query_parts.append("}")

        # Add modifiers
        if mapped_query.parsed_query.modifiers.get("limit"):
            query_parts.append(f"LIMIT {mapped_query.parsed_query.modifiers['limit']}")

        query_string = "\n".join(query_parts)
        return query_string, {}

    def _build_match_clause(
        self, pattern: GraphPattern, mapped_query: MappedQuery
    ) -> str:
        """Build a MATCH clause from a graph pattern"""
        # Use the pattern string if available
        if pattern.pattern_string:
            # Add property filters to pattern
            enhanced_pattern = self._enhance_pattern_with_properties(
                pattern, mapped_query
            )
            return f"MATCH {enhanced_pattern}"

        # Build from nodes and relationships
        pattern_parts = []

        for node in pattern.nodes:
            node_pattern = f"({node['alias']}:{node['type']})"
            pattern_parts.append(node_pattern)

        for rel in pattern.relationships:
            source_alias = self._find_node_alias(pattern.nodes, rel["source"])
            target_alias = self._find_node_alias(pattern.nodes, rel["target"])
            rel_pattern = (
                f"({source_alias})-[{rel['alias']}:{rel['type']}]->({target_alias})"
            )
            pattern_parts.append(rel_pattern)

        return f"MATCH {', '.join(pattern_parts)}"

    def _enhance_pattern_with_properties(
        self, pattern: GraphPattern, mapped_query: MappedQuery
    ) -> str:
        """Add inline property filters to pattern"""
        enhanced = pattern.pattern_string

        # Add node properties
        for node in pattern.nodes:
            if "properties" in node and node["properties"]:
                prop_string = ", ".join(
                    [f"{k}: '{v}'" for k, v in node["properties"].items()]
                )
                enhanced = enhanced.replace(
                    f"{node['alias']}:", f"{node['alias']}: {{{prop_string}}} "
                )

        return enhanced

    def _build_filter_condition(
        self, identifier: str, filter_spec: dict[str, Any], param_name: str
    ) -> str:
        """Build a filter condition"""
        property_path = f"{identifier}.{filter_spec['property']}"
        operator = filter_spec["operator"]

        operator_map = {
            "eq": "=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
            "ne": "<>",
            "contains": "CONTAINS",
            "starts_with": "STARTS WITH",
            "ends_with": "ENDS WITH",
            "between": "BETWEEN",
            "in": "IN",
        }

        cypher_op = operator_map.get(operator, "=")

        if operator == "between":
            # Special handling for between
            return f"{property_path} >= ${param_name}_min AND {property_path} <= ${param_name}_max"
        elif operator in ["contains", "starts_with", "ends_with"]:
            return f"{property_path} {cypher_op} ${param_name}"
        else:
            return f"{property_path} {cypher_op} ${param_name}"

    def _build_return_clause(
        self, projections: list[str], intent: str, modifiers: dict[str, Any]
    ) -> str:
        """Build a RETURN clause"""
        if not projections or projections == ["*"]:
            return "RETURN *"

        # Handle aggregations
        if "aggregate" in intent.lower() or "count" in intent.lower():
            if "group_by" in modifiers:
                group_field = modifiers["group_by"]
                return f"RETURN {group_field}, count(*) as count"
            else:
                return "RETURN count(*) as count"

        # Handle specific projections
        return_items = []
        for projection in projections:
            # Add labels for clarity
            if "." not in projection:
                return_items.append(projection)
            else:
                # Extract property
                alias, prop = projection.rsplit(".", 1)
                return_items.append(f"{projection} as {alias}_{prop}")

        return f"RETURN {', '.join(return_items)}"

    def _build_modifiers(self, modifiers: dict[str, Any]) -> str:
        """Build query modifiers (ORDER BY, LIMIT, SKIP)"""
        modifier_parts = []

        if "sort_by" in modifiers:
            order = modifiers.get("sort_order", "asc").upper()
            modifier_parts.append(f"ORDER BY {modifiers['sort_by']} {order}")

        if "limit" in modifiers:
            modifier_parts.append(f"LIMIT {modifiers['limit']}")

        if "skip" in modifiers:
            modifier_parts.append(f"SKIP {modifiers['skip']}")

        return "\n".join(modifier_parts)

    def _convert_to_sparql_pattern(self, pattern: GraphPattern) -> str:
        """Convert a graph pattern to SPARQL triple patterns"""
        triples = []

        for node in pattern.nodes:
            # Create subject variable
            subject = f"?{node['alias']}"
            # Add type triple
            triples.append(f"{subject} a br_kg:{node['type']}")

            # Add property triples
            if "properties" in node:
                for prop, value in node["properties"].items():
                    if isinstance(value, str):
                        triples.append(f'{subject} br_kg:{prop} "{value}"')
                    else:
                        triples.append(f"{subject} br_kg:{prop} {value}")

        for rel in pattern.relationships:
            source = f"?{self._find_node_alias(pattern.nodes, rel['source'])}"
            target = f"?{self._find_node_alias(pattern.nodes, rel['target'])}"
            predicate = f"br_kg:{rel['type']}"
            triples.append(f"{source} {predicate} {target}")

        return " .\n  ".join(triples) + " ."

    def _build_sparql_filter(self, constraint: dict[str, Any]) -> str | None:
        """Build a SPARQL FILTER expression"""
        if constraint["type"] == "numeric":
            field = f"?{constraint['field']}"
            op = constraint["operator"]
            value = constraint["value"]

            operator_map = {
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
                "eq": "=",
                "ne": "!=",
            }

            sparql_op = operator_map.get(op, "=")
            return f"{field} {sparql_op} {value}"

        elif constraint["type"] == "temporal":
            # Handle date filters
            field = f"?{constraint['field']}"
            return f'{field} > "{constraint["value"]}"^^xsd:date'

        return None

    def _find_node_alias(self, nodes: list[dict], node_id: str) -> str:
        """Find the alias for a node by its ID"""
        for node in nodes:
            if node["id"] == node_id:
                return node["alias"]
        return f"n{node_id}"

    def _generate_fallback_query(self, mapped_query: MappedQuery) -> str | None:
        """Generate a simpler fallback query"""
        if not mapped_query.graph_patterns:
            return None

        # Create a simple pattern with just the main entity
        main_pattern = mapped_query.graph_patterns[0]
        if main_pattern.nodes:
            main_node = main_pattern.nodes[0]
            fallback = f"""
MATCH (n:{main_node['type']})
RETURN n
LIMIT 10
            """.strip()
            return fallback

        return None

    def _optimize_query(
        self, query_string: str, query_type: QueryType, mapped_query: MappedQuery
    ) -> tuple[str, list[str]]:
        """Apply query optimizations"""
        optimizations = []

        if query_type == QueryType.CYPHER:
            # Index hints
            if self._should_use_index_hints(mapped_query):
                query_string = self._add_index_hints(query_string, mapped_query)
                optimizations.append("index_hints")

            # Limit pushdown
            if self._can_pushdown_limit(query_string):
                query_string = self._pushdown_limit(query_string)
                optimizations.append("limit_pushdown")

            # Filter reordering
            query_string = self._reorder_filters(query_string)
            optimizations.append("filter_reordering")

        return query_string, optimizations

    def _should_use_index_hints(self, mapped_query: MappedQuery) -> bool:
        """Determine if index hints should be used"""
        # Use index hints if we have specific property filters
        return bool(mapped_query.node_filters)

    def _add_index_hints(self, query_string: str, mapped_query: MappedQuery) -> str:
        """Add index hints to query"""
        # Add USING INDEX hints for filtered properties
        hints = []
        for node_id, filters in mapped_query.node_filters.items():
            for filter_spec in filters:
                if filter_spec["property"] in ["name", "id", "symbol"]:
                    hints.append(f"USING INDEX {node_id}:{filter_spec['property']}")

        if hints:
            # Insert hints after MATCH clause
            parts = query_string.split("\n")
            for i, part in enumerate(parts):
                if part.startswith("MATCH"):
                    parts.insert(i + 1, "\n".join(hints))
                    break
            query_string = "\n".join(parts)

        return query_string

    def _can_pushdown_limit(self, query_string: str) -> bool:
        """Check if LIMIT can be pushed down"""
        # Can pushdown if no aggregation
        return (
            "count(" not in query_string.lower() and "sum(" not in query_string.lower()
        )

    def _pushdown_limit(self, query_string: str) -> str:
        """Push LIMIT closer to MATCH for early termination"""
        # This is a simplified implementation
        # In practice, would need more sophisticated AST manipulation
        return query_string

    def _reorder_filters(self, query_string: str) -> str:
        """Reorder WHERE conditions for optimal evaluation"""
        # Put most selective filters first
        # This is a simplified implementation
        return query_string

    def _estimate_query_cost(
        self, mapped_query: MappedQuery, query_string: str
    ) -> float:
        """Estimate the computational cost of a query"""
        cost = 1.0

        # Factor in pattern complexity
        for pattern in mapped_query.graph_patterns:
            cost += len(pattern.nodes) * 0.5
            cost += len(pattern.relationships) * 1.0

        # Factor in filters (reduce cost)
        cost -= len(mapped_query.node_filters) * 0.2
        cost -= len(mapped_query.relationship_filters) * 0.1

        # Factor in projections
        if "*" in mapped_query.projections:
            cost += 0.5

        # Factor in modifiers
        if mapped_query.parsed_query.modifiers.get("limit"):
            cost *= 0.5  # LIMIT reduces cost

        return max(0.1, cost)

    def _calculate_confidence(
        self, mapped_query: MappedQuery, optimizations: list[str], estimated_cost: float
    ) -> float:
        """Calculate confidence in the built query"""
        confidence = mapped_query.confidence_score

        # Boost confidence if optimizations were applied
        confidence += len(optimizations) * 0.05

        # Reduce confidence for high-cost queries
        if estimated_cost > 5.0:
            confidence *= 0.8

        # Boost confidence if we have filters
        if mapped_query.node_filters or mapped_query.relationship_filters:
            confidence *= 1.1

        return min(1.0, confidence)
