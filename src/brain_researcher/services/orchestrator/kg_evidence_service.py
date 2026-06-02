"""
BR-KG Evidence Service - Query knowledge graph for demo-related evidence
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default BR-KG service URL
DEFAULT_BR_KG_URL = os.getenv("BR_KG_URL", "http://localhost:5000")


@dataclass
class Evidence:
    """Evidence item from knowledge graph"""

    type: str  # 'paper', 'dataset', 'statmap', 'coordinate'
    title: str
    description: str
    source: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class Citation:
    """Citation reference"""

    id: str
    title: str
    authors: List[str]
    year: int
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None


class KGEvidenceService:
    """
    Service to query BR-KG for demo-related evidence.

    This service:
    1. Queries BR-KG based on demo metadata (task, dataset, contrast)
    2. Retrieves related papers, datasets, and statistical maps
    3. Formats results as Evidence objects
    """

    def __init__(self, br_kg_url: str = DEFAULT_BR_KG_URL, timeout: float = 10.0):
        """
        Initialize KG Evidence Service.

        Args:
            br_kg_url: Base URL for BR-KG service
            timeout: HTTP request timeout in seconds
        """
        self.br_kg_url = br_kg_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    def _build_search_url(self) -> str:
        """Return the correct search endpoint for a mounted or direct BR-KG base."""
        if self.br_kg_url.endswith("/api/kg"):
            return f"{self.br_kg_url}/search"
        return f"{self.br_kg_url}/api/kg/search"

    def _build_concept_evidence_url(self, concept_id: str) -> str:
        if self.br_kg_url.endswith("/api/kg"):
            return f"{self.br_kg_url}/concept/{concept_id}/evidence"
        return f"{self.br_kg_url}/api/kg/concept/{concept_id}/evidence"

    async def get_demo_evidence(
        self, demo_id: str, demo_config: Dict[str, Any], limit: int = 10
    ) -> List[Evidence]:
        """
        Get evidence for a demo from the knowledge graph.

        Args:
            demo_id: Demo identifier
            demo_config: Demo configuration from demo_map.yaml
            limit: Maximum number of evidence items to return

        Returns:
            List of Evidence objects
        """
        try:
            # Build search query from demo metadata
            query = self._build_search_query(demo_config)

            logger.info(f"Querying BR-KG for demo '{demo_id}' with query: {query}")

            # Search for relevant concepts/nodes
            search_results = await self._search_kg(query, limit=limit)

            # Convert search results to Evidence objects
            evidence_items = self._format_evidence(search_results, demo_config)

            logger.info(
                f"Found {len(evidence_items)} evidence items for demo '{demo_id}'"
            )

            return evidence_items[:limit]

        except Exception as e:
            logger.error(f"Failed to get evidence for demo '{demo_id}': {e}")
            # Return empty list on error (graceful degradation)
            return []

    def _build_search_query(self, demo_config: Dict[str, Any]) -> str:
        """
        Build search query from demo configuration.

        Combines task, dataset, and other metadata into a search string.
        """
        query_parts = []

        # Add task
        if "task" in demo_config:
            task = demo_config["task"]
            # Clean up task name (remove dashes, camelCase)
            task_clean = task.replace("-", " ").replace("_", " ")
            query_parts.append(task_clean)

        # Add dataset ID
        if "dataset_id" in demo_config:
            query_parts.append(demo_config["dataset_id"])

        # Add analysis type if specified
        if "analysis_type" in demo_config:
            query_parts.append(demo_config["analysis_type"])

        # Fallback to title keywords
        if not query_parts and "title" in demo_config:
            # Extract key terms from title
            title = demo_config["title"]
            keywords = [
                word
                for word in title.split()
                if len(word) > 3 and word.lower() not in {"analysis", "task", "data"}
            ]
            query_parts.extend(keywords[:3])

        return " ".join(query_parts)

    async def _search_kg(
        self, query: str, limit: int = 10, node_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph via /api/search endpoint.

        Args:
            query: Search query string
            limit: Maximum results
            node_types: Optional list of node types to search

        Returns:
            List of search result dictionaries
        """
        try:
            url = self._build_search_url()

            payload = {"query": query, "limit": limit}

            if node_types:
                payload["node_types"] = node_types

            response = await self.client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            return data

        except httpx.HTTPError as e:
            logger.warning(f"BR-KG search failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in KG search: {e}")
            return []

    async def get_concept_evidence(
        self,
        concept_id: str,
        evidence_types: str = "papers,datasets,statmaps",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Get evidence for a specific concept from /concept/<id>/evidence endpoint.

        Args:
            concept_id: Concept identifier
            evidence_types: Comma-separated list of evidence types
            limit: Maximum results per type

        Returns:
            Dictionary with evidence grouped by type
        """
        try:
            url = self._build_concept_evidence_url(concept_id)

            params = {"types": evidence_types, "limit": limit}

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.warning(f"Failed to get concept evidence for '{concept_id}': {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error getting concept evidence: {e}")
            return {}

    def _format_evidence(
        self, search_results: List[Dict[str, Any]], demo_config: Dict[str, Any]
    ) -> List[Evidence]:
        """
        Convert KG search results to Evidence objects.

        Args:
            search_results: Raw search results from BR-KG
            demo_config: Demo configuration for context

        Returns:
            List of formatted Evidence objects
        """
        evidence_items = []

        for result in search_results:
            node_type = result.get("node_type", "unknown")
            properties = result.get("properties", {})
            matched_fields = result.get("matched_fields", [])
            score = result.get("score", 0.0)

            # Format based on node type
            if node_type == "Paper":
                evidence = Evidence(
                    type="paper",
                    title=properties.get("title", "Untitled Paper"),
                    description=(
                        properties.get("abstract", "")[:200] + "..."
                        if properties.get("abstract")
                        else ""
                    ),
                    source=properties.get("journal", "Unknown Journal"),
                    url=properties.get("url") or properties.get("doi"),
                    metadata={
                        "authors": properties.get("authors", []),
                        "year": properties.get("year"),
                        "doi": properties.get("doi"),
                        "score": score,
                        "matched_fields": matched_fields,
                    },
                )
                evidence_items.append(evidence)

            elif node_type == "Dataset":
                evidence = Evidence(
                    type="dataset",
                    title=properties.get("name", "Unnamed Dataset"),
                    description=(
                        properties.get("description", "")[:200] + "..."
                        if properties.get("description")
                        else ""
                    ),
                    source=f"Dataset {properties.get('id', '')}",
                    url=properties.get("url"),
                    metadata={
                        "n_subjects": properties.get("n_subjects"),
                        "tasks": properties.get("tasks", []),
                        "modalities": properties.get("modalities", []),
                        "score": score,
                        "matched_fields": matched_fields,
                    },
                )
                evidence_items.append(evidence)

            elif node_type == "StatMap":
                evidence = Evidence(
                    type="statmap",
                    title=f"Statistical Map: {properties.get('contrast', 'Unknown Contrast')}",
                    description=f"Brain activation map in {properties.get('space', 'unknown')} space",
                    source=properties.get("source", "NeuroVault"),
                    url=properties.get("url"),
                    metadata={
                        "contrast": properties.get("contrast"),
                        "space": properties.get("space"),
                        "atlas": properties.get("atlas"),
                        "score": score,
                        "matched_fields": matched_fields,
                    },
                )
                evidence_items.append(evidence)

            elif node_type == "Concept":
                evidence = Evidence(
                    type="concept",
                    title=properties.get("label", "Unknown Concept"),
                    description=(
                        properties.get("definition", "")[:200] + "..."
                        if properties.get("definition")
                        else ""
                    ),
                    source="Cognitive Atlas / ONVOC",
                    url=properties.get("url"),
                    metadata={
                        "id": properties.get("id"),
                        "scheme": properties.get("scheme"),
                        "score": score,
                        "matched_fields": matched_fields,
                    },
                )
                evidence_items.append(evidence)

        # Sort by relevance score
        evidence_items.sort(key=lambda x: x.metadata.get("score", 0.0), reverse=True)

        return evidence_items

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
