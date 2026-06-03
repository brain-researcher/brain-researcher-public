from __future__ import annotations

from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.br_kg.spatial.disease_trait_region_materializer import (
    collect_disease_trait_region_evidence,
    materialize_disease_trait_region_associations,
)


class UpdateCapableFakeGraphDB(FakeGraphDB):
    def update_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, object],
    ) -> bool:
        updated = False
        for rel in self._relationships:
            if (
                rel["start"] == start_node
                and rel["end"] == end_node
                and rel["data"].get("type") == rel_type
            ):
                rel["data"].update(properties)
                updated = True
        return updated


def _create_node(db: FakeGraphDB, label: str, node_id: str, **props: object) -> str:
    return db.create_node(label, {"id": node_id, **props}, node_id=node_id)


def _build_graph(db: FakeGraphDB) -> dict[str, str]:
    disease = _create_node(
        db,
        "DiseaseTrait",
        "disease:adhd",
        name="Attention Deficit Hyperactivity Disorder",
    )
    study = _create_node(
        db,
        "Study",
        "study:adhd2022",
        name="ADHD 2022",
        pmid="36702997",
    )
    publication = _create_node(
        db,
        "Publication",
        "pmid:36702997",
        pmid="36702997",
        title="ADHD GWAS",
    )
    region = _create_node(
        db,
        "BrainRegion",
        "region:dlpfc",
        name="Dorsolateral prefrontal cortex",
    )
    coordinate = _create_node(
        db,
        "Coordinate",
        "coord:1",
        x=-42,
        y=22,
        z=31,
    )

    db.create_relationship(study, disease, "STUDIES")
    db.create_relationship(publication, study, "ALIGNS_WITH")
    db.create_relationship(publication, region, "MENTIONS_REGION")
    db.create_relationship(study, coordinate, "HAS_COORDINATE")
    db.create_relationship(coordinate, region, "LOCATED_IN")

    return {
        "disease": disease,
        "study": study,
        "publication": publication,
        "region": region,
        "coordinate": coordinate,
    }


def test_collect_disease_trait_region_evidence_merges_publication_and_coordinate_paths() -> None:
    db = FakeGraphDB()
    ids = _build_graph(db)

    evidence = collect_disease_trait_region_evidence(db)

    disease_evidence = evidence[ids["disease"]]
    assert ids["region"] in disease_evidence

    row = disease_evidence[ids["region"]]
    assert row.supporting_publication_ids == [ids["publication"]]
    assert row.supporting_study_ids == [ids["study"]]
    assert row.supporting_coordinate_ids == [ids["coordinate"]]
    assert "publication:pmid:36702997" in row.evidence_paths
    assert "coordinate:coord:1" in row.evidence_paths


def test_materialize_disease_trait_region_associations_is_idempotent() -> None:
    db = FakeGraphDB()
    ids = _build_graph(db)

    first = materialize_disease_trait_region_associations(db)
    second = materialize_disease_trait_region_associations(db)

    assert first.edges_created == 1
    assert first.edges_skipped_existing == 0
    assert second.edges_created == 0
    assert second.edges_skipped_existing == 1

    rels = db.find_relationships(
        start_node=ids["disease"],
        end_node=ids["region"],
        rel_type="ASSOCIATED_WITH",
    )
    assert len(rels) == 1
    props = rels[0][2]
    assert props["derived"] is True
    assert props["source"] == "disease_trait_region_materializer"
    assert props["supporting_publication_count"] == 1
    assert props["supporting_study_count"] == 1
    assert props["supporting_coordinate_count"] == 1
    assert props["evidence_ids"] == [ids["publication"], ids["study"], ids["coordinate"]]


def test_materialize_updates_existing_association_when_supported() -> None:
    db = UpdateCapableFakeGraphDB()
    ids = _build_graph(db)
    db.create_relationship(
        ids["disease"],
        ids["region"],
        "ASSOCIATED_WITH",
        {"source": "manual", "legacy": True},
    )

    summary = materialize_disease_trait_region_associations(db)

    assert summary.edges_updated == 1
    rels = db.find_relationships(
        start_node=ids["disease"],
        end_node=ids["region"],
        rel_type="ASSOCIATED_WITH",
    )
    assert len(rels) == 1
    props = rels[0][2]
    assert props["source"] == "disease_trait_region_materializer"
    assert props["derived"] is True
    assert props["legacy"] is True


def test_materialize_can_scope_to_explicit_disease_traits() -> None:
    db = FakeGraphDB()
    ids = _build_graph(db)
    other_disease = _create_node(db, "DiseaseTrait", "disease:ocd", name="OCD")
    other_study = _create_node(db, "Study", "study:ocd2024", name="OCD 2024")
    other_publication = _create_node(
        db,
        "Publication",
        "pmid:99999999",
        pmid="99999999",
        title="OCD GWAS",
    )
    other_region = _create_node(db, "BrainRegion", "region:insula", name="Insula")
    db.create_relationship(other_study, other_disease, "STUDIES")
    db.create_relationship(other_publication, other_study, "ALIGNS_WITH")
    db.create_relationship(other_publication, other_region, "MENTIONS_REGION")

    summary = materialize_disease_trait_region_associations(
        db,
        disease_trait_ids=[ids["disease"]],
    )

    assert summary.disease_traits_seen == 1
    assert summary.edges_created == 1
    assert db.find_relationships(
        start_node=ids["disease"],
        end_node=ids["region"],
        rel_type="ASSOCIATED_WITH",
    )
    assert not db.find_relationships(
        start_node=other_disease,
        end_node=other_region,
        rel_type="ASSOCIATED_WITH",
    )
