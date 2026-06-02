"""Advanced visualization agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    AdvancedVisualizationParameters,
    advanced_visualization_from_payload,
    run_advanced_visualization,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class AdvancedVisualizationArgs(BaseModel):
    """Simplified argument schema for visualization requests."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Path to data to visualize")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")
    data_type: str = Field(default="auto", description="Data type hint")
    plot_type: str = Field(default="auto", description="Visualization type")
    figure_format: str = Field(default="png", description="Figure file format")
    interactive_backend: str = Field(
        default="plotly", description="Interactive backend"
    )
    glass_display_mode: Optional[str] = Field(
        default=None, description="Display mode for glass brain"
    )
    seed: Optional[int] = Field(default=None, description="Random seed")


class AdvancedVisualizationTool(NeuroToolWrapper):
    """Delegates visualization to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "advanced_visualization"

    def get_tool_description(self) -> str:
        return "Generate static or interactive visualizations for neuroimaging data."

    def get_args_schema(self):
        return AdvancedVisualizationArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = AdvancedVisualizationArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "visualizations")

            params: AdvancedVisualizationParameters = (
                advanced_visualization_from_payload(payload)
            )
            results = run_advanced_visualization(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Advanced visualization failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class AdvancedVisualizationTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [AdvancedVisualizationTool()]


__all__ = ["AdvancedVisualizationTool", "AdvancedVisualizationTools"]
