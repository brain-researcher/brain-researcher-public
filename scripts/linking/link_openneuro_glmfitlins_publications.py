#!/usr/bin/env python3
"""Link OpenNeuro GLM FitLins contrasts to publication references."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    OpenNeuroGLMFitlinsLoader,
    SOURCE_NAME,
)
from brain_researcher.services.br_kg.graph.neo4j_graph_database import (
    Neo4jGraphDB,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("openneuro_glmfitlins_pub_linker")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Link OpenNeuro GLM FitLins contrasts to publication references."
    )
    parser.add_argument(
        "--datasets-root",
        default="data/openneuro_glmfitlins",
        help="Root folder containing analyses/stat_maps for GLM FitLins data.",
    )
    parser.add_argument(
        "--statsmodel-root",
        default="data/openneuro_glmfitlins/statsmodel_specs",
        help="Path to statsmodel_specs directory.",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j bolt URI.",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username.",
    )
    parser.add_argument(
        "--neo4j-password",
        default="password",
        help="Neo4j password.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    datasets_root = Path(args.datasets_root).expanduser().resolve()
    statsmodel_root = Path(args.statsmodel_root).expanduser().resolve()
    if not statsmodel_root.exists():
        raise SystemExit(f"Statsmodel root not found: {statsmodel_root}")

    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        preload_cache=False,
    )
    loader = OpenNeuroGLMFitlinsLoader(datasets_root=datasets_root)

    dataset_ids = sorted(
        d.name
        for d in statsmodel_root.iterdir()
        if d.is_dir() and d.name.startswith("ds")
    )
    logger.info("Found %d dataset folders", len(dataset_ids))

    stats = {
        "datasets_seen": 0,
        "publications_created": 0,
        "dataset_citation_links": 0,
        "contrast_links": 0,
    }

    for dataset_id in dataset_ids:
        stats["datasets_seen"] += 1
        pub_ids, created_pubs, dataset_links = loader._ensure_publications(
            db, dataset_id
        )
        stats["publications_created"] += created_pubs
        stats["dataset_citation_links"] += dataset_links

        if not pub_ids:
            continue

        contrasts = db.find_nodes(
            "Contrast", {"dataset_id": dataset_id, "source": SOURCE_NAME}
        )
        for contrast_id, _ in contrasts:
            for pub_id in pub_ids:
                if db.create_relationship(
                    contrast_id,
                    pub_id,
                    "BELONGS_TO",
                    {"source": SOURCE_NAME},
                ):
                    stats["contrast_links"] += 1

    logger.info("Done. Stats: %s", stats)


if __name__ == "__main__":
    main()
