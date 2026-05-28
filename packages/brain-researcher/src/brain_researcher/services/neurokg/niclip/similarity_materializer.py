"""Materialize NiCLIP similarity edges into Neo4j.

This is an offline/ETL utility to persist :SIMILAR_TO edges so downstream
retrieval can use graph traversal without recomputing similarities on-the-fly.

Implementation notes:
- Uses precomputed NiCLIP vocabulary embeddings from `data/niclip` (numpy only).
- Writes `(:Task)-[:SIMILAR_TO {method:'niclip', ...}]->(:Task)` edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from brain_researcher.core.ingestion.loaders.niclip_embeddings import (
    NICLIPEmbeddingLoader,
)
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB


@dataclass(frozen=True)
class NiclipSimilarityConfig:
    task_type: str = "cogatlas"
    embedding_type: str = "combined"
    model: str = "BrainGPT-7B-v0.2"
    top_k: int = 20
    threshold: float = 0.35
    delete_existing: bool = True
    batch_size: int = 2000


@dataclass(frozen=True)
class NiclipSimilarityStats:
    vocabulary_size: int
    mapped_tasks: int
    missing_tasks: int
    edges_written: int


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _task_name_to_id_map(db: Neo4jGraphDB) -> dict[str, str]:
    rows = db.execute_query(
        """
        MATCH (t:Task)
        RETURN t.id AS id, t.name AS name, t.label AS label, t.source AS source
        """
    )
    mapping: dict[str, str] = {}
    for row in rows:
        task_id = row.get("id")
        if not isinstance(task_id, str) or not task_id:
            continue
        source = row.get("source")
        is_cogatlas = task_id.startswith("trm_") or (
            isinstance(source, str) and "cognitive_atlas" in source.lower()
        )
        if not is_cogatlas:
            continue
        candidates = [row.get("name"), row.get("label")]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                mapping.setdefault(_normalize_text(candidate), task_id)
    return mapping


def _cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    if embeddings.ndim != 2:
        raise ValueError(f"Expected 2D embeddings, got shape={embeddings.shape}")
    eps = 1e-8
    emb = embeddings.astype(np.float32, copy=False)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = emb / (norms + eps)
    return emb @ emb.T


def materialize_task_similarity_from_embeddings(
    db: Neo4jGraphDB,
    *,
    vocabulary: list[str],
    embeddings: np.ndarray,
    cfg: NiclipSimilarityConfig,
) -> NiclipSimilarityStats:
    if len(vocabulary) != int(embeddings.shape[0]):
        raise ValueError(
            "Vocabulary length must match embeddings rows: "
            f"{len(vocabulary)} != {embeddings.shape[0]}"
        )

    name_to_id = _task_name_to_id_map(db)

    vocab_to_task_id: list[str | None] = []
    missing = 0
    for term in vocabulary:
        task_id = name_to_id.get(_normalize_text(term))
        if task_id is None:
            missing += 1
        vocab_to_task_id.append(task_id)

    similarity = _cosine_similarity_matrix(embeddings)
    np.fill_diagonal(similarity, -1.0)

    top_k = max(0, int(cfg.top_k))
    threshold = float(cfg.threshold)

    if cfg.delete_existing:
        db.execute_query(
            """
            MATCH ()-[r:SIMILAR_TO]->()
            WHERE r.method = 'niclip' OR r.source = 'niclip'
            DELETE r
            """
        )

    timestamp = datetime.now(timezone.utc).isoformat()

    edges: list[dict[str, Any]] = []
    edges_written = 0

    for i, src_id in enumerate(vocab_to_task_id):
        if src_id is None:
            continue
        if top_k == 0:
            continue
        row = similarity[i]
        k = min(top_k, int(row.shape[0]) - 1)
        if k <= 0:
            continue
        idx = np.argpartition(row, -k)[-k:]
        idx = idx[np.argsort(row[idx])[::-1]]
        for j in idx:
            score = float(row[int(j)])
            if score < threshold:
                break
            dst_id = vocab_to_task_id[int(j)]
            if dst_id is None:
                continue
            edges.append({"start_id": src_id, "end_id": dst_id, "score": score})

    if not edges:
        return NiclipSimilarityStats(
            vocabulary_size=len(vocabulary),
            mapped_tasks=len(vocabulary) - missing,
            missing_tasks=missing,
            edges_written=0,
        )

    batch_size = max(1, int(cfg.batch_size))
    for start in range(0, len(edges), batch_size):
        batch = edges[start : start + batch_size]
        db.execute_query(
            """
            UNWIND $rows AS row
            MATCH (a:Task {id: row.start_id})
            MATCH (b:Task {id: row.end_id})
            MERGE (a)-[r:SIMILAR_TO {method: 'niclip'}]->(b)
            SET r.source = 'niclip',
                r.score = row.score,
                r.confidence = row.score,
                r.timestamp = $timestamp,
                r.model = $model,
                r.vocabulary_type = $task_type,
                r.embedding_type = $embedding_type,
                r.threshold = $threshold,
                r.top_k = $top_k
            """,
            {
                "rows": batch,
                "timestamp": timestamp,
                "model": cfg.model,
                "task_type": cfg.task_type,
                "embedding_type": cfg.embedding_type,
                "threshold": cfg.threshold,
                "top_k": cfg.top_k,
            },
        )
        edges_written += len(batch)

    return NiclipSimilarityStats(
        vocabulary_size=len(vocabulary),
        mapped_tasks=len(vocabulary) - missing,
        missing_tasks=missing,
        edges_written=edges_written,
    )


def materialize_niclip_task_similarity(
    db: Neo4jGraphDB,
    *,
    niclip_root: str | None = None,
    cfg: NiclipSimilarityConfig = NiclipSimilarityConfig(),
) -> NiclipSimilarityStats:
    loader = NICLIPEmbeddingLoader(root_path=niclip_root)
    vocabulary = loader.get_vocabulary_list(cfg.task_type)
    embeddings = loader.get_vocabulary_embeddings(
        task_type=cfg.task_type, embedding_type=cfg.embedding_type, model=cfg.model
    )
    if embeddings is None or not vocabulary:
        raise RuntimeError(
            f"Missing NiCLIP vocabulary resources (task_type={cfg.task_type}, "
            f"embedding_type={cfg.embedding_type}, model={cfg.model})"
        )
    return materialize_task_similarity_from_embeddings(
        db, vocabulary=vocabulary, embeddings=embeddings, cfg=cfg
    )
