from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.neurokg.text_embeddings import (
    TextEmbeddingConfig,
    build_text_embedding_records,
    encode_text_records,
    load_psych101_text_records,
)


def test_load_psych101_text_records_reads_task_and_experiment_payloads(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "dataset": {"dataset_id": "psych101"},
                "task_payloads": [
                    {
                        "local_task_id": "psych101:task:n-back",
                        "task_text_v1": "Task n-back working memory",
                        "mapping_status": "canonical_task_linked",
                    }
                ],
                "experiment_payloads": [
                    {
                        "experiment_id": "exp-001",
                        "taskspec_text_v1": "TaskSpec repeated n-back blocks",
                        "mapping_status": "canonical_task_linked",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = load_psych101_text_records(payload_path, include_experiments=True)

    assert len(records) == 2
    assert records[0]["node_type"] == "Task"
    assert records[0]["node_id"] == "psych101:task:n-back"
    assert records[1]["node_type"] == "Experiment"
    assert records[1]["node_id"] == "exp-001"


def test_encode_text_records_hash_backend_is_deterministic() -> None:
    records = [
        {"node_id": "a", "prompt_text": "Task n-back working memory"},
        {"node_id": "b", "prompt_text": "Task flanker response inhibition"},
    ]
    config = TextEmbeddingConfig(
        model_name_or_path="hash-test",
        backend="hash",
        hash_dim=16,
    )

    embeddings_a = encode_text_records(records, config)
    embeddings_b = encode_text_records(records, config)

    assert embeddings_a.shape == (2, 16)
    assert embeddings_b.shape == (2, 16)
    assert (embeddings_a == embeddings_b).all()


def test_build_text_embedding_records_uses_embedding_text_v1() -> None:
    records = [
        {
            "dataset_id": "psych101",
            "node_type": "Task",
            "node_id": "psych101:task:n-back",
            "task_id": "psych101:task:n-back",
            "prompt_text": "Task n-back working memory",
        }
    ]
    config = TextEmbeddingConfig(
        model_name_or_path="hash-test",
        backend="hash",
        hash_dim=8,
    )
    embeddings = encode_text_records(records, config)

    out = build_text_embedding_records(
        records,
        embeddings,
        embedding_property="embedding_text_v1",
        config=config,
    )

    assert len(out) == 1
    assert out[0]["node_id"] == "psych101:task:n-back"
    assert out[0]["embedding_property"] == "embedding_text_v1"
    assert out[0]["dim"] == 8
