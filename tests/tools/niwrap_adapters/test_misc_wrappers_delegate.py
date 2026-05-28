"""Delegate tests for PALM and ANTs IntegrateVectorField NiWrap thin wrappers."""
from unittest.mock import patch

import pytest

from brain_researcher.services.tools.fsl_palm_tool import FSLPALMNiWrapTool
from brain_researcher.services.tools.ants_integrate_vector_tool import (
    ANTsIntegrateVectorFieldTool,
)


@pytest.mark.parametrize(
    "tool_cls,tool_name,kwargs",
    [
        (FSLPALMNiWrapTool, "fsl.palm.run", {"input_file": "in.nii.gz", "design_matrix": "design.mat", "contrast_file": "con.con", "output_dir": "./out"}),
        (ANTsIntegrateVectorFieldTool, "ants.ANTSIntegrateVectorField.run", {"output": "out.nii.gz"}),
    ],
)
@patch("brain_researcher.services.tools.fsl_palm_tool.execute_niwrap_tool")
@patch("brain_researcher.services.tools.ants_integrate_vector_tool.execute_niwrap_tool")
def test_misc_wrappers_delegate(mock_ants_exec, mock_palm_exec, tool_cls, tool_name, kwargs):
    # select correct mock
    name_to_mock = {
        "fsl.palm.run": mock_palm_exec,
        "ants.ANTSIntegrateVectorField.run": mock_ants_exec,
    }
    m = name_to_mock[tool_name]
    m.return_value = {"ok": True}

    tool = tool_cls()
    result = tool._run(**kwargs)

    assert result.status == "success"
    assert result.data == {"ok": True}
    m.assert_called_once()
    call_kwargs = m.call_args.kwargs
    assert call_kwargs["tool_name"] == tool_name
    assert call_kwargs["parameters"] == kwargs
