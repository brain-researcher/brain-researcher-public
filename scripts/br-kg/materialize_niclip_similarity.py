"""Materialize NiCLIP :SIMILAR_TO edges for Task nodes."""

from __future__ import annotations

import argparse

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.niclip.similarity_materializer import (
    NiclipSimilarityConfig,
    materialize_niclip_task_similarity,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize NiCLIP task similarity (:SIMILAR_TO) edges into Neo4j."
    )
    parser.add_argument("--niclip-root", default=None, help="Path to NiCLIP data root")
    parser.add_argument("--task-type", default="cogatlas", help="Vocabulary type")
    parser.add_argument(
        "--embedding-type",
        default="combined",
        choices=["names", "definitions", "combined"],
        help="Vocabulary embedding type",
    )
    parser.add_argument("--model", default="BrainGPT-7B-v0.2", help="Embedding model")
    parser.add_argument(
        "--top-k", type=int, default=20, help="Top-k neighbors per task"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="Cosine similarity threshold",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not delete existing NiCLIP SIMILAR_TO edges before writing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Cypher UNWIND batch size",
    )

    args = parser.parse_args()

    cfg = NiclipSimilarityConfig(
        task_type=str(args.task_type),
        embedding_type=str(args.embedding_type),
        model=str(args.model),
        top_k=int(args.top_k),
        threshold=float(args.threshold),
        delete_existing=not bool(args.keep_existing),
        batch_size=int(args.batch_size),
    )

    db = require_neo4j_db(preload_cache=False)
    try:
        stats = materialize_niclip_task_similarity(
            db, niclip_root=args.niclip_root, cfg=cfg
        )
    finally:
        db.close()

    print(
        "niclip_similarity_materialized",
        {
            "vocabulary_size": stats.vocabulary_size,
            "mapped_tasks": stats.mapped_tasks,
            "missing_tasks": stats.missing_tasks,
            "edges_written": stats.edges_written,
        },
    )


if __name__ == "__main__":
    main()
