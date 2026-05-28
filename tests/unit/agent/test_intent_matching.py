import pytest

from brain_researcher.services.agent.planner.synonyms_loader import match_intents_from_text
from brain_researcher.services.agent.planner.catalog_loader import load_intents


@pytest.fixture(scope="module")
def intents():
    return load_intents()


def _ids(intents_list):
    return [i.id for i in intents_list]


def test_match_intent_glm_first_level(intents):
    matched = match_intents_from_text("glm first level")
    assert "glm_first_level_fmri" in _ids(matched)


def test_match_intent_meta_analysis(intents):
    matched = match_intents_from_text("coordinate based meta analysis")
    assert "meta_analysis_cbma" in _ids(matched)


def test_match_intent_nwb(intents):
    matched = match_intents_from_text("open nwb file")
    assert "nwb_io" in _ids(matched)


def test_match_intent_robustness_audit(intents):
    matched = match_intents_from_text("run a robustness audit with multiverse analysis")
    ids = _ids(matched)
    assert "permutation_testing" in ids


def test_match_intent_condition_matrix(intents):
    matched = match_intents_from_text("build a condition matrix for evidence conflict mapping")
    ids = _ids(matched)
    assert "rag_retrieval" in ids
