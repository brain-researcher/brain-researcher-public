"""Resolver tool that returns canonical EEG montage definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ResolveMontageArgs(BaseModel):
    montage_name: str = Field(
        default="standard_1020", description="Requested montage template"
    )


class ResolveMontageTool(NeuroToolWrapper):
    """Stub montage resolver for EEG pipelines."""

    def get_tool_name(self) -> str:
        return "resolve_montage"

    def get_tool_description(self) -> str:
        return "Resolve montage metadata and channel geometry for EEG analysis."

    def get_args_schema(self):
        return ResolveMontageArgs

    def _run(self, montage_name: str = "standard_1020") -> ToolResult:
        montage_def = f"/artifacts/montages/{montage_name}.json"
        return ToolResult(
            status="success",
            data={
                "outputs": {"montage_def": montage_def},
                "summary": {"montage": montage_name},
            },
        )


__all__ = ["ResolveMontageTool"]
