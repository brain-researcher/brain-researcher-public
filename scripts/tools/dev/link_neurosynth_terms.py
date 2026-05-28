#!/usr/bin/env python3
"""Create HAS_TERM relationships for NeuroSynth publications without re-running full ingestion."""

import argparse
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from brain_researcher.core.ingestion.loaders.neurosynth_unified import NeuroSynthUnifiedLoader
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_publication_map(db: Neo4jGraphDB) -> dict[str, str]:
    logger.info("Fetching existing NeuroSynth publications from Neo4j...")
    pub_map: dict[str, str] = {}
    rows = db.execute_query(
        """
        MATCH (p:Publication {source:'neurosynth'})
        RETURN p.id AS id, p.neurosynth_id AS neurosynth_id, p.pmid AS pmid
        """
    )
    for row in rows:
        node_id = row["id"]
        neurosynth_id = row.get("neurosynth_id")
        pmid = row.get("pmid")
        if neurosynth_id:
            pub_map[str(neurosynth_id)] = node_id
        if pmid:
            pub_map[str(pmid)] = node_id
    logger.info("Indexed %s NeuroSynth publications", len(pub_map))
    return pub_map


def build_term_index_map(db: Neo4jGraphDB, vocabulary: list[str]) -> dict[int, str]:
    logger.info("Fetching NeuroSynth terms from Neo4j...")
    term_rows = db.execute_query(
        """
        MATCH (t:Term {source:'neurosynth'})
        RETURN t.id AS id, t.name AS name
        """
    )
    term_name_to_id = {row["name"].strip(): row["id"] for row in term_rows if row.get("name")}
    index_map: dict[int, str] = {}
    missing = 0
    for idx, term in enumerate(vocabulary):
        term_name = term.strip()
        node_id = term_name_to_id.get(term_name)
        if node_id:
            index_map[idx] = node_id
        else:
            missing += 1
    if missing:
        logger.warning("%s vocabulary entries lack Term nodes; they will be skipped", missing)
    logger.info("Resolved %s/%s vocabulary terms", len(index_map), len(vocabulary))
    return index_map


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--data-path", default="data/neurosynth_nimare/neurosynth_v7")
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--min-weight", type=float, default=0.02)
    parser.add_argument("--batch-size", type=int, default=20000, help="relationship rows per Cypher batch")
    args = parser.parse_args()

    loader = NeuroSynthUnifiedLoader(use_niclip_models=False, data_path=args.data_path)
    data = loader.load_data(
        include_coordinates=False,
        include_metadata=True,
        include_features=True,
        include_models=False,
    )
    metadata_df: pd.DataFrame = data["metadata"].reset_index(drop=True)
    features = data["features"].tocsr()
    vocabulary = data["vocabulary"]

    db = Neo4jGraphDB(uri=args.uri, user=args.user, password=args.password, database=args.database)
    publication_map = build_publication_map(db)
    term_index_map = build_term_index_map(db, vocabulary)

    section_tag = loader.section
    batch: list[dict[str, Any]] = []
    total_edges = 0
    top_k = max(1, args.top_k)
    min_weight = max(0.0, args.min_weight)
    batch_size = max(1000, args.batch_size)

    def flush_batch() -> None:
        nonlocal batch, total_edges
        if not batch:
            return
        db.execute_query(
            """
            UNWIND $rows AS row
            MATCH (p {id: row.publication_id})
            MATCH (t {id: row.term_id})
            MERGE (p)-[r:`HAS_TERM`]->(t)
            SET r += row.props
            """,
            {"rows": batch},
        )
        total_edges += len(batch)
        batch = []

    logger.info(
        "Linking %s NeuroSynth studies to vocabulary terms (top_k=%s, min_weight=%.3f)...",
        len(metadata_df),
        top_k,
        min_weight,
    )

    for idx, row in metadata_df.iterrows():
        raw_identifier = str(row["id"]).strip()
        if not raw_identifier:
            continue
        neurosynth_identifier = f"neurosynth:{raw_identifier}"
        pub_id = (
            publication_map.get(neurosynth_identifier)
            or publication_map.get(raw_identifier)
        )
        if not pub_id:
            continue
        feature_row = features.getrow(idx)
        weights = feature_row.data
        indices = feature_row.indices
        if not len(weights):
            continue
        if min_weight > 0:
            mask = weights >= min_weight
            if not np.any(mask):
                continue
            weights = weights[mask]
            indices = indices[mask]
        if not len(weights):
            continue
        if len(weights) > top_k:
            top_idx = np.argpartition(weights, -top_k)[-top_k:]
            top_weights = weights[top_idx]
            top_indices = indices[top_idx]
            order = np.argsort(top_weights)[::-1]
            selected_weights = top_weights[order]
            selected_indices = top_indices[order]
        else:
            order = np.argsort(weights)[::-1]
            selected_weights = weights[order]
            selected_indices = indices[order]

        for rank, (term_idx, weight) in enumerate(zip(selected_indices, selected_weights), start=1):
            term_node_id = term_index_map.get(int(term_idx))
            if not term_node_id:
                continue
            batch.append(
                {
                    "publication_id": pub_id,
                    "term_id": term_node_id,
                    "props": {
                        "source": "neurosynth",
                        "weight": float(weight),
                        "rank": rank,
                        "section": section_tag,
                    },
                }
            )
        if len(batch) >= batch_size:
            flush_batch()
        if (idx + 1) % 1000 == 0:
            logger.info("Processed %s studies...", idx + 1)

    flush_batch()
    logger.info("Created/updated %s HAS_TERM relationships", total_edges)


if __name__ == "__main__":
    main()
