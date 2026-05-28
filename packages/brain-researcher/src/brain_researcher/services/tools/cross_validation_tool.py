"""Cross-validation agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    CrossValidationParameters,
    cross_validation_from_payload,
    run_cross_validation,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class CrossValidationArgs(BaseModel):
    """Arguments for cross-validation workflows."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Features array (n_samples x n_features)")
    labels_file: str = Field(description="Labels or targets")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")
    groups_file: Optional[str] = Field(default=None, description="Optional group labels")

    cv_type: str = Field(default="kfold", description="Cross-validation type")
    n_splits: int = Field(default=5, description="Number of folds")
    task_type: str = Field(default="classification", description="Task type")
    metrics: List[str] = Field(default_factory=lambda: ["accuracy"], description="Metrics to compute")
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_predictions: bool = Field(default=True, description="Persist fold predictions")
    save_importance: bool = Field(default=True, description="Persist feature importance")


class CrossValidationTool(NeuroToolWrapper):
    """Delegates cross-validation to shared neurocore implementation."""

    def get_tool_name(self) -> str:
        return "cross_validation"

    def get_tool_description(self) -> str:
        return "Run cross-validation (kfold/LOO/group) with fallback metrics."

    def get_args_schema(self):
        return CrossValidationArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = CrossValidationArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "cross_validation")

            params: CrossValidationParameters = cross_validation_from_payload(payload)
            results = run_cross_validation(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Cross-validation failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class CrossValidationTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [CrossValidationTool()]


__all__ = ["CrossValidationTool", "CrossValidationTools"]
