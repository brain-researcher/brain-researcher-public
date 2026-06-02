"""Neo4j writer for Yeo-17 sparse edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from neo4j import GraphDatabase

from brain_researcher.services.br_kg.etl.yeo17_features import Yeo17Feature

CYPHER = """
UNWIND $rows AS row
MERGE (m:StatsMap {id: row.map_id})
  ON CREATE SET m.source = row.map_source,
                m.template_space = coalesce(row.template_space, m.template_space)
MERGE (r:BrainRegion {id: row.region_id})-[:IN_PARCELLATION]->(:Parcellation {id: $atlas_id})
MERGE (m)-[edge:IN_REGION {atlas: $atlas_name, edge_source: row.edge_source}]->(r)
SET edge.measure = $measure,
    edge.weight = row.weight,
    edge.pct_active = row.pct_active,
    edge.n_vox = row.n_vox,
    edge.z_thr = row.z_thr,
    edge.etl_version = row.etl_version,
    edge.expires_at_epoch = row.expires_at_epoch
"""


@dataclass(frozen=True)
class WriterConfig:
    uri: str
    user: str
    password: str
    database: str = "neo4j"


def write_sparse_edges(
    *,
    config: WriterConfig,
    map_id: str,
    map_source: str,
    template_space: Optional[str],
    edge_source: str,
    features: Iterable[Yeo17Feature],
    top_k: int = 8,
    etl_version: str = "v1",
    expires_at_epoch: Optional[int] = None,
) -> int:
    """Write top-K features into the graph."""

    rows = sorted(features, key=lambda f: f.weight, reverse=True)[:top_k]
    if not rows:
        return 0

    payload = [
        {
            "map_id": map_id,
            "map_source": map_source,
            "template_space": template_space,
            "edge_source": edge_source,
            "weight": feature.weight,
            "pct_active": feature.pct_active,
            "n_vox": feature.n_vox,
            "z_thr": feature.z_thr,
            "region_id": feature.region_id,
            "etl_version": etl_version,
            "expires_at_epoch": expires_at_epoch,
        }
        for feature in rows
    ]

    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            session.run(
                CYPHER,
                rows=payload,
                atlas_id="atlas:yeo2011_17",
                atlas_name="yeo17",
                measure="mean_z",
            )
    finally:
        driver.close()

    return len(payload)


__all__ = ["WriterConfig", "write_sparse_edges"]
