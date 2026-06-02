"""Nipype workflow runner as a pluggable tool.

This keeps the platform's native DAG executor unchanged while letting callers
run a Nipype workflow end-to-end as a single tool invocation.

Usage contract (lightweight):
- Provide a Python module file that exposes `build_workflow(**inputs) -> Workflow`
  or a fully qualified import path like `pkg.module:build_workflow`.
- The tool will import and invoke `build_workflow`, set `base_dir`, then run
  `workflow.run(plugin=..., plugin_args=...)`.
- Outputs: `outputs.base_dir`, `outputs.plugin`, `outputs.runtime_report`.

If Nipype is not installed, the tool returns an error result instead of
raising, so orchestrator/worker can surface a clear message.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class NipypeRunnerArgs(BaseModel):
    workflow: str = Field(
        description=(
            "Path to a python file exporting build_workflow(**inputs) or "
            "a module path 'pkg.module:build_workflow'"
        )
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict, description="Keyword args passed to build_workflow"
    )
    plugin: str = Field(
        default="Linear", description="Nipype plugin (e.g., Linear, MultiProc)"
    )
    plugin_args: Dict[str, Any] = Field(
        default_factory=dict, description="Optional plugin arguments"
    )
    base_dir: Optional[str] = Field(
        default=None, description="Working directory for Nipype workflow"
    )


def _import_builder(spec: str):
    """Import build_workflow callable from file path or module path."""

    if ":" in spec:
        mod_path, func_name = spec.split(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, func_name)

    path = Path(spec)
    if not path.exists():
        raise FileNotFoundError(f"Workflow module not found: {spec}")

    module_name = f"nipype_workflow_{path.stem}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Cannot load module from {spec}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)  # type: ignore[arg-type]
    return getattr(module, "build_workflow")


class NipypeWorkflowRunnerTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "nipype_workflow_runner"

    def get_tool_description(self) -> str:
        return "Run a Nipype workflow built by build_workflow(**inputs)."

    def get_args_schema(self):
        return NipypeRunnerArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            import nipype  # type: ignore
            from nipype.pipeline import engine as pe  # noqa: F401  # ensure available
        except Exception as exc:
            return ToolResult(
                status="error",
                error=f"Nipype is required but not available: {exc}",
                data={"missing_dependency": "nipype"},
            )

        args = NipypeRunnerArgs(**kwargs)
        try:
            build_workflow = _import_builder(args.workflow)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})

        try:
            wf = build_workflow(**(args.inputs or {}))
        except Exception as exc:
            return ToolResult(
                status="error", error=f"build_workflow failed: {exc}", data={}
            )

        base_dir = Path(args.base_dir) if args.base_dir else Path.cwd() / "nipype_runs"
        base_dir.mkdir(parents=True, exist_ok=True)
        try:
            wf.base_dir = str(base_dir)
        except Exception:
            pass

        try:
            res = wf.run(plugin=args.plugin, plugin_args=dict(args.plugin_args))
        except Exception as exc:
            return ToolResult(
                status="error",
                error=f"Nipype execution failed: {exc}",
                data={"base_dir": str(base_dir)},
            )

        report = {
            "plugin": args.plugin,
            "plugin_args": args.plugin_args,
            "base_dir": str(base_dir),
            "nodes": getattr(res, "nodes", None),
        }

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "base_dir": str(base_dir),
                    "plugin": args.plugin,
                    "runtime_report": json.loads(json.dumps(report, default=str)),
                },
                "report": report,
            },
        )


@dataclass
class NipypeRunnerTools:
    @staticmethod
    def get_all_tools():
        return [NipypeWorkflowRunnerTool()]


__all__ = ["NipypeWorkflowRunnerTool", "NipypeRunnerTools"]
