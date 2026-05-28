"""Tests for the ONVOC unified loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.core.ingestion.loaders.onvoc_unified import OnvocUnifiedLoader


@pytest.fixture()
def onvoc_tmpdir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "onvoc"
    data_dir.mkdir()
    concepts = [
        {
            "id": "ONVOC_0000001",
            "uri": "https://w3id.org/onvoc/ONVOC_0000001",
            "label": "Behaviors",
            "definition": "Root class",
            "synonyms": ["Behaviour"],
            "is_top_concept": True,
            "scheme": "ONVOC",
            "top_of": ["ONVOC_SCHEME"],
        },
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
    ]
    relationships = [
        {
            "child_id": "ONVOC_0000002",
            "parent_id": "ONVOC_0000001",
            "relation": "skos:broader",
            "edge_type": "CLASSIFIED_UNDER",
        }
    ]
    (data_dir / "onvoc_concepts.json").write_text(json.dumps(concepts, indent=2))
    (data_dir / "onvoc_relationships.json").write_text(json.dumps(relationships, indent=2))
    return data_dir


def test_loader_reads_concepts_and_relationships(onvoc_tmpdir: Path) -> None:
    loader = OnvocUnifiedLoader(data_dir=onvoc_tmpdir)
    concepts = loader.load_concepts()
    rels = loader.load_relationships()

    assert len(concepts) == 2
    assert {c["id"] for c in concepts} == {"ONVOC_0000001", "ONVOC_0000002"}
    assert rels == [
        {
            "child_id": "ONVOC_0000002",
            "parent_id": "ONVOC_0000001",
            "relation": "skos:broader",
            "edge_type": "CLASSIFIED_UNDER",
        }
    ]


def test_loader_missing_files_raises(tmp_path: Path) -> None:
    loader = OnvocUnifiedLoader(data_dir=tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        loader.load_concepts()
