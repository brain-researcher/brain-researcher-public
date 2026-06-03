"""
Enhanced Search API with Natural Language Processing

This module extends the graph API with smart search capabilities,
including NL query parsing, summarization, and similarity search.
"""

import logging
from typing import Any

from flask import Flask, jsonify, request

from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB
from brain_researcher.services.br_kg.utils.nl_query_parser import NLQueryParser

logger = logging.getLogger(__name__)


class EnhancedSearchAPI:
    """Enhanced search functionality for BR-KG."""

    def __init__(self, db: BRKGGraphDB):
        self.db = db
        self.parser = NLQueryParser()

    def smart_search(self, query: str, limit: int = 100) -> dict[str, Any]:
        """
        Perform smart search with natural language understanding.

        Args:
            query: Natural language query
            limit: Maximum results to return

        Returns:
            Search results with parsed filters and transparency info
        """
        # Parse the natural language query
        parsed = self.parser.parse(query)

        # Execute the generated Cypher query
        try:
            # Get nodes from the Cypher query
            nodes = self._execute_cypher_search(parsed["cypher"])

            # Format results
            results = {
                "query": query,
                "parsed": {
                    "entity_type": parsed["entity_type"],
                    "filters": parsed["filters"],
                    "date_range": parsed["date_range"],
                    "confidence": parsed["confidence"],
                    "summary": parsed["parsed_entities"],
                },
                "cypher": parsed["cypher"],
                "results": nodes[:limit],
                "total_count": len(nodes),
                "displayed_count": min(len(nodes), limit),
            }

            return results

        except Exception as e:
            logger.error(f"Search execution error: {str(e)}")

            # Return parse info even if query fails
            return {
                "query": query,
                "parsed": parsed,
                "cypher": parsed["cypher"],
                "error": str(e),
                "results": [],
                "total_count": 0,
                "displayed_count": 0,
            }

    def _execute_cypher_search(self, cypher: str) -> list[dict[str, Any]]:
        """Execute Cypher query and return formatted results."""
        # This is a simplified version - in production, you'd execute actual Cypher
        # For now, we'll use the existing find_nodes method

        results = []

        # Parse the Cypher to extract node type (simplified)
        if "Study" in cypher:
            nodes = self.db.find_nodes(labels="Study")
        elif "Author" in cypher:
            nodes = self.db.find_nodes(labels="Author")
        elif "Concept" in cypher:
            nodes = self.db.find_nodes(labels="Concept")
        elif "Task" in cypher:
            nodes = self.db.find_nodes(labels="Task")
        elif "BrainRegion" in cypher:
            nodes = self.db.find_nodes(labels="BrainRegion")
        elif "Dataset" in cypher:
            nodes = self.db.find_nodes(labels="Dataset")
        else:
            nodes = []

        # Format nodes for response
        for node_id, node_data in nodes[:100]:  # Limit for performance
            formatted_node = {
                "id": node_id,
                "type": (
                    node_data.get("labels", ["Unknown"])[0]
                    if "labels" in node_data
                    else "Unknown"
                ),
                "properties": {k: v for k, v in node_data.items() if k != "labels"},
            }

            # Add display name
            if "name" in node_data:
                formatted_node["display_name"] = node_data["name"]
            elif "title" in node_data:
                formatted_node["display_name"] = node_data["title"]
            elif "pmid" in node_data:
                formatted_node["display_name"] = f"Study PMID: {node_data['pmid']}"
            else:
                formatted_node["display_name"] = node_id

            results.append(formatted_node)

        return results

    def summarize_selection(
        self, node_ids: list[str], max_length: int = 500
    ) -> dict[str, Any]:
        """
        Generate a summary of selected nodes.

        Args:
            node_ids: List of node IDs to summarize
            max_length: Maximum summary length

        Returns:
            Summary information
        """
        if not node_ids:
            return {"summary": "No nodes selected", "node_count": 0}

        # Fetch node data
        nodes_data = []
        node_types = {}

        for node_id in node_ids[:50]:  # Limit to prevent overload
            # Find node in graph
            if node_id in self.db.graph.nodes:
                node_data = self.db.graph.nodes[node_id]
                nodes_data.append(node_data)

                # Count node types
                node_type = (
                    node_data.get("labels", ["Unknown"])[0]
                    if "labels" in node_data
                    else "Unknown"
                )
                node_types[node_type] = node_types.get(node_type, 0) + 1

        # Generate summary based on node types
        summary_parts = []

        # Type distribution
        type_summary = ", ".join(
            [
                f"{count} {type}{'s' if count > 1 else ''}"
                for type, count in node_types.items()
            ]
        )
        summary_parts.append(f"Selected {len(nodes_data)} nodes: {type_summary}")

        # Content summary by type
        if "Study" in node_types:
            study_summaries = self._summarize_studies(nodes_data)
            if study_summaries:
                summary_parts.append(f"Studies focus on: {study_summaries}")

        if "Concept" in node_types:
            concept_names = [
                n.get("name", "")
                for n in nodes_data
                if "Concept" in n.get("labels", [])
            ][:10]
            if concept_names:
                summary_parts.append(f"Concepts: {', '.join(concept_names)}")

        if "BrainRegion" in node_types:
            region_names = [
                n.get("name", "")
                for n in nodes_data
                if "BrainRegion" in n.get("labels", [])
            ][:10]
            if region_names:
                summary_parts.append(f"Brain regions: {', '.join(region_names)}")

        if "Task" in node_types:
            task_names = [
                n.get("name", "") for n in nodes_data if "Task" in n.get("labels", [])
            ][:10]
            if task_names:
                summary_parts.append(f"Tasks: {', '.join(task_names)}")

        # Combine summary
        full_summary = ". ".join(summary_parts)

        # Truncate if needed
        if len(full_summary) > max_length:
            full_summary = full_summary[: max_length - 3] + "..."

        return {
            "summary": full_summary,
            "node_count": len(nodes_data),
            "node_types": node_types,
            "node_ids": node_ids[:50],  # Return truncated list
        }

    def _summarize_studies(self, nodes_data: list[dict]) -> str:
        """Extract key themes from study nodes."""
        studies = [n for n in nodes_data if "Study" in n.get("labels", [])]

        if not studies:
            return ""

        # Extract key terms from titles and abstracts
        term_counts = {}

        for study in studies[:20]:  # Limit for performance
            title = study.get("title", "")
            abstract = study.get("abstract", "")

            # Simple keyword extraction (could be enhanced with NLP)
            text = f"{title} {abstract}".lower()

            # Look for neuroscience terms
            neuro_terms = [
                "memory",
                "attention",
                "emotion",
                "language",
                "perception",
                "motor",
                "executive",
                "learning",
                "fmri",
                "neuroimaging",
                "cortex",
                "activation",
                "connectivity",
                "network",
            ]

            for term in neuro_terms:
                if term in text:
                    term_counts[term] = term_counts.get(term, 0) + 1

        # Get top terms
        top_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        if top_terms:
            return ", ".join([term for term, count in top_terms])
        else:
            return "various neuroscience topics"

    def find_similar(self, node_id: str, limit: int = 20) -> dict[str, Any]:
        """
        Find nodes similar to a given node.

        Args:
            node_id: ID of the reference node
            limit: Maximum similar nodes to return

        Returns:
            Similar nodes with similarity scores
        """
        if node_id not in self.db.graph.nodes:
            return {"error": "Node not found", "node_id": node_id, "similar_nodes": []}

        # Get reference node
        ref_node = self.db.graph.nodes[node_id]
        ref_type = (
            ref_node.get("labels", ["Unknown"])[0]
            if "labels" in ref_node
            else "Unknown"
        )

        # Get connected nodes (1-hop neighbors)
        neighbors = list(self.db.graph.neighbors(node_id))

        # Find nodes of the same type
        same_type_nodes = []
        all_nodes = self.db.find_nodes(labels=ref_type)

        for other_id, other_data in all_nodes[:100]:  # Limit search
            if other_id != node_id:
                # Calculate simple similarity based on shared neighbors
                other_neighbors = set(self.db.graph.neighbors(other_id))
                shared_neighbors = set(neighbors).intersection(other_neighbors)

                if shared_neighbors:
                    similarity = len(shared_neighbors) / (
                        len(neighbors) + len(other_neighbors) - len(shared_neighbors)
                    )
                    same_type_nodes.append(
                        {
                            "node": {
                                "id": other_id,
                                "type": ref_type,
                                "properties": other_data,
                            },
                            "similarity": similarity,
                            "shared_connections": len(shared_neighbors),
                        }
                    )

        # Sort by similarity
        same_type_nodes.sort(key=lambda x: x["similarity"], reverse=True)

        return {
            "reference_node": {"id": node_id, "type": ref_type, "properties": ref_node},
            "similar_nodes": same_type_nodes[:limit],
            "total_found": len(same_type_nodes),
        }


