from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from brain_researcher.services.orchestrator import taskbeacon_mcp_adapter as adapter
from brain_researcher.services.orchestrator.taskbeacon_mcp_adapter import (
    TaskBeaconMCPCallResult,
    download_taskbeacon_task,
    list_taskbeacon_tasks,
    localize_taskbeacon_task,
    run_taskbeacon_qa_sim,
)


def _mcp_result(
    tool: str,
    structured: Any,
    *,
    text: str = "",
    ok: bool = True,
) -> TaskBeaconMCPCallResult:
    return TaskBeaconMCPCallResult(
        tool=tool,
        ok=ok,
        structured=structured,
        text=text,
        raw={"structuredContent": structured, "content": []},
        error=None if ok else text or "failed",
    )

def test_list_taskbeacon_tasks_prefers_github_html_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_caller(*_args, **_kwargs):
        raise AssertionError("MCP caller should not run when GitHub HTML succeeds")

    monkeypatch.setattr(
        adapter,
        "_list_taskbeacon_tasks_via_github_sync",
        lambda: [
            {"repo": "TaskBeacon/T000015-ant"},
            {"repo": "TaskBeacon/T000001-stroop"},
        ],
    )

    result = list_taskbeacon_tasks(query="ant", limit=10, caller=fail_caller)

    assert result["source"] == "taskbeacon_github_html"
    assert result["count"] == 1
    assert result["tasks"] == [{"repo": "TaskBeacon/T000015-ant"}]
    assert result["raw"] is None


def test_list_taskbeacon_tasks_falls_back_to_mcp_when_github_html_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_caller(tool: str, arguments: dict[str, Any], *, config):
        assert tool == "list_tasks"
        assert arguments == {}
        return _mcp_result(
            tool,
            {
                "tasks": [
                    {"repo": "TaskBeacon/T000015-ant", "readme_snippet": "ANT task"},
                    {"repo": "TaskBeacon/T000001-stroop", "readme_snippet": "Stroop"},
                ]
            },
        )

    monkeypatch.setattr(
        adapter,
        "_list_taskbeacon_tasks_via_github_sync",
        lambda: (_ for _ in ()).throw(RuntimeError("github html unavailable")),
    )

    result = list_taskbeacon_tasks(query="ant", limit=10, caller=fake_caller)

    assert result["source"] == "taskbeacon_mcp"
    assert result["count"] == 1
    assert result["github_error"] == "github html unavailable"
    assert result["tasks"] == [
        {"repo": "TaskBeacon/T000015-ant", "readme_snippet": "ANT task"}
    ]


def test_list_taskbeacon_tasks_parses_github_html_catalog_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter._taskbeacon_github_repo_cache = None

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, _url: str, *, params: dict[str, Any]):
            page = int(params["page"])
            if page == 1:
                return FakeResponse(
                    """
                    <a href="/TaskBeacon/T000015-ant">ANT</a>
                    <a href="/TaskBeacon/H000032-antisaccade">AS</a>
                    <a href="/TaskBeacon/not-a-task">ignore</a>
                    <a href="/TaskBeacon/T000015-ant">dup</a>
                    """
                )
            return FakeResponse("<html></html>")

    monkeypatch.setattr(adapter.httpx, "Client", lambda **_kwargs: FakeClient())

    rows = adapter._list_taskbeacon_tasks_via_github_sync()

    assert rows == [
        {"repo": "TaskBeacon/T000015-ant"},
        {"repo": "TaskBeacon/H000032-antisaccade"},
    ]
    adapter._taskbeacon_github_repo_cache = None


@pytest.mark.asyncio
async def test_async_list_taskbeacon_tasks_prefers_github_html_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(adapter.anyio.to_thread, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        adapter,
        "_list_taskbeacon_tasks_via_github_sync",
        lambda: [
            {"repo": "TaskBeacon/T000015-ant"},
            {"repo": "TaskBeacon/T000001-stroop"},
        ],
    )

    result = await adapter.async_list_taskbeacon_tasks(query="ant", limit=10)

    assert result["source"] == "taskbeacon_github_html"
    assert result["count"] == 1
    assert result["tasks"] == [{"repo": "TaskBeacon/T000015-ant"}]
    assert result["raw"] is None


