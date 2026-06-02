"""Feature selection agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    FeatureSelectionParameters,
    feature_selection_from_payload,
    run_feature_selection,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class FeatureSelectionArgs(BaseModel):
    """Arguments exposed to the agent for feature selection."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Input feature matrix")
    labels_file: Optional[str] = Field(
        default=None, description="Labels for supervised methods"
    )
    output_dir: Optional[str] = Field(default=None, description="Output directory")

    method: str = Field(default="univariate", description="Feature selection method")
    task_type: str = Field(default="classification", description="Task type")
    n_features: Optional[int] = Field(
        default=None, description="Number of features to select"
    )
    percentile: Optional[int] = Field(default=None, description="Percentile to select")
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_indices: bool = Field(default=True, description="Persist selected indices")
    save_scores: bool = Field(default=True, description="Persist feature scores")
    save_reduced_data: bool = Field(default=True, description="Persist reduced dataset")


class FeatureSelectionTool(NeuroToolWrapper):
    """Delegates feature selection to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "feature_selection"

    def get_tool_description(self) -> str:
        return "Select informative features using univariate/statistical heuristics."

    def get_args_schema(self):
        return FeatureSelectionArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = FeatureSelectionArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "feature_selection")

            params: FeatureSelectionParameters = feature_selection_from_payload(payload)
            results = run_feature_selection(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Feature selection failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class FeatureSelectionTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [FeatureSelectionTool()]


__all__ = ["FeatureSelectionTool", "FeatureSelectionTools"]
