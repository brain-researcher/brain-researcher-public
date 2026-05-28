"""Delegate tests for new AFNI NiWrap-backed tools."""

from unittest.mock import patch

import pytest

from brain_researcher.services.tools.afni_clustsim_tool import (
    AFNI3dBlurInMaskTool,
    AFNI3dReHoTool,
)


@pytest.mark.parametrize(
    "tool_cls,tool_name",
    [
        (AFNI3dBlurInMaskTool, "afni.3dBlurInMask.run"),
        (AFNI3dReHoTool, "afni.3dReHo.run"),
    ],
)
def test_afni_wrappers_delegate(tool_cls, tool_name):
    tool = tool_cls()
    kwargs = {"dummy": "value"}

    with patch("brain_researcher.services.tools.afni_clustsim_tool.execute_niwrap_tool") as mock_exec:
        mock_exec.return_value = {"ok": True}
        result = tool._run(**kwargs)

    mock_exec.assert_called_once()
    called_tool_name = mock_exec.call_args.kwargs.get("tool_name")
    called_params = mock_exec.call_args.kwargs.get("parameters")

    assert called_tool_name == tool_name
    assert called_params == kwargs
    assert result.status == "success"
