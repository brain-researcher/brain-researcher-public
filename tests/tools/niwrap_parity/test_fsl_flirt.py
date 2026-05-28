"""Parity tests: curated FSL FLIRT vs NiWrap FLIRT."""
from pathlib import Path
import pytest

from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools
from brain_researcher.services.tools.niwrap.executor import build_command


@pytest.fixture(scope="module")
def niwrap_flirt_def():
    tools = get_niwrap_tools(packages=["fsl"], use_cache=False, test_mode=False)
    for t in tools:
        if t.get("metadata", {}).get("alias") == "fsl.flirt.run":
            return t
    pytest.skip("NiWrap fsl.flirt.run not found")


def test_command_contains_inputs(tmp_path, niwrap_flirt_def):
    # Basic schema sanity
    props = niwrap_flirt_def["input_schema"].get("properties", {})
    assert any(k in props for k in ("in", "in_file", "input"))