def register_enhanced_search_endpoints(app: Flask, db: BRKGGraphDB):
    """Register enhanced search endpoints with the Flask app."""

    search_api = EnhancedSearchAPI(db)

    @app.route("/api/search/smart", methods=["POST", "GET"])
    def smart_search():
        """Smart search with natural language understanding."""
        if request.method == "POST":
            data = request.get_json()
            query = data.get("query", "")
            limit = data.get("limit", 100)
        else:
            query = request.args.get("q", "")
            limit = int(request.args.get("limit", 100))

        if not query:
            return jsonify({"error": "Query is required"}), 400

        results = search_api.smart_search(query, limit)
        return jsonify(results)

    @app.route("/api/summarize", methods=["POST"])
    def summarize_selection():
        """Summarize selected nodes."""
        data = request.get_json()
        node_ids = data.get("node_ids", [])
        max_length = data.get("max_length", 500)

        if not node_ids:
            return jsonify({"error": "node_ids are required"}), 400

        summary = search_api.summarize_selection(node_ids, max_length)
        return jsonify(summary)

    @app.route("/api/similar/<node_id>", methods=["GET"])
    def find_similar(node_id: str):
        """Find nodes similar to the given node."""
        limit = int(request.args.get("limit", 20))

        similar = search_api.find_similar(node_id, limit)
        return jsonify(similar)

    @app.route("/api/parse", methods=["POST"])
    def parse_query():
        """Parse natural language query without executing (for transparency)."""
        data = request.get_json()
        query = data.get("query", "")

        if not query:
            return jsonify({"error": "Query is required"}), 400

        parsed = search_api.parser.parse(query)
        return jsonify(parsed)

    # Add endpoint documentation
    @app.route("/api/search/help", methods=["GET"])
    def search_help():
        """Return search help and examples."""
        return jsonify(
            {
                "endpoints": {
                    "/api/search/smart": "Smart search with natural language",
                    "/api/summarize": "Summarize selected nodes",
                    "/api/similar/<node_id>": "Find similar nodes",
                    "/api/parse": "Parse query without executing",
                },
                "examples": {
                    "natural_language": [
                        "working memory papers in frontal cortex from 2020-2023",
                        "recent studies on attention and stroop task",
                        "papers by Smith about emotion in amygdala",
                        "brain regions involved in language processing",
                    ],
                    "filters_extracted": [
                        "Concepts: working memory, attention, emotion",
                        "Brain regions: frontal cortex, amygdala",
                        "Tasks: stroop, n-back",
                        "Date ranges: 2020-2023, last 5 years",
                    ],
                },
                "response_format": {
                    "smart_search": {
                        "query": "original query",
                        "parsed": {
                            "entity_type": "papers|authors|datasets|etc",
                            "filters": {"concepts": [], "regions": [], "tasks": []},
                            "date_range": [2020, 2023],
                            "confidence": 0.85,
                        },
                        "cypher": "generated Cypher query",
                        "results": [],
                    }
                },
            }
        )


# Example usage
if __name__ == "__main__":
    # Test the parser
    parser = NLQueryParser()
    test_query = "working memory studies in prefrontal cortex from last 5 years"
    result = parser.parse(test_query)
    print(f"Parsed: {result}")
