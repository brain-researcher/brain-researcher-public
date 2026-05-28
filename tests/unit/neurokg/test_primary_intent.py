from brain_researcher.services.neurokg.loader.tools_catalog_loader import select_primary_intent


def test_primary_intent_prefers_method_over_impl():
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "priority": ["glm_first_level_fmri"],
    }
    result = select_primary_intent(
        ["generic_container_op", "glm_first_level_fmri"],
        category=None,
        families=[],
        intent_config=intent_config,
    )
    assert result == "glm_first_level_fmri"


def test_primary_intent_fallbacks_to_category():
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "priority": [],
    }
    result = select_primary_intent(
        ["generic_container_op"],
        category="preprocessing",
        families=[],
        intent_config=intent_config,
    )
    assert result == "preprocessing"


def test_primary_intent_priority_order():
    intent_config = {
        "impl_intents": [],
        "priority": ["registration", "skull_strip_mri"],
    }
    result = select_primary_intent(
        ["skull_strip_mri", "registration"],
        category=None,
        families=[],
        intent_config=intent_config,
    )
    assert result == "registration"
