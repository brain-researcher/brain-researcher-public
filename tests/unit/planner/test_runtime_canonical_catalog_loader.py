from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    get_tool_by_id,
    legacy_tool_to_capability,
    load_tools_catalog_json,
)


def test_merged_catalog_container_tool_survives_into_planner_index():
    tools = load_tools_catalog_json()
    assert "spm12_vbm" in tools

    capability = legacy_tool_to_capability("spm12_vbm", tools["spm12_vbm"])
    assert capability.id == "spm12_vbm"
    assert capability.runtime_kind == "container"

    get_capability_index.cache_clear()
    index = get_capability_index(include_local_first=True)
    assert "spm12_vbm" in index.by_id


def test_get_tool_by_id_resolves_legacy_aliases_to_runtime_names():
    get_capability_index.cache_clear()

    expectations = {
        "fsl.bet.run": "fsl_bet",
        "python.fetch_atlas.run": "fetch_atlas",
        "python.searchlight_fmri.run": "searchlight_analysis",
        "cat12": "spm12_vbm",
        "python.neuroimaging.spm12_vbm": "spm12_vbm",
    }

    for raw_id, canonical_id in expectations.items():
        tool = get_tool_by_id(raw_id)
        assert tool is not None, raw_id
        assert tool.id == canonical_id
