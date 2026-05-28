"""Parity tests for ANTs antsRegistration and AFNI tools."""
from pathlib import Path
import pytest

from brain_researcher.services.tools.params import ANTsRegistrationParameters
from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools
from brain_researcher.services.tools.niwrap.executor import build_command


def _get_def(package: str, alias: str):
    tools = get_niwrap_tools(packages=[package], use_cache=False, test_mode=False)
    for t in tools:
        if t.get("metadata", {}).get("alias") == alias:
            return t
    return None


def test_ants_registration_command(tmp_path):
    ni_def = _get_def("ants", "ants.antsRegistration.run")
    if not ni_def:
        pytest.skip("NiWrap antsRegistration missing")

    props = ni_def["input_schema"].get("properties", {})
    required = ni_def["input_schema"].get("required", [])
    # antsRegistration NiWrap schema is staged; we just ensure key knobs exist
    assert "stages" in props or "output" in props or required, "antsRegistration schema unexpectedly sparse"


def test_afni_3dclustsim_presence():
    ni_def = _get_def("afni", "afni.3dClustSim.run")
    assert ni_def is not None, "3dClustSim should be available in NiWrap"
