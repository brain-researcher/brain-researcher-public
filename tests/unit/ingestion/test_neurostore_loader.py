import json
from pathlib import Path

import pytest

from brain_researcher.core.ingestion.loaders.neurostore_unified import (
    NeurostoreUnifiedLoader,
    TaskMatchResult,
)


class FakeTaskResolver:
    matcher = None

    def __init__(self) -> None:
        self.labels: list[str] = []

    def match_label(self, label: str) -> TaskMatchResult | None:
        self.labels.append(label)
        if "resolver task" not in label.lower():
            return None
        return TaskMatchResult(
            match={
                "canonical_id": "task:resolver",
                "label": "Resolver Task",
                "confidence": 0.91,
            },
            method="fake_resolver",
            fallback_node_id="neurostore_task:resolver-fallback",
        )


def _write_study(tmp_path: Path, study_id: str, info: dict, results: dict) -> None:
    study_dir = tmp_path / study_id
    study_dir.mkdir(parents=True, exist_ok=True)
    with (study_dir / "info.json").open("w", encoding="utf-8") as handle:
        json.dump(info, handle)
    with (study_dir / "results.json").open("w", encoding="utf-8") as handle:
        json.dump(results, handle)


@pytest.fixture()
def neurostore_fixture(tmp_path: Path) -> Path:
    fmri_task = {
        "TaskName": "N-Back Working Memory",
        "TaskDescription": "Participants performed a 2-back working memory task.",
        "DesignDetails": "Block design with alternating 0-back and 2-back blocks.",
        "Conditions": ["2-back", "0-back"],
        "TaskMetrics": ["Accuracy", "Reaction Time"],
        "Concepts": ["Working Memory"],
        "Domain": ["Executive cognitive control"],
        "RestingState": False,
        "TaskDesign": ["Blocked"],
        "TaskDuration": "10 minutes",
    }
    behavioral_task = {
        "TaskName": "Digit Span Test",
        "TaskDescription": "Participants recalled sequences of digits.",
        "DesignDetails": "Adaptive staircase procedure with forward span.",
        "Conditions": ["Forward"],
        "TaskMetrics": ["Span Length"],
        "Concepts": ["Working Memory"],
        "Domain": ["Learning and memory"],
        "TaskDesign": ["Other"],
    }
    info = {
        "date": "2025-06-12T16:57:59",
        "identifiers": {
            "dbid": "studyA",
            "pmid": "12345678",
            "doi": "10.1000/test",
        },
        "inputs": {"some_file.txt": "abc123"},
        "valid": True,
    }
    results = {
        "Modality": ["fMRI-BOLD"],
        "StudyObjective": "Assess working memory load effects.",
        "fMRITasks": [fmri_task],
        "BehavioralTasks": [behavioral_task],
    }
    _write_study(tmp_path, "studyA", info, results)
    return tmp_path


