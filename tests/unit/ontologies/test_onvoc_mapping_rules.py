"""Tests for ONVOC mapping rule generation."""

from __future__ import annotations

from pathlib import Path

import yaml

from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree
from scripts.tools.ontologies.build_onvoc_mapping_rules import (
    build_diagnosis_rules,
    build_hed_rules,
    build_instrument_rules,
    build_medication_rules,
    build_modality_rules,
    build_payload,
    build_phenotype_rules,
    derive_anchors,
    derive_contrast_rules,
    load_crosswalk,
)


def test_mapping_rules_cover_all_families(tmp_path: Path) -> None:
    tree_payload = {
        "version": "0.1.0",
        "tree": [
            {
                "id": "ONVOC_ROOT",
                "label": "Root",
                "level": 1,
                "children": [
                    {"id": "ONVOC_CHILD_A", "label": "Child A", "level": 2},
                    {"id": "ONVOC_CHILD_B", "label": "Child B", "level": 2},
                ],
            }
        ],
        "constraints": {},
    }
    tree_path = tmp_path / "tree.yaml"
    tree_path.write_text(yaml.safe_dump(tree_payload), encoding="utf-8")

    crosswalk_payload = {
        "tasks": {
            "task:foo": {"primary": "ONVOC_CHILD_A"},
            "task:bar": {"primary": "ONVOC_CHILD_B"},
        },
        "phenotypes": {
            "age": {
                "kind": "numeric",
                "source": "participants.tsv:age",
                "bins": [
                    {"lt": 18, "map_to_family": "ONVOC_CHILD_A"},
                    {"gte": 18, "map_to_family": "ONVOC_CHILD_B"},
                ],
            }
        },
        "diagnosis": [
            {
                "name": "Example",
                "pattern": "(?i)example",
                "map_to_family": "ONVOC_CHILD_A",
            }
        ],
        "medications": [
            {
                "name": "Med",
                "synonyms": ["medication"],
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
        "instruments": [
            {
                "name": "Instrument",
                "synonyms": ["instrument"],
                "map_to_family": "ONVOC_CHILD_A",
            }
        ],
        "hed": [
            {
                "name": "Visual",
                "tags_any": ["visual"],
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
        "modalities": [
            {
                "name": "BOLD",
                "where": {"modality": "bold"},
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
    }
    crosswalk_path = tmp_path / "crosswalk.yaml"
    crosswalk_path.write_text(yaml.safe_dump(crosswalk_payload), encoding="utf-8")

    tree = OnvocTree.load(tree_path)
    crosswalk = load_crosswalk(crosswalk_path)

    allowed_levels = {2}
    include: set[str] = set()
    exclude: set[str] = set()
    exclude_subtrees: set[str] = set()

    anchors = derive_anchors(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    assert {anchor["onvoc_uri"] for anchor in anchors} == {
        "ONVOC_CHILD_A",
        "ONVOC_CHILD_B",
    }
    seed_sets = {tuple(anchor["seed_tasks"]) for anchor in anchors}
    assert ("task:bar",) in seed_sets
    assert ("task:foo",) in seed_sets

    contrast_rules = derive_contrast_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    phenotype_rules = build_phenotype_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    diagnosis_rules = build_diagnosis_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    medication_rules = build_medication_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    instrument_rules = build_instrument_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    hed_rules = build_hed_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )
    modality_rules = build_modality_rules(
        tree, crosswalk, allowed_levels, include, exclude, exclude_subtrees
    )

    payload = build_payload(
        tree_path,
        tree,
        anchors,
        contrast_rules,
        phenotype_rules,
        diagnosis_rules,
        medication_rules,
        instrument_rules,
        hed_rules,
        modality_rules,
        allowed_levels,
        {
            "include_families": [],
            "exclude_families": [],
            "exclude_subtrees": [],
        },
    )
    assert payload["version"] == "0.3.0"
    assert payload["family_levels"] == ["l2"]
    assert payload["constraints"]["derive_cannot_link_from_siblings"] is True
    assert payload["phenotype_rules"] and payload["diagnosis_rules"]
    assert payload["channels"]["lambda_by_channel"]["phenotype"] == 0.5
