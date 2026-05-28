import json

import yaml

from brain_researcher.services.neurokg.etl.loaders.dataset_index_loader import (
    DatasetIndexLoader,
)
from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB


def test_dataset_index_loader_creates_dataset_and_links_tasks(tmp_path):
    db = FakeGraphDB()
    task_node_id = db.create_node("Task", {"name": "n-back"}, node_id="tsk_nback")

    dataset_id = "TEST_DS"
    index_payload = {
        "metadata": {"location": str(tmp_path / "oak_mount_root")},
        "datasets": {
            dataset_id: {
                "full_name": "Test Dataset",
                "description": "Synthetic dataset entry for unit tests",
                "data_types": ["fMRI", "?"],
                "tasks": ["n-back", "Unknown Task"],
            }
        },
    }
    index_path = tmp_path / "data_index.json"
    index_path.write_text(json.dumps(index_payload))

    config_payload = {
        "oak_mount": {
            "datasets": {"test_ds": str(tmp_path / "oak_mount_root" / "TEST_DS")}
        },
    }
    config_path = tmp_path / "data_paths.yaml"
    config_path.write_text(yaml.safe_dump(config_payload))

    loader = DatasetIndexLoader(index_path=index_path, config_path=config_path, db=db)
    stats = loader.load()

    dataset_node = db.get_node(dataset_id)
    assert dataset_node is not None
    assert dataset_node["name"] == "Test Dataset"
    assert dataset_node["data_types"] == ["fMRI"]
    assert isinstance(dataset_node.get("matched_task_canonicals"), list)
    assert "Unknown Task" in dataset_node["unmatched_tasks"]
    assert dataset_node["storage"]["metadata_root"] == index_payload["metadata"]["location"]

    relationships = db.find_relationships(start_node=dataset_id, rel_type="HAS_TASK")
    assert len(relationships) == 1
    assert relationships[0][1] == task_node_id

    assert stats["datasets_processed"] == 1
    assert stats["relationships_created"] == 1
    assert stats["tasks_matched"] == 1
    assert stats["tasks_unmatched"] == 1
