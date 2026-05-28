"""Unit tests for the GWAS Catalog top-loci loader."""

from __future__ import annotations

from typing import Any

import httpx

from brain_researcher.services.neurokg.etl.loaders.gwas_catalog_top_loci_loader import (
    GENOME_WIDE_SIGNIFICANCE,
    fetch_top_loci_snapshot,
)


def _study(
    accession_id: str,
    *,
    pubmed_id: str | None = None,
    publication: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"accessionId": accession_id}
    if pubmed_id or publication or title:
        payload["publicationInfo"] = {
            "pubmedId": pubmed_id,
            "publication": publication,
            "title": title,
        }
    return payload


def _studies_response(studies: list[dict[str, Any] | str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for study in studies:
        if isinstance(study, str):
            items.append({"accessionId": study})
        else:
            items.append(study)
    return {
        "_embedded": {"studies": items},
        "page": {"totalPages": 1, "number": 0},
    }


def _associations_response(associations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_embedded": {"associations": associations},
        "page": {"totalPages": 1, "number": 0},
    }


def _make_association(
    *,
    rsid: str = "rs123",
    allele: str = "A",
    gene: str = "BRCA1",
    pvalue: float = 1e-8,
    effect_key: str = "orPerCopyNum",
    effect_value: float = 1.2,
    chromosome: str = "6",
    position: str = "12345",
) -> dict[str, Any]:
    payload = {
        "pvalue": pvalue,
        "pvalueMantissa": 1.0,
        "pvalueExponent": -8,
        "standardError": 0.05,
        "loci": [
            {
                "strongestRiskAlleles": [{"riskAlleleName": f"{rsid}-{allele}"}],
                "authorReportedGenes": [{"geneName": gene}],
            }
        ],
        "snps": [
            {
                "rsId": rsid,
                "locations": [
                    {
                        "chromosomeName": chromosome,
                        "chromosomePosition": position,
                    }
                ],
            }
        ],
    }
    payload[effect_key] = effect_value
    return payload


class TestFetchTopLociSnapshot:
    def test_fetch_snapshot_returns_structured_rows(self) -> None:
        associations = [
            _make_association(rsid="rs111", gene="GEN1", pvalue=1e-12),
            _make_association(rsid="rs222", gene="GEN2", pvalue=2e-10),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "findByEfoTrait" in url:
                return httpx.Response(200, json=_studies_response(["GCST000001"]))
            if "associations" in url:
                return httpx.Response(200, json=_associations_response(associations))
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        snapshot = fetch_top_loci_snapshot(
            client=client,
            disorder_trait_queries={"disease:schizophrenia": "schizophrenia"},
            request_delay=0,
        )

        assert len(snapshot.node_rows) == 2
        assert len(snapshot.relationship_rows) == 2
        assert {
            row["node_id"] for row in snapshot.node_rows
        } == {"locus:rs111", "locus:rs222"}
        for row in snapshot.node_rows:
            assert row["labels"] == ("RiskLocus",)
            assert row["properties"]["source"] == "gwas_catalog_top_loci_loader"
        for row in snapshot.relationship_rows:
            assert row["rel_type"] == "ASSOCIATED_WITH"
            assert row["end_id"] == "disease:schizophrenia"

    def test_filters_to_genome_wide_significant_and_ranks_before_cap(self) -> None:
        associations = [
            _make_association(rsid="rs_loose", pvalue=1e-6),
            _make_association(rsid="rs_mid", pvalue=GENOME_WIDE_SIGNIFICANCE),
            _make_association(rsid="rs_best", pvalue=1e-20),
            _make_association(rsid="rs_other", pvalue=2e-9),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "findByEfoTrait" in url:
                return httpx.Response(200, json=_studies_response(["GCST000001"]))
            if "associations" in url:
                return httpx.Response(200, json=_associations_response(associations))
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        snapshot = fetch_top_loci_snapshot(
            client=client,
            disorder_trait_queries={"disease:schizophrenia": "schizophrenia"},
            max_associations_per_disorder=2,
            request_delay=0,
        )

        assoc_rows = [row for row in snapshot.relationship_rows if row["rel_type"] == "ASSOCIATED_WITH"]
        assert len(assoc_rows) == 2
        kept = {(row["start_id"], row["properties"]["rank"]) for row in assoc_rows}
        assert kept == {("locus:rs_best", 1), ("locus:rs_other", 2)}
        assert all(row["properties"]["p_value"] <= GENOME_WIDE_SIGNIFICANCE for row in assoc_rows)

    def test_keeps_strongest_duplicate_association_and_emits_study_provenance(self) -> None:
        weaker = _make_association(rsid="rs555", pvalue=2e-8, gene="GEN_WEAK")
        stronger = _make_association(rsid="rs555", pvalue=1e-12, gene="GEN_STRONG")

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "findByEfoTrait" in url:
                return httpx.Response(
                    200,
                    json=_studies_response(
                        [
                            _study("GCST000001", pubmed_id="111"),
                            _study("GCST000002", pubmed_id="222"),
                        ]
                    ),
                )
            if "GCST000001/associations" in url:
                return httpx.Response(200, json=_associations_response([weaker]))
            if "GCST000002/associations" in url:
                return httpx.Response(200, json=_associations_response([stronger]))
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        snapshot = fetch_top_loci_snapshot(
            client=client,
            disorder_trait_queries={"disease:schizophrenia": "schizophrenia"},
            study_ids_by_pmid={
                "111": ["study:openmed_pgc_schizophrenia:study1"],
                "222": ["study:openmed_pgc_schizophrenia:study2"],
            },
            request_delay=0,
        )

        assoc_rows = [row for row in snapshot.relationship_rows if row["rel_type"] == "ASSOCIATED_WITH"]
        lead_rows = [row for row in snapshot.relationship_rows if row["rel_type"] == "HAS_LEAD_LOCUS"]

        assert len(assoc_rows) == 1
        assert assoc_rows[0]["properties"]["p_value"] == 1e-12
        assert assoc_rows[0]["properties"]["study_accession"] == "GCST000002"
        assert assoc_rows[0]["properties"]["study_id"] == "study:openmed_pgc_schizophrenia:study2"

        assert len(lead_rows) == 2
        assert {row["start_id"] for row in lead_rows} == {
            "study:openmed_pgc_schizophrenia:study1",
            "study:openmed_pgc_schizophrenia:study2",
        }
        assert {row["properties"]["p_value"] for row in lead_rows} == {2e-8, 1e-12}

    def test_deduplicates_risk_locus_nodes_across_disorders(self) -> None:
        association = [_make_association(rsid="rs999", pvalue=1e-12)]

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "findByEfoTrait" in url:
                return httpx.Response(200, json=_studies_response(["GCST000001"]))
            if "associations" in url:
                return httpx.Response(200, json=_associations_response(association))
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        snapshot = fetch_top_loci_snapshot(
            client=client,
            disorder_trait_queries={
                "disease:schizophrenia": "schizophrenia",
                "disease:adhd": "attention deficit hyperactivity disorder",
            },
            request_delay=0,
        )

        assert len(snapshot.node_rows) == 1
        assoc_rows = [row for row in snapshot.relationship_rows if row["rel_type"] == "ASSOCIATED_WITH"]
        assert len(assoc_rows) == 2
        assert {row["end_id"] for row in assoc_rows} == {
            "disease:schizophrenia",
            "disease:adhd",
        }

    def test_skips_association_without_rsid(self) -> None:
        bad_assoc: dict[str, Any] = {
            "pvalue": 1e-9,
            "loci": [
                {
                    "strongestRiskAlleles": [{"riskAlleleName": ""}],
                    "authorReportedGenes": [],
                }
            ],
            "snps": [],
        }
        good_assoc = _make_association(rsid="rs100", pvalue=1e-10)

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "findByEfoTrait" in url:
                return httpx.Response(200, json=_studies_response(["GCST000001"]))
            if "associations" in url:
                return httpx.Response(200, json=_associations_response([bad_assoc, good_assoc]))
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        snapshot = fetch_top_loci_snapshot(
            client=client,
            disorder_trait_queries={"disease:schizophrenia": "schizophrenia"},
            request_delay=0,
        )

        assert [row["node_id"] for row in snapshot.node_rows] == ["locus:rs100"]
