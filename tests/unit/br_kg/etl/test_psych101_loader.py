from __future__ import annotations

from pathlib import Path

import yaml

from brain_researcher.services.br_kg.etl.loaders.psych101_loader import (
    Psych101IngestLoader,
    build_psych101_graph_plan,
    ingest_psych101,
    normalize_psych101_dataset_metadata,
    normalize_psych101_experiment_row,
)


class FakeNeo4jDB:
    def __init__(self) -> None:
        self.nodes: list[tuple[list[str], dict, str | None]] = []
        self.relationships: list[tuple[str, str, str, dict]] = []

    def create_node(self, labels, properties=None, node_id=None, auto_commit=True):
        del auto_commit
        label_list = [labels] if isinstance(labels, str) else list(labels)
        self.nodes.append((label_list, dict(properties or {}), node_id))
        return node_id or str(len(self.nodes))

    def create_relationship(
        self,
        start_node,
        end_node,
        rel_type,
        properties=None,
        auto_commit=True,
    ):
        del auto_commit
        self.relationships.append(
            (start_node, end_node, rel_type, dict(properties or {}))
        )
        return True


def _sample_dataset_metadata() -> dict[str, object]:
    return {
        "dataset_id": "psych101",
        "title": "Psych-101",
        "description": "A large collection of human decision-making and memory experiments.",
        "source": "HuggingFace",
        "url": "https://huggingface.co/datasets/marcelbinz/Psych-101",
        "license": "Apache-2.0",
        "tags": ["decision-making", "memory", "psychology"],
        "n_participants": 60000,
        "n_experiments": 160,
    }


def _sample_experiment_row() -> dict[str, object]:
    return {
        "experiment_id": "exp-001",
        "name": "Probabilistic bandit choice task",
        "description": "Participants choose under uncertainty and learn from feedback.",
        "paradigm": "bandit choice",
        "model": "centaur",
        "n_participants": 220,
        "n_trials": 120,
        "open_loop": True,
        "confidence": 0.91,
    }


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
                                "aliases": [
                                    "2-back",
                                    "2 back",
                                    "working memory challenge",
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "tf_decision_making",
                "label": "Decision Making",
                "description": "Choice and learning tasks.",
                "subfamilies": [
                    {
                        "id": "sf_bandit_learning",
                        "label": "Bandit Learning",
                        "paradigms": [
                            {
                                "name": "bandit choice",
                                "aliases": [
                                    "choose between options",
                                    "learn from feedback",
                                ],
                            }
                        ],
                    }
                ],
            },
        ]
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_normalize_dataset_metadata_extracts_core_fields() -> None:
    loader = Psych101IngestLoader()

    normalized = loader.normalize_dataset_metadata(_sample_dataset_metadata())

    assert normalized["dataset_id"] == "psych101"
    assert normalized["name"] == "Psych-101"
    assert normalized["source"] == "HuggingFace"
    assert normalized["n_participants"] == 60000
    assert normalized["n_experiments"] == 160
    assert "decision-making" in normalized["task_families"]
    assert "memory" in normalized["task_families"]


def test_normalize_experiment_row_extracts_labels_and_families() -> None:
    loader = Psych101IngestLoader()

    normalized = loader.normalize_experiment_row(
        _sample_experiment_row(),
        index=3,
        dataset_metadata=_sample_dataset_metadata(),
    )

    assert normalized["experiment_id"] == "exp-001"
    assert normalized["dataset_id"] == "psych101"
    assert normalized["task_label"] == "bandit task"
    assert "decision-making" in normalized["task_families"]
    assert "learning" in normalized["task_families"]
    assert normalized["is_open_loop"] is True
    assert normalized["confidence"] == 0.91


