import os
from pathlib import Path

import pytest

if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )

from brain_researcher.services.neurokg.etl.load_all import MasterDataLoader
from brain_researcher.services.neurokg.graph.graph_factory import create_graph_client

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def loader():
    db = create_graph_client()
    mdl = MasterDataLoader(db=db)
    try:
        yield mdl
    finally:
        mdl.close()


def test_register_neuroquery_nimare(loader):
    config = {
        "sources": {
            "neuroquery": {
                "mode": "on_demand",
                "data_path": str(FIXTURE_DIR / "neuroquery_sample.json"),
                "cache_ttl_sec": 0,
            },
            "nimare": {
                "mode": "on_demand",
                "data_path": str(FIXTURE_DIR / "nimare_sample.json"),
                "cache_ttl_sec": 0,
            },
        },
        "create_links": False,
    }
    loader.load_all(sources=["neuroquery", "nimare"], config=config)

    records = loader.ondemand.fetch(
        "neuroquery", task_ids=["task:nback"], region_ids=["schaefer2018_200_17n_2mm:L_DLPFC"]
    )
    assert len(records) == 1
    assert records[0]["score"] == 0.78

    nimare_records = loader.ondemand.fetch(
        "nimare", task_ids=["task:gng"], region_ids=["harvard_oxford_sub25:Left Caudate"]
    )
    assert nimare_records[0]["probability"] == 0.41


def test_register_neuroscout_allen(loader):
    config = {
        "sources": {
            "neuroscout": {
                "mode": "on_demand",
                "data_path": str(FIXTURE_DIR / "neuroscout_features.json"),
                "cache_ttl_sec": 0,
            },
            "allen_hba": {
                "mode": "on_demand",
                "data_path": str(FIXTURE_DIR / "allen_hba_sample.json"),
                "cache_ttl_sec": 0,
            },
        },
        "create_links": False,
    }
    loader.load_all(sources=["neuroscout", "allen_hba"], config=config)

    feature_records = loader.ondemand.fetch(
        "neuroscout", contrast_ids=["contrast:movie-vs-rest"], feature_names=["luminance"]
    )
    assert feature_records[0]["value"] == 0.72

    expression_records = loader.ondemand.fetch(
        "allen_hba", region_ids=["harvard_oxford_cort25:Anterior Cingulate"], gene_symbols=["COMT"]
    )
    assert expression_records[0]["expression"] == 1.32
