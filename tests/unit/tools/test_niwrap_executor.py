from __future__ import annotations

from unittest.mock import patch

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool


def test_execute_niwrap_tool_supports_legacy_tool_name_entrypoint() -> None:
    fake_tool = {
        "name": "fsl.6.0.4.bet.run",
        "metadata": {
            "package": "fsl",
            "command_line": "bet",
            "boutiques_inputs": [],
        },
    }

    with patch(
        "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name",
        return_value=None,
    ), patch(
        "brain_researcher.services.tools.niwrap.catalog.get_niwrap_tools",
        return_value=[fake_tool],
    ), patch(
        "brain_researcher.services.tools.niwrap.executor._resolve_container_config",
        return_value={
            "image": "fsl.sif",
            "runtime": "apptainer",
            "binds": [],
            "env": {},
            "network_disabled": True,
        },
    ), patch(
        "brain_researcher.services.tools.executors.run_container",
        return_value={"exit_code": 0, "stdout": "ok", "stderr": "", "mode": "container"},
    ):
        result = execute_niwrap_tool(
            tool_definition=None,
            tool_name="fsl.bet.run",
            parameters={},
        )

    assert result["tool"] == "fsl.6.0.4.bet.run"
    assert result["exit_code"] == 0
    assert result["stdout"] == "ok"
