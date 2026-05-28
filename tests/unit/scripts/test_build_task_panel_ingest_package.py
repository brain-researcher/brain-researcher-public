from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build.build_task_panel_ingest_package import (
    _route_task_lane_candidate,
    build_task_panel_ingest_package,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


@pytest.mark.parametrize(
    ("source_label", "onvoc_label", "expected_reason", "expected_allow"),
    [
        ("semantic", "Semantics", "router_generic_construct", False),
        ("working memory", "Working Memory", "router_generic_construct", False),
        ("social perception", "Social Perception", "router_generic_construct", False),
        ("emotion regulation", "Emotion Regulation", "router_generic_construct", False),
        (
            "reward responsiveness",
            "Reward Responsiveness",
            "router_generic_construct",
            False,
        ),
        ("Resting-state fMRI", "Language", "router_modality_method", False),
        ("activation overlap", "Language", "router_baseline_meta", False),
        ("word generation", "Speech Production", "router_review_only", False),
        ("semantic localizers", "Semantics", "router_explicit_task_signal", True),
        (
            "emotion downregulation",
            "Emotion Regulation",
            "router_onvoc_task_context:emotion regulation",
            True,
        ),
    ],
)
def test_task_lane_router_reason_buckets(
    source_label: str,
    onvoc_label: str,
    expected_reason: str,
    expected_allow: bool,
) -> None:
    route = _route_task_lane_candidate(
        row={
            "source_label": source_label,
            "normalization": {"onvoc": {"onvoc_label": onvoc_label}},
        },
        source_labels_by_id={},
        task_matcher=None,
    )

    assert route.reason == expected_reason
    assert route.allow_task_lane is expected_allow
    assert route.input_label == source_label


def test_task_panel_package_can_fold_to_subfamily(tmp_path: Path) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 1}})

    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "onvoc_id": "ONVOC_9990003",
                "onvoc_label": "Response Inhibition",
                "method": "crosswalk_task_family",
                "reason": "crosswalk_task_family",
            }
        ],
    )

    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990003",
                "properties": {
                    "onvoc_id": "ONVOC_9990003",
                    "onvoc_label": "Response Inhibition",
                    "mapping_method": "crosswalk_task_family",
                    "mapping_reason": "crosswalk_task_family",
                },
            }
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])

    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:1"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990003",
                    "label": "Response Inhibition",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990003",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990003",
                        "onvoc_label": "Go/No-Go",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990003",
                    }
                },
            }
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:go-no-go": {
                    "primary": "ONVOC_9990003",
                }
            }
        },
    )

    taxonomy_path = tmp_path / "task_families_master.yaml"
    _write_json(
        taxonomy_path,
        {
            "families": [
                {
                    "id": "tf_conflict_inhibition",
                    "label": "Conflict & Inhibition",
                    "description": "desc",
                    "subfamilies": [
                        {
                            "id": "sf_response_inhibition",
                            "label": "Response Inhibition",
                            "paradigms": [
                                {
                                    "name": "Go/No-Go",
                                    "aliases": ["Go No Go", "Go/No-Go"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "task_panel_pkg"
    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=output_dir,
        crosswalk_path=crosswalk_path,
        task_taxonomy_path=taxonomy_path,
        task_fold_mode="subfamily",
    )

    assert summary["counts"]["task_records_kept"] == 1
    assert summary["counts"]["task_ids_canonical_total"] == 1
    assert summary["counts"]["task_records_family_matched"] == 1

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["target"]["id"].startswith("task:subfamily:")
    assert (
        records[0]["normalization"]["task_panel"]["family_id"]
        == "tf_conflict_inhibition"
    )
    assert (
        records[0]["normalization"]["task_panel"]["subfamily_id"]
        == "sf_response_inhibition"
    )

    readme_text = (output_dir / "README_task_panel_package.md").read_text(
        encoding="utf-8"
    )
    assert "--quality-profile kg_task_panel" in readme_text


def test_task_panel_package_prefers_specific_source_label_over_generic_onvoc_label(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 1}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:inclusive_face_name_fmri_task",
                "source_label": "Inclusive Face-Name fMRI Task",
                "onvoc_id": "ONVOC_9990493",
                "onvoc_label": "Episodic Memory",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            }
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990493",
                "properties": {
                    "onvoc_id": "ONVOC_9990493",
                    "onvoc_label": "Episodic Memory",
                    "mapping_method": "crosswalk_label",
                    "mapping_reason": "crosswalk_label_exact",
                },
            }
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:42"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990493",
                    "label": "Episodic Memory",
                    "original_id": "concept:inclusive_face_name_fmri_task",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990493",
                    "original_canonical_id": "concept:inclusive_face_name_fmri_task",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990493",
                        "onvoc_label": "Episodic Memory",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990493",
                    }
                },
            }
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:associative_memory": {
                    "primary": "ONVOC_9990493",
                }
            }
        },
    )

    taxonomy_path = tmp_path / "task_families_master.yaml"
    _write_json(
        taxonomy_path,
        {
            "families": [
                {
                    "id": "tf_ltm_declarative",
                    "label": "Long-Term Declarative Memory",
                    "description": "desc",
                    "subfamilies": [
                        {
                            "id": "sf_item_recognition",
                            "label": "Item Recognition",
                            "paradigms": [
                                {
                                    "name": "Old/New Recognition (Yes/No)",
                                }
                            ],
                        },
                        {
                            "id": "sf_associative_memory",
                            "label": "Associative Memory",
                            "paradigms": [
                                {
                                    "name": "Paired-Associate Learning (PAL)",
                                }
                            ],
                        },
                    ],
                }
            ]
        },
    )

    alias_extensions_path = tmp_path / "task_family_alias_extensions.yaml"
    _write_json(
        alias_extensions_path,
        {
            "aliases": [
                {
                    "alias": "episodic memory",
                    "family_id": "tf_ltm_declarative",
                    "subfamily_id": "sf_item_recognition",
                    "paradigm_name": "Old/New Recognition (Yes/No)",
                },
                {
                    "alias": "inclusive face-name fmri task",
                    "family_id": "tf_ltm_declarative",
                    "subfamily_id": "sf_associative_memory",
                    "paradigm_name": "Paired-Associate Learning (PAL)",
                },
            ]
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_source_first",
        crosswalk_path=crosswalk_path,
        task_taxonomy_path=taxonomy_path,
        task_alias_extensions_path=alias_extensions_path,
        task_fold_mode="subfamily",
    )

    assert summary["counts"]["task_records_kept"] == 1
    assert summary["counts"]["task_records_family_matched"] == 1
    assert summary["counts"]["task_records_family_unmatched"] == 0

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_panel_norm = records[0]["normalization"]["task_panel"]
    assert task_panel_norm["family_id"] == "tf_ltm_declarative"
    assert task_panel_norm["subfamily_id"] == "sf_associative_memory"
    assert (
        task_panel_norm["family_match_input_label"] == "Inclusive Face-Name fMRI Task"
    )
    assert (
        task_panel_norm["router_input_label"] == "Inclusive Face-Name fMRI Task"
    )
    assert (
        task_panel_norm["family_match_resolved_label"]
        == "Inclusive Face-Name fMRI Task"
    )
    assert task_panel_norm["family_match_method"] == "exact_alias"
    assert records[0]["target"]["id"] == "task:subfamily:sf_associative_memory"


def test_task_panel_package_uses_mapping_source_labels_for_alias_fold(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 3}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:semantic_localizers",
                "source_label": "semantic localizers",
                "onvoc_id": "ONVOC_9990477",
                "onvoc_label": "Semantics",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
            {
                "status": "mapped",
                "source_id": "concept:phonological_localizers",
                "source_label": "phonological localizers",
                "onvoc_id": "ONVOC_9990475",
                "onvoc_label": "Phonological Processing",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
            {
                "status": "mapped",
                "source_id": "concept:inclusive_face_name_fmri_task",
                "source_label": "Inclusive Face-Name fMRI Task",
                "onvoc_id": "ONVOC_9990493",
                "onvoc_label": "Episodic Memory",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990477",
                "properties": {"onvoc_id": "ONVOC_9990477"},
            },
            {
                "target_id": "concept:ONVOC_9990475",
                "properties": {"onvoc_id": "ONVOC_9990475"},
            },
            {
                "target_id": "concept:ONVOC_9990493",
                "properties": {"onvoc_id": "ONVOC_9990493"},
            },
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])

    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:1"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990477",
                    "label": "Semantics",
                    "original_id": "concept:semantic_localizers",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990477",
                    "original_canonical_id": "concept:semantic_localizers",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990477",
                        "onvoc_label": "Semantics",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990477",
                    }
                },
            },
            {
                "paper": {"id": "pmid:2"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990475",
                    "label": "Phonological Processing",
                    "original_id": "concept:phonological_localizers",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990475",
                    "original_canonical_id": "concept:phonological_localizers",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990475",
                        "onvoc_label": "Phonological Processing",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990475",
                    }
                },
            },
            {
                "paper": {"id": "pmid:3"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990493",
                    "label": "Episodic Memory",
                    "original_id": "concept:inclusive_face_name_fmri_task",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990493",
                    "original_canonical_id": "concept:inclusive_face_name_fmri_task",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990493",
                        "onvoc_label": "Episodic Memory",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990493",
                    }
                },
            },
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:semantic_processing": {"primary": "ONVOC_9990477"},
                "task:phonological_processing": {"primary": "ONVOC_9990475"},
                "task:associative_memory": {"primary": "ONVOC_9990493"},
            }
        },
    )

    taxonomy_path = tmp_path / "task_families_master.yaml"
    _write_json(
        taxonomy_path,
        {
            "families": [
                {
                    "id": "tf_language_semantic",
                    "label": "Language",
                    "description": "desc",
                    "subfamilies": [
                        {
                            "id": "sf_semantic_processing",
                            "label": "Semantic Processing",
                            "paradigms": [
                                {
                                    "name": "Semantic Decision / Category Verification",
                                    "aliases": ["semantic decision"],
                                }
                            ],
                        },
                        {
                            "id": "sf_phonology_morphology",
                            "label": "Phonology",
                            "paradigms": [
                                {
                                    "name": "Rhyme Judgment / Phonological Decision",
                                    "aliases": ["phonological processing"],
                                }
                            ],
                        },
                    ],
                },
                {
                    "id": "tf_ltm_declarative",
                    "label": "Long-term Memory",
                    "description": "desc",
                    "subfamilies": [
                        {
                            "id": "sf_associative_memory",
                            "label": "Associative Memory",
                            "paradigms": [
                                {
                                    "name": "Paired-Associate Learning (PAL)",
                                    "aliases": ["associative memory"],
                                }
                            ],
                        }
                    ],
                },
            ]
        },
    )

    alias_extensions_path = tmp_path / "task_family_alias_extensions.yaml"
    _write_json(
        alias_extensions_path,
        {
            "aliases": [
                {
                    "alias": "semantic localizers",
                    "family_id": "tf_language_semantic",
                    "subfamily_id": "sf_semantic_processing",
                    "paradigm_name": "Semantic Decision / Category Verification",
                },
                {
                    "alias": "phonological localizers",
                    "family_id": "tf_language_semantic",
                    "subfamily_id": "sf_phonology_morphology",
                    "paradigm_name": "Rhyme Judgment / Phonological Decision",
                },
                {
                    "alias": "inclusive face-name fmri task",
                    "family_id": "tf_ltm_declarative",
                    "subfamily_id": "sf_associative_memory",
                    "paradigm_name": "Paired-Associate Learning (PAL)",
                },
            ]
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_aliases",
        crosswalk_path=crosswalk_path,
        task_taxonomy_path=taxonomy_path,
        task_alias_extensions_path=alias_extensions_path,
        task_fold_mode="subfamily",
    )

    assert summary["counts"]["task_records_kept"] == 3
    assert summary["counts"]["task_records_family_matched"] == 3
    assert summary["counts"]["task_records_family_unmatched"] == 0

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_input = {
        record["normalization"]["task_panel"]["family_match_input_label"]: record
        for record in records
    }
    assert by_input["semantic localizers"]["normalization"]["task_panel"][
        "subfamily_id"
    ] == ("sf_semantic_processing")
    assert (
        by_input["semantic localizers"]["normalization"]["task_panel"][
            "family_match_input_label"
        ]
        == by_input["semantic localizers"]["normalization"]["task_panel"][
            "router_input_label"
        ]
    )
    assert (
        by_input["semantic localizers"]["normalization"]["task_panel"][
            "family_match_resolved_label"
        ]
        == "semantic localizers"
    )
    assert by_input["phonological localizers"]["normalization"]["task_panel"][
        "subfamily_id"
    ] == ("sf_phonology_morphology")
    assert (
        by_input["phonological localizers"]["normalization"]["task_panel"][
            "family_match_input_label"
        ]
        == by_input["phonological localizers"]["normalization"]["task_panel"][
            "router_input_label"
        ]
    )
    assert (
        by_input["phonological localizers"]["normalization"]["task_panel"][
            "family_match_resolved_label"
        ]
        == "phonological localizers"
    )
    assert (
        by_input["Inclusive Face-Name fMRI Task"]["normalization"]["task_panel"][
            "subfamily_id"
        ]
        == "sf_associative_memory"
    )
    assert (
        by_input["Inclusive Face-Name fMRI Task"]["normalization"]["task_panel"][
            "family_match_input_label"
        ]
        == by_input["Inclusive Face-Name fMRI Task"]["normalization"]["task_panel"][
            "router_input_label"
        ]
    )
    assert (
        by_input["Inclusive Face-Name fMRI Task"]["normalization"]["task_panel"][
            "family_match_resolved_label"
        ]
        == "Inclusive Face-Name fMRI Task"
    )
    assert (
        by_input["semantic localizers"]["normalization"]["task_panel"][
            "router_input_label"
        ]
        == "semantic localizers"
    )
    assert (
        by_input["phonological localizers"]["normalization"]["task_panel"][
            "router_input_label"
        ]
        == "phonological localizers"
    )
    assert (
        by_input["Inclusive Face-Name fMRI Task"]["normalization"]["task_panel"][
            "router_input_label"
        ]
        == "Inclusive Face-Name fMRI Task"
    )


def test_task_panel_package_canonicalizes_publication_identity_before_packaging(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 1}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:word_reading",
                "source_label": "word reading",
                "onvoc_id": "ONVOC_9990478",
                "onvoc_label": "Reading Comprehension",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            }
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990478",
                "properties": {
                    "onvoc_id": "ONVOC_9990478",
                    "onvoc_label": "Reading Comprehension",
                },
            }
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {
                    "id": "paper:10_1007_s00426_021_01479_5",
                    "pmid": " 12345678 ",
                    "doi": "10.1007/S00426-021-01479-5",
                    "title": "Reading study",
                },
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990478",
                    "label": "Reading Comprehension",
                    "original_id": "concept:word_reading",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990478",
                    "original_canonical_id": "concept:word_reading",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990478",
                        "onvoc_label": "Reading Comprehension",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990478",
                    }
                },
            }
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:reading": {"primary": "ONVOC_9990478"},
            }
        },
    )

    taxonomy_path = tmp_path / "task_families_master.yaml"
    _write_json(
        taxonomy_path,
        {
            "families": [
                {
                    "id": "tf_language_semantic",
                    "label": "Language",
                    "description": "desc",
                    "subfamilies": [
                        {
                            "id": "sf_lexical_access_orthography",
                            "label": "Lexical Access",
                            "paradigms": [{"name": "Reading Comprehension"}],
                        }
                    ],
                }
            ]
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_pubcanon",
        crosswalk_path=crosswalk_path,
        task_taxonomy_path=taxonomy_path,
        task_fold_mode="subfamily",
    )

    assert summary["counts"]["task_records_kept"] == 1
    assert summary["counts"]["publication_ids_canonicalized"] == 1

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["paper"]["id"] == "pmid:12345678"
    assert records[0]["paper"]["original_id"] == "paper:10_1007_s00426_021_01479_5"
    assert records[0]["paper"]["doi"] == "10.1007/s00426-021-01479-5"


def test_task_panel_package_reroutes_generic_constructs_out_of_task_lane(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 2}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:attention",
                "source_label": "attention",
                "onvoc_id": "ONVOC_9990466",
                "onvoc_label": "Cognitive Inhibition",
                "method": "crosswalk_task_family",
                "reason": "crosswalk_task_alias_fuzzy",
            },
            {
                "status": "mapped",
                "source_id": "concept:word_reading",
                "source_label": "word reading",
                "onvoc_id": "ONVOC_9990478",
                "onvoc_label": "Reading Comprehension",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990466",
                "properties": {
                    "onvoc_id": "ONVOC_9990466",
                    "onvoc_label": "Cognitive Inhibition",
                    "source_label": "attention",
                },
            },
            {
                "target_id": "concept:ONVOC_9990478",
                "properties": {
                    "onvoc_id": "ONVOC_9990478",
                    "onvoc_label": "Reading Comprehension",
                    "source_label": "word reading",
                },
            },
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:11", "title": "Attention paper"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990466",
                    "label": "Cognitive Inhibition",
                    "original_id": "concept:attention",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990466",
                    "original_canonical_id": "concept:attention",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990466",
                        "onvoc_label": "Cognitive Inhibition",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990466",
                    }
                },
            },
            {
                "paper": {"id": "pmid:12", "title": "Reading paper"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990478",
                    "label": "Reading Comprehension",
                    "original_id": "concept:word_reading",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990478",
                    "original_canonical_id": "concept:word_reading",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990478",
                        "onvoc_label": "Reading Comprehension",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990478",
                    }
                },
            },
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:cognitive-inhibition": {"primary": "ONVOC_9990466"},
                "task:reading": {"primary": "ONVOC_9990478"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_router_construct",
        crosswalk_path=crosswalk_path,
        task_fold_mode="onvoc",
    )

    assert summary["counts"]["mapping_rows_task_kept"] == 1
    assert summary["counts"]["task_records_kept"] == 1
    assert summary["counts"]["task_router_rejected"] >= 1
    assert summary["task_router_reason_counts"]["router_generic_construct"] >= 1

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["paper"]["id"] == "pmid:12"
    assert records[0]["normalization"]["task_panel"]["router_reason"] == (
        "router_explicit_task_signal"
    )
    assert records[0]["normalization"]["task_panel"]["router_input_label"] == (
        "word reading"
    )


