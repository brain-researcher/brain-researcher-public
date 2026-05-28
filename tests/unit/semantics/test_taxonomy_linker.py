import pytest

from brain_researcher.services.neurokg.etl.linkers.taxonomy_linker import TaxonomyLinker


def test_taxonomy_linker_returns_concepts_for_known_task():
    linker = TaxonomyLinker()
    task = {
        "id": "neurostore_task:demo",
        "taxonomy_match": {
            "canonical_id": "task:n-back",
            "match_method": "taxonomy_rule",
            "confidence": 0.93,
            "match_string": "Verbal n-back",
            "source_rule": {"id": "rule-nback"},
        },
    }

    suggestions = linker.suggestions_for_task(task)
    assert suggestions, "Expected at least one suggestion for n-back"
    concept_ids = {s.concept_id for s in suggestions}
    assert "trm_4a3fd79d0a5c8" in concept_ids
    assert suggestions[0].confidence == pytest.approx(0.93, rel=1e-6)


def test_taxonomy_linker_applies_fallback_confidence():
    linker = TaxonomyLinker()
    task = {
        "id": "neurostore_task:demo",
        "taxonomy_match": {
            "canonical_id": "task:go_no-go",
            "match_method": "alias_match",
            "match_string": "go nogo",
        },
    }

    suggestions = linker.suggestions_for_task(task)
    assert suggestions
    assert suggestions[0].confidence == pytest.approx(0.8, rel=1e-6)


def test_taxonomy_linker_handles_unknown_canonical():
    linker = TaxonomyLinker()
    task = {
        "id": "neurostore_task:demo",
        "taxonomy_match": {
            "canonical_id": "task:nonexistent",
            "match_method": "taxonomy_rule",
        },
    }

    assert linker.suggestions_for_task(task) == []
