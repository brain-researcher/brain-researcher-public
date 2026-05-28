"""Compatibility smoke tests: curated FSL tools vs NiWrap coverage.

These tests do not execute containers; they only verify that NiWrap exposes
known FSL tools we care about (bet, flirt, fnirt) and that basic metadata is
present. This is the first step toward migrating curated wrappers to NiWrap.
"""
from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools


def _alias_set(package: str) -> set[str]:
    tools = get_niwrap_tools(packages=[package], use_cache=False, test_mode=False)
    return {t["metadata"].get("alias") for t in tools if t.get("metadata")}


def _get_by_alias(package: str, alias: str):
    tools = get_niwrap_tools(packages=[package], use_cache=False, test_mode=False)
    for t in tools:
        if t.get("metadata", {}).get("alias") == alias:
            return t
    return None


def test_fsl_aliases_present():
    aliases = _alias_set("fsl")
    for expected in {"fsl.bet.run", "fsl.flirt.run", "fsl.fnirt.run"}:
        assert expected in aliases, f"NiWrap missing alias {expected}"


def test_fsl_metadata_basic():
    for alias, app in [
        ("fsl.bet.run", "bet"),
        ("fsl.flirt.run", "flirt"),
        ("fsl.fnirt.run", "fnirt"),
    ]:
        tool = _get_by_alias("fsl", alias)
        assert tool is not None, f"No tool for alias {alias}"
        meta = tool["metadata"]
        assert meta["package"] == "fsl"
        assert meta["app"] == app
        assert tool["input_schema"].get("properties"), "Input schema empty"
        # Ensure container info is present
        assert meta.get("container"), "Missing container spec"
