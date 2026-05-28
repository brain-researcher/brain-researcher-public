from __future__ import annotations

from unittest.mock import patch

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool


def _tool_definition(name: str, boutiques_inputs: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "metadata": {
            "package": "fsl",
            "command_line": "fix [FEAT]",
            "boutiques_inputs": boutiques_inputs
            or [
                {
                    "id": "feat_dir",
                    "value-key": "[FEAT]",
                    "type": "String",
                }
            ],
        },
    }


def test_execute_niwrap_tool_supports_legacy_tool_name_signature():
    tool_def = _tool_definition("fsl.6.0.7.fslFixText.run")

    with patch(
        "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name",
        return_value=tool_def,
    ), patch(
        "brain_researcher.services.tools.niwrap.executor._resolve_container_config",
        return_value={"image": "dummy.sif", "binds": [], "env": {}},
    ), patch(
        "brain_researcher.services.tools.executors.run_container",
        return_value={"exit_code": 0, "stdout": "ok", "stderr": "", "mode": "container"},
    ):
        result = execute_niwrap_tool(
            tool_name="fsl.fslFixText.run",
            parameters={"feat_dir": "demo.feat"},
        )

    assert result["tool"] == "fsl.6.0.7.fslFixText.run"
    assert result["exit_code"] == 0
    assert result["stdout"] == "ok"


def test_execute_niwrap_tool_resolves_short_name_via_catalog_scan():
    tool_def = _tool_definition(
        "ants.2.5.4.antsRegistration.run",
        boutiques_inputs=[
            {
                "id": "fixed_image",
                "value-key": "[FIXED]",
                "type": "String",
            },
            {
                "id": "moving_image",
                "value-key": "[MOVING]",
                "type": "String",
            },
        ],
    )

    with patch(
        "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name",
        return_value=None,
    ), patch(
        "brain_researcher.services.tools.niwrap.catalog.get_niwrap_tools",
        return_value=[tool_def],
    ), patch(
        "brain_researcher.services.tools.niwrap.executor._resolve_container_config",
        return_value={"image": "dummy.sif", "binds": [], "env": {}},
    ), patch(
        "brain_researcher.services.tools.executors.run_container",
        return_value={"exit_code": 0, "stdout": "ok", "stderr": "", "mode": "container"},
    ):
        result = execute_niwrap_tool(
            tool_name="ants.antsRegistration.run",
            parameters={"fixed_image": "fixed.nii.gz", "moving_image": "moving.nii.gz"},
        )

    assert result["tool"] == "ants.2.5.4.antsRegistration.run"
    assert result["exit_code"] == 0
