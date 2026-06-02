from __future__ import annotations

from brain_researcher.services.br_kg.spatial.create_activation_edges import (
    collect_coordinate_evidence,
)
from tests.unit.br_kg._graph_test_utils import UnitGraphDB


def test_collect_coordinate_evidence_links_study_coordinates_to_region() -> None:
    db = UnitGraphDB()

    concept_id = db.create_node("Concept", {"name": "test_concept"})
    study_id = db.create_node("Study", {"pmid": "12345"})
    region_id = db.create_node("BrainRegion", {"name": "test_region"})

    db.create_relationship(study_id, concept_id, "STUDIES")
    for i in range(3):
        coord_id = db.create_node("Coordinate", {"x": i, "y": i, "z": i})
        db.create_relationship(study_id, coord_id, "HAS_COORDINATE")
        db.create_relationship(coord_id, region_id, "LOCATED_IN")

    evidence = collect_coordinate_evidence(db, "Concept")

    assert concept_id in evidence
    assert "test_region" in evidence[concept_id]
    assert len(evidence[concept_id]["test_region"]) == 3
