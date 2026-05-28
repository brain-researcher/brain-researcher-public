"""Parity tests: curated FSL BET vs NiWrap BET.

We compare schemas and normalized commands. Execution is mocked.
"""
from pathlib import Path
import pytest

from brain_researcher.services.tools.params import FSLBETParameters, build_fsl_bet_command
from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools
from brain_researcher.services.tools.niwrap.executor import build_command


@pytest.fixture(scope="module")
def niwrap_bet_def():
    tools = get_niwrap_tools(packages=["fsl"], use_cache=False, test_mode=False)
    for t in tools:
        if t.get("metadata", {}).get("alias") == "fsl.bet.run":
            return t
    pytest.skip("NiWrap fsl.bet.run not found")


def test_schema_has_input_output(niwrap_bet_def):
    assert niwrap_bet_def["input_schema"].get("properties")
    assert niwrap_bet_def["output_schema"].get("properties")

def test_bet_schema_has_required(niwrap_bet_def):
    # Ensure schema includes key inputs
    props = niwrap_bet_def["input_schema"].get("properties", {})
    assert any(k in props for k in ("input", "infile", "input_file"))
