"""Ensure thin FSL wrappers delegate to NiWrap executor with correct tool_id."""
from unittest.mock import patch

import pytest

from brain_researcher.services.tools.fsl_bet_tool import FSLBETTool
from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTool
from brain_researcher.services.tools.fsl_fnirt_tool import FSLFNIRTTool
from brain_researcher.services.tools.fsl_fix_tool import FSLFIXNiWrapTool


def _basic_kwargs(name):
    if name == "bet":
        return {"input_file": "in.nii.gz", "output_file": "out.nii.gz"}
    if name == "flirt":
        return {
            "input_file": "in.nii.gz",
            "reference_file": "ref.nii.gz",
            "output_file": "out.nii.gz",
        }
    if name == "fnirt":
        return {
            "in_file": "in.nii.gz",
            "ref_file": "ref.nii.gz",
            "output_dir": "./out",
            "out_file": "out.nii.gz",
        }
    if name == "fix":
        return {
            "feat_dir": "./feat",
            "threshold": 20,
        }
    raise ValueError(name)


@pytest.mark.parametrize(
    "tool_cls,tool_name,kwargs_key",
    [
        (FSLBETTool, "fsl.bet.run", "bet"),
        (FSLFLIRTTool, "fsl.flirt.run", "flirt"),
        (FSLFNIRTTool, "fsl.fnirt.run", "fnirt"),
        (FSLFIXNiWrapTool, "fsl.fslFixText.run", "fix"),
    ],
)
@patch("brain_researcher.services.tools.fsl_bet_tool.execute_niwrap_tool")
@patch("brain_researcher.services.tools.fsl_flirt_tool.execute_niwrap_tool")
@patch("brain_researcher.services.tools.fsl_fnirt_tool.execute_niwrap_tool")
@patch("brain_researcher.services.tools.fsl_fix_tool.execute_niwrap_tool")
def test_fsl_wrappers_delegate(mock_fix, mock_fnirt, mock_flirt, mock_bet, tool_cls, tool_name, kwargs_key):
    # select correct mock
    name_to_mock = {
        "fsl.bet.run": mock_bet,
        "fsl.flirt.run": mock_flirt,
        "fsl.fnirt.run": mock_fnirt,
        "fsl.fslFixText.run": mock_fix,
    }
    m = name_to_mock[tool_name]
    m.return_value = {"ok": True}

    tool = tool_cls()
    kwargs = _basic_kwargs(kwargs_key)
    result = tool._run(**kwargs)

    assert result.status == "success"
    assert result.data == {"ok": True}
    m.assert_called_once()
    call_kwargs = m.call_args.kwargs
    assert call_kwargs["tool_name"] == tool_name
    # ensure passthrough of params
    assert all(item in call_kwargs["parameters"].items() for item in kwargs.items())
