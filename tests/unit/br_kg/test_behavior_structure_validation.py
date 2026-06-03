from __future__ import annotations

import json

from brain_researcher.services.br_kg.analytics.behavior_structure_validation import (
    build_behavior_structure_validation,
    write_behavior_structure_validation_artifacts,
)


def test_behavior_structure_validation_builds_pairwise_summary(tmp_path):
    raw_slice = {
        "nodes": [
            {
                "id": "task:t1",
                "labels": ["Task"],
                "properties": {
                    "id": "task:t1",
                    "name": "Task 1",
                    "source": "Psych-101",
                    "family_id": "tf_value_based_decision",
                    "subfamily_id": "sf_bandit",
                    "embedding_text_v1": [1.0, 0.0],
                    "embedding_centaur_behavior_v1": [1.0, 0.0],
                },
            },
            {
                "id": "task:t2",
                "labels": ["Task"],
                "properties": {
                    "id": "task:t2",
                    "name": "Task 2",
                    "source": "Psych-101",
                    "family_id": "tf_value_based_decision",
                    "subfamily_id": "sf_bandit",
                    "embedding_text_v1": [0.9, 0.1],
                    "embedding_centaur_behavior_v1": [0.95, 0.05],
                },
            },
            {
                "id": "task:t3",
                "labels": ["Task"],
                "properties": {
                    "id": "task:t3",
                    "name": "Task 3",
                    "source": "Psych-101",
                    "family_id": "tf_working_memory",
                    "subfamily_id": "sf_interference",
                    "embedding_text_v1": [0.1, 0.9],
                    "embedding_centaur_behavior_v1": [0.2, 0.8],
                },
            },
            {
                "id": "tf:decision",
                "labels": ["TaskFamily"],
                "properties": {"id": "tf:decision", "name": "Decision"},
            },
            {
                "id": "task:canonical",
                "labels": ["Task"],
                "properties": {"id": "task:canonical", "name": "Canonical"},
            },
        ],
        "edges": [
            {
                "source": "task:t1",
                "target": "tf:decision",
                "edge_type": "BELONGS_TO_FAMILY",
            },
            {
                "source": "task:t2",
                "target": "tf:decision",
                "edge_type": "BELONGS_TO_FAMILY",
            },
            {
                "source": "task:t2",
                "target": "task:canonical",
                "edge_type": "MAPS_TO",
            },
            {
                "source": "task:t3",
                "target": "task:canonical",
                "edge_type": "MAPS_TO",
            },
        ],
    }

    result = build_behavior_structure_validation(raw_slice)

    summary = result["summary"]
    assert summary["task_node_count"] == 3
    assert summary["pairwise_count"] == 3
    assert summary["connected_pair_count"] == 3
    assert summary["group_stats"]["behavior_family_separation_margin"] is not None

    rows = result["pairwise_records"]
    same_family_row = next(
        row
        for row in rows
        if {row["task_a_id"], row["task_b_id"]} == {"task:t1", "task:t2"}
    )
    assert same_family_row["same_family"] is True
    assert same_family_row["graph_distance"] == 2

    artifact_paths = write_behavior_structure_validation_artifacts(
        result,
        output_dir=tmp_path,
    )
    assert (tmp_path / "pairwise_metrics.tsv").exists()
    assert (
        json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))[
            "task_node_count"
        ]
        == 3
    )
    assert artifact_paths["summary_json"].endswith("summary.json")
