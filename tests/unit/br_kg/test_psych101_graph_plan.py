from __future__ import annotations

from pathlib import Path

import yaml

from brain_researcher.services.br_kg.etl.loaders.psych101_loader import (
    build_psych101_graph_plan,
    ingest_psych101,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


def _write_taxonomy(path: Path) -> None:
    payload = {
        "families": [
            {
                "id": "tf_working_memory",
                "label": "Working Memory",
                "description": "Working memory and updating tasks.",
                "subfamilies": [
                    {
                        "id": "sf_wm_updating_streaming",
                        "label": "WM Updating in Streams",
                        "paradigms": [
                            {
                                "name": "n-back",
                                "aliases": ["2-back", "2 back"],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _write_guardrail_taxonomy(path: Path) -> None:
    payload = {
        "families": [
            {
                "id": "tf_localizers_baseline",
                "label": "Functional Localizers & Baseline Tasks",
                "description": "Localizer tasks.",
                "subfamilies": [
                    {
                        "id": "sf_attention_control_networks",
                        "label": "Attention & Control Network Localizers",
                        "paradigms": [
                            {
                                "name": "Default Mode Network (DMN) Localizer",
                                "aliases": ["default"],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _write_curated_registry(path: Path, mappings: list[dict] | None = None) -> None:
    payload = {
        "version": 1,
        "ruleset_version": "test",
        "description": "Test-only curated registry.",
        "defaults": {"source": "psych101_curated_registry"},
        "mappings": mappings or [],
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_build_graph_plan_uses_canonical_task_family_ids(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_taxonomy(taxonomy_path)
    _write_curated_registry(registry_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    plan = build_psych101_graph_plan(
        {
            "dataset_id": "psych101",
            "title": "Psych-101",
        },
        [
            {
                "experiment_id": "peterson2021using/2-back/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "peterson2021using/2-back/exp1.csv",
                "n_participants": 2,
                "n_trials": 20,
            }
        ],
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    experiment = plan.normalized_experiments[0]
    assert experiment["experiment_path"] == "peterson2021using/2-back/exp1.csv"
    assert experiment["task_family_id"] == "tf_working_memory"
    assert experiment["task_subfamily_id"] == "sf_wm_updating_streaming"
    assert experiment["task_paradigm_name"] == "n-back"
    assert experiment["name"] == "n-back"

    family_node = next(
        node for node in plan.nodes if node["node_id"] == "tf_working_memory"
    )
    assert family_node["labels"] == ["TaskFamily"]
    assert family_node["properties"]["family_label"] == "Working Memory"

    task_node = next(
        node for node in plan.nodes if node["labels"] == ["Task"] and node["properties"]["name"] == "n-back"
    )
    assert task_node["properties"]["family_id"] == "tf_working_memory"
    assert task_node["properties"]["subfamily_id"] == "sf_wm_updating_streaming"
    assert task_node["properties"]["description"] is None

    assert any(
        rel["start_node"] == "peterson2021using/2-back/exp1.csv"
        and rel["end_node"] == "tf_working_memory"
        and rel["rel_type"] == "CLASSIFIED_UNDER"
        for rel in plan.relationships
    )
    assert any(
        rel["start_node"] == task_node["node_id"]
        and rel["end_node"] == "tf_working_memory"
        and rel["rel_type"] == "BELONGS_TO_FAMILY"
        for rel in plan.relationships
    )


def test_task_ontology_candidates_skip_generic_names_and_artifact_paths(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(registry_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    from brain_researcher.services.br_kg.etl.loaders.psych101_loader import (
        Psych101IngestLoader,
    )

    loader = Psych101IngestLoader(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )
    candidates = loader._task_ontology_candidates(
        {
            "experiment_name": "exp1",
            "experiment_path": "badham2017deficits/exp1.csv",
            "source_files": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet",
            "description": "You will be shown several examples of geometric objects.",
        },
        context_text="exp1 You will be shown several examples of geometric objects.",
    )

    fields = {candidate["field"] for candidate in candidates}
    texts = {candidate["text"] for candidate in candidates}

    assert "source_files" not in fields
    assert "description" not in fields
    assert "context" not in fields
    assert "exp1" not in texts
    assert "default" not in texts


def test_build_graph_plan_does_not_force_localizer_match_from_hf_artifact_paths(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(registry_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    plan = build_psych101_graph_plan(
        {
            "dataset_id": "psych101",
            "title": "Psych-101",
        },
        [
            {
                "experiment_id": "badham2017deficits/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "badham2017deficits/exp1.csv",
                "source_files": "https://huggingface.co/datasets/marcelbinz/Psych-101/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet",
                "description": "You will be shown several examples of geometric objects.",
                "n_participants": 2,
                "n_trials": 20,
            }
        ],
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    experiment = plan.normalized_experiments[0]
    assert experiment["experiment_path"] == "badham2017deficits/exp1.csv"
    assert experiment.get("task_family_id") is None
    assert experiment.get("task_paradigm_name") is None
    assert experiment.get("name") == "exp1"


def test_extract_task_labels_drops_generic_aliases_when_specific_label_exists(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(registry_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    from brain_researcher.services.br_kg.etl.loaders.psych101_loader import (
        Psych101IngestLoader,
    )

    loader = Psych101IngestLoader(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )
    labels = loader.extract_task_labels(
        "You will make repeated choices between immediate and delayed money rewards.",
        {
            "experiment_name": "exp1",
            "description": "You will make repeated choices between immediate and delayed money rewards.",
        },
        ontology_match={
            "task_label": "intertemporal choice",
            "paradigm_name": "Fixed-Set Intertemporal Choice",
        },
    )

    assert labels
    assert any("choice" in label.lower() for label in labels)
    assert "choice task" not in labels
    assert "exp1" not in labels


def test_ingest_maps_psych101_task_to_existing_cogat_task(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_taxonomy(taxonomy_path)
    _write_curated_registry(registry_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    db = FakeGraphDB()
    cogat_task_id = "TRM_4A3FD79D0A5C8"
    db.create_node(
        "Task",
        {
            "id": cogat_task_id,
            "task_id": cogat_task_id,
            "name": "n-back",
            "definition": "Maintain and update items in working memory.",
            "definition_source": "cognitive_atlas",
        },
        node_id=cogat_task_id,
    )

    result = ingest_psych101(
        {
            "dataset_id": "psych101",
            "title": "Psych-101",
        },
        [
            {
                "experiment_id": "peterson2021using/2-back/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "peterson2021using/2-back/exp1.csv",
                "description": "Participants respond when the current item matches the one from two trials ago.",
                "n_participants": 2,
                "n_trials": 20,
            }
        ],
        db=db,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    local_task_id = "psych101:task:n-back"
    maps_to_edges = db.find_relationships(
        start_node=local_task_id,
        end_node=cogat_task_id,
        rel_type="MAPS_TO",
    )

    assert result["stats"]["task_map_relationships"] == 1
    assert len(maps_to_edges) == 1
    assert maps_to_edges[0][2]["canonical_label"] == "n-back"
    local_task = db.get_node(local_task_id)
    assert local_task is not None
    assert local_task["description"] == (
        "Participants respond when the current item matches the one from two trials ago."
    )
    assert local_task["description_source"] == "psych101_experiment_text"
    assert local_task["canonical_task_id"] == cogat_task_id
    assert local_task["canonical_task_name"] == "n-back"
    assert local_task["canonical_definition"] == "Maintain and update items in working memory."
    assert local_task["canonical_definition_source"] == "cognitive_atlas"
    assert any(
        rel[0] == "peterson2021using/2-back/exp1.csv"
        and rel[1] == local_task_id
        and rel[2]["type"] == "USES_TASK"
        for rel in db.find_relationships(rel_type="USES_TASK")
    )


def test_build_graph_plan_uses_curated_registry_for_high_confidence_slug_mapping(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(
        registry_path,
        mappings=[
            {
                "experiment_slug": "enkavi2019adaptivenback",
                "task_label": "n-back",
                "canonical_task": {
                    "canonical_id": "task:n-back",
                    "label": "n-back",
                    "links": {"cogat": "TRM_4A3FD79D0A5C8"},
                },
                "family": {
                    "family_id": "tf_working_memory",
                    "family_label": "Working Memory",
                    "subfamily_id": "sf_wm_updating_streaming",
                    "subfamily_label": "WM Updating in Streams",
                    "paradigm_name": "n-back",
                },
                "provenance": {
                    "confidence": 1.0,
                    "rationale": "Adaptive n-back variant.",
                },
            }
        ],
    )
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    plan = build_psych101_graph_plan(
        {"dataset_id": "psych101", "title": "Psych-101"},
        [
            {
                "experiment_id": "enkavi2019adaptivenback/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "enkavi2019adaptivenback/exp1.csv",
                "description": "Remember the last N letters and respond if they match.",
                "n_participants": 4,
                "n_trials": 40,
            }
        ],
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    experiment = plan.normalized_experiments[0]
    assert experiment["experiment_slug"] == "enkavi2019adaptivenback"
    assert experiment["task_family_id"] == "tf_working_memory"
    assert experiment["task_subfamily_id"] == "sf_wm_updating_streaming"
    assert experiment["task_paradigm_name"] == "n-back"
    assert experiment["task_ontology_match_method"] == "psych101_curated_registry"
    assert experiment["canonical_task_id"] == "task:n-back"
    assert experiment["canonical_task_cogat_id"] == "TRM_4A3FD79D0A5C8"
    assert experiment["name"] == "n-back"

    task_node = next(
        node
        for node in plan.nodes
        if node["labels"] == ["Task"] and node["properties"]["name"] == "n-back"
    )
    assert task_node["properties"]["canonical_task_id"] == "task:n-back"
    assert task_node["properties"]["canonical_task_cogat_id"] == "TRM_4A3FD79D0A5C8"
    assert task_node["properties"]["family_id"] == "tf_working_memory"


def test_ingest_uses_curated_registry_to_map_local_task_to_existing_cogat_task(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(
        registry_path,
        mappings=[
            {
                "experiment_slug": "enkavi2019adaptivenback",
                "task_label": "n-back",
                "canonical_task": {
                    "canonical_id": "task:n-back",
                    "label": "n-back",
                    "links": {"cogat": "TRM_4A3FD79D0A5C8"},
                },
                "family": {
                    "family_id": "tf_working_memory",
                    "family_label": "Working Memory",
                    "subfamily_id": "sf_wm_updating_streaming",
                    "subfamily_label": "WM Updating in Streams",
                    "paradigm_name": "n-back",
                },
                "provenance": {
                    "confidence": 1.0,
                    "rationale": "Adaptive n-back variant.",
                },
            }
        ],
    )
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    db = FakeGraphDB()
    cogat_task_id = "TRM_4A3FD79D0A5C8"
    db.create_node(
        "Task",
        {
            "id": cogat_task_id,
            "task_id": cogat_task_id,
            "name": "n-back",
            "definition": "Maintain and update items in working memory.",
            "definition_source": "cognitive_atlas",
        },
        node_id=cogat_task_id,
    )

    result = ingest_psych101(
        {"dataset_id": "psych101", "title": "Psych-101"},
        [
            {
                "experiment_id": "enkavi2019adaptivenback/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "enkavi2019adaptivenback/exp1.csv",
                "description": "Remember the last N letters and respond if they match.",
                "n_participants": 4,
                "n_trials": 40,
            }
        ],
        db=db,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    maps_to_edges = db.find_relationships(
        start_node="psych101:task:n-back",
        end_node=cogat_task_id,
        rel_type="MAPS_TO",
    )
    assert result["stats"]["task_map_relationships"] == 1
    assert len(maps_to_edges) == 1
    assert maps_to_edges[0][2]["match_method"] == "psych101_curated_registry"
    assert maps_to_edges[0][2]["canonical_label"] == "n-back"


def test_ingest_does_not_create_local_to_local_mapsto_edges_for_curated_labels(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    registry_path = tmp_path / "psych101_registry.yaml"
    _write_guardrail_taxonomy(taxonomy_path)
    _write_curated_registry(
        registry_path,
        mappings=[
            {
                "experiment_slug": "enkavi2019gonogo",
                "task_label": "go/no-go task",
                "canonical_task": {
                    "canonical_id": "task:go_no-go",
                    "label": "go/no-go",
                    "links": {"cogat": "TRM_4D559BCD67C18"},
                },
                "family": {
                    "family_id": "tf_conflict_inhibition",
                    "family_label": "Conflict & Inhibitory Control",
                    "subfamily_id": "sf_response_inhibition",
                    "subfamily_label": "Response Inhibition",
                    "paradigm_name": "Go/No-Go (withhold)",
                },
                "provenance": {
                    "confidence": 1.0,
                    "rationale": "Classic go/no-go task.",
                },
            }
        ],
    )
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    db = FakeGraphDB()
    result = ingest_psych101(
        {"dataset_id": "psych101", "title": "Psych-101"},
        [
            {
                "experiment_id": "enkavi2019gonogo/exp1.csv",
                "experiment_name": "exp1",
                "experiment_path": "enkavi2019gonogo/exp1.csv",
                "description": "Respond to green circles and withhold to red circles.",
                "n_participants": 4,
                "n_trials": 40,
            }
        ],
        db=db,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
        curated_registry_path=registry_path,
    )

    assert result["stats"]["task_map_relationships"] == 0
    assert not [
        rel
        for rel in db.find_relationships(rel_type="MAPS_TO")
        if rel[0].startswith("psych101:task:") and rel[1].startswith("psych101:task:")
    ]