def test_task_panel_package_reroutes_modality_labels_out_of_task_lane(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 2}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:resting_state_fmri",
                "source_label": "Resting-state fMRI",
                "onvoc_id": "ONVOC_9990431",
                "onvoc_label": "Language",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
            {
                "status": "mapped",
                "source_id": "concept:semantic_localizers",
                "source_label": "semantic localizers",
                "onvoc_id": "ONVOC_9990477",
                "onvoc_label": "Semantics",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990431",
                "properties": {
                    "onvoc_id": "ONVOC_9990431",
                    "onvoc_label": "Language",
                    "source_label": "Resting-state fMRI",
                },
            },
            {
                "target_id": "concept:ONVOC_9990477",
                "properties": {
                    "onvoc_id": "ONVOC_9990477",
                    "onvoc_label": "Semantics",
                    "source_label": "semantic localizers",
                },
            },
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:21"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990431",
                    "label": "Language",
                    "original_id": "concept:resting_state_fmri",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990431",
                    "original_canonical_id": "concept:resting_state_fmri",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990431",
                        "onvoc_label": "Language",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990431",
                    }
                },
            },
            {
                "paper": {"id": "pmid:22"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990477",
                    "label": "Semantics",
                    "original_id": "concept:semantic_localizers",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990477",
                    "original_canonical_id": "concept:semantic_localizers",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990477",
                        "onvoc_label": "Semantics",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990477",
                    }
                },
            },
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:language": {"primary": "ONVOC_9990431"},
                "task:semantic_processing": {"primary": "ONVOC_9990477"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_router_modality",
        crosswalk_path=crosswalk_path,
        task_fold_mode="onvoc",
    )

    assert summary["counts"]["mapping_rows_task_kept"] == 1
    assert summary["counts"]["task_records_kept"] == 1
    assert summary["task_router_reason_counts"]["router_modality_method"] >= 1

    records_path = Path(summary["artifacts"]["task_panel_records"])
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["paper"]["id"] == "pmid:22"
    assert records[0]["normalization"]["task_panel"]["router_input_label"] == (
        "semantic localizers"
    )


