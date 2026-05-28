import os
from pathlib import Path

import pytest

from brain_researcher.services.neurokg.graph.graph_factory import create_graph_client
from brain_researcher.services.neurokg.etl.load_all import MasterDataLoader

pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SCHOLARLY_SAMPLE = FIXTURE_DIR / "scholarly_sample.json"
NIDM_SAMPLE = FIXTURE_DIR / "nidm_sample.json"

SAMPLE_NODE_IDS = [
    "10.1007/s11571-023-1001-0",
    "10.1093/brain/awx123",
    "https://orcid.org/0000-0001-1111-2222",
    "author:brian-johnson",
    "https://orcid.org/0000-0002-3333-4444",
    "https://ror.org/01bj3aw26",
    "institution:neuroscience-research-centre",
    "https://ror.org/02h7xzp07",
    "nidm:map:test-001",
    "contrast:wm-baseline",
    "software:spm12",
]


def _neo4j_env_available() -> bool:
    return all(os.getenv(var) for var in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))


@pytest.fixture
def neo4j_loader():
    if not _neo4j_env_available():
        pytest.skip("NEO4J_URI/USER/PASSWORD must be set to run Neo4j integration tests.")

    db = create_graph_client()
    loader = MasterDataLoader(db=db)

    try:
        yield loader
    finally:
        try:
            loader.db.execute_query(
                "MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": SAMPLE_NODE_IDS}
            )
        finally:
            loader.db.close()


def test_scholarly_and_nidm_ingest_round_trip(neo4j_loader):
    loader = neo4j_loader

    scholarly_stats = loader.load_scholarly_metadata(
        {
            "metadata_path": str(SCHOLARLY_SAMPLE),
            "cache_dir": "data/neurokg/raw/scholarly_metadata",
        }
    )
    assert scholarly_stats["publications_upserted"] >= 2

    nidm_stats = loader.load_nidm_results(
        {
            "nidm_paths": [str(NIDM_SAMPLE)],
            "cache_dir": "data/neurokg/raw/nidm",
        }
    )
    assert nidm_stats["stat_maps_upserted"] == 1

    pub_node = loader.db.find_nodes("Publication", {"id": "10.1007/s11571-023-1001-0"})
    assert pub_node, "Expected primary DOI to be ingested"

    citation_edges = loader.db.find_relationships(
        start_node=pub_node[0][0], rel_type="CITES"
    )
    assert citation_edges, "Expected CITES relationship from primary DOI"

    stat_map = loader.db.find_nodes("StatisticalMap", {"id": "nidm:map:test-001"})
    assert stat_map, "Expected NIDM statistical map node"

    derived_edges = loader.db.find_relationships(
        start_node=stat_map[0][0], rel_type="DERIVED_FROM"
    )
    assert derived_edges, "Expected DERIVED_FROM relationship for statistical map"
