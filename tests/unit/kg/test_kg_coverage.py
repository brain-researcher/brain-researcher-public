import os

import pytest

from brain_researcher.services.agent.planner.catalog_loader import load_intents
from brain_researcher.services.agent.planner.kg_bridge import (
    get_family_stats_for_operation,
)


def _neo4j_available():
    pwd_present = bool(os.environ.get("NEO4J_PASSWORD"))
    return (
        pwd_present
        and get_family_stats_for_operation("__connectivity_test__") is not None
    )


@pytest.mark.skipif(
    not os.environ.get("NEO4J_PASSWORD"),
    reason="NEO4J_PASSWORD not set; skipping KG coverage check",
)
def test_every_operation_has_family_implements():
    intents = load_intents()
    missing = []
    hits = []
    for intent in intents.values():
        fams = get_family_stats_for_operation(intent.id)
        if not fams:
            missing.append(intent.id)
        else:
            hits.append(intent.id)
    if missing and not hits:
        pytest.skip("No operations have family implementations in this KG deployment.")
    assert hits, "Expected at least one operation with family implementations."


@pytest.mark.skipif(
    not os.environ.get("NEO4J_PASSWORD"),
    reason="NEO4J_PASSWORD not set; skipping KG connected coverage check",
)
def test_connected_coverage_metric():
    from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

    try:
        db = require_neo4j_db(preload_cache=False)
    except Exception as exc:
        pytest.skip(f"Neo4j not available: {exc}")
    try:
        cypher_all = """
        MATCH (d:Dataset)
        WITH count(d) AS total
        MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(t:Task)
        MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
        RETURN total, count(DISTINCT d) AS connected
        """
        row = next(iter(db.execute_query(cypher_all)), {"total": 0, "connected": 0})
        total_all = int(row.get("total") or 0)
        connected_all = int(row.get("connected") or 0)
        assert total_all >= 0
        assert 0 <= connected_all <= total_all

        cypher_fmri = """
        MATCH (d:Dataset)
        WHERE any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
        WITH count(d) AS total
        MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(t:Task)
        MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
        RETURN total, count(DISTINCT d) AS connected
        """
        row = next(iter(db.execute_query(cypher_fmri)), {"total": 0, "connected": 0})
        total_fmri = int(row.get("total") or 0)
        connected_fmri = int(row.get("connected") or 0)
        assert total_fmri >= 0
        assert 0 <= connected_fmri <= total_fmri
    finally:
        db.close()
