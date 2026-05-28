import pytest

from brain_researcher.services.agent.planner.synonyms_loader import match_intents_from_text


@pytest.mark.parametrize(
    "query,expected",
    [
        ("run tckgen on this dwi", "dmri_tractography"),
        ("please recon-all the T1", "smri_recon_all"),
        ("use bidsapp.fmriprep.run", "fmriprep_preprocessing"),
        ("bet this structural", "skull_strip_mri"),
        ("wb_command surface-smoothing", "generic_container_op"),
        ("mrtrix3 dwi2fod", "dmri_model_fit"),
    ],
)
def test_intent_matching_niwrap_fallbacks(query: str, expected: str):
    ids = [i.id for i in match_intents_from_text(query)]
    assert expected in ids
