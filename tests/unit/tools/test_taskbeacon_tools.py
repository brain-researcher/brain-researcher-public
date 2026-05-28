from __future__ import annotations

from pathlib import Path

from brain_researcher.services.tools import taskbeacon_tools
from brain_researcher.services.tools.registry import UnifiedToolRegistry


def test_taskbeacon_tool_module_exports_expected_names() -> None:
    names = {tool.get_tool_name() for tool in taskbeacon_tools.get_all_tools()}

    assert names == {
        "taskbeacon.list_tasks",
        "taskbeacon.download_task",
        "taskbeacon.localize_task",
        "taskbeacon.run_qa_sim",
    }


def test_taskbeacon_list_tool_wraps_adapter(monkeypatch) -> None:
    def fake_list_taskbeacon_tasks(**kwargs):
        assert kwargs["query"] == "ant"
        assert kwargs["limit"] == 5
        return {"status": "success", "tasks": [{"repo": "TaskBeacon/T000015-ant"}]}

    monkeypatch.setattr(
        taskbeacon_tools,
        "list_taskbeacon_tasks",
        fake_list_taskbeacon_tasks,
    )

    result = taskbeacon_tools.TaskBeaconListTasksTool()._run(query="ant", limit=5)

    assert result.status == "success"
    assert result.data == {
        "status": "success",
        "tasks": [{"repo": "TaskBeacon/T000015-ant"}],
    }


def test_taskbeacon_run_tool_uses_work_dir_as_workspace_root(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    def fake_run_taskbeacon_qa_sim(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "artifacts": []}

    monkeypatch.setattr(
        taskbeacon_tools,
        "run_taskbeacon_qa_sim",
        fake_run_taskbeacon_qa_sim,
    )

    result = taskbeacon_tools.TaskBeaconRunQASimTool()._run(
        task_path="projects/proj/taskbeacon/T000015-ant",
        work_dir=str(tmp_path),
    )

    assert result.status == "success"
    assert calls[0]["workspace_root"] == tmp_path


def test_taskbeacon_download_tool_uses_work_dir_as_workspace_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []

    def fake_download_taskbeacon_task(**kwargs):
        calls.append(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        taskbeacon_tools,
        "download_taskbeacon_task",
        fake_download_taskbeacon_task,
    )

    result = taskbeacon_tools.TaskBeaconDownloadTaskTool()._run(
        repo="TaskBeacon/T000015-ant",
        work_dir=str(tmp_path),
    )

    assert result.status == "success"
    assert calls[0]["workspace_root"] == tmp_path


def test_taskbeacon_download_tool_surfaces_in_band_adapter_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_download_taskbeacon_task(**_kwargs):
        return {"status": "error", "stderr": "fatal: network blocked"}

    monkeypatch.setattr(
        taskbeacon_tools,
        "download_taskbeacon_task",
        fake_download_taskbeacon_task,
    )

    result = taskbeacon_tools.TaskBeaconDownloadTaskTool()._run(
        repo="TaskBeacon/T000015-ant",
        work_dir=str(tmp_path),
    )

    assert result.status == "error"
    assert result.data == {"status": "error", "stderr": "fatal: network blocked"}
    assert "fatal: network blocked" in str(result.error)


def test_taskbeacon_localize_tool_uses_work_dir_as_workspace_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []

    def fake_localize_taskbeacon_task(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "text": "localized"}

    monkeypatch.setattr(
        taskbeacon_tools,
        "localize_taskbeacon_task",
        fake_localize_taskbeacon_task,
    )

    result = taskbeacon_tools.TaskBeaconLocalizeTaskTool()._run(
        task_path="projects/proj/taskbeacon/T000015-ant",
        target_language="French",
        work_dir=str(tmp_path),
    )

    assert result.status == "success"
    assert calls[0]["workspace_root"] == tmp_path


def test_taskbeacon_tools_are_catalog_discoverable() -> None:
    registry = UnifiedToolRegistry()

    specs = {
        name: registry.get_toolspec_by_name(name)
        for name in (
            "taskbeacon.list_tasks",
            "taskbeacon.download_task",
            "taskbeacon.localize_task",
            "taskbeacon.run_qa_sim",
        )
    }

    assert all(spec is not None for spec in specs.values())
    assert specs["taskbeacon.list_tasks"].python_class == (
        "brain_researcher.services.tools.taskbeacon_tools"
    )
    caps = specs["taskbeacon.list_tasks"].execution_capabilities
    assert caps is not None
    assert caps.needs_network is True
    assert tuple(caps.allowed_domains) == (
        "github.com",
        "api.github.com",
        "raw.githubusercontent.com",
    )
    assert specs["taskbeacon.run_qa_sim"].approval_level == "confirm"


def test_taskbeacon_tools_are_exposed_for_search() -> None:
    registry = UnifiedToolRegistry()

    names = {spec.name for spec in registry.get_exposed_toolspecs(force_reload=True)}

    assert {
        "taskbeacon.list_tasks",
        "taskbeacon.download_task",
        "taskbeacon.localize_task",
        "taskbeacon.run_qa_sim",
    } <= names
