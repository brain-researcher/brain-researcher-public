"""
Minimal in-memory stand-in for the Neo4j graph database used in unit tests.

The fake implements only the handful of graph operations exercised by
DB-agnostic unit tests.  Anything outside that surface area raises
``NotImplementedError`` so tests do not accidentally rely on behaviours that
require a real backend.
"""

from __future__ import annotations

import collections
import hashlib
import json
from collections.abc import Iterable
from typing import Any


class FakeGraphDB:
    """Lightweight graph helper for unit tests."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._relationships: list[dict[str, Any]] = []
        self._rel_counter = 0

    # ---------------------------------------------------------------------#
    # Supported surface area
    # ---------------------------------------------------------------------#
    def create_node(
        self,
        labels: str | Iterable[str],
        properties: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> str:
        """Create an in-memory node."""
        props: dict[str, Any] = dict(properties or {})
        label_list = list(labels) if not isinstance(labels, str) else [labels]

        if node_id is None:
            if "id" in props:
                node_id = str(props["id"])
            else:
                key_props = {
                    k: v
                    for k, v in props.items()
                    if k in {"name", "pmid", "doi", "concept_id", "x", "y", "z"}
                } or {k: v for k, v in props.items() if k != "labels"}
                digest_input = (
                    f"{'-'.join(label_list)}-{json.dumps(key_props, sort_keys=True)}"
                )
                node_id = hashlib.md5(digest_input.encode()).hexdigest()

        stored = dict(props)
        stored["labels"] = label_list
        self._nodes[node_id] = stored
        return node_id

    def create_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str | bool:
        """Create an in-memory relationship."""
        if start_node not in self._nodes or end_node not in self._nodes:
            return False

        rel_props = dict(properties or {})
        rel_props["type"] = rel_type
        self._rel_counter += 1
        rel_id = f"{start_node}:{rel_type}:{end_node}:{self._rel_counter}"
        self._relationships.append(
            {"id": rel_id, "start": start_node, "end": end_node, "data": rel_props}
        )
        return rel_id

    def find_nodes(
        self,
        labels: str | Iterable[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return nodes matching label/property filters."""
        if isinstance(labels, str):
            label_filter = {labels}
        elif labels is None:
            label_filter = None
        else:
            label_filter = set(labels)

        props = properties or {}
        results: list[tuple[str, dict[str, Any]]] = []
        for node_id, node_data in self._nodes.items():
            node_labels = set(node_data.get("labels", []))
            if label_filter and not (label_filter & node_labels):
                continue

            matches = True
            for key, value in props.items():
                if node_data.get(key) != value:
                    matches = False
                    break
            if matches:
                results.append((node_id, node_data))
        return results

    def find_relationships(
        self,
        start_node: str | None = None,
        end_node: str | None = None,
        rel_type: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Return relationships matching the supplied filters."""
        results: list[tuple[str, str, dict[str, Any]]] = []
        for rel in self._relationships:
            if start_node and rel["start"] != start_node:
                continue
            if end_node and rel["end"] != end_node:
                continue
            if rel_type and rel["data"].get("type") != rel_type:
                continue
            results.append((rel["start"], rel["end"], dict(rel["data"])))
        return results

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        node = self._nodes.get(node_id)
        return dict(node) if node is not None else None

    def commit(self) -> None:
        """Parity with real backends (no-op for in-memory graphs)."""
        return None

    def begin(self) -> None:
        """Parity with real backends (no-op for in-memory graphs)."""
        return None

    def rollback(self) -> None:
        """Parity with real backends (no-op for in-memory graphs)."""
        return None

    def graph_bfs(
        self,
        start_node_id: str,
        depth: int = 2,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Perform a bounded breadth-first traversal."""
        if start_node_id not in self._nodes:
            raise ValueError(f"Node {start_node_id} not found in graph")

        visited: set[str] = set()
        queue: collections.deque[tuple[str, int]] = collections.deque(
            [(start_node_id, 0)]
        )
        edges: list[dict[str, Any]] = []

        while queue:
            current, current_depth = queue.popleft()
            if current in visited or current_depth > depth:
                continue
            visited.add(current)

            if current_depth == depth:
                continue

            for rel in self._relationships:
                if rel["start"] == current:
                    queue.append((rel["end"], current_depth + 1))
                    edges.append(
                        {
                            "start": rel["start"],
                            "end": rel["end"],
                            "type": rel["data"].get("type", "RELATED"),
                            "properties": {
                                k: v for k, v in rel["data"].items() if k != "type"
                            },
                        }
                    )
                elif rel["end"] == current:
                    queue.append((rel["start"], current_depth + 1))
                    edges.append(
                        {
                            "start": rel["start"],
                            "end": rel["end"],
                            "type": rel["data"].get("type", "RELATED"),
                            "properties": {
                                k: v for k, v in rel["data"].items() if k != "type"
                            },
                        }
                    )

        nodes = [
            {
                "id": node_id,
                "labels": self._nodes[node_id].get("labels", []),
                "name": self._nodes[node_id].get("name", node_id),
                "properties": {
                    k: v
                    for k, v in self._nodes[node_id].items()
                    if k not in {"labels", "name"}
                },
            }
            for node_id in visited
        ]

        deduped_edges: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for edge in edges:
            key = (edge["start"], edge["end"], edge["type"])
            if key not in seen:
                seen.add(key)
                deduped_edges.append(edge)

        return nodes, deduped_edges

    # ---------------------------------------------------------------------#
    # Everything else
    # ---------------------------------------------------------------------#
    def __getattr__(self, item: str) -> Any:
        raise NotImplementedError(f"FakeGraphDB does not implement '{item}'")
