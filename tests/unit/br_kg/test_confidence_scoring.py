from brain_researcher.services.br_kg.quality.confidence import (
    compute_confidence_from_props,
    support_keys,
)


def test_support_keys_prioritize_pmid():
    evidence = {
        "pmid": "123",
        "doi": "10.1000/xyz",
        "dataset_key": "openneuro:ds000001",
    }
    keys = support_keys(evidence)
    assert keys == ["pmid:123"]


def test_support_keys_fallback_to_doi():
    evidence = {"doi": "10.1000/xyz"}
    keys = support_keys(evidence)
    assert keys == ["doi:10.1000/xyz"]


def test_compute_confidence_from_props_basic():
    rel_props = {
        "evidence": [
            {
                "pmid": "123",
                "source": "cogatlas",
                "evidence_type": "ontology_link",
            }
        ],
        "prov_source": "major_ontology",
        "prov_method": "exact_id",
    }
    result = compute_confidence_from_props(rel_props)
    assert result is not None
    assert 0.05 <= result["confidence"] <= 0.2
    assert result["support_count_unique"] == 1
    assert result["source_diversity"] == 1
