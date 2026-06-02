"""Offline text_v1 embedding helpers for Psych-101 task payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.services.br_kg.behavior_embeddings import (
    BehaviorEmbeddingConfig,
    _hash_embedding,
    build_embedding_records,
)
from brain_researcher.services.br_kg.text_v1 import DEFAULT_TEXT_V1_MODEL


@dataclass
class TextEmbeddingConfig:
    """Configuration for offline text_v1 embedding extraction."""

    model_name_or_path: str = DEFAULT_TEXT_V1_MODEL
    backend: str = "sentence_transformers"
    batch_size: int = 32
    normalize: bool = True
    device: str | None = None
    hash_dim: int = 384
    pooling: str = "sentence_transformers_default"


def load_psych101_text_records(
    payload_json: str | Path,
    *,
    include_experiments: bool = False,
) -> list[dict[str, Any]]:
    """Load text_v1-ready records from a Psych-101 payload pack JSON."""

    path = Path(payload_json)
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset_id = str((payload.get("dataset") or {}).get("dataset_id") or "").strip()
    records: list[dict[str, Any]] = []

    for task_payload in payload.get("task_payloads") or []:
        node_id = str(task_payload.get("local_task_id") or "").strip()
        prompt_text = str(task_payload.get("task_text_v1") or "").strip()
        if not node_id or not prompt_text:
            continue
        records.append(
            {
                "dataset_id": dataset_id,
                "node_type": "Task",
                "node_id": node_id,
                "task_id": node_id,
                "mapping_status": task_payload.get("mapping_status"),
                "prompt_text": prompt_text,
            }
        )

    if include_experiments:
        for experiment_payload in payload.get("experiment_payloads") or []:
            node_id = str(experiment_payload.get("experiment_id") or "").strip()
            prompt_text = str(experiment_payload.get("taskspec_text_v1") or "").strip()
            if not node_id or not prompt_text:
                continue
            records.append(
                {
                    "dataset_id": dataset_id,
                    "node_type": "Experiment",
                    "node_id": node_id,
                    "experiment_id": node_id,
                    "mapping_status": experiment_payload.get("mapping_status"),
                    "prompt_text": prompt_text,
                }
            )

    return records


def encode_text_records(
    records: list[dict[str, Any]],
    config: TextEmbeddingConfig,
) -> np.ndarray:
    """Encode text records into embeddings using the configured backend."""

    texts = [str(record.get("prompt_text") or "").strip() for record in records]
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    if config.backend == "hash":
        vectors = np.vstack(
            [_hash_embedding(text, dim=config.hash_dim) for text in texts]
        ).astype(np.float32)
        if config.normalize:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
        return vectors

    if config.backend != "sentence_transformers":
        raise ValueError(f"Unsupported text embedding backend: {config.backend}")

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "sentence-transformers is required for backend=sentence_transformers"
        ) from exc

    model_kwargs: dict[str, Any] = {}
    if config.device:
        model_kwargs["device"] = config.device
    model = SentenceTransformer(config.model_name_or_path, **model_kwargs)
    vectors = model.encode(
        texts,
        batch_size=max(1, int(config.batch_size)),
        convert_to_numpy=True,
        normalize_embeddings=bool(config.normalize),
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


def build_text_embedding_records(
    records: list[dict[str, Any]],
    embeddings: np.ndarray,
    *,
    embedding_property: str = "embedding_text_v1",
    config: TextEmbeddingConfig,
) -> list[dict[str, Any]]:
    """Build write-ready embedding records for Psych-101 text_v1 payloads."""

    behavior_like_config = BehaviorEmbeddingConfig(
        model_name_or_path=config.model_name_or_path,
        backend=config.backend,
        pooling=config.pooling,
        batch_size=config.batch_size,
        normalize=config.normalize,
        device=config.device,
        hash_dim=config.hash_dim,
    )
    return build_embedding_records(
        records,
        embeddings,
        embedding_property=embedding_property,
        config=behavior_like_config,
    )
