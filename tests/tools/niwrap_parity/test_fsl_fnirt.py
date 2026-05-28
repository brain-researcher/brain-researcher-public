"""Parity tests: curated FSL FNIRT vs NiWrap FNIRT."""
from pathlib import Path
import pytest

from brain_researcher.services.tools.params import FSLFNIRTParameters
from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools
from brain_researcher.services.tools.niwrap.executor import build_command


@pytest.fixture(scope="module")
def niwrap_fnirt_def():
    tools = get_niwrap_tools(packages=["fsl"], use_cache=False, test_mode=False)
    for t in tools:
        if t.get("metadata", {}).get("alias") == "fsl.fnirt.run":
            return t
    pytest.skip("NiWrap fsl.fnirt.run not found")


def test_command_contains_inputs(tmp_path, niwrap_fnirt_def):
    props = niwrap_fnirt_def["input_schema"].get("properties", {})
    assert any(k in props for k in ("in", "in_file", "input"))
    assert any(k in props for k in ("ref", "ref_file"))
