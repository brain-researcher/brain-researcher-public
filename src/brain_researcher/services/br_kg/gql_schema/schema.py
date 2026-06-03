"""
Strawberry GraphQL schema for BR-KG.

Notes
- Imports of `strawberry` are deferred inside functions to avoid hard
  dependency at import time for environments not using GraphQL.
- Resolvers use the existing DB helper selection from seed_neo4j.get_db.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from brain_researcher.services.br_kg.db.bootstrap import get_db


# ----------------------
# Internal model helpers
# ----------------------
@dataclass
class Node:
    id: str
    labels: list[str]
    properties: dict[str, Any]


def _db():
    return get_db()


def _find_nodes_by_label_and_prop(
    label: str, prop: str | None = None, value: Any = None
) -> list[Node]:
    db = _db()
    props = {prop: value} if prop is not None else None
    out: list[Node] = []
    for nid, p in db.find_nodes(label, props):  # type: ignore[attr-defined]
        labels = p.get("labels") or ([label] if label else [])
        out.append(
            Node(
                id=str(nid),
                labels=list(labels),
                properties={k: v for k, v in p.items() if k not in {"id", "labels"}},
            )
        )
    return out


def _find_nodes_by_label_and_prop_in(
    label: str, prop: str, values: list[Any]
) -> list[Node]:
    out: list[Node] = []
    if not values:
        return out
    db = _db()
    for val in values:
        for nid, p in db.find_nodes(label, {prop: val}):  # type: ignore[attr-defined]
            labels = p.get("labels") or ([label] if label else [])
            out.append(
                Node(
                    id=str(nid),
                    labels=list(labels),
                    properties={
                        k: v for k, v in p.items() if k not in {"id", "labels"}
                    },
                )
            )
    return out


def _find_node_by_id(nid: str) -> Node | None:
    db = _db()
    matches = db.find_nodes(None, {"id": nid})  # type: ignore[attr-defined]
    if not matches:
        return None
    _, p = matches[0]
    labels = p.get("labels", [])
    return Node(
        id=nid,
        labels=list(labels),
        properties={k: v for k, v in p.items() if k not in {"id", "labels"}},
    )


def _bfs(start_id: str, depth: int = 2) -> tuple[list[Node], list[dict[str, Any]]]:
    db = _db()
    if hasattr(db, "graph_bfs"):
        nodes, edges = db.graph_bfs(start_id, depth)  # type: ignore[attr-defined]
        return [Node(**n) for n in nodes], edges
    # Fallback: shallow expansion using relationships helper if available
    nodes: list[Node] = []
    edges: list[dict[str, Any]] = []
    center = _find_node_by_id(start_id)
    if center:
        nodes.append(center)
    if hasattr(db, "find_relationships"):
        for a, b, rp in db.find_relationships(start_id, None, None):  # type: ignore[attr-defined]
            edges.append(
                {"start": a, "end": b, "type": rp.get("type", ""), "properties": rp}
            )
            n = _find_node_by_id(b)
            if n:
                nodes.append(n)
        for a, b, rp in db.find_relationships(None, start_id, None):  # type: ignore[attr-defined]
            edges.append(
                {"start": a, "end": b, "type": rp.get("type", ""), "properties": rp}
            )
            n = _find_node_by_id(a)
            if n:
                nodes.append(n)
    return nodes, edges


# -----------------
# Schema definition
# -----------------
def build_schema() -> Any:
    try:
        import strawberry
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "strawberry-graphql is required for the GraphQL API. Install strawberry-graphql to enable."
        ) from exc

    @strawberry.type
    class KVPair:
        key: str
        value: str  # Simplified to string for now

    def to_kv(props: dict[str, Any]) -> list[KVPair]:
        return [KVPair(key=str(k), value=str(v)) for k, v in props.items()]

    @strawberry.type
    class GNode:
        id: str
        labels: list[str]
        properties: list[KVPair]

    @strawberry.type
    class GEdge:
        start: str
        end: str
        type: str
        properties: list[KVPair]

    @strawberry.type
    class Graph:
        nodes: list[GNode]
        edges: list[GEdge]

    # Specific node types (minimal shape)
    @strawberry.type
    class Concept:
        id: str
        name: str | None

    @strawberry.type
    class Task:
        id: str
        name: str | None

    @strawberry.type
    class Region:
        id: str
        name: str | None
        abbreviation: str | None

    @strawberry.type
    class Dataset:
        id: str
        name: str | None
        accession: str | None

    @strawberry.type
    class Publication:
        id: str
        pmid: str | None
        title: str | None
        abstract: str | None
        concepts: list[str] | None

    def _as_typed(label: str, n: Node):
        p = n.properties
        if label == "Concept":
            return Concept(id=n.id, name=p.get("name"))
        if label == "Task":
            return Task(id=n.id, name=p.get("name"))
        if label == "Region":
            return Region(
                id=n.id, name=p.get("name"), abbreviation=p.get("abbreviation")
            )
        if label == "Dataset":
            return Dataset(id=n.id, name=p.get("name"), accession=p.get("accession"))
        if label == "Publication":
            return Publication(
                id=n.id,
                pmid=p.get("pmid"),
                title=p.get("title"),
                abstract=p.get("abstract"),
                concepts=p.get("concepts"),
            )
        return None

    # -----------------
    # Query root
    # -----------------
    @strawberry.type
    class Query:
        @strawberry.field
        def node_by_id(self, id: str) -> GNode | None:
            n = _find_node_by_id(id)
            if not n:
                return None
            return GNode(id=n.id, labels=n.labels, properties=to_kv(n.properties))

        @strawberry.field
        def concepts(self, name: str | None = None) -> list[Concept]:
            if name:
                nodes = _find_nodes_by_label_and_prop("Concept", "name", name)
            else:
                nodes = _find_nodes_by_label_and_prop("Concept")
            return [Concept(id=n.id, name=n.properties.get("name")) for n in nodes]

        @strawberry.field
        def tasks(self, name: str | None = None) -> list[Task]:
            nodes = (
                _find_nodes_by_label_and_prop("Task", "name", name)
                if name
                else _find_nodes_by_label_and_prop("Task")
            )
            return [Task(id=n.id, name=n.properties.get("name")) for n in nodes]

        @strawberry.field
        def regions(self, name: str | None = None) -> list[Region]:
            nodes = (
                _find_nodes_by_label_and_prop("Region", "name", name)
                if name
                else _find_nodes_by_label_and_prop("Region")
            )
            return [
                Region(
                    id=n.id,
                    name=n.properties.get("name"),
                    abbreviation=n.properties.get("abbreviation"),
                )
                for n in nodes
            ]

        @strawberry.field
        def datasets(self, accession: str | None = None) -> list[Dataset]:
            nodes = (
                _find_nodes_by_label_and_prop("Dataset", "accession", accession)
                if accession
                else _find_nodes_by_label_and_prop("Dataset")
            )
            return [
                Dataset(
                    id=n.id,
                    name=n.properties.get("name"),
                    accession=n.properties.get("accession"),
                )
                for n in nodes
            ]

        @strawberry.field
        def publications(self, pmid: str | None = None) -> list[Publication]:
            nodes = (
                _find_nodes_by_label_and_prop("Publication", "pmid", pmid)
                if pmid
                else _find_nodes_by_label_and_prop("Publication")
            )
            return [
                Publication(
                    id=n.id,
                    pmid=n.properties.get("pmid"),
                    title=n.properties.get("title"),
                    abstract=n.properties.get("abstract"),
                    concepts=n.properties.get("concepts"),
                )
                for n in nodes
            ]

        @strawberry.field
        def publications_by_pmids(self, pmids: list[str]) -> list[Publication]:
            nodes = _find_nodes_by_label_and_prop_in("Publication", "pmid", pmids)
            return [
                Publication(
                    id=n.id,
                    pmid=n.properties.get("pmid"),
                    title=n.properties.get("title"),
                    abstract=n.properties.get("abstract"),
                    concepts=n.properties.get("concepts"),
                )
                for n in nodes
            ]

        @strawberry.field
        def bfs(self, start_id: str, depth: int = 2) -> Graph:
            nodes, edges = _bfs(start_id, depth)
            gnodes = [
                GNode(id=n.id, labels=n.labels, properties=to_kv(n.properties))
                for n in nodes
            ]
            gedges = [
                GEdge(
                    start=e["start"],
                    end=e["end"],
                    type=e.get("type", ""),
                    properties=to_kv(e.get("properties", {})),
                )
                for e in edges
            ]
            return Graph(nodes=gnodes, edges=gedges)

    # -----------------
    # Mutations
    # -----------------
    def _validate_props(required: list[str], props: dict[str, Any]) -> None:
        missing = [k for k in required if not props.get(k)]
        if missing:
            raise ValueError(f"Missing required properties: {missing}")

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create_concept(self, id: str, name: str) -> Concept:
            _validate_props(["id", "name"], {"id": id, "name": name})
            db = _db()
            db.create_node("Concept", {"id": id, "name": name})  # type: ignore[attr-defined]
            return Concept(id=id, name=name)

        @strawberry.mutation
        def create_task(self, id: str, name: str) -> Task:
            _validate_props(["id", "name"], {"id": id, "name": name})
            db = _db()
            db.create_node("Task", {"id": id, "name": name})  # type: ignore[attr-defined]
            return Task(id=id, name=name)

        @strawberry.mutation
        def create_publication(
            self, pmid: str, title: str | None = None
        ) -> Publication:
            _validate_props(["pmid"], {"pmid": pmid})
            db = _db()
            nid = db.create_node("Publication", {"pmid": pmid, "title": title or ""})  # type: ignore[attr-defined]
            return Publication(id=nid, pmid=pmid, title=title or "")

        @strawberry.mutation
        def create_region(self, name: str, abbreviation: str | None = None) -> Region:
            _validate_props(["name"], {"name": name})
            db = _db()
            nid = db.create_node("Region", {"name": name, "abbreviation": abbreviation or ""})  # type: ignore[attr-defined]
            return Region(id=nid, name=name, abbreviation=abbreviation or "")

        @strawberry.mutation
        def create_dataset(
            self, id: str, name: str | None = None, accession: str | None = None
        ) -> Dataset:
            _validate_props(["id"], {"id": id})
            db = _db()
            db.create_node("Dataset", {"id": id, "name": name or "", "accession": accession or ""})  # type: ignore[attr-defined]
            return Dataset(id=id, name=name or "", accession=accession or "")

        @strawberry.mutation
        def create_relationship(
            self,
            start_id: str,
            end_id: str,
            type: str,
            source: str | None = None,
            confidence: float | None = None,
            timestamp: str | None = None,
        ) -> bool:
            _validate_props(
                ["start_id", "end_id", "type"],
                {"start_id": start_id, "end_id": end_id, "type": type},
            )
            db = _db()
            props = {"source": source, "confidence": confidence, "timestamp": timestamp}
            props = {k: v for k, v in props.items() if v is not None}
            return bool(db.create_relationship(start_id, end_id, type, props))  # type: ignore[attr-defined]

    schema = strawberry.Schema(query=Query, mutation=Mutation)
    return schema
