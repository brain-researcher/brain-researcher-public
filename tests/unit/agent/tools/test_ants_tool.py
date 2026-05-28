from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from brain_researcher.services.tools.ants_tool import (
    ANTsRegistrationArgs,
    ANTsRegistrationTool,
)


def test_ants_tool_metadata() -> None:
    tool = ANTsRegistrationTool()

    assert tool.get_tool_name() == "ants_registration"
    assert "registration" in tool.get_tool_description().lower()
    assert tool.get_args_schema() is ANTsRegistrationArgs


@patch("brain_researcher.services.tools.ants_tool.render_registration_checkerboard_png")
@patch("brain_researcher.services.tools.ants_tool.execute_niwrap_tool")
def test_ants_registration_emits_qc_png_when_warped_output_exists(
    mock_execute,
    mock_render,
    tmp_path,
) -> None:
    fixed = tmp_path / "fixed.nii.gz"
    moving = tmp_path / "moving.nii.gz"
    warped = tmp_path / "reg_Warped.nii.gz"
    fixed.touch()
    moving.touch()
    warped.touch()

    mock_execute.return_value = {
        "outputs": {
            "warped_image": str(warped),
            "affine_transform": str(tmp_path / "reg_0GenericAffine.mat"),
        }
    }
    mock_render.side_effect = lambda *_args, **_kwargs: str(_args[2])

    tool = ANTsRegistrationTool()
    result = tool._run(
        fixed_image=str(fixed),
        moving_image=str(moving),
        output_prefix=str(tmp_path / "reg"),
    )

    assert result.status == "success"
    assert result.data["outputs"]["qc_png"].endswith("_qc.png")
    assert result.data["outputs"]["checkerboard"].endswith("_qc.png")
    mock_render.assert_called_once()
    rendered_path = Path(result.data["outputs"]["qc_png"])
    assert rendered_path.name.endswith("_qc.png")
