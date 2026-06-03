"""BR tool wrappers for TaskBeacon MCP handoff operations."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.taskbeacon_handoff import (
    default_taskbeacon_target_path,
    normalize_taskbeacon_repo,
)
from brain_researcher.services.tools.taskbeacon_mcp_adapter import (
    TaskBeaconMCPError,
    download_taskbeacon_task,
    list_taskbeacon_tasks,
    localize_taskbeacon_task,
    run_taskbeacon_qa_sim,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class TaskBeaconListTasksArgs(BaseModel):
    query: str | None = Field(default=None, description="Optional substring filter")
    limit: int | None = Field(default=100, ge=1, le=1000, description="Maximum tasks")


class TaskBeaconDownloadTaskArgs(BaseModel):
    repo: str = Field(..., description="TaskBeacon repo, e.g. TaskBeacon/T000015-ant")
    workspace_root: str = Field(default=".", description="BR workspace root")
    project_id: str = Field(default="proj_workspace", description="Project namespace")
    target_path: str | None = Field(
        default=None,
        description="Workspace-relative target path; defaults under projects/<project>/taskbeacon/",
    )
    ref: str | None = Field(default=None, description="Optional git ref fallback")
    prefer_mcp: bool = Field(default=True, description="Try taskbeacon-mcp first")


class TaskBeaconLocalizeTaskArgs(BaseModel):
    workspace_root: str = Field(default=".", description="BR workspace root")
    task_path: str = Field(..., description="Workspace-relative TaskBeacon task path")
    target_language: str = Field(..., description="Target language, e.g. French")
    voice: str | None = Field(default=None, description="Optional TaskBeacon voice")


class TaskBeaconRunQASimArgs(BaseModel):
    workspace_root: str = Field(default=".", description="BR workspace root")
    task_path: str = Field(..., description="Workspace-relative TaskBeacon task path")
    mode: str = Field(default="qa", description="qa or sim")
    config_path: str | None = Field(
        default=None,
        description="Optional workspace-relative config path",
    )
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


def _error_result(exc: Exception, *, code: str = "taskbeacon_failed") -> ToolResult:
    return ToolResult(
        status="error",
        error=str(exc),
        data={"error_code": code, "exception_type": type(exc).__name__},
    )


def _download_error(data: dict) -> str | None:
    if data.get("status") != "error":
        return None
    return str(
        data.get("stderr")
        or data.get("error")
        or data.get("mcp_error")
        or data.get("error_file")
        or "TaskBeacon download failed"
    )


class TaskBeaconListTasksTool(NeuroToolWrapper):
    """List TaskBeacon tasks through the upstream taskbeacon-mcp server."""

    name = "taskbeacon.list_tasks"
    tool_name = "taskbeacon.list_tasks"
    TAGS = ["taskbeacon", "mcp", "catalog"]
    SIDE_EFFECTS: list[str] = []

    def get_tool_name(self) -> str:
        return self.tool_name

    def get_tool_description(self) -> str:
        return "List available TaskBeacon tasks via taskbeacon-mcp"

    def get_args_schema(self):
        return TaskBeaconListTasksArgs

    def _run(
        self,
        query: str | None = None,
        limit: int | None = 100,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            return ToolResult(
                status="success",
                data=list_taskbeacon_tasks(query=query, limit=limit),
            )
        except Exception as exc:
            code = "taskbeacon_mcp_unavailable" if isinstance(exc, TaskBeaconMCPError) else "taskbeacon_failed"
            return _error_result(exc, code=code)


class TaskBeaconDownloadTaskTool(NeuroToolWrapper):
    """Download a TaskBeacon task into a BR workspace."""

    name = "taskbeacon.download_task"
    tool_name = "taskbeacon.download_task"
    TAGS = ["taskbeacon", "mcp", "download", "workspace"]
    SIDE_EFFECTS = ["network", "filesystem_write"]

    def get_tool_name(self) -> str:
        return self.tool_name

    def get_tool_description(self) -> str:
        return "Download a TaskBeacon task into a BR workspace with hosted overlays"

    def get_args_schema(self):
        return TaskBeaconDownloadTaskArgs

    def _run(
        self,
        repo: str,
        workspace_root: str = ".",
        project_id: str = "proj_workspace",
        target_path: str | None = None,
        ref: str | None = None,
        prefer_mcp: bool = True,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            normalized_repo = normalize_taskbeacon_repo(repo)
            if normalized_repo is None:
                raise ValueError("repo is required")
            resolved_target = target_path or default_taskbeacon_target_path(
                project_id,
                normalized_repo,
            )
            root = Path(workspace_root)
            if work_dir and workspace_root == ".":
                root = Path(work_dir)
            data = download_taskbeacon_task(
                workspace_root=root,
                repo=normalized_repo,
                target_path=resolved_target,
                ref=ref,
                prefer_mcp=prefer_mcp,
            )
            failure = _download_error(data)
            if failure:
                return ToolResult(status="error", data=data, error=failure)
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return _error_result(exc)


class TaskBeaconLocalizeTaskTool(NeuroToolWrapper):
    """Ask TaskBeacon MCP for localization prompt messages for a task repo."""

    name = "taskbeacon.localize_task"
    tool_name = "taskbeacon.localize_task"
    TAGS = ["taskbeacon", "mcp", "localization"]
    SIDE_EFFECTS = ["may_delete_taskbeacon_voice_cache"]

    def get_tool_name(self) -> str:
        return self.tool_name

    def get_tool_description(self) -> str:
        return "Localize a workspace TaskBeacon task via taskbeacon-mcp prompts"

    def get_args_schema(self):
        return TaskBeaconLocalizeTaskArgs

    def _run(
        self,
        task_path: str,
        target_language: str,
        workspace_root: str = ".",
        voice: str | None = None,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            root = Path(workspace_root)
            if work_dir and workspace_root == ".":
                root = Path(work_dir)
            data = localize_taskbeacon_task(
                workspace_root=root,
                task_path=task_path,
                target_language=target_language,
                voice=voice,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            code = "taskbeacon_mcp_unavailable" if isinstance(exc, TaskBeaconMCPError) else "taskbeacon_failed"
            return _error_result(exc, code=code)


class TaskBeaconRunQASimTool(NeuroToolWrapper):
    """Run TaskBeacon QA/sim through the BR shell runtime boundary."""

    name = "taskbeacon.run_qa_sim"
    tool_name = "taskbeacon.run_qa_sim"
    DANGEROUS = True
    APPROVAL_LEVEL = "confirm"
    TAGS = ["taskbeacon", "psychopy", "qa", "sim", "shell"]
    SIDE_EFFECTS = ["execute_external_task_code", "filesystem_write"]

    def get_tool_name(self) -> str:
        return self.tool_name

    def get_tool_description(self) -> str:
        return "Run a TaskBeacon task in BR-hosted QA/sim mode"

    def get_args_schema(self):
        return TaskBeaconRunQASimArgs

    def _run(
        self,
        task_path: str,
        workspace_root: str = ".",
        mode: str = "qa",
        config_path: str | None = None,
        timeout_seconds: int = 300,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            root = Path(workspace_root)
            if work_dir and workspace_root == ".":
                root = Path(work_dir)
            data = run_taskbeacon_qa_sim(
                workspace_root=root,
                task_path=task_path,
                mode=mode,
                config_path=config_path,
                timeout_seconds=timeout_seconds,
            )
            return ToolResult(
                status="success" if data.get("status") == "success" else "error",
                data=data,
                error=None if data.get("status") == "success" else data.get("stderr"),
            )
        except Exception as exc:
            return _error_result(exc)


def get_all_tools() -> list[NeuroToolWrapper]:
    return [
        TaskBeaconListTasksTool(),
        TaskBeaconDownloadTaskTool(),
        TaskBeaconLocalizeTaskTool(),
        TaskBeaconRunQASimTool(),
    ]


__all__ = [
    "TaskBeaconDownloadTaskTool",
    "TaskBeaconListTasksTool",
    "TaskBeaconLocalizeTaskTool",
    "TaskBeaconRunQASimTool",
    "get_all_tools",
]
