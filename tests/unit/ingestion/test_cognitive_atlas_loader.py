"""Unit tests for the Cognitive Atlas unified loader."""

import json
import time
from pathlib import Path

from brain_researcher.core.ingestion.loaders.cognitive_atlas_unified import (
    CognitiveAtlasUnifiedLoader,
)


def _write_task(tasks_dir: Path, task_id: str, concepts: list[dict]) -> Path:
    payload = {
        "id": task_id,
        "name": f"Task {task_id}",
        "concepts": concepts,
    }
    path = tasks_dir / f"{task_id}.json"
    path.write_text(json.dumps(payload))
    return path


def test_loads_ca_assertions_and_metadata(tmp_path):
    tasks_dir = tmp_path / "tasks_full"
    tasks_dir.mkdir(parents=True)

    _write_task(
        tasks_dir,
        "tsk_1",
        [
            {
                "concept_id": "con_1",
                "name": "Concept One",
                "relationship": "ASSERTS",
                "contrasts": [
                    {"id": "ctr_1"},
                ],
            }
        ],
    )

    loader = CognitiveAtlasUnifiedLoader(
        use_niclip_data=False,
        data_dir=str(tmp_path),
        use_ca_assertions=True,
    )

    loader._concepts_cache = [
        {
            "id": "con_1",
            "concept_classes": [
                {
                    "id": "ctp_attention",
                    "name": "Attention",
                    "relationship": "CLASSIFIED_UNDER",
                }
            ],
        }
    ]

    mappings = loader.load_mappings()

    assert mappings["concept_to_task"]["con_1"] == ["tsk_1"]
    assert mappings["task_to_concepts"]["tsk_1"] == ["Concept One"]

    processes = mappings["concept_to_process"]["con_1"]
    assert processes == [
        {
            "id": "ctp_attention",
            "name": "Attention",
            "relationship": "CLASSIFIED_UNDER",
            "description": None,
        }
    ]

    metadata = mappings["task_concept_metadata"]["tsk_1::con_1"]
    assert metadata["method"] == "assertion"
    assert metadata["relationship"] == "ASSERTS"
    assert metadata["source"] == "cognitive_atlas"
    assert metadata["contrasts"] == ["ctr_1"]


def test_ca_assertion_cache_invalidates_on_source_change(tmp_path):
    tasks_dir = tmp_path / "tasks_full"
    tasks_dir.mkdir(parents=True)

    task_path = _write_task(
        tasks_dir,
        "tsk_cache",
        [
            {
                "concept_id": "con_a",
                "name": "Concept A",
                "relationship": "ASSERTS",
            }
        ],
    )

    loader = CognitiveAtlasUnifiedLoader(
        use_niclip_data=False,
        data_dir=str(tmp_path),
        use_ca_assertions=True,
    )
    first_mappings = loader.load_mappings()

    cache_file = tmp_path / ".cache" / "ca_assertions.json"
    assert cache_file.exists()
    assert first_mappings["concept_to_task"] == {"con_a": ["tsk_cache"]}

    updated_payload = json.loads(task_path.read_text())
    updated_payload["concepts"].append(
        {
            "concept_id": "con_b",
            "name": "Concept B",
        }
    )
    # Ensure file modification time differs so the fingerprint changes on all filesystems.
    time.sleep(0.01)
    task_path.write_text(json.dumps(updated_payload))

    loader_reloaded = CognitiveAtlasUnifiedLoader(
        use_niclip_data=False,
        data_dir=str(tmp_path),
        use_ca_assertions=True,
    )
    second_mappings = loader_reloaded.load_mappings()

    assert set(second_mappings["concept_to_task"].keys()) == {"con_a", "con_b"}
