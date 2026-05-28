from __future__ import annotations

import pytest
from pydantic import ValidationError

from brain_researcher.services.neurokg.schemas.edge_schemas import (
    ALLOWED_EDGES,
    EDGE_SIGNATURES,
    EDGE_TYPES,
    validate_edge,
)
from brain_researcher.services.neurokg.schemas.node_schemas import (
    NODE_TYPES,
    validate_node,
)


def _prov() -> dict[str, object]:
    return {
        "source": "manual",
        "method": "rule",
        "confidence": 0.95,
        "loader_version": "test",
    }


GWAS_EDGE_TYPES = {
    "STUDIES",
    "HAS_POPULATION",
    "HAS_LEAD_LOCUS",
    "IMPLICATES_GENE",
    "ASSOCIATED_WITH",
}
GWAS_EDGE_SCHEMA_SUPPORTED = GWAS_EDGE_TYPES.issubset(EDGE_TYPES)


def test_gwas_node_types_are_registered() -> None:
    expected = {"Study", "DiseaseTrait", "Population", "Gene", "RiskLocus"}

    assert expected.issubset(NODE_TYPES)


@pytest.mark.parametrize(
    "node_type,payload",
    [
        (
            "Study",
            {
                "id": "study:pgc_mdd_001",
                "title": "PGC Major Depressive Disorder GWAS",
                "doi": "10.1234/pgc.mdd.001",
                "pmid": "12345678",
                "year": 2024,
                "prov": _prov(),
            },
        ),
        (
            "DiseaseTrait",
            {
                "id": "trait:mdd",
                "name": "Major depressive disorder",
                "phenotype_id": "MONDO:0001234",
                "category": "psychiatric",
                "prov": _prov(),
            },
        ),
        (
            "Population",
            {
                "id": "population:eur",
                "name": "European ancestry",
                "ancestry": "EUR",
                "prov": _prov(),
            },
        ),
        (
            "Gene",
            {
                "id": "gene:drd2",
                "symbol": "DRD2",
                "hgnc_id": "HGNC:3020",
                "prov": _prov(),
            },
        ),
        (
            "RiskLocus",
            {
                "id": "locus:rs123",
                "name": "Lead risk locus 1",
                "rsid": "rs123",
                "chromosome": "11",
                "position": 113000,
                "p_value": 1e-9,
                "prov": _prov(),
            },
        ),
    ],
)
def test_validate_node_accepts_gwas_metadata_nodes(
    node_type: str, payload: dict[str, object]
) -> None:
    node = validate_node(node_type, payload)

    assert node.id == payload["id"]


@pytest.mark.xfail(
    not GWAS_EDGE_SCHEMA_SUPPORTED,
    reason="GWAS edge types are not yet registered in edge_schemas",
    strict=False,
)
def test_gwas_edges_are_registered_with_expected_signatures() -> None:
    expected = {
        "STUDIES",
        "HAS_POPULATION",
        "HAS_LEAD_LOCUS",
        "IMPLICATES_GENE",
        "ASSOCIATED_WITH",
    }

    assert expected.issubset(EDGE_TYPES)
    assert ALLOWED_EDGES["STUDIES"] == (("Publication", "Study"), ("Concept", "DiseaseTrait"))
    assert ("Study", "DiseaseTrait") in EDGE_SIGNATURES["STUDIES"]
    assert ALLOWED_EDGES["HAS_POPULATION"] == ("Study", "Population")
    assert ALLOWED_EDGES["HAS_LEAD_LOCUS"] == ("Study", "RiskLocus")
    assert ALLOWED_EDGES["IMPLICATES_GENE"] == ("RiskLocus", "Gene")
    assert ALLOWED_EDGES["ASSOCIATED_WITH"] == (
        ("Concept", "DiseaseTrait", "RiskLocus"),
        ("Region", "BrainRegion", "DiseaseTrait"),
    )
    assert ("RiskLocus", "DiseaseTrait") in EDGE_SIGNATURES["ASSOCIATED_WITH"]


@pytest.mark.xfail(
    not GWAS_EDGE_SCHEMA_SUPPORTED,
    reason="GWAS edge types are not yet registered in edge_schemas",
    strict=False,
)
@pytest.mark.parametrize(
    "edge_type,payload,expected_source,expected_target",
    [
        (
            "STUDIES",
            {
                "source_id": "study:pgc_mdd_001",
                "target_id": "trait:mdd",
                "source_type": "Study",
                "target_type": "DiseaseTrait",
                "confidence": 0.97,
                "prov": _prov(),
            },
            "Study",
            "DiseaseTrait",
        ),
        (
            "HAS_POPULATION",
            {
                "source_id": "study:pgc_mdd_001",
                "target_id": "population:eur",
                "source_type": "Study",
                "target_type": "Population",
                "confidence": 0.96,
                "prov": _prov(),
            },
            "Study",
            "Population",
        ),
        (
            "HAS_LEAD_LOCUS",
            {
                "source_id": "study:pgc_mdd_001",
                "target_id": "locus:rs123",
                "source_type": "Study",
                "target_type": "RiskLocus",
                "confidence": 0.95,
                "prov": _prov(),
            },
            "Study",
            "RiskLocus",
        ),
        (
            "IMPLICATES_GENE",
            {
                "source_id": "locus:rs123",
                "target_id": "gene:drd2",
                "source_type": "RiskLocus",
                "target_type": "Gene",
                "confidence": 0.94,
                "prov": _prov(),
            },
            "RiskLocus",
            "Gene",
        ),
        (
            "ASSOCIATED_WITH",
            {
                "source_id": "locus:rs123",
                "target_id": "trait:mdd",
                "source_type": "RiskLocus",
                "target_type": "DiseaseTrait",
                "confidence": 0.93,
                "prov": _prov(),
            },
            "RiskLocus",
            "DiseaseTrait",
        ),
    ],
)
def test_validate_edge_accepts_gwas_metadata_relationships(
    edge_type: str,
    payload: dict[str, object],
    expected_source: str,
    expected_target: str,
) -> None:
    edge = validate_edge(edge_type, payload)

    assert edge.source_type == expected_source
    assert edge.target_type == expected_target


@pytest.mark.xfail(
    not GWAS_EDGE_SCHEMA_SUPPORTED,
    reason="GWAS edge types are not yet registered in edge_schemas",
    strict=False,
)
def test_validate_edge_rejects_wrong_direction_for_associated_with() -> None:
    with pytest.raises(ValidationError):
        validate_edge(
            "ASSOCIATED_WITH",
            {
                "source_id": "trait:mdd",
                "target_id": "locus:rs123",
                "source_type": "DiseaseTrait",
                "target_type": "RiskLocus",
                "confidence": 0.9,
                "prov": _prov(),
            },
        )