def test_neurostore_loader_parses_study_and_tasks(neurostore_fixture: Path) -> None:
    loader = NeurostoreUnifiedLoader(data_dir=neurostore_fixture)

    studies = loader.load_studies()
    assert len(studies) == 1
    study = studies[0]
    assert study["identifiers"]["pmid"] == "12345678"
    assert study["stats"]["fmri_tasks"] == 1
    assert study["stats"]["behavioral_tasks"] == 1

    tasks = loader.extract_tasks()
    assert len(tasks) == 2
    fmri_task = next(task for task in tasks if task["task_type"] == "fmri")
    assert fmri_task["name"] == "n-back working memory"
    assert fmri_task["concepts_normalized"] == ["working memory"]
    assert fmri_task["publication_id"] == "pmid:12345678"
    assert fmri_task["taxonomy_match"]
    assert fmri_task["taxonomy_match"]["canonical_id"] == "task:n-back"
    assert fmri_task["collection_id"].startswith("neurostore_collection:")
    assert fmri_task["canonical_task_id"] == "task:n-back"
    assert fmri_task["family_id"] == "tf_working_memory"

    publications = loader.prepare_publications()
    assert publications[0]["id"] == "pmid:12345678"

    collections = loader.prepare_collections()
    assert len(collections) == 1
    collection = collections[0]
    assert collection["id"].startswith("neurostore_collection:")
    assert collection["study_id"] == "studyA"

    task_nodes = loader.prepare_task_nodes()
    fmri_node = next(node for node in task_nodes if node["task_type"] == "fmri")
    assert fmri_node["id"].startswith("neurostore_task:")
    assert fmri_node["text_with_concepts"].startswith("n-back working memory")
    assert fmri_node["taxonomy_match"]["canonical_id"] == "task:n-back"
    assert fmri_node["family_id"] == "tf_working_memory"

    pub_relationships = loader.prepare_relationships()
    assert pub_relationships
    rel = pub_relationships[0]
    assert rel["type"] == "REPORTS_TASK"
    assert rel["start"] == "pmid:12345678"
    assert rel["properties"]["raw_label"] == "N-Back Working Memory"
    collection_relationships = loader.prepare_relationships(start_field="collection_id")
    assert collection_relationships
    col_rel = collection_relationships[0]
    assert col_rel["start"].startswith("neurostore_collection:")

    kg_payload = loader.export_for_kg()
    assert len(kg_payload["nodes"]) == 4  # publication + collection + two tasks
    assert len(kg_payload["edges"]) == 4  # pub + collection edges for two tasks

    stats = loader.get_statistics()
    assert stats["studies"] == 1
    assert stats["fmri_tasks"] == 1
    assert stats["behavioral_tasks"] == 1


def test_neurostore_loader_include_invalid(tmp_path: Path) -> None:
    valid_info = {
        "date": "2025-01-01",
        "identifiers": {"dbid": "validStudy"},
        "valid": True,
    }
    valid_results = {"Modality": ["EEG"], "fMRITasks": [], "BehavioralTasks": []}
    _write_study(tmp_path, "validStudy", valid_info, valid_results)

    invalid_info = {
        "date": "2025-01-02",
        "identifiers": {"dbid": "invalidStudy"},
        "valid": False,
    }
    invalid_results = {
        "Modality": ["fMRI-BOLD"],
        "fMRITasks": [],
        "BehavioralTasks": [],
    }
    _write_study(tmp_path, "invalidStudy", invalid_info, invalid_results)

    loader = NeurostoreUnifiedLoader(data_dir=tmp_path)
    studies = loader.load_studies()
    assert len(studies) == 1
    assert loader.skipped_invalid == ["invalidStudy"]

    inclusive_loader = NeurostoreUnifiedLoader(data_dir=tmp_path, include_invalid=True)
    inclusive_studies = inclusive_loader.load_studies()
    assert len(inclusive_studies) == 2


def test_neurostore_loader_accepts_structural_task_resolver(tmp_path: Path) -> None:
    info = {
        "date": "2025-01-01",
        "identifiers": {"dbid": "resolverStudy", "pmid": "999"},
        "valid": True,
    }
    results = {
        "Modality": ["fMRI-BOLD"],
        "fMRITasks": [{"TaskName": "Resolver Task", "Concepts": []}],
        "BehavioralTasks": [],
    }
    _write_study(tmp_path, "resolverStudy", info, results)

    resolver = FakeTaskResolver()
    loader = NeurostoreUnifiedLoader(data_dir=tmp_path, task_resolver=resolver)
    loader.load_studies()
    tasks = loader.extract_tasks()

    assert resolver.labels == ["Resolver Task"]
    assert tasks[0]["taxonomy_match"]["canonical_id"] == "task:resolver"
    assert (
        tasks[0]["taxonomy_match"]["_fallback_node_id"]
        == "neurostore_task:resolver-fallback"
    )
    assert tasks[0]["match_method"] == "fake_resolver"