def test_task_panel_package_keeps_response_inhibition_phrase(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 1}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:response_inhibition",
                "source_label": "response inhibition",
                "onvoc_id": "ONVOC_9990466",
                "onvoc_label": "Cognitive Inhibition",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            }
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990466",
                "properties": {
                    "onvoc_id": "ONVOC_9990466",
                    "onvoc_label": "Cognitive Inhibition",
                    "source_label": "response inhibition",
                },
            }
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:31"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990466",
                    "label": "Cognitive Inhibition",
                    "original_id": "concept:response_inhibition",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990466",
                    "original_canonical_id": "concept:response_inhibition",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990466",
                        "onvoc_label": "Cognitive Inhibition",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990466",
                    }
                },
            }
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:response_inhibition": {"primary": "ONVOC_9990466"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_response_inhibition",
        crosswalk_path=crosswalk_path,
        task_fold_mode="onvoc",
    )

    assert summary["counts"]["task_records_kept"] == 1
    assert summary["task_router_reason_counts"]["router_explicit_task_signal"] >= 1

    records = [
        json.loads(line)
        for line in Path(summary["artifacts"]["task_panel_records"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert records[0]["normalization"]["task_panel"]["router_input_label"] == (
        "response inhibition"
    )


def test_task_panel_package_keeps_onvoc_context_task_phrases(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 2}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:recall",
                "source_label": "recall",
                "onvoc_id": "ONVOC_9990493",
                "onvoc_label": "Episodic Memory",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
            {
                "status": "mapped",
                "source_id": "concept:emotion_downregulation",
                "source_label": "emotion downregulation",
                "onvoc_id": "ONVOC_9990462",
                "onvoc_label": "Emotion Regulation",
                "method": "crosswalk_task_family",
                "reason": "crosswalk_task_family",
            },
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990493",
                "properties": {
                    "onvoc_id": "ONVOC_9990493",
                    "onvoc_label": "Episodic Memory",
                    "source_label": "recall",
                },
            },
            {
                "target_id": "concept:ONVOC_9990462",
                "properties": {
                    "onvoc_id": "ONVOC_9990462",
                    "onvoc_label": "Emotion Regulation",
                    "source_label": "emotion downregulation",
                },
            },
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:41"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990493",
                    "label": "Episodic Memory",
                    "original_id": "concept:recall",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990493",
                    "original_canonical_id": "concept:recall",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990493",
                        "onvoc_label": "Episodic Memory",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990493",
                    }
                },
            },
            {
                "paper": {"id": "pmid:42"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990462",
                    "label": "Emotion Regulation",
                    "original_id": "concept:emotion_downregulation",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990462",
                    "original_canonical_id": "concept:emotion_downregulation",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990462",
                        "onvoc_label": "Emotion Regulation",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990462",
                    }
                },
            },
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:episodic-memory": {"primary": "ONVOC_9990493"},
                "task:emotion-regulation": {"primary": "ONVOC_9990462"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_onvoc_context",
        crosswalk_path=crosswalk_path,
        task_fold_mode="onvoc",
    )

    assert summary["counts"]["task_records_kept"] == 2
    assert (
        summary["task_router_reason_counts"]["router_onvoc_task_context:episodic memory"]
        >= 1
    )
    assert (
        summary["task_router_reason_counts"][
            "router_onvoc_task_context:emotion regulation"
        ]
        >= 1
    )


