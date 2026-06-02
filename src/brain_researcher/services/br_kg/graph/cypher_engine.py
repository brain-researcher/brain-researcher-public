#!/usr/bin/env python3
"""
BR-KG Cypher-like Query Engine

This module implements a Cypher-like query engine for the BR-KG graph database.
"""

import logging
import re
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CypherEngine:
    """
    A Cypher-like query engine for the BR-KG graph database.
    """

    def __init__(self, graph_db):
        """
        Initialize the Cypher engine.

        Args:
            graph_db: BRKGGraphDB instance
        """
        self.graph_db = graph_db
        logger.info("CypherEngine initialized")

    def execute(self, query: str) -> list[dict[str, Any]]:
        """
        Execute a Cypher-like query.

        Args:
            query: Cypher-like query string

        Returns:
            List of result dictionaries
        """
        logger.info(f"Executing query: {query}")

        # Parse the query
        if query.strip().upper().startswith("MATCH"):
            return self._execute_match(query)
        elif query.strip().upper().startswith("CREATE"):
            return self._execute_create(query)
        elif query.strip().upper().startswith("MERGE"):
            return self._execute_merge(query)
        else:
            raise ValueError(f"Unsupported query type: {query}")

    def _execute_match(self, query: str) -> list[dict[str, Any]]:
        """
        Execute a MATCH query.

        Args:
            query: MATCH query string

        Returns:
            List of result dictionaries
        """
        # Simple pattern matching for node patterns like (n:Label {prop: value})
        node_pattern = r"\(([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)\s*({.*?})?\)"

        # Extract node patterns
        node_matches = re.findall(node_pattern, query)

        if not node_matches:
            raise ValueError(f"No valid node patterns found in query: {query}")

        # Process the first node pattern
        var_name, label, props_str = node_matches[0]

        # Parse properties if present
        properties = {}
        if props_str:
            # Simple property parsing (this is a simplified version)
            props_str = props_str.strip("{}")
            if props_str:
                for prop in props_str.split(","):
                    key, value = prop.split(":")
                    key = key.strip()
                    value = value.strip()

                    # Handle string values
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    # Handle numeric values
                    elif value.isdigit():
                        value = int(value)
                    elif value.replace(".", "", 1).isdigit() and value.count(".") <= 1:
                        value = float(value)

                    properties[key] = value

        # Execute the query using the graph database
        nodes = self.graph_db.find_nodes(label, properties)

        # Process RETURN clause
        return_clause = re.search(
            r"RETURN\s+(.+?)(?:$|\s+ORDER BY|\s+LIMIT)", query, re.IGNORECASE
        )
        if not return_clause:
            # Return all properties of matched nodes
            return [{"node": node_id, **node_data} for node_id, node_data in nodes]

        # Parse return items
        return_items = [item.strip() for item in return_clause.group(1).split(",")]

        # Process ORDER BY clause
        order_by = None
        order_by_clause = re.search(
            r"ORDER BY\s+(.+?)(?:$|\s+LIMIT)", query, re.IGNORECASE
        )
        if order_by_clause:
            order_by = order_by_clause.group(1).strip()

        # Process LIMIT clause
        limit = None
        limit_clause = re.search(r"LIMIT\s+(\d+)", query, re.IGNORECASE)
        if limit_clause:
            limit = int(limit_clause.group(1))

        # Prepare results
        results = []
        for node_id, node_data in nodes:
            result = {}
            for item in return_items:
                if item == var_name:
                    result[var_name] = node_id
                elif item.startswith(f"{var_name}."):
                    prop = item.split(".")[1]
                    if prop in node_data:
                        result[item] = node_data[prop]
                    else:
                        result[item] = None
                else:
                    # Handle other return items (simplified)
                    result[item] = None
            results.append(result)

        # Apply ORDER BY
        if order_by:
            # Simple ordering (this is a simplified version)
            field = order_by.split()[0]
            desc = "DESC" in order_by.upper()
            results.sort(key=lambda x: x.get(field, ""), reverse=desc)

        # Apply LIMIT
        if limit is not None:
            results = results[:limit]

        return results

    def _execute_create(self, query: str) -> list[dict[str, Any]]:
        """
        Execute a CREATE query.

        Args:
            query: CREATE query string

        Returns:
            List with a single result dictionary containing the created node/relationship ID
        """
        # Simple pattern matching for node creation like CREATE (n:Label {prop: value})
        node_pattern = r"CREATE\s+\(([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)\s*({.*?})?\)"
        node_match = re.search(node_pattern, query, re.IGNORECASE)

        if node_match:
            var_name, label, props_str = node_match.groups()

            # Parse properties if present
            properties = {}
            if props_str:
                # Simple property parsing (this is a simplified version)
                props_str = props_str.strip("{}")
                if props_str:
                    for prop in props_str.split(","):
                        key, value = prop.split(":")
                        key = key.strip()
                        value = value.strip()

                        # Handle string values
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        # Handle numeric values
                        elif value.isdigit():
                            value = int(value)
                        elif (
                            value.replace(".", "", 1).isdigit()
                            and value.count(".") <= 1
                        ):
                            value = float(value)

                        properties[key] = value

            # Create the node
            node_id = self.graph_db.create_node(label, properties)
            return [{"node_id": node_id}]

        # Simple pattern matching for relationship creation
        rel_pattern = r"CREATE\s+\(([a-zA-Z0-9_]+)\)-\[([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)\s*({.*?})?\]->\(([a-zA-Z0-9_]+)\)"
        rel_match = re.search(rel_pattern, query, re.IGNORECASE)

        if rel_match:
            start_var, rel_var, rel_type, props_str, end_var = rel_match.groups()

            # For simplicity, assume start_var and end_var are node IDs
            start_node = start_var
            end_node = end_var

            # Parse properties if present
            properties = {}
            if props_str:
                # Simple property parsing (this is a simplified version)
                props_str = props_str.strip("{}")
                if props_str:
                    for prop in props_str.split(","):
                        key, value = prop.split(":")
                        key = key.strip()
                        value = value.strip()

                        # Handle string values
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        # Handle numeric values
                        elif value.isdigit():
                            value = int(value)
                        elif (
                            value.replace(".", "", 1).isdigit()
                            and value.count(".") <= 1
                        ):
                            value = float(value)

                        properties[key] = value

            # Create the relationship
            rel_id = self.graph_db.create_relationship(
                start_node, end_node, rel_type, properties
            )
            return [{"relationship_id": rel_id}]

        raise ValueError(f"Invalid CREATE query format: {query}")

    def _execute_merge(self, query: str) -> list[dict[str, Any]]:
        """
        Execute a MERGE query.

        Args:
            query: MERGE query string

        Returns:
            List with a single result dictionary containing the merged node/relationship ID
        """
        # Simple pattern matching for node merging like MERGE (n:Label {prop: value})
        node_pattern = r"MERGE\s+\(([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)\s*({.*?})?\)"
        node_match = re.search(node_pattern, query, re.IGNORECASE)

        if node_match:
            var_name, label, props_str = node_match.groups()

            # Parse properties if present
            properties = {}
            if props_str:
                # Simple property parsing (this is a simplified version)
                props_str = props_str.strip("{}")
                if props_str:
                    for prop in props_str.split(","):
                        key, value = prop.split(":")
                        key = key.strip()
                        value = value.strip()

                        # Handle string values
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        # Handle numeric values
                        elif value.isdigit():
                            value = int(value)
                        elif (
                            value.replace(".", "", 1).isdigit()
                            and value.count(".") <= 1
                        ):
                            value = float(value)

                        properties[key] = value

            # Try to find the node first
            nodes = self.graph_db.find_nodes(label, properties)

            if nodes:
                # Node exists, return its ID
                node_id, _ = nodes[0]
                return [{"node_id": node_id, "created": False}]
            else:
                # Node doesn't exist, create it
                node_id = self.graph_db.create_node(label, properties)
                return [{"node_id": node_id, "created": True}]

        raise ValueError(f"Invalid MERGE query format: {query}")
