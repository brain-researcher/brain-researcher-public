"""Compatibility smoke tests for ANTs and AFNI NiWrap coverage."""
from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools


def _alias_set(package: str) -> set[str]:
    tools = get_niwrap_tools(packages=[package], use_cache=False, test_mode=False)
    return {t["metadata"].get("alias") for t in tools if t.get("metadata")}


def test_ants_alias_present():
    aliases = _alias_set("ants")
    assert "ants.antsRegistration.run" in aliases


def test_afni_aliases_present():
    aliases = _alias_set("afni")
    expected = {"afni.3dBlurInMask.run", "afni.3dReHo.run"}
    missing = expected - aliases
    assert not missing, f"Missing AFNI tools: {missing}"
