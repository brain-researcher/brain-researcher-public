from __future__ import annotations

import httpx

from brain_researcher.services.br_kg.etl.loaders.openmed_pgc_hf_loader import (
    DEFAULT_HF_AUTHOR,
    discover_openmed_pgc_dataset_ids,
    fetch_openmed_pgc_dataset_metadata,
    ingest_openmed_pgc_snapshot,
    openmed_pgc_snapshot_to_graph_inputs,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.br_kg.spatial.disease_trait_region_materializer import (
    materialize_disease_trait_region_associations,
)


def _request_key(request: httpx.Request) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        request.url.scheme,
        request.url.host,
        request.url.path,
        tuple(sorted(request.url.params.multi_items())),
    )


def _mock_transport(response_map: dict[tuple[str, str, str, tuple[tuple[str, str], ...]], object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = _request_key(request)
        if key not in response_map:
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        payload = response_map[key]
        if isinstance(payload, str):
            return httpx.Response(200, text=payload, request=request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def _dataset_api_url(dataset_id: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return ("https", "huggingface.co", f"/api/datasets/{dataset_id}", ())


def _readme_url(dataset_id: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        "https",
        "huggingface.co",
        f"/datasets/{dataset_id}/resolve/main/README.md",
        (),
    )


def _splits_url(dataset_id: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        "https",
        "datasets-server.huggingface.co",
        "/splits",
        (("dataset", dataset_id),),
    )


def _info_url(dataset_id: str, config: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        "https",
        "datasets-server.huggingface.co",
        "/info",
        (("config", config), ("dataset", dataset_id)),
    )


def _first_rows_url(dataset_id: str, config: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        "https",
        "datasets-server.huggingface.co",
        "/first-rows",
        (("config", config), ("dataset", dataset_id), ("split", "train")),
    )


def test_discover_openmed_pgc_dataset_ids_filters_openmed_repos() -> None:
    transport = _mock_transport(
        {
            (
                "https",
                "huggingface.co",
                "/api/datasets",
                (("author", DEFAULT_HF_AUTHOR), ("limit", "100"), ("search", "pgc")),
            ): [
                {"id": "OpenMed/pgc-adhd"},
                {"id": "OpenMed/not-pgc"},
                {"id": "OpenMed/pgc-schizophrenia"},
                {"id": "OtherOrg/pgc-foo"},
            ]
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        dataset_ids = discover_openmed_pgc_dataset_ids(client=client)

    assert dataset_ids == ("OpenMed/pgc-adhd", "OpenMed/pgc-schizophrenia")


def test_fetch_openmed_pgc_dataset_metadata_parses_readme_and_config_metadata() -> None:
    dataset_id = "OpenMed/pgc-bipolar"
    readme = """---
license: cc-by-4.0
task_categories:
- tabular-regression
- tabular-classification
tags:
- gwas
- pgc
pretty_name: PGC Bipolar Disorder GWAS Summary Statistics
configs:
- config_name: bip2011
  default: true
  data_files:
  - split: train
    path: data/bip2011/*.parquet
- config_name: bip2024
  data_files:
  - split: train
    path: data/bip2024/*.parquet
---

## Subsets

| Config | Phenotype | Journal | Year | PubMed | Rows | License |
|--------|-----------|---------|------|--------|------|---------|
| `bip2011` | Bipolar Disorder | Nature Genetics | 2011 | [21926972](https://pubmed.ncbi.nlm.nih.gov/21926972/) | — | CC BY 4.0 |
| `bip2024` | Bipolar Disorder & Schizophrenia | Nature | 2024 | [39843750](https://pubmed.ncbi.nlm.nih.gov/39843750/) | 12345 | CC BY 4.0 |
| `bip2025` | Alcohol Use / AUDIT | Nature | 2025 | [40000000](https://pubmed.ncbi.nlm.nih.gov/40000000/) | 54321 | CC BY 4.0 |
| `bip2026` | Anxiety Disorders & Factors | Nature | 2026 | [40000001](https://pubmed.ncbi.nlm.nih.gov/40000001/) | 1000 | CC BY 4.0 |
"""

    transport = _mock_transport(
        {
            _dataset_api_url(dataset_id): {
                "id": dataset_id,
                "cardData": {
                    "pretty_name": "PGC Bipolar Disorder GWAS Summary Statistics",
                    "license": "cc-by-4.0",
                    "configs": [
                        {"config_name": "bip2011", "default": True},
                        {"config_name": "bip2024"},
                        {"config_name": "bip2025"},
                        {"config_name": "bip2026"},
                    ],
                    "tags": ["gwas", "pgc"],
                },
                "tags": ["gwas", "summary-statistics"],
            },
            _readme_url(dataset_id): readme,
            _splits_url(dataset_id): {
                "splits": [
                    {"dataset": dataset_id, "config": "bip2011", "split": "train"},
                    {"dataset": dataset_id, "config": "bip2024", "split": "train"},
                    {"dataset": dataset_id, "config": "bip2025", "split": "train"},
                    {"dataset": dataset_id, "config": "bip2026", "split": "train"},
                ],
                "pending": [],
                "failed": [],
            },
            _info_url(dataset_id, "bip2011"): {
                "dataset_info": {
                    "config_name": "bip2011",
                    "splits": {"train": {"num_examples": 9876}},
                },
                "partial": False,
            },
            _info_url(dataset_id, "bip2024"): {
                "dataset_info": {
                    "config_name": "bip2024",
                    "splits": {"train": {"num_examples": 12345}},
                },
                "partial": False,
            },
            _info_url(dataset_id, "bip2025"): {
                "dataset_info": {
                    "config_name": "bip2025",
                    "splits": {"train": {"num_examples": 54321}},
                },
                "partial": False,
            },
            _info_url(dataset_id, "bip2026"): {
                "dataset_info": {
                    "config_name": "bip2026",
                    "splits": {"train": {"num_examples": 1000}},
                },
                "partial": False,
            },
            _first_rows_url(dataset_id, "bip2011"): {
                "rows": [
                    {"row": {"SNP": "rs1", "_source_file": "bip2011_eur.gz"}},
                ]
            },
            _first_rows_url(dataset_id, "bip2024"): {
                "rows": [
                    {"row": {"SNP": "rs2", "_source_file": "bip2024_eur_meta.gz"}},
                ]
            },
            _first_rows_url(dataset_id, "bip2025"): {
                "rows": [
                    {"row": {"SNP": "rs3", "_source_file": "bip2025_afr_meta.gz"}},
                ]
            },
            _first_rows_url(dataset_id, "bip2026"): {
                "rows": [
                    {"row": {"SNP": "rs4", "_source_file": "bip2026_meta.gz"}},
                ]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        metadata = fetch_openmed_pgc_dataset_metadata(dataset_id, client=client)

    assert metadata.dataset_id == dataset_id
    assert metadata.title == "PGC Bipolar Disorder GWAS Summary Statistics"
    assert metadata.license == "cc-by-4.0"
    assert metadata.tags == ("gwas", "summary-statistics", "pgc")
    assert metadata.config_names == ("bip2011", "bip2024", "bip2025", "bip2026")
    assert len(metadata.studies) == 4

    study_map = {study.config_name: study for study in metadata.studies}
    assert study_map["bip2011"].rows == 9876
    assert study_map["bip2011"].phenotype == "Bipolar Disorder"
    assert study_map["bip2024"].expanded_traits == ("Bipolar Disorder", "Schizophrenia")
    assert study_map["bip2024"].disease_trait_id == "disease:bipolar_disorder"
    assert study_map["bip2024"].ancestry_hints == ("European",)
    assert {
        descriptor.node_id for descriptor in study_map["bip2024"].population_descriptors
    } == {"population:eur"}
    assert study_map["bip2025"].expanded_traits == ("Alcohol Use",)
    assert study_map["bip2025"].population_descriptors[0].ancestry_code == "AFR"
    assert study_map["bip2026"].expanded_traits == ("Anxiety Disorders",)
    assert metadata.splits[0]["config"] == "bip2011"


def test_snapshot_ingest_and_brainregion_derivation_handles_composites() -> None:
    dataset_id = "OpenMed/pgc-bipolar"
    readme = """---
license: cc-by-4.0
pretty_name: PGC Bipolar Disorder GWAS Summary Statistics
configs:
- config_name: bip2024
---

## Subsets

| Config | Phenotype | Journal | Year | PubMed | Rows | License |
|--------|-----------|---------|------|--------|------|---------|
| `bip2024` | Bipolar Disorder & Schizophrenia | Nature | 2024 | [39843750](https://pubmed.ncbi.nlm.nih.gov/39843750/) | 12345 | CC BY 4.0 |
| `bip2025` | Alcohol Use / AUDIT | Nature | 2025 | [40000000](https://pubmed.ncbi.nlm.nih.gov/40000000/) | 54321 | CC BY 4.0 |
| `bip2026` | Anxiety Disorders & Factors | Nature | 2026 | [40000001](https://pubmed.ncbi.nlm.nih.gov/40000001/) | 1000 | CC BY 4.0 |
"""
    transport = _mock_transport(
        {
            _dataset_api_url(dataset_id): {
                "id": dataset_id,
                "cardData": {
                    "pretty_name": "PGC Bipolar Disorder GWAS Summary Statistics",
                    "license": "cc-by-4.0",
                    "configs": [{"config_name": "bip2024"}],
                },
            },
            _readme_url(dataset_id): readme,
            _splits_url(dataset_id): {
                "splits": [
                    {"dataset": dataset_id, "config": "bip2024", "split": "train"},
                    {"dataset": dataset_id, "config": "bip2025", "split": "train"},
                    {"dataset": dataset_id, "config": "bip2026", "split": "train"},
                ]
            },
            _info_url(dataset_id, "bip2024"): {
                "dataset_info": {"splits": {"train": {"num_examples": 12345}}},
                "partial": False,
            },
            _info_url(dataset_id, "bip2025"): {
                "dataset_info": {"splits": {"train": {"num_examples": 54321}}},
                "partial": False,
            },
            _info_url(dataset_id, "bip2026"): {
                "dataset_info": {"splits": {"train": {"num_examples": 1000}}},
                "partial": False,
            },
            _first_rows_url(dataset_id, "bip2024"): {
                "rows": [{"row": {"_source_file": "bip2024_eur_meta.gz"}}]
            },
            _first_rows_url(dataset_id, "bip2025"): {
                "rows": [{"row": {"_source_file": "bip2025_afr_meta.gz"}}]
            },
            _first_rows_url(dataset_id, "bip2026"): {
                "rows": [{"row": {"_source_file": "bip2026_meta.gz"}}]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        snapshot = openmed_pgc_snapshot_to_graph_inputs(
            client=client,
            explicit_dataset_ids=(dataset_id,),
        )

    study_rows = [row for row in snapshot.node_rows if "Study" in row["labels"]]
    trait_rows = [row for row in snapshot.node_rows if "DiseaseTrait" in row["labels"]]
    assert len(study_rows) == 3
    assert any(
        row["properties"]["phenotype"] == "Bipolar Disorder & Schizophrenia"
        and row["properties"]["expanded_traits"] == ["Bipolar Disorder", "Schizophrenia"]
        for row in study_rows
    )
    assert any(row["properties"]["name"] == "Schizophrenia" for row in trait_rows)
    assert any(row["properties"]["name"] == "Alcohol Use" for row in trait_rows)
    assert any(row["properties"]["name"] == "Anxiety Disorders" for row in trait_rows)
    population_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "Population" in row["labels"]
    }
    publication_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "Publication" in row["labels"]
    }
    disease_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "DiseaseTrait" in row["labels"]
    }
    assert population_rows["population:eur"]["ancestry_code"] == "EUR"
    assert population_rows["population:eur"]["population_type"] == "ancestry"
    assert population_rows["population:afr"]["ancestry_code"] == "AFR"
    assert "population:openmed_pgc_bipolar:bip2026" not in population_rows
    assert publication_rows["pmid:39843750"]["source"] == "openmed_pgc_hf_loader"
    assert "title" not in publication_rows["pmid:39843750"]
    assert disease_rows["disease:schizophrenia"]["source"] == "openmed_pgc_hf_loader"

    study_edges = [
        row
        for row in snapshot.relationship_rows
        if row["rel_type"] == "STUDIES"
        and row["start_id"].endswith("bip2024")
    ]
    assert len(study_edges) == 2
    assert {edge["properties"]["trait_label"] for edge in study_edges} == {
        "Bipolar Disorder",
        "Schizophrenia",
    }
    population_edges = [
        row
        for row in snapshot.relationship_rows
        if row["rel_type"] == "HAS_POPULATION"
        and row["start_id"].endswith("bip2024")
    ]
    assert len(population_edges) == 1
    assert population_edges[0]["properties"]["ancestry_code"] == "EUR"
    assert population_edges[0]["properties"]["population_type"] == "ancestry"
    assert not [
        row
        for row in snapshot.relationship_rows
        if row["rel_type"] == "HAS_POPULATION"
        and row["start_id"].endswith("bip2026")
    ]

    db = FakeGraphDB()
    with httpx.Client(transport=transport, timeout=10.0) as ingest_client:
        ingest_result = ingest_openmed_pgc_snapshot(
            db,
            client=ingest_client,
            explicit_dataset_ids=(dataset_id,),
        )
    assert ingest_result["nodes_created"] >= 6
    assert db.find_relationships(rel_type="ALIGNS_WITH")

    # Seed a path for the derived layer.
    derived_db = FakeGraphDB()
    trait_id = derived_db.create_node(
        "DiseaseTrait",
        {"id": "disease:bipolar_disorder", "name": "Bipolar Disorder"},
        node_id="disease:bipolar_disorder",
    )
    study_id = derived_db.create_node(
        "Study",
        {"id": "study:toy:bip2024", "name": "bip2024"},
        node_id="study:toy:bip2024",
    )
    pub_id = derived_db.create_node(
        "Publication",
        {"id": "pmid:39843750", "pmid": "39843750"},
        node_id="pmid:39843750",
    )
    region_id = derived_db.create_node(
        "BrainRegion",
        {"id": "region:dlpfc", "name": "DLPFC"},
        node_id="region:dlpfc",
    )
    derived_db.create_relationship(study_id, trait_id, "STUDIES")
    derived_db.create_relationship(pub_id, study_id, "ALIGNS_WITH")
    derived_db.create_relationship(pub_id, region_id, "MENTIONS_REGION")

    summary = materialize_disease_trait_region_associations(derived_db)
    assert summary.edges_created == 1
    assert derived_db.find_relationships(
        start_node=trait_id, end_node=region_id, rel_type="ASSOCIATED_WITH"
    )


def test_population_normalization_recovers_ancestry_and_cohort_nodes() -> None:
    dataset_id = "OpenMed/pgc-mixed"
    readme = """---
license: cc-by-4.0
pretty_name: PGC Mixed Population Metadata
configs:
- config_name: adhd2022
- config_name: scz2013sweden
- config_name: mdd2023diverse
---

## Subsets

| Config | Phenotype | Journal | Year | PubMed | Rows | License |
|--------|-----------|---------|------|--------|------|---------|
| `adhd2022` | ADHD | Nature Genetics | 2022 | [36791868](https://pubmed.ncbi.nlm.nih.gov/36791868/) | 100 | CC BY 4.0 |
| `scz2013sweden` | Schizophrenia (Swedish) | Nature Genetics | 2013 | [23974872](https://pubmed.ncbi.nlm.nih.gov/23974872/) | 200 | CC BY 4.0 |
| `mdd2023diverse` | Major Depression (Multi-Ancestry) | Nature Genetics | 2023 | [38876780](https://pubmed.ncbi.nlm.nih.gov/38876780/) | 300 | CC BY 4.0 |
"""
    transport = _mock_transport(
        {
            _dataset_api_url(dataset_id): {
                "id": dataset_id,
                "cardData": {
                    "pretty_name": "PGC Mixed Population Metadata",
                    "license": "cc-by-4.0",
                    "configs": [
                        {"config_name": "adhd2022"},
                        {"config_name": "scz2013sweden"},
                        {"config_name": "mdd2023diverse"},
                    ],
                },
            },
            _readme_url(dataset_id): readme,
            _splits_url(dataset_id): {
                "splits": [
                    {"dataset": dataset_id, "config": "adhd2022", "split": "train"},
                    {"dataset": dataset_id, "config": "scz2013sweden", "split": "train"},
                    {"dataset": dataset_id, "config": "mdd2023diverse", "split": "train"},
                ]
            },
            _info_url(dataset_id, "adhd2022"): {
                "dataset_info": {"splits": {"train": {"num_examples": 100}}},
                "partial": False,
            },
            _info_url(dataset_id, "scz2013sweden"): {
                "dataset_info": {"splits": {"train": {"num_examples": 200}}},
                "partial": False,
            },
            _info_url(dataset_id, "mdd2023diverse"): {
                "dataset_info": {"splits": {"train": {"num_examples": 300}}},
                "partial": False,
            },
            _first_rows_url(dataset_id, "adhd2022"): {
                "rows": [{"row": {"_source_file": "ADHD2022_iPSYCH_deCODE_PGC.meta.gz"}}]
            },
            _first_rows_url(dataset_id, "scz2013sweden"): {
                "rows": [{"row": {"_source_file": "scz.swe.pgc1.results.v3.txt.gz"}}]
            },
            _first_rows_url(dataset_id, "mdd2023diverse"): {
                "rows": [{"row": {"_source_file": "mdd2023diverse_SAS_wto_UKB_Neff.csv"}}]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        snapshot = openmed_pgc_snapshot_to_graph_inputs(
            client=client,
            explicit_dataset_ids=(dataset_id,),
        )

    population_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "Population" in row["labels"]
    }
    assert population_rows["population:ipsych"]["cohort"] == "iPSYCH"
    assert population_rows["population:decode"]["cohort"] == "deCODE"
    assert population_rows["population:swedish"]["cohort"] == "Swedish cohort"
    assert population_rows["population:swedish"]["ancestry_code"] == "EUR"
    assert population_rows["population:multi_ancestry"]["ancestry_code"] == "MULTI"
    assert population_rows["population:sas"]["ancestry_code"] == "SAS"
    assert "population:uk_biobank" not in population_rows


def test_population_normalization_distinguishes_african_american_from_african() -> None:
    dataset_id = "OpenMed/pgc-african-american"
    readme = """---
license: cc-by-4.0
pretty_name: PGC PTSD Population Metadata
configs:
- config_name: ptsd2018
---

## Subsets

| Config | Phenotype | Journal | Year | PubMed | Rows | License |
|--------|-----------|---------|------|--------|------|---------|
| `ptsd2018` | PTSD | Nature Communications | 2018 | [28439101](https://pubmed.ncbi.nlm.nih.gov/28439101/) | 100 | CC BY 4.0 |
"""
    transport = _mock_transport(
        {
            _dataset_api_url(dataset_id): {
                "id": dataset_id,
                "cardData": {
                    "pretty_name": "PGC PTSD Population Metadata",
                    "license": "cc-by-4.0",
                    "configs": [{"config_name": "ptsd2018"}],
                },
            },
            _readme_url(dataset_id): readme,
            _splits_url(dataset_id): {
                "splits": [
                    {"dataset": dataset_id, "config": "ptsd2018", "split": "train"},
                ]
            },
            _info_url(dataset_id, "ptsd2018"): {
                "dataset_info": {"splits": {"train": {"num_examples": 100}}},
                "partial": False,
            },
            _first_rows_url(dataset_id, "ptsd2018"): {
                "rows": [{"row": {"_source_file": "SORTED_PTSD_AA7_ALL_study_specific_PCs1.txt"}}]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        snapshot = openmed_pgc_snapshot_to_graph_inputs(
            client=client,
            explicit_dataset_ids=(dataset_id,),
        )

    population_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "Population" in row["labels"]
    }
    assert population_rows["population:aam"]["ancestry_code"] == "AAM"
    assert population_rows["population:aam"]["name"] == "African American"
    assert "population:afr" not in population_rows


def test_population_normalization_prefers_specific_east_asian_over_broad_asian() -> None:
    dataset_id = "OpenMed/pgc-schizophrenia"
    readme = """---
license: cc-by-4.0
pretty_name: PGC Schizophrenia Population Metadata
configs:
- config_name: scz2019asi
---

## Subsets

| Config | Phenotype | Journal | Year | PubMed | Rows | License |
|--------|-----------|---------|------|--------|------|---------|
| `scz2019asi` | Schizophrenia | Nature Genetics | 2019 | [31594949](https://pubmed.ncbi.nlm.nih.gov/31594949/) | 100 | CC BY 4.0 |
"""
    transport = _mock_transport(
        {
            _dataset_api_url(dataset_id): {
                "id": dataset_id,
                "cardData": {
                    "pretty_name": "PGC Schizophrenia Population Metadata",
                    "license": "cc-by-4.0",
                    "configs": [{"config_name": "scz2019asi"}],
                },
            },
            _readme_url(dataset_id): readme,
            _splits_url(dataset_id): {
                "splits": [
                    {"dataset": dataset_id, "config": "scz2019asi", "split": "train"},
                ]
            },
            _info_url(dataset_id, "scz2019asi"): {
                "dataset_info": {"splits": {"train": {"num_examples": 100}}},
                "partial": False,
            },
            _first_rows_url(dataset_id, "scz2019asi"): {
                "rows": [{"row": {"_source_file": "daner_natgen_eas_chrx.gz"}}]
            },
        }
    )

    with httpx.Client(transport=transport, timeout=10.0) as client:
        snapshot = openmed_pgc_snapshot_to_graph_inputs(
            client=client,
            explicit_dataset_ids=(dataset_id,),
        )

    population_rows = {
        row["node_id"]: row["properties"]
        for row in snapshot.node_rows
        if "Population" in row["labels"]
    }
    assert population_rows["population:eas"]["ancestry_code"] == "EAS"
    assert "population:asian" not in population_rows