def test_task_panel_package_rejects_plain_generic_concepts_but_keeps_task_phrases(
    tmp_path: Path,
) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 8}})
    rows = [
        {
            "paper_id": "pmid:81",
            "source_id": "concept:semantic",
            "source_label": "semantic",
            "onvoc_id": "ONVOC_9990477",
            "onvoc_label": "Semantics",
        },
        {
            "paper_id": "pmid:82",
            "source_id": "concept:semantic_localizers",
            "source_label": "semantic localizers",
            "onvoc_id": "ONVOC_9990477",
            "onvoc_label": "Semantics",
        },
        {
            "paper_id": "pmid:83",
            "source_id": "concept:working_memory",
            "source_label": "working memory",
            "onvoc_id": "ONVOC_9990450",
            "onvoc_label": "Working Memory",
        },
        {
            "paper_id": "pmid:84",
            "source_id": "concept:response_inhibition",
            "source_label": "response inhibition",
            "onvoc_id": "ONVOC_9990466",
            "onvoc_label": "Cognitive Inhibition",
        },
        {
            "paper_id": "pmid:85",
            "source_id": "concept:social_perception",
            "source_label": "social perception",
            "onvoc_id": "ONVOC_9990503",
            "onvoc_label": "Social Perception",
        },
        {
            "paper_id": "pmid:86",
            "source_id": "concept:emotion_regulation",
            "source_label": "emotion regulation",
            "onvoc_id": "ONVOC_9990462",
            "onvoc_label": "Emotion Regulation",
        },
        {
            "paper_id": "pmid:87",
            "source_id": "concept:reward_responsiveness",
            "source_label": "reward responsiveness",
            "onvoc_id": "ONVOC_9990610",
            "onvoc_label": "Reward Responsiveness",
        },
        {
            "paper_id": "pmid:88",
            "source_id": "concept:emotion_downregulation",
            "source_label": "emotion downregulation",
            "onvoc_id": "ONVOC_9990462",
            "onvoc_label": "Emotion Regulation",
        },
    ]
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": row["source_id"],
                "source_label": row["source_label"],
                "onvoc_id": row["onvoc_id"],
                "onvoc_label": row["onvoc_label"],
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            }
            for row in rows
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": f"concept:{row['onvoc_id']}",
                "properties": {
                    "onvoc_id": row["onvoc_id"],
                    "onvoc_label": row["onvoc_label"],
                    "source_label": row["source_label"],
                },
            }
            for row in rows
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": row["paper_id"]},
                "target": {
                    "type": "Concept",
                    "id": f"concept:{row['onvoc_id']}",
                    "label": row["onvoc_label"],
                    "original_id": row["source_id"],
                },
                "mapping": {
                    "canonical_id": f"concept:{row['onvoc_id']}",
                    "original_canonical_id": row["source_id"],
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": row["onvoc_id"],
                        "onvoc_label": row["onvoc_label"],
                        "onvoc_uri": f"https://w3id.org/onvoc/{row['onvoc_id']}",
                    }
                },
            }
            for row in rows
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:semantic-processing": {"primary": "ONVOC_9990477"},
                "task:working-memory": {"primary": "ONVOC_9990450"},
                "task:response-inhibition": {"primary": "ONVOC_9990466"},
                "task:social-perception": {"primary": "ONVOC_9990503"},
                "task:emotion-regulation": {"primary": "ONVOC_9990462"},
                "task:reward": {"primary": "ONVOC_9990610"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_generic_concepts",
        crosswalk_path=crosswalk_path,
        task_fold_mode="onvoc",
    )

    assert summary["counts"]["task_records_kept"] == 3
    assert summary["counts"]["mapping_rows_task_kept"] == 3
    assert summary["counts"]["task_router_rejected"] >= 5
    assert summary["task_router_reason_counts"]["router_generic_construct"] >= 5
    assert summary["task_router_reason_counts"]["router_explicit_task_signal"] >= 2
    assert (
        summary["task_router_reason_counts"][
            "router_onvoc_task_context:emotion regulation"
        ]
        >= 1
    )

    records = [
        json.loads(line)
        for line in Path(summary["artifacts"]["task_panel_records"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    by_paper = {record["paper"]["id"]: record for record in records}
    assert set(by_paper) == {"pmid:82", "pmid:84", "pmid:88"}
    assert by_paper["pmid:82"]["normalization"]["task_panel"]["router_input_label"] == (
        "semantic localizers"
    )
    assert by_paper["pmid:84"]["normalization"]["task_panel"]["router_input_label"] == (
        "response inhibition"
    )
    assert by_paper["pmid:88"]["normalization"]["task_panel"]["router_input_label"] == (
        "emotion downregulation"
    )


def test_task_panel_package_keeps_alias_driven_task_labels(tmp_path: Path) -> None:
    onvoc_dir = tmp_path / "onvoc"
    onvoc_dir.mkdir(parents=True, exist_ok=True)

    _write_json(onvoc_dir / "report_onvoc.json", {"summary": {"maps_to_edges": 2}})
    _write_jsonl(
        onvoc_dir / "mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:word_generation",
                "source_label": "word generation",
                "onvoc_id": "ONVOC_9990479",
                "onvoc_label": "Speech Production",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
            {
                "status": "mapped",
                "source_id": "concept:attentional_orienting",
                "source_label": "attentional orienting",
                "onvoc_id": "ONVOC_9990447",
                "onvoc_label": "Spatial Attention",
                "method": "crosswalk_label",
                "reason": "crosswalk_label_exact",
            },
        ],
    )
    _write_jsonl(
        onvoc_dir / "edges_maps_to.jsonl",
        [
            {
                "target_id": "concept:ONVOC_9990479",
                "properties": {
                    "onvoc_id": "ONVOC_9990479",
                    "onvoc_label": "Speech Production",
                    "source_label": "word generation",
                },
            },
            {
                "target_id": "concept:ONVOC_9990447",
                "properties": {
                    "onvoc_id": "ONVOC_9990447",
                    "onvoc_label": "Spatial Attention",
                    "source_label": "attentional orienting",
                },
            },
        ],
    )
    _write_jsonl(onvoc_dir / "edges_same_as.jsonl", [])
    _write_jsonl(
        onvoc_dir / "kggen_normalized_onvoc.jsonl",
        [
            {
                "paper": {"id": "pmid:51", "title": "Word generation paper"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990479",
                    "label": "Speech Production",
                    "original_id": "concept:word_generation",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990479",
                    "original_canonical_id": "concept:word_generation",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990479",
                        "onvoc_label": "Speech Production",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990479",
                    }
                },
            },
            {
                "paper": {"id": "pmid:52", "title": "Orienting paper"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ONVOC_9990447",
                    "label": "Spatial Attention",
                    "original_id": "concept:attentional_orienting",
                },
                "mapping": {
                    "canonical_id": "concept:ONVOC_9990447",
                    "original_canonical_id": "concept:attentional_orienting",
                    "mapping_type": "synonym",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_9990447",
                        "onvoc_label": "Spatial Attention",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_9990447",
                    }
                },
            },
        ],
    )

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    _write_json(
        crosswalk_path,
        {
            "tasks": {
                "task:speech-production": {"primary": "ONVOC_9990479"},
                "task:spatial-attention": {"primary": "ONVOC_9990447"},
            }
        },
    )

    summary = build_task_panel_ingest_package(
        onvoc_dir=onvoc_dir,
        output_dir=tmp_path / "task_panel_pkg_alias_rescue",
        crosswalk_path=crosswalk_path,
        task_fold_mode="subfamily",
        task_taxonomy_path=Path("configs/taxonomy/exports/task_families_master.yaml"),
        task_alias_extensions_path=Path(
            "configs/taxonomy/exports/task_family_alias_extensions.yaml"
        ),
    )

    assert summary["counts"]["task_records_kept"] == 2
    assert summary["task_router_reason_counts"]["router_task_family_exact_alias"] >= 1
    assert summary["task_router_reason_counts"]["router_explicit_task_signal"] >= 1

    records = [
        json.loads(line)
        for line in Path(summary["artifacts"]["task_panel_records"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    by_paper = {record["paper"]["id"]: record for record in records}
    assert (
        by_paper["pmid:51"]["normalization"]["task_panel"]["router_input_label"]
        == "word generation"
    )
    assert (
        by_paper["pmid:51"]["normalization"]["task_panel"]["family_match_input_label"]
        == "word generation"
    )
    assert (
        by_paper["pmid:51"]["normalization"]["task_panel"][
            "family_match_resolved_label"
        ]
        == "word generation"
    )
    assert (
        by_paper["pmid:51"]["normalization"]["task_panel"]["subfamily_id"]
        == "sf_language_production"
    )
    assert (
        by_paper["pmid:52"]["normalization"]["task_panel"]["router_input_label"]
        == "attentional orienting"
    )
    assert (
        by_paper["pmid:52"]["normalization"]["task_panel"]["family_match_input_label"]
        == "attentional orienting"
    )
    assert (
        by_paper["pmid:52"]["normalization"]["task_panel"][
            "family_match_resolved_label"
        ]
        == "attentional orienting"
    )
    assert (
        by_paper["pmid:52"]["normalization"]["task_panel"]["router_reason"]
        == "router_explicit_task_signal"
    )
    assert (
        by_paper["pmid:52"]["normalization"]["task_panel"]["subfamily_id"]
        == "sf_spatial_orienting_cueing"
    )
