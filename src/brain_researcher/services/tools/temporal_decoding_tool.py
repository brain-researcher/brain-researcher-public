"""Temporal decoding agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    TemporalDecodingParameters,
    run_temporal_decoding,
    temporal_decoding_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class TemporalDecodingArgs(BaseModel):
    """Arguments for temporal decoding workflows."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Path to time series data")
    labels_file: str = Field(description="Path to labels")
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    method: str = Field(default="sliding_window", description="Decoding method")
    classifier: str = Field(default="lda", description="Classifier type")
    window_size: Optional[int] = Field(default=None, description="Window size")
    window_step: int = Field(default=1, description="Window step")
    cv_folds: int = Field(default=5, description="Cross-validation folds")
    random_state: Optional[int] = Field(default=42, description="Random seed")
    save_accuracies: bool = Field(default=True, description="Persist accuracy trace")
    save_patterns: bool = Field(default=True, description="Persist temporal patterns")


class TemporalDecodingTool(NeuroToolWrapper):
    """Delegates temporal decoding to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "temporal_decoding"

    def get_tool_description(self) -> str:
        return "Perform temporal decoding with fallback classifiers."

    def get_args_schema(self):
        return TemporalDecodingArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = TemporalDecodingArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "temporal_decoding")

            params: TemporalDecodingParameters = temporal_decoding_from_payload(payload)
            results = run_temporal_decoding(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Temporal decoding failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class TemporalDecodingTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [TemporalDecodingTool()]


__all__ = ["TemporalDecodingTool", "TemporalDecodingArgs", "TemporalDecodingTools"]
