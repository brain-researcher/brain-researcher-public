from __future__ import annotations

from pathlib import Path

from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.br_kg.task_family_enrichment import (
    TaskFamilyEnrichmentConfig,
    enrich_existing_task_family_links,
)


def _write_taxonomy(path: Path) -> Path:
    path.write_text(
        """
families:
  - id: tf_conflict_inhibition
    label: Conflict / Inhibition
    description: Inhibitory control and conflict monitoring.
    subfamilies:
      - id: sf_response_inhibition
        label: Response Inhibition
        paradigms:
          - name: Flanker Task
            aliases:
              - flanker
""".strip(),
        encoding="utf-8",
    )
    return path


def test_enrich_existing_task_family_links_adds_family_edge_for_dataset_task(
    tmp_path: Path,
) -> None:
    taxonomy_path = _write_taxonomy(tmp_path / "task_families.yaml")
    db = FakeGraphDB()
    dataset_id = db.create_node("Dataset", {"id": "ds000001", "name": "Demo Dataset"})
    task_id = db.create_node("Task", {"id": "task:flanker", "name": "flanker"})
    db.create_relationship(dataset_id, task_id, "HAS_TASK", {"source": "test"})

    summary = enrich_existing_task_family_links(
        db,
        config=TaskFamilyEnrichmentConfig(
            taxonomy_path=str(taxonomy_path),
            alias_extensions_path=None,
        ),
    )

    task_node = db.get_node(task_id)
    assert summary["candidate_task_count"] == 1
    assert summary["matched_task_count"] == 1
    assert task_node is not None
    assert task_node["family_id"] == "tf_conflict_inhibition"
    assert task_node["subfamily_id"] == "sf_response_inhibition"

    family_nodes = db.find_nodes("TaskFamily", {"id": "tf_conflict_inhibition"})
    assert len(family_nodes) == 1
    family_node_id, _ = family_nodes[0]
    family_edges = db.find_relationships(
        start_node=task_id,
        end_node=family_node_id,
        rel_type="BELONGS_TO_FAMILY",
    )
    assert len(family_edges) == 1
    assert family_edges[0][2]["subfamily_id"] == "sf_response_inhibition"


def test_enrich_existing_task_family_links_skips_tasks_with_existing_family(
    tmp_path: Path,
) -> None:
    taxonomy_path = _write_taxonomy(tmp_path / "task_families.yaml")
    db = FakeGraphDB()
    task_id = db.create_node(
        "Task",
        {
            "id": "task:flanker",
            "name": "flanker",
            "family_id": "tf_conflict_inhibition",
        },
    )
    family_id = db.create_node(
        "TaskFamily",
        {"id": "tf_conflict_inhibition", "name": "Conflict / Inhibition"},
        node_id="tf_conflict_inhibition",
    )
    ta_id = db.create_node("TaskAnalysis", {"id": "ta:001", "name": "Analysis"})
    db.create_relationship(ta_id, task_id, "MAPS_TO", {"source": "test"})
    db.create_relationship(
        task_id,
        family_id,
        "BELONGS_TO_FAMILY",
        {"source": "existing"},
    )

    summary = enrich_existing_task_family_links(
        db,
        config=TaskFamilyEnrichmentConfig(
            taxonomy_path=str(taxonomy_path),
            alias_extensions_path=None,
            include_dataset_tasks=False,
            include_task_analysis_tasks=True,
            only_missing_family=True,
        ),
    )

    assert summary["candidate_task_count"] == 0
    assert summary["matched_task_count"] == 0
    family_edges = db.find_relationships(
        start_node=task_id,
        rel_type="BELONGS_TO_FAMILY",
    )
    assert len(family_edges) == 1
