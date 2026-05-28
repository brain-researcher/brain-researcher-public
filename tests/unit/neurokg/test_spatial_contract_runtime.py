from __future__ import annotations

import pytest
from pydantic import ValidationError

from brain_researcher.services.neurokg.graph.performance_optimizer import (
    PerformanceOptimizer,
)
from brain_researcher.services.neurokg.query.persisted_queries import QueryLibrary
from brain_researcher.services.neurokg.schemas.edge_schemas import (
    EDGE_SIGNATURES,
    OPTIONAL_EDGE_SIGNATURES,
    validate_edge,
)


def _prov() -> dict[str, object]:
    return {
        "source": "manual",
        "method": "rule",
        "confidence": 0.9,
        "loader_version": "test",
    }


def test_in_region_accepts_canonical_statsmap_to_brainregion() -> None:
    edge = validate_edge(
        "IN_REGION",
        {
            "source_id": "map:test-001",
            "target_id": "atlas:test:1",
            "source_type": "StatsMap",
            "target_type": "BrainRegion",
            "assignment_method": "atlas_lookup",
            "prov": _prov(),
        },
    )

    assert edge.source_type == "StatsMap"
    assert edge.target_type == "BrainRegion"
    assert ("StatsMap", "BrainRegion") in EDGE_SIGNATURES["IN_REGION"]


def test_in_region_keeps_coordinate_region_compatibility() -> None:
    edge = validate_edge(
        "IN_REGION",
        {
            "source_id": "coord:mni:2:1:2:3:study-001",
            "target_id": "atlas:test:1",
            "assignment_method": "atlas_lookup",
            "prov": _prov(),
        },
    )

    assert edge.source_type == "Coordinate"
    assert edge.target_type == "Region"
    assert OPTIONAL_EDGE_SIGNATURES["IN_REGION"] == (("Coordinate", "Region"),)


def test_in_region_rejects_cross_product_signature() -> None:
    with pytest.raises(ValidationError):
        validate_edge(
            "IN_REGION",
            {
                "source_id": "coord:mni:2:1:2:3:study-001",
                "target_id": "atlas:test:1",
                "source_type": "Coordinate",
                "target_type": "BrainRegion",
                "assignment_method": "atlas_lookup",
                "prov": _prov(),
            },
        )


def test_part_of_is_brainregion_only() -> None:
    edge = validate_edge(
        "PART_OF",
        {
            "source_id": "atlas:test:child",
            "target_id": "atlas:test:parent",
            "hierarchy_type": "anatomical",
            "prov": _prov(),
        },
    )

    assert edge.source_type == "BrainRegion"
    assert edge.target_type == "BrainRegion"
    assert EDGE_SIGNATURES["PART_OF"] == (("BrainRegion", "BrainRegion"),)

    with pytest.raises(ValidationError):
        validate_edge(
            "PART_OF",
            {
                "source_id": "atlas:test:child",
                "target_id": "atlas:test:parent",
                "source_type": "Region",
                "target_type": "Region",
                "hierarchy_type": "anatomical",
                "prov": _prov(),
            },
        )


def test_persisted_queries_prefer_brainregion_spatial_contract() -> None:
    library = QueryLibrary()
    pub_to_coords = library.get_query("Q2_PUB_TO_COORDS")
    nearby_regions = library.get_query("Q11_NEARBY_REGIONS")

    assert pub_to_coords is not None
    assert "['StatsMap', 'StatMap', 'StatisticalMap']" in pub_to_coords.query
    assert "(m)-[:IN_REGION]->(brain_region:BrainRegion)" in pub_to_coords.query
    assert "(c)-[:IN_REGION]->(legacy_region:Region)" in pub_to_coords.query
    assert "coalesce(" not in pub_to_coords.query

    assert nearby_regions is not None
    assert "r:BrainRegion OR r:Region" in nearby_regions.query
    assert "distance_mm" in nearby_regions.query


class _FakeResult:
    def single(self) -> dict[str, int]:
        return {"count": 0, "updated_count": 0}


class _FakeSession:
    def __init__(self, queries: list[tuple[str, dict[str, object]]]):
        self._queries = queries

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, query: str, **params):
        self._queries.append((query, params))
        return _FakeResult()


class _FakeDriver:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []

    def session(self) -> _FakeSession:
        return _FakeSession(self.queries)


def test_performance_optimizer_covers_canonical_spatial_paths() -> None:
    driver = _FakeDriver()
    optimizer = PerformanceOptimizer(driver)

    optimizer.add_performance_indexes()

    index_queries = [query for query, _params in driver.queries]
    assert any("n:BrainRegion" in query for query in index_queries)
    assert any("n:StatsMap" in query for query in index_queries)
    assert any("n:Region" in query for query in index_queries)

    driver.queries.clear()
    optimizer.optimize_queries()

    explain_queries = [query for query, _params in driver.queries]
    assert any(
        "MATCH (m:StatsMap)-[:IN_REGION]->(br:BrainRegion)" in query
        for query in explain_queries
    )
    assert any(
        "MATCH (child:BrainRegion)-[:PART_OF]->(parent:BrainRegion)" in query
        for query in explain_queries
    )
    assert any("[:ACTIVATES]" in query and "r:BrainRegion OR r:Region" in query for query in explain_queries)
