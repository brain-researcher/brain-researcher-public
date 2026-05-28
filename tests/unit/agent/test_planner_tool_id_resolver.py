from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM
from brain_researcher.services.agent.planner.tool_id_resolver import (
    resolve_planner_tool_id_to_registry_tool_names,
)
from brain_researcher.services.agent.tool_executor import ToolExecutor


@pytest.mark.parametrize(
    ("tool_id", "expected"),
    [
        ("python.data_harmonization.run", "data_harmonization"),
        ("python.brain_simulation.run", "brain_simulation"),
        ("python.realtime_fmri.run", "realtime_fmri"),
        ("python.lesion_detection.run", "lesion_detection"),
        ("python.searchlight_fmri.run", "searchlight_analysis"),
        ("fsl.bet.run", "fsl_bet"),
        ("fsl.flirt.run", "fsl_flirt"),
        ("ants.brain_extraction.run", "ants_brain_extraction"),
    ],
)
def test_resolve_planner_python_tool_ids(tool_id: str, expected: str) -> None:
    names = resolve_planner_tool_id_to_registry_tool_names(tool_id)
    assert names == [expected]


def test_neuro_agent_llm_maps_planner_ids_to_registry_tools() -> None:
    dummy = SimpleNamespace()
    dummy.tools = [
        SimpleNamespace(name="data_harmonization"),
        SimpleNamespace(name="brain_simulation"),
    ]

    method = NeuroAgentLLM._convert_planner_tool_ids_to_registry_tools.__get__(
        dummy, NeuroAgentLLM
    )

    selected = method(
        ["python.data_harmonization.run", "python.brain_simulation.run"],
        families=[],
    )

    assert [t.name for t in selected] == ["data_harmonization", "brain_simulation"]


def test_tool_executor_get_tool_falls_back_to_resolved_registry_name() -> None:
    fake_tool = object()
    fake_registry = MagicMock()
    fake_registry.get_tool.side_effect = (
        lambda name: fake_tool if name == "data_harmonization" else None
    )

    fake_neurodesk = MagicMock()
    fake_neurodesk.get_tool_by_name.return_value = None

    executor = ToolExecutor(tool_registry=fake_registry, neurodesk_tools=fake_neurodesk)
    resolved = executor._get_tool("python.data_harmonization.run")
    assert resolved is fake_tool


def test_tool_executor_get_tool_falls_back_to_dotted_runtime_name() -> None:
    fake_tool = object()
    fake_registry = MagicMock()
    fake_registry.get_tool.side_effect = (
        lambda name: fake_tool if name == "fsl_bet" else None
    )

    fake_neurodesk = MagicMock()
    fake_neurodesk.get_tool_by_name.return_value = None

    executor = ToolExecutor(tool_registry=fake_registry, neurodesk_tools=fake_neurodesk)
    resolved = executor._get_tool("fsl.bet.run")
    assert resolved is fake_tool


def test_tool_executor_get_tool_raises_for_unregistered_resolved_name() -> None:
    fake_registry = MagicMock()
    fake_registry.get_tool.return_value = None

    fake_neurodesk = MagicMock()
    fake_neurodesk.get_tool_by_name.return_value = None

    executor = ToolExecutor(tool_registry=fake_registry, neurodesk_tools=fake_neurodesk)

    with pytest.raises(ValueError, match="Tool 'ants.brain_extraction.run' not found"):
        executor._get_tool("ants.brain_extraction.run")


pytestmark = pytest.mark.unit
