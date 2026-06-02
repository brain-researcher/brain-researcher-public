from __future__ import annotations

from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


class _GraphView:
    def __init__(self, nodes: dict[str, dict[str, object]]) -> None:
        self.nodes = nodes


class UnitGraphDB(FakeGraphDB):
    """Small in-memory graph stub for DB-agnostic BR-KG unit tests."""

    def __init__(self) -> None:
        super().__init__()
        self.graph = _GraphView(self._nodes)

    def get_stats(self) -> dict[str, object]:
        node_labels: dict[str, int] = {}
        for node_data in self._nodes.values():
            for label in node_data.get("labels", []):
                node_labels[label] = node_labels.get(label, 0) + 1

        relationship_types: dict[str, int] = {}
        for rel in self._relationships:
            rel_type = str(rel["data"].get("type"))
            relationship_types[rel_type] = relationship_types.get(rel_type, 0) + 1

        return {
            "total_nodes": len(self._nodes),
            "total_relationships": len(self._relationships),
            "node_labels": node_labels,
            "relationship_types": relationship_types,
        }

    def close(self) -> None:
        return None