def test_download_taskbeacon_task_uses_mcp_then_applies_runtime_patch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    def fake_caller(tool: str, arguments: dict[str, Any], *, config):
        assert tool == "download_task"
        assert arguments == {"repo": "TaskBeacon/T000015-ant"}
        source = Path(config.cwd) / "T000015-ant"
        (source / "config").mkdir(parents=True)
        (source / "main.py").write_text("print('task')\n", encoding="utf-8")
        (source / "config" / "config_qa.yaml").write_text(
            "window:\n  screen: 1\nqa:\n  output_dir: outputs/qa\n",
            encoding="utf-8",
        )
        return _mcp_result(tool, {"template_path": "T000015-ant"})

    result = download_taskbeacon_task(
        workspace_root=workspace,
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj/taskbeacon/T000015-ant",
        caller=fake_caller,
    )

    target = workspace / "projects" / "proj" / "taskbeacon" / "T000015-ant"
    assert result["status"] == "success"
    assert result["source"] == "taskbeacon_mcp"
    assert (target / "main.py").exists()
    assert (target / "config" / "br_config_qa.yaml").exists()
    assert (target / "run_br_taskbeacon.sh").exists()


def test_download_taskbeacon_task_can_skip_mcp_and_use_direct_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="fatal: network blocked",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = download_taskbeacon_task(
        workspace_root=tmp_path,
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj/taskbeacon/T000015-ant",
        prefer_mcp=False,
    )

    assert result["status"] == "error"
    assert result["source"] == "direct_git_fallback"
    assert "fatal: network blocked" in (
        tmp_path
        / "projects"
        / "proj"
        / "taskbeacon"
        / "T000015-ant"
        / "BR_TASKBEACON_IMPORT_ERROR.txt"
    ).read_text(encoding="utf-8")


def test_download_taskbeacon_task_skips_mcp_when_ref_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_caller(*_args, **_kwargs):
        raise AssertionError("MCP caller should not run when ref is requested")

    def fake_materialize_taskbeacon_repo(**kwargs):
        return {
            "status": "success",
            "repo": kwargs["repo"],
            "ref": kwargs["ref"],
            "target_dir": str(tmp_path / "target"),
        }

    monkeypatch.setattr(
        adapter,
        "materialize_taskbeacon_repo",
        fake_materialize_taskbeacon_repo,
    )

    result = download_taskbeacon_task(
        workspace_root=tmp_path,
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj/taskbeacon/T000015-ant",
        ref="feature/ref",
        caller=fail_caller,
    )

    assert result["source"] == "direct_git_fallback"
    assert result["ref"] == "feature/ref"
    assert "does not accept refs" in result["mcp_skipped_reason"]


def test_download_taskbeacon_task_rejects_mcp_paths_outside_temp_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_caller(tool: str, arguments: dict[str, Any], *, config):
        return _mcp_result(tool, {"template_path": str(tmp_path)})

    def fake_materialize_taskbeacon_repo(**kwargs):
        return {"status": "fallback", "repo": kwargs["repo"]}

    monkeypatch.setattr(
        adapter,
        "materialize_taskbeacon_repo",
        fake_materialize_taskbeacon_repo,
    )

    result = download_taskbeacon_task(
        workspace_root=tmp_path / "workspace",
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj/taskbeacon/T000015-ant",
        caller=fake_caller,
    )

    assert result["source"] == "direct_git_fallback"
    assert "outside the temporary MCP root" in result["mcp_error"]


def test_localize_taskbeacon_task_enforces_workspace_relative_path(tmp_path: Path) -> None:
    task = tmp_path / "projects" / "proj" / "taskbeacon" / "T000015-ant"
    task.mkdir(parents=True)

    def fake_caller(tool: str, arguments: dict[str, Any], *, config):
        assert tool == "localize"
        assert arguments["target_language"] == "French"
        assert arguments["task_path"] == str(task.resolve())
        return _mcp_result(tool, {"prompt_messages": [{"role": "user"}]})

    result = localize_taskbeacon_task(
        workspace_root=tmp_path,
        task_path="projects/proj/taskbeacon/T000015-ant",
        target_language="French",
        caller=fake_caller,
    )

    assert result["source"] == "taskbeacon_mcp"
    assert result["prompt_messages"] == {"prompt_messages": [{"role": "user"}]}


def test_run_taskbeacon_qa_sim_uses_br_shell_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = tmp_path / "projects" / "proj" / "taskbeacon" / "T000015-ant"
    task.mkdir(parents=True)
    (task / "main.py").write_text("print('task')\n", encoding="utf-8")
    (task / "outputs" / "qa").mkdir(parents=True)
    (task / "outputs" / "qa" / "qa_trace.csv").write_text("trial\n1\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="qa ok",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_taskbeacon_qa_sim(
        workspace_root=tmp_path,
        task_path="projects/proj/taskbeacon/T000015-ant",
        mode="qa",
    )

    assert result["status"] == "success"
    assert captured["command"][1].endswith("scripts/runtime/run_taskbeacon_task.sh")
    assert captured["command"][2:5] == ["qa", "--task-dir", str(task.resolve())]
    assert result["artifacts"] == ["outputs/qa/qa_trace.csv"]
