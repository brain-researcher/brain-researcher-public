#!/usr/bin/env python3
"""Backfill embedding_text_v1 onto Psych-101 Task nodes from payload-pack text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.br_kg.behavior_embeddings import (
    apply_embedding_records_to_db,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.text_embeddings import (
    TextEmbeddingConfig,
    build_text_embedding_records,
    encode_text_records,
    load_psych101_text_records,
)
from brain_researcher.services.br_kg.text_v1 import DEFAULT_TEXT_V1_MODEL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--payload-json",
        required=True,
        help="Psych-101 centaur task payload pack JSON file.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional summary JSON output path.",
    )
    parser.add_argument(
        "--model-name-or-path",
        default=DEFAULT_TEXT_V1_MODEL,
        help="Sentence-transformers model name or path for text_v1 embeddings.",
    )
    parser.add_argument(
        "--embedding-backend",
        default="sentence_transformers",
        choices=("sentence_transformers", "hash"),
        help="Embedding backend. Hash is for dry runs only.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Sentence-transformers batch size.",
    )
    parser.add_argument(
        "--device",
        help="Optional explicit device, e.g. cpu or cuda.",
    )
    parser.add_argument(
        "--write-to-neo4j",
        default="true",
        choices=("true", "false"),
        help="Whether to write embedding_text_v1 into Neo4j.",
    )
    parser.add_argument(
        "--neo4j-database",
        help="Optional Neo4j database override.",
    )
    parser.add_argument(
        "--include-experiments",
        action="store_true",
        help="Also encode experiment taskspec_text_v1 payloads.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    payload_path = Path(args.payload_json).expanduser().resolve()
    out_path = Path(
        args.output_file
        or str(
            payload_path.with_name(
                payload_path.stem.replace("_task_payloads", "") + "_text_v1_embeddings.json"
            )
        )
    ).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = load_psych101_text_records(
        payload_path,
        include_experiments=bool(args.include_experiments),
    )
    config = TextEmbeddingConfig(
        model_name_or_path=args.model_name_or_path,
        backend=args.embedding_backend,
        batch_size=max(1, int(args.batch_size)),
        device=args.device,
    )
    vectors = encode_text_records(records, config)
    embedding_records = build_text_embedding_records(
        records,
        vectors,
        embedding_property="embedding_text_v1",
        config=config,
    )

    records_path = out_path.with_name(
        out_path.stem.replace("_text_v1_embeddings", "_task_text_v1_embeddings") + ".jsonl"
    )
    neo4j_summary_path = out_path.with_name(
        out_path.stem.replace("_text_v1_embeddings", "_text_v1_neo4j_ingest") + ".json"
    )

    records_path.write_text(
        "\n".join(json.dumps(record) for record in embedding_records)
        + ("\n" if embedding_records else ""),
        encoding="utf-8",
    )

    neo4j_summary = {
        "status": "not_requested",
        "embedding_property": "embedding_text_v1",
        "database": args.neo4j_database,
    }
    if args.write_to_neo4j == "true":
        db = require_neo4j_db(database=args.neo4j_database, preload_cache=False)
        neo4j_summary = apply_embedding_records_to_db(
            db,
            embedding_records,
            write_experiment_embeddings=bool(args.include_experiments),
        )
        neo4j_summary["status"] = "success"
        neo4j_summary["database"] = args.neo4j_database
        if hasattr(db, "commit"):
            db.commit()
        if hasattr(db, "close"):
            db.close()

    payload = {
        "schema_version": "psych101-text-v1-embeddings-v1",
        "embedding_property": "embedding_text_v1",
        "backend": config.backend,
        "model_name_or_path": config.model_name_or_path,
        "summary": {
            "n_records": len(records),
            "n_embeddings": len(embedding_records),
            "neo4j_ingest_status": neo4j_summary.get("status"),
        },
        "outputs": {
            "records_jsonl": str(records_path),
            "neo4j_ingest_summary": str(neo4j_summary_path),
        },
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    neo4j_summary_path.write_text(json.dumps(neo4j_summary, indent=2), encoding="utf-8")

    print(f"Wrote artifacts to {out_path.parent}")
    print(f"Records embedded: {len(embedding_records)}")
    print(f"Neo4j ingest status: {neo4j_summary.get('status')}")
    print(
        "Artifacts:",
        {
            "text_embeddings": str(out_path),
            "records_jsonl": str(records_path),
            "neo4j_ingest_summary": str(neo4j_summary_path),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
