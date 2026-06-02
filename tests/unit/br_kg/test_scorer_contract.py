from __future__ import annotations

from pathlib import Path

import yaml

from brain_researcher.services.br_kg.extractors import (
    extract_hed_tags,
    extract_modalities,
    load_participant_profile,
)
from brain_researcher.services.br_kg.scoring.scorer import (
    MappingRules,
    Scorer,
    collect_cohort_evidence,
    collect_task_evidence,
)
from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree


def _write_tree(tmp_path: Path) -> Path:
    payload = {
        "version": "0.1.0",
        "tree": [
            {
                "id": "ONVOC_ROOT",
                "label": "Root",
                "level": 1,
                "children": [
                    {
                        "id": "ONVOC_CHILD_A",
                        "label": "Child A",
                        "level": 2,
                    },
                    {
                        "id": "ONVOC_CHILD_B",
                        "label": "Child B",
                        "level": 2,
                    },
                ],
            }
        ],
        "constraints": {},
    }
    path = tmp_path / "tree.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _write_rules(tmp_path: Path, tree_path: Path) -> Path:
    payload = {
        "version": "0.3.0",
        "backbone": {"onvoc_tree": str(tree_path)},
        "family_levels": ["l2"],
        "channels": {
            "lambda_by_channel": {
                "task": 1.0,
                "contrast": 0.3,
                "phenotype": 0.5,
                "modality": 0.3,
                "hed": 0.4,
            }
        },
        "anchors": [
            {
                "family_id": "onvoc_child_a",
                "onvoc_uri": "ONVOC_CHILD_A",
                "label": "Child A",
                "level": 2,
                "seed_tasks": ["task:n-back"],
            },
            {
                "family_id": "onvoc_child_b",
                "onvoc_uri": "ONVOC_CHILD_B",
                "label": "Child B",
                "level": 2,
                "seed_tasks": ["task:go-no-go"],
            },
        ],
        "contrast_rules": [
            {
                "name": "WM",
                "map_to_family": "ONVOC_CHILD_A",
                "pattern": "(?i)2-back",
                "match_task": ["task:n-back"],
                "prior_boost": 0.25,
            }
        ],
        "phenotype_rules": [
            {
                "name": "Age",
                "source": "participants.tsv:age",
                "prior_boost": 0.3,
                "bins": [
                    {"lt": 18, "map_to_family": "ONVOC_CHILD_A"},
                    {"gte": 18, "map_to_family": "ONVOC_CHILD_B"},
                ],
            }
        ],
        "diagnosis_rules": [
            {
                "name": "Attention",
                "pattern": "(?i)adhd",
                "prior_boost": 0.5,
                "map_to_family": "ONVOC_CHILD_A",
            }
        ],
        "medication_rules": [
            {
                "name": "Stimulant",
                "synonyms": ["methylphenidate"],
                "prior_boost": 0.35,
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
        "instrument_rules": [
            {
                "name": "STAI",
                "synonyms": ["stai"],
                "prior_boost": 0.35,
                "map_to_family": "ONVOC_CHILD_A",
            }
        ],
        "hed_rules": [
            {
                "name": "Visual",
                "tags_any": ["visual"],
                "prior_boost": 0.25,
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
        "modality_rules": [
            {
                "name": "BOLD",
                "where": {"modality": "bold"},
                "prior_boost": 0.2,
                "map_to_family": "ONVOC_CHILD_B",
            }
        ],
        "constraints": {"derive_cannot_link_from_siblings": True},
    }
    path = tmp_path / "mapping_rules.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_scorer_task_and_cohort(tmp_path: Path) -> None:
    tree_path = _write_tree(tmp_path)
    rules_path = _write_rules(tmp_path, tree_path)

    rules = MappingRules.load(rules_path)
    tree = OnvocTree.load(tree_path)
    scorer = Scorer(rules, tree)

    task_scores = collect_task_evidence(
        scorer,
        "task:n-back",
        contrast_names=["2-back > 0-back"],
    )
    assert task_scores["ONVOC_CHILD_A"] > 0.4
    assert task_scores.get("ONVOC_CHILD_B", 0.0) >= 0.0

    base = Path("tests/fixtures/bids_min")
    phenos = load_participant_profile(base / "participants.tsv")
    modalities = extract_modalities(base / "sub-01_scans.tsv")
    hed_tags = extract_hed_tags(base / "sub-01_task-nback_events.tsv")

    cohort_scores = collect_cohort_evidence(
        scorer,
        phenotypes=phenos,
        diagnosis=phenos.get("diagnosis"),
        medications=phenos.get("medication"),
        instruments=phenos.get("instrument"),
        modalities=modalities,
        hed_tags=hed_tags,
    )

    assert cohort_scores["ONVOC_CHILD_B"] > 0.0
    assert len(cohort_scores) >= 1
