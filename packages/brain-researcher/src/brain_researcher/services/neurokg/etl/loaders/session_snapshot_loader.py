"""Load Brain Researcher session snapshots into BR-KG."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from brain_researcher.services.mcp.session_lessons import (
    SESSION_KG_NODE_LABELS,
    SESSION_KG_QUERY_EXAMPLES,
    SESSION_KG_RELATIONSHIP_TYPES,
    build_session_kg_rows,
)

LOADER_VERSION = "session_snapshot_loader.v1"


@dataclass
class SessionSnapshotLoadStats:
    """Counts and errors from one session-snapshot KG load."""

    sessions_seen: int = 0
    nodes_written: int = 0
    relationships_written: int = 0
    skipped_relationships: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions_seen": self.sessions_seen,
            "nodes_written": self.nodes_written,
            "relationships_written": self.relationships_written,
            "skipped_relationships": self.skipped_relationships,
            "error_count": len(self.errors),
            "errors": self.errors,
        }


def build_session_snapshot_graph_payload(
    digests: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Normalize one or more session digests into de-duplicated KG rows."""

    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for digest in digests:
        graph = build_session_kg_rows(digest)
        for node in graph["nodes"]:
            node_id = str(node.get("id") or "")
            if not node_id:
                continue
            existing = nodes_by_id.get(node_id)
            if existing is None:
                nodes_by_id[node_id] = node
                continue
            merged_props = {
                **dict(existing.get("properties") or {}),
                **dict(node.get("properties") or {}),
            }
            existing["properties"] = merged_props
        for edge in graph["edges"]:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            edge_type = str(edge.get("type") or "")
            props = dict(edge.get("properties") or {})
            prop_key = json.dumps(props, sort_keys=True, default=str)
            edges_by_key[(source, edge_type, target, prop_key)] = edge
    return {"nodes": list(nodes_by_id.values()), "edges": list(edges_by_key.values())}


def validate_session_graph_payload(
    graph: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    """Return endpoint errors that would prevent relationship creation."""

    node_ids = {str(node.get("id") or "") for node in graph.get("nodes", [])}
    errors: list[dict[str, str]] = []
    for edge in graph.get("edges", []):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        edge_type = str(edge.get("type") or "")
        if source not in node_ids:
            errors.append({"edge_type": edge_type, "missing_source": source})
        if target not in node_ids:
            errors.append({"edge_type": edge_type, "missing_target": target})
    return errors


def load_session_graph_payload(
    db: Any,
    graph: dict[str, list[dict[str, Any]]],
    *,
    sessions_seen: int = 0,
) -> SessionSnapshotLoadStats:
    """Write normalized session graph rows to a graph DB handle."""

    stats = SessionSnapshotLoadStats(sessions_seen=sessions_seen)
    node_ids: set[str] = set()
    for node in graph.get("nodes", []):
        node_id = str(node.get("id") or "")
        labels = list(node.get("labels") or [])
        if not node_id or not labels:
            stats.errors.append({"error": "invalid_node", "node_id": node_id})
            continue
        props = dict(node.get("properties") or {})
        props["id"] = node_id
        props.setdefault("kg_source", "research_logging")
        props.setdefault("loader_version", LOADER_VERSION)
        db.create_node(labels, props, node_id=node_id)
        node_ids.add(node_id)
        stats.nodes_written += 1

    for edge in graph.get("edges", []):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        edge_type = str(edge.get("type") or "")
        if source not in node_ids or target not in node_ids:
            stats.skipped_relationships += 1
            stats.errors.append(
                {
                    "error": "missing_endpoint",
                    "source": source,
                    "target": target,
                    "type": edge_type,
                }
            )
            continue
        props = dict(edge.get("properties") or {})
        props.setdefault("kg_source", "research_logging")
        props.setdefault("loader_version", LOADER_VERSION)
        created = db.create_relationship(source, target, edge_type, props)
        if created:
            stats.relationships_written += 1
        else:
            stats.skipped_relationships += 1
            stats.errors.append(
                {
                    "error": "relationship_not_created",
                    "source": source,
                    "target": target,
                    "type": edge_type,
                }
            )

    commit = getattr(db, "commit", None)
    if callable(commit):
        commit()
    return stats


def load_session_digests(
    db: Any,
    digests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build and write session KG rows, returning a structured summary."""

    graph = build_session_snapshot_graph_payload(digests)
    endpoint_errors = validate_session_graph_payload(graph)
    if endpoint_errors:
        return {
            "ok": False,
            "error": "invalid_session_graph_payload",
            "endpoint_errors": endpoint_errors,
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        }
    stats = load_session_graph_payload(db, graph, sessions_seen=len(digests))
    return {
        "ok": len(stats.errors) == 0,
        "stats": stats.to_dict(),
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "node_labels": list(SESSION_KG_NODE_LABELS),
        "relationship_types": list(SESSION_KG_RELATIONSHIP_TYPES),
        "query_examples": list(SESSION_KG_QUERY_EXAMPLES),
    }
