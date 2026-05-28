from __future__ import annotations

from brain_researcher.services.tools.catalog_loader import (
    resolve_catalog_tool_ids,
    resolve_runtime_tool_ids,
)


def test_resolve_runtime_tool_ids_bridges_searchlight_catalog_and_runtime_ids():
    runtime_ids = resolve_runtime_tool_ids("python.searchlight_fmri.run", include_self=True)
    assert "searchlight_analysis" in runtime_ids
    assert "run_searchlight" in runtime_ids

    catalog_ids = resolve_catalog_tool_ids("searchlight_analysis", include_self=True)
    assert "python.searchlight_fmri.run" in catalog_ids


def test_resolve_runtime_tool_ids_keeps_dotted_runtime_heuristic():
    candidates = resolve_runtime_tool_ids("ants.brain_extraction.run", include_self=False)
    assert candidates[0] == "ants_brain_extraction"
    assert "ants_brain_extraction" in candidates


def test_resolve_runtime_tool_ids_keeps_canonical_runtime_ids_first():
    candidates = resolve_runtime_tool_ids("fsl_bet", include_self=True)

    assert candidates == ["fsl_bet"]
    assert "fsl.bet.run" not in candidates


def test_resolve_catalog_tool_ids_adds_runtime_heuristic_back_to_planner_id():
    catalog_ids = resolve_catalog_tool_ids("fsl_bet", include_self=True)

    assert "fsl_bet" in catalog_ids
    assert "fsl.bet.run" in catalog_ids


def test_resolve_runtime_tool_ids_bridges_glm_multiverse_alias_to_canonical_id():
    runtime_ids = resolve_runtime_tool_ids("glm_multiverse.run", include_self=True)

    assert runtime_ids == ["glm_multiverse"]

    catalog_ids = resolve_catalog_tool_ids("glm_multiverse", include_self=True)
    assert "glm_multiverse" in catalog_ids
    assert "glm_multiverse.run" in catalog_ids
