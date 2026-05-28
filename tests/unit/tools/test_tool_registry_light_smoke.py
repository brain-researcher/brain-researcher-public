"""Smoke tests for ToolRegistry light mode registration."""

from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_light_registry_includes_pipeline_search_and_afni_deconvolve():
    registry = ToolRegistry(light_mode=True)

    assert registry.get_tool("pipeline.search") is not None
    assert registry.get_tool("afni_3dDeconvolve") is not None
    assert registry.get_tool("ibl_neuropixels_workflow") is not None
    assert registry.get_tool("ibl_decoding_dataset") is not None
    assert registry.get_tool("qbold_fabber") is not None
    assert registry.get_tool("calibrated_perfusion_surrogate") is not None
    assert registry.get_tool("literature.fixed_hrf_scoping") is not None
    assert registry.get_tool("reproducibility.bundle") is not None
