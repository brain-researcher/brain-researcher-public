"""Pipeline search tool (Python backend) that queries Neo4j pipelines.

Exposed as a simple tool for LLM router/planner:
  input: task (str), modalities (optional list[str])
  output: list of pipelines with id/name/steps
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.shared.toolsagent_pipeline_catalog import (
    search_pipelines,
)
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult


class PipelineSearchArgs(BaseModel):
    task: str = Field(
        ..., description="Task description, e.g., 't1 preprocessing to MNI'."
    )
    modalities: Optional[List[str]] = Field(
        None, description="Optional modalities filter, e.g., ['smri']"
    )
    limit: int = Field(3, description="Max pipelines to return")


class PipelineSearchTool(BRKGToolWrapper):
    tool_name = "pipeline.search"
    description = (
        "Search predefined pipelines (Neo4j) and return ordered tool steps. "
        "Uses NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD when explicit connection "
        "arguments are not provided."
    )
    args_schema = PipelineSearchArgs

    def get_tool_name(self) -> str:
        return self.tool_name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self):
        return PipelineSearchArgs

    def _run(
        self, task: str, modalities: Optional[List[str]] = None, limit: int = 3
    ) -> ToolResult:
        pipelines = search_pipelines(task=task, modalities=modalities, limit=limit)
        return ToolResult(status="success", data={"pipelines": pipelines})


# For legacy registry-style access
def get_all_tools():
    return [PipelineSearchTool()]


__all__ = ["PipelineSearchTool", "PipelineSearchArgs", "get_all_tools"]
