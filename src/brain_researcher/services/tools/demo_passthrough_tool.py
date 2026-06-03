"""Simple stub tool used for live end-to-end smoke tests."""

from __future__ import annotations

from typing import Any

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class DemoPassthroughTool(NeuroToolWrapper):
    """No-op tool that always succeeds and echoes its inputs."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "demo_passthrough"

    def get_tool_description(self) -> str:
        return "Return provided payload for smoke-testing the plan executor."

    def get_args_schema(self):
        # Accept arbitrary keyword args
        from pydantic import BaseModel, ConfigDict

        class DemoArgs(BaseModel):
            model_config = ConfigDict(extra="allow")

            message: str | None = None
            payload: dict[str, Any] | None = None

        return DemoArgs

    def _run(
        self,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        **kwargs,
    ) -> ToolResult:
        summary = message or "demo-pass"
        outputs = {"payload": payload or {}, "extra": kwargs}
        return ToolResult(
            status="success", data={"outputs": outputs, "summary": {"message": summary}}
        )


__all__ = ["DemoPassthroughTool"]
