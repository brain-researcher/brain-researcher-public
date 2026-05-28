from __future__ import annotations

from brain_researcher.services.tools.runtime_profiles import (
    get_neurodesk_package_profile,
    normalize_runtime_package_name,
)


def test_normalize_runtime_package_name_maps_runtime_tool_ids_to_packages() -> None:
    assert normalize_runtime_package_name("fsl_bet") == "fsl"
    assert normalize_runtime_package_name("ants_registration") == "ants"
    assert normalize_runtime_package_name("spm12_vbm") == "cat12"


def test_get_neurodesk_package_profile_resolves_runtime_tool_ids() -> None:
    fsl_profile = get_neurodesk_package_profile("fsl_bet")
    ants_profile = get_neurodesk_package_profile("ants_registration")
    cat12_profile = get_neurodesk_package_profile("spm12_vbm")

    assert fsl_profile is not None
    assert fsl_profile["name"] == "fsl"
    assert fsl_profile["module_name"] == "fsl"
    assert fsl_profile["version"] == "6.0.7.18"

    assert ants_profile is not None
    assert ants_profile["name"] == "ants"
    assert ants_profile["module_name"] == "ants"

    assert cat12_profile is not None
    assert cat12_profile["name"] == "cat12"
    assert cat12_profile["module_name"] == "cat12"
    assert cat12_profile["recommended_version"] == "12.9"
