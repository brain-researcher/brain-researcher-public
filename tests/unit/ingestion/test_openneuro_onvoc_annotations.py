"""Tests for OpenNeuro ONVOC dataset annotation ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.core.ingestion.loaders.openneuro_onvoc_annotations import (
    LEGACY_CONCEPT_SCHEME,
    NEGATIVE_REL_TYPE,
    POSITIVE_REL_TYPE,
    OpenNeuroOnvocAnnotationApplier,
    OpenNeuroOnvocAnnotationLoader,
    canonical_openneuro_dataset_node_id,
    legacy_onvoc_node_id,
)
from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB


def _write_annotation_fixture(tmp_path: Path) -> Path:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir()

    concepts = [
        {
            "id": "ONVOC_0000002",
            "uri": "https://w3id.org/onvoc/ONVOC_0000002",
            "label": "Sleep",
            "definition": "Sleep related studies",
            "synonyms": [],
            "is_top_concept": False,
            "scheme": "ONVOC",
            "top_of": [],
        },
        {
            "id": "ONVOC_0000003",
            "uri": "https://w3id.org/onvoc/ONVOC_0000003",
            "label": "Updated Label",
            "definition": "Updated concept label",
            "synonyms": [],
            "is_top_concept": False,
            "scheme": "ONVOC",
            "top_of": [],
        },
        {
            "id": "ONVOC_0000004",
            "uri": "https://w3id.org/onvoc/ONVOC_0000004",
            "label": "Healthy Controls",
            "definition": "Healthy participants",
            "synonyms": [],
            "is_top_concept": False,
            "scheme": "ONVOC",
            "top_of": [],
        },
    ]
    (onvoc_dir / "onvoc_concepts.json").write_text(json.dumps(concepts, indent=2))

    annotations = [
        {
            "id": "ds000001",
            "label": "Dataset One",
            "description": "Annotated dataset",
            "authors": ["Ada Lovelace"],
            "accessionNumber": "ds000001",
            "doi": "10.1234/example",
            "license": "CC0",
            "keywords": [
                {
                    "id": "ONVOC:0000002",
                    "label": "Sleep",
                    "comment": "",
                    "text": "sleep",
                },
                {
                    "id": "ONVOC:0000999",
                    "label": "Retired Term",
                    "comment": "",
                    "text": "legacy",
                },
            ],
            "inclusionTerms": [
                {
                    "id": "ONVOC:0000002",
                    "label": "Sleep",
                    "comment": "",
                    "text": "sleep cohort",
                },
                {
                    "id": "ONVOC:0000003",
                    "label": "Older Label",
                    "comment": "",
                    "text": "",
                },
            ],
            "exclusionTerms": [
                {
                    "id": "ONVOC:0000004",
                    "label": "Healthy Controls",
                    "comment": "",
                    "text": "",
                }
            ],
            "keywordProvenance": {
                "ONVOC:0000002": [{"source": "keyword_source"}],
                "ONVOC:0000999": [{"source": "legacy_source"}],
            },
            "inclusionTermProvenance": {
                "ONVOC:0000002": [{"source": "inclusion_source"}],
                "ONVOC:0000003": [{"source": "older_source"}],
            },
            "exclusionTermProvenance": {
                "ONVOC:0000004": [{"source": "exclude_source"}]
            },
        }
    ]
    (onvoc_dir / "datasets_openneuro_march18th.json").write_text(
        json.dumps(annotations, indent=2)
    )
    return onvoc_dir


def test_loader_normalizes_ids_and_reports_validation(tmp_path: Path) -> None:
    onvoc_dir = _write_annotation_fixture(tmp_path)
    loader = OpenNeuroOnvocAnnotationLoader(
        annotations_path=onvoc_dir / "datasets_openneuro_march18th.json",
        onvoc_dir=onvoc_dir,
    )

    records = loader.load_records()

    assert len(records) == 1
    assert records[0]["keywords"][0]["raw_id"] == "ONVOC:0000002"
    assert records[0]["keywords"][0]["concept_id"] == "ONVOC_0000002"
    assert records[0]["inclusionTerms"][1]["concept_id"] == "ONVOC_0000003"

    validation = loader.validate_records(records=records)

    assert [row["concept_id"] for row in validation["missing_terms"]] == [
        "ONVOC_0000999"
    ]
    assert [row["concept_id"] for row in validation["label_mismatches"]] == [
        "ONVOC_0000003"
    ]
    assert validation["label_mismatches"][0]["annotation_labels"] == ["Older Label"]


def test_applier_upserts_dataset_and_relationships(tmp_path: Path) -> None:
    onvoc_dir = _write_annotation_fixture(tmp_path)
    loader = OpenNeuroOnvocAnnotationLoader(
        annotations_path=onvoc_dir / "datasets_openneuro_march18th.json",
        onvoc_dir=onvoc_dir,
    )
    db = FakeGraphDB()
    for concept_id, label in (
        ("ONVOC_0000002", "Sleep"),
        ("ONVOC_0000003", "Updated Label"),
        ("ONVOC_0000004", "Healthy Controls"),
    ):
        db.create_node(
            ["Concept", "OnvocClass"],
            {"id": concept_id, "label": label, "scheme": "ONVOC"},
            node_id=concept_id,
        )

    stats = OpenNeuroOnvocAnnotationApplier(db, loader=loader).apply()

    dataset_id = canonical_openneuro_dataset_node_id("ds000001")
    dataset = db.get_node(dataset_id)
    assert dataset is not None
    assert dataset["description"] == "Annotated dataset"
    assert dataset["onvoc_keyword_ids"] == ["ONVOC_0000002", "ONVOC_0000999"]
    assert dataset["onvoc_inclusion_term_ids"] == [
        "ONVOC_0000002",
        "ONVOC_0000003",
    ]
    assert dataset["onvoc_exclusion_term_ids"] == ["ONVOC_0000004"]

    positive_links = db.find_relationships(
        start_node=dataset_id,
        end_node="ONVOC_0000002",
        rel_type=POSITIVE_REL_TYPE,
    )
    assert len(positive_links) == 1
    positive_props = positive_links[0][2]
    assert positive_props["annotation_fields"] == ["keywords", "inclusionTerms"]

    exclusion_links = db.find_relationships(
        start_node=dataset_id,
        end_node="ONVOC_0000004",
        rel_type=NEGATIVE_REL_TYPE,
    )
    assert len(exclusion_links) == 1

    legacy_node = db.get_node(legacy_onvoc_node_id("ONVOC_0000999"))
    assert legacy_node is not None
    assert legacy_node["scheme"] == LEGACY_CONCEPT_SCHEME
    legacy_links = db.find_relationships(
        start_node=dataset_id,
        end_node=legacy_onvoc_node_id("ONVOC_0000999"),
        rel_type=POSITIVE_REL_TYPE,
    )
    assert len(legacy_links) == 1

    assert stats["datasets_created"] == 1
    assert stats["positive_links_created"] == 3
    assert stats["exclusion_links_created"] == 1
    assert stats["legacy_concepts_upserted"] == 1
    assert [row["concept_id"] for row in stats["missing_reference_terms"]] == [
        "ONVOC_0000999"
    ]
    assert stats["missing_graph_terms"] == []


def test_applier_is_idempotent_for_relationship_counts(tmp_path: Path) -> None:
    onvoc_dir = _write_annotation_fixture(tmp_path)
    loader = OpenNeuroOnvocAnnotationLoader(
        annotations_path=onvoc_dir / "datasets_openneuro_march18th.json",
        onvoc_dir=onvoc_dir,
    )
    db = FakeGraphDB()
    for concept_id in ("ONVOC_0000002", "ONVOC_0000003", "ONVOC_0000004"):
        db.create_node(
            ["Concept", "OnvocClass"],
            {"id": concept_id, "label": concept_id, "scheme": "ONVOC"},
            node_id=concept_id,
        )

    applier = OpenNeuroOnvocAnnotationApplier(db, loader=loader)
    first = applier.apply()
    second = applier.apply()

    assert first["positive_links_created"] == 3
    assert first["exclusion_links_created"] == 1
    assert second["positive_links_created"] == 0
    assert second["exclusion_links_created"] == 0


def test_applier_merges_into_canonical_openneuro_dataset_node(tmp_path: Path) -> None:
    onvoc_dir = _write_annotation_fixture(tmp_path)
    loader = OpenNeuroOnvocAnnotationLoader(
        annotations_path=onvoc_dir / "datasets_openneuro_march18th.json",
        onvoc_dir=onvoc_dir,
    )
    db = FakeGraphDB()
    canonical_id = canonical_openneuro_dataset_node_id("ds000001")
    db.create_node(
        "Dataset",
        {
            "id": canonical_id,
            "source_repo_id": "ds000001",
            "name": "Canonical Dataset One",
        },
        node_id=canonical_id,
    )
    db.create_node(
        ["Concept", "OnvocClass"],
        {"id": "ONVOC_0000002", "label": "Sleep", "scheme": "ONVOC"},
        node_id="ONVOC_0000002",
    )
    db.create_node(
        ["Concept", "OnvocClass"],
        {"id": "ONVOC_0000003", "label": "Updated Label", "scheme": "ONVOC"},
        node_id="ONVOC_0000003",
    )
    db.create_node(
        ["Concept", "OnvocClass"],
        {"id": "ONVOC_0000004", "label": "Healthy Controls", "scheme": "ONVOC"},
        node_id="ONVOC_0000004",
    )

    stats = OpenNeuroOnvocAnnotationApplier(db, loader=loader).apply()

    dataset = db.get_node(canonical_id)
    assert dataset is not None
    assert dataset["dataset_id"] == "ds000001"
    assert dataset["title"] == "Dataset One"
    assert db.get_node("ds000001") is None
    positive_links = db.find_relationships(
        start_node=canonical_id,
        rel_type=POSITIVE_REL_TYPE,
    )
    assert len(positive_links) == 3
    assert stats["datasets_created"] == 0
