from __future__ import annotations

from brain_researcher.services.tools.executor import _resolve_python_tool_instance
from brain_researcher.services.tools.spec import ToolSpec


def test_resolve_module_function_entrypoint_for_run_local_script():
    spec = ToolSpec(
        name="run_local_script",
        description="stub",
        backend="python",
        python_class=(
            "brain_researcher.services.tools.grandmaster.runtime_tools:"
            "run_local_script_tool"
        ),
    )

    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert hasattr(tool, "run")
    assert callable(tool.run)


def test_resolve_class_entrypoint_still_works():
    spec = ToolSpec(
        name="fitlins.multiverse_robustness_report",
        description="stub",
        backend="python",
        python_class=(
            "brain_researcher.services.tools.multiverse_robustness_tool."
            "FitLinsMultiverseRobustnessReportTool"
        ),
    )

    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.__class__.__name__ == "FitLinsMultiverseRobustnessReportTool"


def test_resolve_invalid_entrypoint_returns_none():
    spec = ToolSpec(
        name="broken_tool",
        description="stub",
        backend="python",
        python_class="brain_researcher.services.tools.does_not_exist:missing",
    )

    assert _resolve_python_tool_instance(spec) is None


def test_resolve_module_prefers_non_alias_task_mapping_impl():
    spec = ToolSpec(
        name="task_to_concept_mapping",
        description="stub",
        backend="python",
        python_class="brain_researcher.services.tools.neurokg_tools",
    )

    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.__class__.__name__ == "TaskMappingTool"


def test_resolve_explicit_task_mapping_class_entrypoint():
    spec = ToolSpec(
        name="task_to_concept_mapping",
        description="stub",
        backend="python",
        python_class="brain_researcher.services.tools.neurokg_tools.TaskMappingTool",
    )

    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.__class__.__name__ == "TaskMappingTool"
