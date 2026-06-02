"""Dynamic connectivity agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    DynamicConnectivityParameters,
    dynamic_connectivity_from_payload,
    run_dynamic_connectivity,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class DynamicConnectivityArgs(BaseModel):
    """Arguments for dynamic connectivity workflows."""

    model_config = ConfigDict(extra="ignore")

    timeseries: Optional[str] = Field(
        default=None,
        description="Alias for timeseries_file (time x ROI).",
    )
    timeseries_file: Optional[str] = Field(
        default=None,
        description="ROI time series (time x ROI).",
    )
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    connectivity_method: str = Field(
        default="correlation", description="Connectivity metric"
    )
    dynamic_method: str = Field(default="sliding_window", description="Dynamic method")
    window_length: Optional[int] = Field(default=None, description="Window length")
    step_size: Optional[int] = Field(
        default=None,
        description=(
            "Step size between windows (in timepoints). Alias for window_overlap "
            "when used with window_length."
        ),
    )
    window_overlap: float = Field(default=0.5, description="Overlap fraction")
    n_states: int = Field(default=5, description="Number of states")
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_matrices: bool = Field(default=True, description="Persist window matrices")
    save_states: bool = Field(default=True, description="Persist state assignments")
    save_metrics: bool = Field(default=True, description="Persist metrics")


class DynamicConnectivityTool(NeuroToolWrapper):
    """Delegates dynamic connectivity to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "dynamic_connectivity"

    def get_tool_description(self) -> str:
        return "Compute fallback dynamic connectivity windows and states."

    def get_args_schema(self):
        return DynamicConnectivityArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = DynamicConnectivityArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "timeseries_file" not in payload and "timeseries" in payload:
                payload["timeseries_file"] = payload.pop("timeseries")
            if "timeseries_file" not in payload or not payload["timeseries_file"]:
                raise ValueError("timeseries_file is required (or provide timeseries).")
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "dynamic_connectivity")
            if "step_size" in payload:
                window_length = payload.get("window_length")
                if not window_length:
                    raise ValueError("step_size requires window_length to be set.")
                step_size = int(payload.pop("step_size"))
                if step_size < 1:
                    raise ValueError("step_size must be >= 1.")
                overlap = 1.0 - (step_size / float(window_length))
                payload.setdefault("window_overlap", max(0.0, min(0.99, overlap)))

            params: DynamicConnectivityParameters = dynamic_connectivity_from_payload(
                payload
            )
            results = run_dynamic_connectivity(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Dynamic connectivity failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class DynamicConnectivityTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [DynamicConnectivityTool()]


__all__ = [
    "DynamicConnectivityTool",
    "DynamicConnectivityArgs",
    "DynamicConnectivityTools",
]
