from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brain_researcher.services.br_kg.task_family_matcher import (
    TaskFamilyMatcher,
    build_task_family_tree,
    normalize_task_label,
)


def _write_taxonomy(path: Path) -> None:
    payload = {
        "families": [
            {
                "id": "tf_working_memory",
                "label": "Working Memory",
                "description": "Working memory tasks.",
                "subfamilies": [
                    {
                        "id": "sf_wm_updating_streaming",
                        "label": "WM Updating in Streams",
                        "paradigms": [
                            {
                                "name": "n-back",
                                "aliases": ["n back", "one-back"],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "tf_attention",
                "label": "Attention",
                "description": "Attention tasks.",
                "subfamilies": [
                    {
                        "id": "sf_auditory_attention",
                        "label": "Auditory Attention",
                        "paradigms": [
                            {"name": "auditory oddball"},
                            {"name": "visual oddball"},
                        ],
                    }
                ],
            },
        ]
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _write_alias_extensions(path: Path) -> None:
    payload = {
        "aliases": [
            {
                "alias": "2-back task",
                "family_id": "tf_working_memory",
                "subfamily_id": "sf_wm_updating_streaming",
                "paradigm_name": "n-back",
            },
            {
                # Existing taxonomy alias should remain authoritative.
                "alias": "one-back",
                "family_id": "tf_attention",
                "subfamily_id": "sf_auditory_attention",
                "paradigm_name": "auditory oddball",
            },
        ]
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_normalize_task_label_strips_parenthetical_and_suffix():
    assert normalize_task_label("(Visuo)Motor Tracing Task") == "motor tracing"
    assert normalize_task_label("0-back/2-back Task") == "0 back 2 back"


def test_match_exact_alias(tmp_path):
    taxonomy_path = tmp_path / "taxonomy.yaml"
    _write_taxonomy(taxonomy_path)
    matcher = TaskFamilyMatcher(taxonomy_path=taxonomy_path, enable_fuzzy=True)

    record, method, score = matcher.match("one-back task")

    assert record is not None
    assert record.family_id == "tf_working_memory"
    assert method == "exact_alias"
    assert score == 1.0


def test_match_aggressive_fuzzy_guarded(tmp_path):
    pytest.importorskip("rapidfuzz")

    taxonomy_path = tmp_path / "taxonomy.yaml"
    _write_taxonomy(taxonomy_path)
    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        fuzzy_threshold=0.9,
        aggressive_mode=True,
        aggressive_primary_threshold=0.6,
        aggressive_secondary_threshold=0.5,
        min_token_overlap=1,
        ambiguity_margin=0.03,
    )

    record, method, score = matcher.match("nback working memory challenge")

    assert record is not None
    assert record.family_id == "tf_working_memory"
    assert method == "aggressive_fuzzy_guarded"
    assert score is not None
    assert score >= 0.5


def test_match_rejects_noise_labels(tmp_path):
    taxonomy_path = tmp_path / "taxonomy.yaml"
    _write_taxonomy(taxonomy_path)
    matcher = TaskFamilyMatcher(taxonomy_path=taxonomy_path, enable_fuzzy=True)

    record, method, score = matcher.match("18F-FDG-PET")

    assert record is None
    assert method == "noise_rejected"
    assert score is None


def test_match_rejects_ambiguous_label(tmp_path):
    pytest.importorskip("rapidfuzz")

    taxonomy_path = tmp_path / "taxonomy.yaml"
    _write_taxonomy(taxonomy_path)
    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        aggressive_mode=True,
        aggressive_primary_threshold=0.4,
        aggressive_secondary_threshold=0.4,
        min_token_overlap=1,
        ambiguity_margin=0.2,
    )

    record, method, score = matcher.match("oddball task")

    assert record is None
    assert method == "ambiguous_rejected"
    assert score is None


def test_alias_extensions_add_new_alias_without_overriding_taxonomy(tmp_path):
    taxonomy_path = tmp_path / "taxonomy.yaml"
    alias_extensions_path = tmp_path / "aliases.yaml"
    _write_taxonomy(taxonomy_path)
    _write_alias_extensions(alias_extensions_path)

    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        enable_fuzzy=True,
    )

    record_new, method_new, score_new = matcher.match("2-back task")
    assert record_new is not None
    assert record_new.family_id == "tf_working_memory"
    assert method_new == "exact_alias"
    assert score_new == 1.0

    # "one-back" exists in taxonomy already and should not be overridden by extension.
    record_existing, method_existing, score_existing = matcher.match("one-back")
    assert record_existing is not None
    assert record_existing.family_id == "tf_working_memory"
    assert method_existing == "exact_alias"
    assert score_existing == 1.0


def test_repo_alias_extensions_cover_salvaged_task_labels():
    taxonomy_path = Path("configs/taxonomy/exports/task_families_master.yaml")
    alias_extensions_path = Path(
        "configs/taxonomy/exports/task_family_alias_extensions.yaml"
    )

    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        enable_fuzzy=True,
    )

    cases = {
        "semantic localizers": "sf_semantic_processing",
        "phonological localizers": "sf_phonology_morphology",
        "inclusive face-name fmri task": "sf_associative_memory",
        "semantics": "sf_semantic_processing",
        "conversational implicature": "sf_discourse_pragmatics_prosody",
        "ci processing": "sf_discourse_pragmatics_prosody",
        "word generation": "sf_language_production",
        "overt word generation": "sf_language_production",
        "visual feature search": "sf_visual_search_capture",
        "social perception": "sf_social_perception_attention",
        "face processing": "sf_social_perception_attention",
        "personally familiar faces": "sf_social_perception_attention",
        "face emotion processing": "sf_social_perception_attention",
        "familiarity": "sf_familiarity_exposure",
    }

    for label, expected_subfamily in cases.items():
        record, method, score = matcher.match(label)
        assert record is not None
        assert record.subfamily_id == expected_subfamily
        assert method == "exact_alias"
        assert score == 1.0


def test_build_task_family_tree_counts_and_unmapped_order():
    entities = [
        {
            "id": "task:nback",
            "label": "N-back",
            "display_label": "N-back",
            "family_id": "tf_working_memory",
            "family_label": "Working Memory",
            "subfamily_id": "sf_wm_updating_streaming",
            "subfamily_label": "WM Updating in Streams",
        },
        {
            "id": "task:noise",
            "label": "18F-FDG-PET",
            "display_label": "18F-FDG-PET",
            "family_id": None,
            "subfamily_id": None,
        },
    ]

    tree = build_task_family_tree(entities, include_unmapped=True)

    assert len(tree) == 2
    assert tree[0]["id"] == "tf_working_memory"
    assert tree[0]["task_count"] == 1
    assert tree[0]["children"][0]["task_count"] == 1
    assert tree[-1]["id"] == "tf_unmapped"
    assert tree[-1]["task_count"] == 1
    assert tree[-1]["children"][0]["task_count"] == 1