def test_normalize_experiment_row_preserves_cohort_metadata() -> None:
    loader = Psych101IngestLoader()
    row = {
        **_sample_experiment_row(),
        "site": "site_a",
        "cohort": "adult_human",
        "cohort_metadata": {
            "schema_version": "br-cohort-metadata-v1",
            "participant_id_scope": "experiment_local",
            "group_audit": {
                "resolved_group_keys": ["site", "cohort"],
                "missing_group_keys": [],
                "group_counts": {
                    "site": {
                        "participant_counts": {"site_a": 12},
                        "row_counts": {"site_a": 120},
                    }
                },
            },
        },
    }

    normalized = loader.normalize_experiment_row(
        row,
        index=0,
        dataset_metadata=_sample_dataset_metadata(),
    )

    assert normalized["site"] == "site_a"
    assert normalized["cohort"] == "adult_human"
    assert normalized["site_or_cohort"] == ["site_a", "adult_human"]
    assert normalized["audit_group_keys"] == ["site", "cohort"]
    assert normalized["cohort_metadata"]["group_audit"]["resolved_group_keys"] == [
        "site",
        "cohort",
    ]


def test_build_graph_plan_emits_graph_ready_records() -> None:
    plan = build_psych101_graph_plan(
        _sample_dataset_metadata(),
        [_sample_experiment_row()],
    )

    assert plan.normalized_dataset["dataset_id"] == "psych101"
    assert len(plan.normalized_experiments) == 1
    assert any(node["labels"] == ["Dataset", "Psych101Dataset"] for node in plan.nodes)
    assert any(
        node["labels"] == ["Experiment", "Psych101Experiment"] for node in plan.nodes
    )
    assert any(node["labels"] == ["TaskFamily"] for node in plan.nodes)
    assert any(node["labels"] == ["Task"] for node in plan.nodes)
    assert any(rel["rel_type"] == "HAS_EXPERIMENT" for rel in plan.relationships)
    assert any(rel["rel_type"] == "USES_TASK" for rel in plan.relationships)


def test_build_graph_plan_rolls_up_dataset_cohort_metadata() -> None:
    dataset_metadata = _sample_dataset_metadata()
    row = {
        **_sample_experiment_row(),
        "cohort_metadata": {
            "schema_version": "br-cohort-metadata-v1",
            "participant_id_scope": "experiment_local",
            "group_audit": {
                "requested_group_keys": ["site"],
                "resolved_group_keys": ["site"],
                "missing_group_keys": [],
                "group_counts": {
                    "site": {
                        "participant_counts": {"site_a": 2},
                        "row_counts": {"site_a": 20},
                        "missing_participant_count": 0,
                        "missing_row_count": 0,
                    }
                },
            },
        },
    }

    plan = build_psych101_graph_plan(dataset_metadata, [row])
    dataset_node = next(
        node for node in plan.nodes if "Psych101Dataset" in node["labels"]
    )
    experiment_node = next(
        node for node in plan.nodes if "Psych101Experiment" in node["labels"]
    )
    task_node = next(node for node in plan.nodes if node["labels"] == ["Task"])

    assert dataset_node["properties"]["cohort_metadata"]["group_audit"]["group_counts"][
        "site"
    ]["participant_counts"] == {"site_a": 2}
    assert experiment_node["properties"]["cohort_metadata"]["group_audit"][
        "resolved_group_keys"
    ] == ["site"]
    assert task_node["properties"]["cohort_metadata"]["group_audit"][
        "resolved_group_keys"
    ] == ["site"]


def test_ingest_writes_to_db_like_object() -> None:
    db = FakeNeo4jDB()

    result = ingest_psych101(
        _sample_dataset_metadata(),
        [_sample_experiment_row()],
        db=db,
    )

    assert result["stats"]["dataset_nodes"] == 1
    assert result["stats"]["experiment_nodes"] == 1
    assert result["stats"]["task_nodes"] >= 1
    assert result["stats"]["relationships"] >= 2
    assert any(labels == ["Dataset", "Psych101Dataset"] for labels, _, _ in db.nodes)
    assert any(rel_type == "HAS_EXPERIMENT" for _, _, rel_type, _ in db.relationships)


