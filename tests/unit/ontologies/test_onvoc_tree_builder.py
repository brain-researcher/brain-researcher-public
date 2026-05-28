"""Tests for ONVOC tree building utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tools.ontologies.build_onvoc_tree import (
    OnvocTreeBuilder,
    build_payload,
    load_onvoc_artifacts,
)


@pytest.fixture()
def sample_onvoc(tmp_path: Path) -> tuple[Path, Path]:
    concepts = [
        {
            "id": "ONVOC_ROOT_MEMORY",
            "uri": "https://example.org/ONVOC_ROOT_MEMORY",
            "label": "Memory",
            "is_top_concept": True,
            "synonyms": [],
        },
        {
            "id": "ONVOC_ROOT_COGNITION",
            "uri": "https://example.org/ONVOC_ROOT_COGNITION",
            "label": "Cognition",
            "is_top_concept": True,
            "synonyms": [],
        },
        {
            "id": "ONVOC_WORKING_MEMORY",
            "uri": "https://example.org/ONVOC_WORKING_MEMORY",
            "label": "Working memory",
            "synonyms": ["WM task"],
            "is_top_concept": False,
        },
        {
            "id": "ONVOC_EPISODIC_MEMORY",
            "uri": "https://example.org/ONVOC_EPISODIC_MEMORY",
            "label": "Episodic memory",
            "synonyms": [],
            "is_top_concept": False,
        },
    ]
    relationships = [
        {
            "child_id": "ONVOC_WORKING_MEMORY",
            "parent_id": "ONVOC_ROOT_MEMORY",
            "relation": "skos:broader",
        },
        {
            "child_id": "ONVOC_WORKING_MEMORY",
            "parent_id": "ONVOC_ROOT_COGNITION",
            "relation": "skos:broader",
        },
        {
            "child_id": "ONVOC_EPISODIC_MEMORY",
            "parent_id": "ONVOC_ROOT_MEMORY",
            "relation": "skos:broader",
        },
    ]
    concepts_path = tmp_path / "onvoc_concepts.json"
    relationships_path = tmp_path / "onvoc_relationships.json"
    concepts_path.write_text(json.dumps(concepts), encoding="utf-8")
    relationships_path.write_text(json.dumps(relationships), encoding="utf-8")
    return concepts_path, relationships_path


def test_build_payload_creates_tree_and_constraints(sample_onvoc: tuple[Path, Path]) -> None:
    concepts_path, relationships_path = sample_onvoc
    nodes, parents, children = load_onvoc_artifacts(concepts_path, relationships_path)

    builder = OnvocTreeBuilder(nodes, parents, children)
    roots = builder.select_roots(
        allow_substrings=["memory"],
        block_substrings=[],
    )
    payload = build_payload(
        builder,
        roots=roots,
        max_depth=3,
        concepts_path=concepts_path,
        relationships_path=relationships_path,
        lexical_stopwords=["task", "paradigm"],
        fold_max_leaves=25,
        fold_min_children=2,
    )

    assert payload["version"] == "0.1.0"
    assert payload["source"]["concepts"].endswith("onvoc_concepts.json")
    assert payload["policy"]["multi_parent_primary_choice"]["order"][0] == "shortest_to_l1"
    tree = payload["tree"]
    assert len(tree) == 1
    memory = tree[0]
    assert memory["id"] == "ONVOC_ROOT_MEMORY"
    assert memory["uri"] == "https://example.org/ONVOC_ROOT_MEMORY"
    children_nodes = {child["id"]: child for child in memory.get("children", [])}
    assert set(children_nodes) == {"ONVOC_WORKING_MEMORY", "ONVOC_EPISODIC_MEMORY"}

    working = children_nodes["ONVOC_WORKING_MEMORY"]
    assert working["synonyms"] == ["WM task"]
    assert working["alt_parents"] == ["ONVOC_ROOT_COGNITION"]

    constraints = payload["constraints"]["cannot_link"]
    paired_ids = {tuple(item["ids"]) for item in constraints}
    assert ("ONVOC_EPISODIC_MEMORY", "ONVOC_WORKING_MEMORY") in paired_ids or (
        "ONVOC_WORKING_MEMORY",
        "ONVOC_EPISODIC_MEMORY",
    ) in paired_ids
