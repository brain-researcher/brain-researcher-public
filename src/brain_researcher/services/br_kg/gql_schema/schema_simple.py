"""
Simplified GraphQL schema for BR-KG that works with newer Strawberry.
"""

from typing import List, Optional

import strawberry

from brain_researcher.services.br_kg.db.bootstrap import get_db


# Database helper
def _db():
    return get_db()


# GraphQL Types
@strawberry.type
class RegionRef:
    """Lightweight reference to a region (avoids recursive nesting)."""
    id: Optional[str]
    name: Optional[str]
    abbreviation: Optional[str]


@strawberry.type
class Coordinate:
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    space: Optional[str]
    region: Optional[RegionRef] = None


@strawberry.type
class Concept:
    id: str
    name: Optional[str]


@strawberry.type
class Task:
    id: str
    name: Optional[str]

    @strawberry.field
    def regions(self) -> List["Region"]:
        """Regions linked to this task via statmaps/regions."""
        db = _db()
        regions: list[Region] = []
        try:
            cypher = """
            MATCH (t:Task {id:$id})<-[:HAS_TASK]-(m)
            OPTIONAL MATCH (m)-[:HAS_REGION|IN_REGION|LOCATED_IN|IN_PARCELLATION]->(r1:BrainRegion)
            OPTIONAL MATCH (m)-[:HAS_COORDINATE]->(c)-[:LOCATED_IN|HAS_REGION|IN_REGION|IN_PARCELLATION]->(r2:BrainRegion)
            WITH collect(DISTINCT r1) + collect(DISTINCT r2) AS regs
            UNWIND regs AS r
            WITH DISTINCT r WHERE r IS NOT NULL
            RETURN r.id AS id, r.name AS name, r.abbreviation AS abbreviation
            """
            for row in db.execute_query(cypher, {"id": self.id}):
                regions.append(Region(
                    id=str(row.get("id")),
                    name=row.get("name"),
                    abbreviation=row.get("abbreviation")
                ))
            # Fallback: if no task-specific regions, return top global regions by coordinate count
            if not regions:
                fallback = """
                MATCH (r:BrainRegion)<-[:LOCATED_IN]-(c:Coordinate)
                RETURN r.id AS id, r.name AS name, r.abbreviation AS abbreviation, count(c) AS cnt
                ORDER BY cnt DESC
                LIMIT 10
                """
                for row in db.execute_query(fallback, {}):
                    regions.append(Region(
                        id=str(row.get("id")),
                        name=row.get("name"),
                        abbreviation=row.get("abbreviation")
                    ))
        except Exception:
            # Best-effort; return empty on errors to avoid breaking persisted queries
            pass
        return regions

    @strawberry.field
    def networks(self) -> List["Network"]:
        """Networks linked to this task via statmaps' IN_NETWORK edges."""
        db = _db()
        nets: list[Network] = []
        try:
            cypher = """
            MATCH (t:Task {id:$id})<-[:HAS_TASK]-(m:StatMap)-[:IN_NETWORK]->(n:Network)
            RETURN DISTINCT n.name AS name, n.id AS id
            """
            for row in db.execute_query(cypher, {"id": self.id}):
                nets.append(Network(
                    id=str(row.get("id", row.get("name"))),
                    name=row.get("name")
                ))
        except Exception:
            pass
        return nets


@strawberry.type
class Region:
    id: str
    name: Optional[str]
    abbreviation: Optional[str]

    @strawberry.field
    def coordinates(self) -> List[Coordinate]:
        """Best-effort coordinates associated with this region."""
        db = _db()
        coords: list[Coordinate] = []
        try:
            cypher = """
            MATCH (r {id:$id})<-[:LOCATED_IN|HAS_REGION|IN_REGION]-(c:Coordinate)
            RETURN c.x AS x, c.y AS y, c.z AS z, c.space AS space
            LIMIT 200
            """
            for row in db.execute_query(cypher, {"id": self.id}):
                coords.append(
                    Coordinate(
                        x=row.get("x"),
                        y=row.get("y"),
                        z=row.get("z"),
                        space=row.get("space"),
                        region=RegionRef(
                            id=self.id,
                            name=self.name,
                            abbreviation=self.abbreviation,
                        ),
                    )
                )
        except Exception:
            pass
        return coords


@strawberry.type
class Dataset:
    id: str
    name: Optional[str]
    accession: Optional[str]


@strawberry.type
class Publication:
    id: str
    pmid: Optional[str]
    title: Optional[str]
    abstract: Optional[str] = None
    concepts: Optional[List[str]] = None