def test_module_wrappers_reuse_loader_defaults() -> None:
    normalized_dataset = normalize_psych101_dataset_metadata(_sample_dataset_metadata())
    normalized_row = normalize_psych101_experiment_row(
        _sample_experiment_row(),
        index=0,
        dataset_metadata=normalized_dataset,
    )

    assert normalized_dataset["dataset_id"] == "psych101"
    assert normalized_row["task_label"] == "bandit task"


def test_normalize_experiment_row_uses_path_and_taxonomy_match(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    _write_taxonomy(taxonomy_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    loader = Psych101IngestLoader(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
    )
    row = {
        "experiment_id": "exp-path-001",
        "experiment_path": "peterson2021using/2-back/exp1.csv",
        "name": "Experiment 1",
        "description": "Working memory challenge with changing targets.",
        "prompt": "Remember the target when it reappears.",
    }

    normalized = loader.normalize_experiment_row(
        row, index=2, dataset_metadata=_sample_dataset_metadata()
    )

    assert normalized["task_family_id"] == "tf_working_memory"
    assert normalized["task_family_label"] == "Working Memory"
    assert normalized["task_subfamily_id"] == "sf_wm_updating_streaming"
    assert normalized["task_paradigm_name"] == "n-back"
    assert normalized["task_ontology_match_method"] == "exact_alias"
    assert normalized["task_ontology_match_field"] == "experiment_path"
    assert normalized["task_label"] == "n-back"
    assert normalized["provenance"]["source_paths"] == [
        "peterson2021using/2-back/exp1.csv"
    ]


def test_normalize_experiment_row_records_ontology_evidence_from_prompt_and_description(
    tmp_path: Path,
) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    _write_taxonomy(taxonomy_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    loader = Psych101IngestLoader(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
    )
    row = {
        "experiment_id": "exp-path-002",
        "experiment_path": "peterson2021using/exp1.csv",
        "name": "Task 2",
        "description": "Choose between options",
        "prompt": "Learn from feedback",
    }

    normalized = loader.normalize_experiment_row(
        row, index=3, dataset_metadata=_sample_dataset_metadata()
    )
    evidence = normalized["task_ontology_evidence"]
    evidence_fields = {item["field"] for item in evidence}

    assert normalized["task_family_id"] == "tf_decision_making"
    assert normalized["task_subfamily_id"] == "sf_bandit_learning"
    assert normalized["task_paradigm_name"] == "bandit choice"
    assert normalized["task_ontology_match_field"] in {"description", "prompt"}
    assert {"description", "prompt", "experiment_path"}.issubset(evidence_fields)
    assert any(item.get("matched") for item in evidence)


def test_build_graph_plan_preserves_task_ontology_metadata(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "task_families.yaml"
    alias_path = tmp_path / "task_family_alias_extensions.yaml"
    _write_taxonomy(taxonomy_path)
    alias_path.write_text("aliases: []\n", encoding="utf-8")

    plan = build_psych101_graph_plan(
        _sample_dataset_metadata(),
        [
            {
                "experiment_id": "exp-path-003",
                "experiment_path": "peterson2021using/2-back/exp1.csv",
                "name": "Experiment 3",
                "description": "Working memory challenge with changing targets.",
                "prompt": "Remember the target when it reappears.",
            }
        ],
        dataset_id="psych101",
        source_name="Psych-101",
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path,
    )

    experiment_node = next(
        node
        for node in plan.nodes
        if node["labels"] == ["Experiment", "Psych101Experiment"]
    )
    assert experiment_node["properties"]["task_family_id"] == "tf_working_memory"
    assert (
        experiment_node["properties"]["task_ontology_match_field"] == "experiment_path"
    )
    assert experiment_node["properties"]["task_ontology"]["matched"] is True
