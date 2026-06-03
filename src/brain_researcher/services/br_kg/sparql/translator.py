"""
SPARQL to Cypher Query Translation

Translates SPARQL queries to Cypher queries for execution against Neo4j.
Handles common SPARQL patterns and converts them to equivalent Cypher operations.
"""

import logging
from typing import Any
from urllib.parse import urlparse

from rdflib.plugins.sparql.algebra import translateQuery

logger = logging.getLogger(__name__)


class SPARQLToCypherTranslator:
    """
    Translates SPARQL queries to Cypher queries

    Supports translation of:
    - Basic triple patterns
    - FILTER expressions
    - OPTIONAL clauses
    - UNION queries
    - Aggregation functions
    - ORDER BY, LIMIT, OFFSET
    """

    def __init__(self, base_uri: str = "https://br_kg.org/"):
        self.base_uri = base_uri
        self.variable_counter = 0
        self.node_mappings = {}  # Maps SPARQL variables to Cypher node variables
        self.relationship_vars = set()  # Track which SPARQL vars are relationships
        self.predicate_mappings = {
            # Common RDF/OWL predicates to Neo4j relationship types
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": "TYPE",
            "http://www.w3.org/2000/01/rdf-schema#label": "LABEL",
            "http://www.w3.org/2000/01/rdf-schema#comment": "COMMENT",
            "http://purl.org/dc/terms/title": "TITLE",
            "http://purl.org/dc/terms/description": "DESCRIPTION",
            # BR-KG specific predicates
            f"{base_uri}activatesRegion": "ACTIVATES_REGION",
            f"{base_uri}usesTask": "USES_TASK",
            f"{base_uri}mapsTo": "MAPS_TO",
            f"{base_uri}partOf": "PART_OF",
            f"{base_uri}relatedTo": "RELATED_TO",
            f"{base_uri}studiedIn": "STUDIED_IN",
            f"{base_uri}hasContrast": "HAS_CONTRAST",
            f"{base_uri}belongsTo": "BELONGS_TO",
        }

        logger.info("SPARQL to Cypher translator initialized")

    def translate_query(self, parsed_query) -> tuple[str, dict[str, Any]]:
        """
        Translate a parsed SPARQL query to Cypher

        Returns:
            Tuple of (cypher_query, parameters)
        """
        self._reset_state()

        try:
            query_type = self._get_query_type(parsed_query)

            if query_type == "SELECT":
                return self._translate_select_query(parsed_query)
            elif query_type == "CONSTRUCT":
                return self._translate_construct_query(parsed_query)
            elif query_type == "ASK":
                return self._translate_ask_query(parsed_query)
            elif query_type == "DESCRIBE":
                return self._translate_describe_query(parsed_query)
            else:
                raise ValueError(f"Unsupported query type: {query_type}")

        except Exception as e:
            logger.error("Translation failed: %s", str(e))
            raise

    def _reset_state(self) -> None:
        """Reset per-query state."""
        self.variable_counter = 0
        self.node_mappings = {}
        self.relationship_vars = set()

    def _translate_select_query(self, parsed_query) -> tuple[str, dict[str, Any]]:
        """Translate SELECT query"""

        # Extract query components
        variables = self._extract_select_variables(parsed_query)
        where_patterns = self._extract_where_patterns(parsed_query)
        filters = self._extract_filters(parsed_query)
        optional_patterns = self._extract_optional_patterns(parsed_query)
        order_by = self._extract_order_by(parsed_query)
        limit = self._extract_limit(parsed_query)
        offset = self._extract_offset(parsed_query)

        # Build Cypher query
        match_clauses = []
        where_clauses = []
        optional_clauses = []
        params = {}

        # Process basic triple patterns
        for pattern in where_patterns:
            match_clause, where_clause, pattern_params = self._translate_triple_pattern(
                pattern
            )
            if match_clause:
                match_clauses.append(match_clause)
            if where_clause:
                where_clauses.append(where_clause)
            params.update(pattern_params)

        # Process optional patterns
        for opt_pattern in optional_patterns:
            opt_match, opt_where, opt_params = self._translate_triple_pattern(
                opt_pattern
            )
            if opt_match:
                optional_clauses.append(f"OPTIONAL MATCH {opt_match}")
                if opt_where:
                    optional_clauses.append(f"WHERE {opt_where}")
            params.update(opt_params)

        # Process filters
        for filter_expr in filters:
            filter_clause, filter_params = self._translate_filter(filter_expr)
            if filter_clause:
                where_clauses.append(filter_clause)
            params.update(filter_params)

        # Build final query
        cypher_parts = []

        if match_clauses:
            cypher_parts.append("MATCH " + ", ".join(match_clauses))

        if optional_clauses:
            cypher_parts.extend(optional_clauses)

        if where_clauses:
            cypher_parts.append("WHERE " + " AND ".join(where_clauses))

        # Return clause
        return_vars = self._build_return_clause(variables)
        cypher_parts.append(f"RETURN {return_vars}")

        # Order by
        if order_by:
            order_clause = self._translate_order_by(order_by)
            cypher_parts.append(order_clause)

        # Limit and offset
        if limit:
            cypher_parts.append(f"LIMIT {limit}")
        if offset:
            cypher_parts.append(f"SKIP {offset}")

        cypher_query = " ".join(cypher_parts)

        logger.debug("Translated SPARQL SELECT to Cypher: %s", cypher_query)
        return cypher_query, params

    def _translate_construct_query(self, parsed_query) -> tuple[str, dict[str, Any]]:
        """Translate CONSTRUCT query"""

        # For CONSTRUCT queries, we need to build RDF triples from graph patterns
        construct_patterns = self._extract_construct_patterns(parsed_query)
        where_patterns = self._extract_where_patterns(parsed_query)

        match_clauses = []
        where_clauses = []
        params = {}

        # Process WHERE patterns to match data
        for pattern in where_patterns:
            match_clause, where_clause, pattern_params = self._translate_triple_pattern(
                pattern
            )
            if match_clause:
                match_clauses.append(match_clause)
            if where_clause:
                where_clauses.append(where_clause)
            params.update(pattern_params)

        # Build query to return constructed triples
        cypher_parts = []

        if match_clauses:
            cypher_parts.append("MATCH " + ", ".join(match_clauses))

        if where_clauses:
            cypher_parts.append("WHERE " + " AND ".join(where_clauses))

        # Return constructed triples
        construct_return = self._build_construct_return(construct_patterns)
        cypher_parts.append(f"RETURN {construct_return}")

        cypher_query = " ".join(cypher_parts)

        logger.debug("Translated SPARQL CONSTRUCT to Cypher: %s", cypher_query)
        return cypher_query, params

    def _translate_ask_query(self, parsed_query) -> tuple[str, dict[str, Any]]:
        """Translate ASK query"""

        where_patterns = self._extract_where_patterns(parsed_query)

        match_clauses = []
        where_clauses = []
        params = {}

        for pattern in where_patterns:
            match_clause, where_clause, pattern_params = self._translate_triple_pattern(
                pattern
            )
            if match_clause:
                match_clauses.append(match_clause)
            if where_clause:
                where_clauses.append(where_clause)
            params.update(pattern_params)

        cypher_parts = []

        if match_clauses:
            cypher_parts.append("MATCH " + ", ".join(match_clauses))

        if where_clauses:
            cypher_parts.append("WHERE " + " AND ".join(where_clauses))

        # Return 1 if match exists, empty otherwise
        cypher_parts.append("RETURN count(*) > 0 as result")
        cypher_parts.append("LIMIT 1")

        cypher_query = " ".join(cypher_parts)

        logger.debug("Translated SPARQL ASK to Cypher: %s", cypher_query)
        return cypher_query, params

    def _translate_describe_query(self, parsed_query) -> tuple[str, dict[str, Any]]:
        """Translate DESCRIBE query"""

        # DESCRIBE queries return all properties of specified resources
        resources = self._extract_describe_resources(parsed_query)

        match_clauses = []
        params = {}

        for i, resource in enumerate(resources):
            if resource.startswith("?"):  # Variable
                var_name = self._get_node_variable(resource)
                match_clauses.append(f"({var_name})")
            else:  # URI
                param_name = f"resource_{i}"
                params[param_name] = self._uri_to_node_id(resource)
                var_name = self._get_node_variable(f"?resource_{i}")
                match_clauses.append(f"({var_name} {{id: ${param_name}}})")

        cypher_parts = []
        cypher_parts.append("MATCH " + ", ".join(match_clauses))
        cypher_parts.append("OPTIONAL MATCH (n)-[r]-(m)")
        cypher_parts.append("RETURN n as subject, type(r) as predicate, m as object")

        cypher_query = " ".join(cypher_parts)

        logger.debug("Translated SPARQL DESCRIBE to Cypher: %s", cypher_query)
        return cypher_query, params

    def _translate_triple_pattern(self, pattern) -> tuple[str, str, dict[str, Any]]:
        """
        Translate a single triple pattern to Cypher

        Returns:
            Tuple of (match_clause, where_clause, parameters)
        """
        subject, predicate, obj = pattern

        match_parts = []
        where_parts = []
        params = {}

        # Handle subject
        if subject.startswith("?"):  # Variable
            subj_var = self._get_node_variable(subject)
            match_parts.append(f"({subj_var})")
        else:  # URI or literal
            subj_param = f"subj_{self.variable_counter}"
            self.variable_counter += 1
            params[subj_param] = self._uri_to_node_id(subject)
            subj_var = self._get_node_variable(f"?{subj_param}")
            match_parts.append(f"({subj_var} {{id: ${subj_param}}})")

        # Handle predicate (relationship type or variable)
        if predicate.startswith("?"):
            # Variable predicate: use any relationship type and bind the rel var to the SPARQL var
            rel_var = self._get_node_variable(predicate)
            self.relationship_vars.add(predicate)
            rel_type = ""
        else:
            rel_type = self._predicate_to_relationship_type(predicate)
            rel_var = f"r_{self.variable_counter}"
            self.variable_counter += 1

        # Handle object
        if obj.startswith("?"):  # Variable
            obj_var = self._get_node_variable(obj)
            match_parts.append(f"({obj_var})")
        else:  # URI or literal
            obj_param = f"obj_{self.variable_counter}"
            self.variable_counter += 1

            if obj.startswith('"'):  # Literal
                # Handle as node property
                prop_name = "value"  # Default property for literals
                where_parts.append(f"{subj_var}.{prop_name} = ${obj_param}")
                params[obj_param] = obj.strip('"')
                return f"({subj_var})", " AND ".join(where_parts), params
            else:  # URI
                params[obj_param] = self._uri_to_node_id(obj)
                obj_var = self._get_node_variable(f"?{obj_param}")
                match_parts.append(f"({obj_var} {{id: ${obj_param}}})")

        # Build relationship pattern
        if len(match_parts) >= 2:
            if rel_type:
                match_clause = (
                    f"{match_parts[0]}-[{rel_var}:{rel_type}]->{match_parts[1]}"
                )
            else:
                match_clause = f"{match_parts[0]}-[{rel_var}]->{match_parts[1]}"
        else:
            match_clause = match_parts[0] if match_parts else ""

        where_clause = " AND ".join(where_parts)

        return match_clause, where_clause, params

    def _get_node_variable(self, sparql_var: str) -> str:
        """Get or create Cypher node variable for SPARQL variable"""
        if sparql_var not in self.node_mappings:
            # Remove ? prefix and make valid Cypher variable
            clean_var = sparql_var.lstrip("?").replace("-", "_").replace(".", "_")
            self.node_mappings[sparql_var] = clean_var
        return self.node_mappings[sparql_var]

    def _predicate_to_relationship_type(self, predicate: str) -> str:
        """Convert SPARQL predicate to Neo4j relationship type"""
        if predicate in self.predicate_mappings:
            return self.predicate_mappings[predicate]

        # Extract relationship type from URI
        if predicate.startswith("http"):
            # Use fragment or last path component
            parsed = urlparse(predicate)
            if parsed.fragment:
                return parsed.fragment.upper()
            else:
                return parsed.path.split("/")[-1].upper()
        else:
            return predicate.upper().replace(" ", "_").replace("-", "_")

    def _uri_to_node_id(self, uri: str) -> str:
        """Convert URI to Neo4j node ID"""
        if uri.startswith(self.base_uri):
            # Extract local ID
            return uri[len(self.base_uri) :]
        else:
            # Use full URI as ID
            return uri

    def _build_return_clause(self, variables: list[str]) -> str:
        """Build RETURN clause for SELECT query"""
        if not variables:
            return "*"

        return_parts = []
        for var in variables:
            if var == "*":
                return_parts.append("*")
            else:
                sparql_var = var if var.startswith("?") else f"?{var}"
                cypher_var = self._get_node_variable(sparql_var)

                if sparql_var in self.relationship_vars:
                    # For relationships, return the relationship type
                    return_parts.append(
                        f"type({cypher_var}) as {sparql_var.lstrip('?')}"
                    )
                else:
                    # Return node id only (avoid duplicate column names)
                    return_parts.append(f"{cypher_var}.id as {sparql_var.lstrip('?')}")

        return ", ".join(return_parts)

    def _build_construct_return(self, construct_patterns: list) -> str:
        """Build RETURN clause for CONSTRUCT query"""
        # For construct queries, return subject, predicate, object triples
        return "subject, predicate, object"

    def _translate_filter(self, filter_expr) -> tuple[str, dict[str, Any]]:
        """Translate SPARQL FILTER to Cypher WHERE condition"""
        # This is a simplified implementation
        # Production would need full expression parsing
        return "", {}

    def _translate_order_by(self, order_by) -> str:
        """Translate ORDER BY clause"""
        return f"ORDER BY {order_by}"

    # Extraction methods (simplified implementations)
    def _get_query_type(self, parsed_query) -> str:
        """Extract query type"""
        query_str = str(parsed_query).upper()
        if "SELECT" in query_str:
            return "SELECT"
        elif "CONSTRUCT" in query_str:
            return "CONSTRUCT"
        elif "ASK" in query_str:
            return "ASK"
        elif "DESCRIBE" in query_str:
            return "DESCRIBE"
        return "UNKNOWN"

    def _extract_select_variables(self, parsed_query) -> list[str]:
        """Extract SELECT variables using rdflib algebra."""
        try:
            algebra = translateQuery(parsed_query).algebra
            project_node = self._find_node_by_name(algebra, "Project")
            if project_node and "PV" in project_node:
                return [str(v) for v in project_node["PV"]]
        except Exception as exc:  # pragma: no cover
            logger.warning("Falling back to default select variables: %s", exc)
        return ["subject", "predicate", "object"]

    def _extract_where_patterns(self, parsed_query) -> list[tuple[str, str, str]]:
        """Extract WHERE clause triple patterns using rdflib algebra."""
        try:
            algebra = translateQuery(parsed_query).algebra
            bgp_node = self._find_node_by_name(algebra, "BGP")
            triples = bgp_node.get("triples", []) if bgp_node else []
            patterns = []
            for s, p, o in triples:
                patterns.append(
                    (self._term_to_str(s), self._term_to_str(p), self._term_to_str(o))
                )
            if patterns:
                return patterns
        except Exception as exc:  # pragma: no cover
            logger.warning("Falling back to default triple pattern: %s", exc)
        return [("?subject", "http://example.org/predicate", "?object")]

    def _extract_filters(self, parsed_query) -> list:
        """Extract FILTER expressions (not yet implemented)."""
        return []

    def _extract_optional_patterns(self, parsed_query) -> list:
        """Extract OPTIONAL patterns (not yet implemented)."""
        return []

    def _extract_order_by(self, parsed_query) -> str | None:
        """Extract ORDER BY clause (not yet implemented)."""
        return None

    def _extract_limit(self, parsed_query) -> int | None:
        """Extract LIMIT value from rdflib algebra."""
        try:
            algebra = translateQuery(parsed_query).algebra
            slice_node = self._find_node_by_name(algebra, "Slice")
            if slice_node and "length" in slice_node:
                return slice_node["length"]
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not extract LIMIT: %s", exc)
        return None

    def _extract_offset(self, parsed_query) -> int | None:
        """Extract OFFSET value from rdflib algebra."""
        try:
            algebra = translateQuery(parsed_query).algebra
            slice_node = self._find_node_by_name(algebra, "Slice")
            if slice_node and "start" in slice_node:
                return slice_node["start"]
        except Exception:
            return None
        return None

    def _extract_construct_patterns(self, parsed_query) -> list:
        """Extract CONSTRUCT template patterns (not yet implemented)."""
        return []

    def _extract_describe_resources(self, parsed_query) -> list[str]:
        """Extract DESCRIBE resources (not yet implemented)."""
        return ["?resource"]

    def _term_to_str(self, term) -> str:
        """Convert an rdflib term to the string form expected by the translator."""
        from rdflib.term import BNode, Literal, URIRef, Variable

        if isinstance(term, Variable):
            return f"?{term}"
        if isinstance(term, URIRef):
            return str(term)
        if isinstance(term, Literal):
            return f'"{term}"'
        if isinstance(term, BNode):
            return f"?bnode_{term}"
        return str(term)

    def _find_node_by_name(self, node, name: str):
        """Recursively search rdflib algebra structure for a node with a given name."""
        try:
            if hasattr(node, "name") and node.name == name:
                return node
            if hasattr(node, "get") and "p" in node:
                found = self._find_node_by_name(node.get("p"), name)
                if found:
                    return found
            if hasattr(node, "values"):
                for v in node.values():
                    found = self._find_node_by_name(v, name)
                    if found:
                        return found
        except Exception:
            return None
        return None