@strawberry.type
class Network:
    id: Optional[str]
    name: Optional[str]

    @strawberry.field
    def coordinates(self) -> List[Coordinate]:
        """
        Best-effort coordinates linked to this publication.
        Currently returns an empty list if no links are present.
        """
        db = _db()
        coords: list[Coordinate] = []
        try:
            cypher = """
            MATCH (p:Publication {pmid:$pmid})-[:REPORTS]->(c:Coordinate)
            OPTIONAL MATCH (c)-[:LOCATED_IN|HAS_REGION|IN_REGION]->(r)
            RETURN c.x AS x, c.y AS y, c.z AS z, c.space AS space,
                   r.id AS rid, r.name AS rname, r.abbreviation AS rabbr
            LIMIT 500
            """
            for row in db.execute_query(cypher, {"pmid": self.pmid or self.id}):
                coords.append(
                    Coordinate(
                        x=row.get("x"),
                        y=row.get("y"),
                        z=row.get("z"),
                        space=row.get("space"),
                        region=RegionRef(
                            id=row.get("rid"),
                            name=row.get("rname"),
                            abbreviation=row.get("rabbr"),
                        ),
                    )
                )
        except Exception:
            pass
        return coords


@strawberry.type
class Query:
    @strawberry.field
    def concepts(self, name: Optional[str] = None) -> List[Concept]:
        db = _db()
        props = {"name": name} if name else None
        nodes = []
        for nid, p in db.find_nodes("Concept", props):
            nodes.append(Concept(id=str(nid), name=p.get("name")))
        return nodes

    @strawberry.field
    def tasks(self, name: Optional[str] = None) -> List[Task]:
        db = _db()
        props = {"name": name} if name else None
        nodes = []
        for nid, p in db.find_nodes("Task", props):
            nodes.append(Task(id=str(nid), name=p.get("name")))
        return nodes

    @strawberry.field
    def regions(self, name: Optional[str] = None) -> List[Region]:
        db = _db()
        props = {"name": name} if name else None
        nodes = []
        for nid, p in db.find_nodes("Region", props):
            nodes.append(Region(
                id=str(nid),
                name=p.get("name"),
                abbreviation=p.get("abbreviation")
            ))
        return nodes

    @strawberry.field
    def publications(self, pmid: Optional[str] = None) -> List[Publication]:
        db = _db()
        props = {"pmid": pmid} if pmid else None
        nodes = []
        for nid, p in db.find_nodes("Publication", props):
            nodes.append(Publication(
                id=str(nid),
                pmid=p.get("pmid"),
                title=p.get("title"),
                abstract=p.get("abstract"),
                concepts=p.get("concepts"),
            ))
        return nodes

    @strawberry.field
    def publications_by_pmids(self, pmids: List[str]) -> List[Publication]:
        db = _db()
        out: List[Publication] = []
        for pmid in pmids:
            for nid, p in db.find_nodes("Publication", {"pmid": pmid}):
                out.append(
                    Publication(
                        id=str(nid),
                        pmid=p.get("pmid"),
                        title=p.get("title"),
                        abstract=p.get("abstract"),
                        concepts=p.get("concepts"),
                    )
                )
        return out


@strawberry.type
class RelationshipInfo:
    """Information about a relationship with provenance."""
    type: str
    source_id: str
    target_id: str
    confidence: Optional[float]
    source: Optional[str]
    timestamp: Optional[str]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def create_concept(self, id: str, name: str) -> Concept:
        db = _db()
        db.create_node("Concept", {"id": id, "name": name})
        return Concept(id=id, name=name)

    @strawberry.mutation
    def create_task(self, id: str, name: str) -> Task:
        db = _db()
        db.create_node("Task", {"id": id, "name": name})
        return Task(id=id, name=name)

    @strawberry.mutation
    def create_publication(self, pmid: str, title: Optional[str] = None) -> Publication:
        db = _db()
        nid = db.create_node("Publication", {"pmid": pmid, "title": title or ""})
        return Publication(id=str(nid), pmid=pmid, title=title)

    @strawberry.mutation
    def create_region(self, name: str, abbreviation: Optional[str] = None) -> Region:
        db = _db()
        nid = db.create_node("Region", {"name": name, "abbreviation": abbreviation or ""})
        return Region(id=str(nid), name=name, abbreviation=abbreviation)

    @strawberry.mutation
    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        confidence: Optional[float] = None,
        source: Optional[str] = None
    ) -> RelationshipInfo:
        """Create a relationship with provenance tracking."""
        from datetime import datetime

        db = _db()
        timestamp = datetime.now().isoformat()

        props = {
            "confidence": confidence,
            "source": source or "GraphQL API",
            "timestamp": timestamp
        }

        # Remove None values
        props = {k: v for k, v in props.items() if v is not None}

        db.create_relationship(source_id, target_id, rel_type, props)

        return RelationshipInfo(
            type=rel_type,
            source_id=source_id,
            target_id=target_id,
            confidence=confidence,
            source=source or "GraphQL API",
            timestamp=timestamp
        )


def build_schema():
    """Build and return the GraphQL schema."""
    return strawberry.Schema(query=Query, mutation=Mutation)
