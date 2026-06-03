"""Encoding models agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    EncodingModelParameters,
    encoding_model_from_payload,
    run_encoding_model,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class EncodingModelsArgs(BaseModel):
    """Arguments for encoding model workflows."""

    model_config = ConfigDict(extra="ignore")

    brain_data_file: str = Field(description="Brain data matrix (time x voxels)")
    stimulus_file: str = Field(description="Stimulus/design matrix (time x features)")
    output_dir: str | None = Field(default=None, description="Output directory")

    model_type: str = Field(default="ridge", description="Encoding model type")
    n_folds: int = Field(default=5, description="Cross-validation folds")
    standardize: bool = Field(default=True, description="Standardize features")
    add_derivatives: bool = Field(
        default=False, description="Append temporal derivatives"
    )
    random_state: int | None = Field(default=42, description="Random seed")
    save_models: bool = Field(default=True, description="Persist model metadata")
    save_predictions: bool = Field(default=True, description="Persist predictions")
    save_weights: bool = Field(default=True, description="Persist encoding weights")


class EncodingModelsTool(NeuroToolWrapper):
    """Delegates encoding models to neurocore implementation."""

    def get_tool_name(self) -> str:
        return "encoding_models"

    def get_tool_description(self) -> str:
        return "Fit encoding models linking stimuli to brain responses (fallback)."

    def get_args_schema(self):
        return EncodingModelsArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = EncodingModelsArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "encoding_models")

            params: EncodingModelParameters = encoding_model_from_payload(payload)
            results = run_encoding_model(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Encoding model failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class EncodingModelsTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools():
        return [EncodingModelsTool()]


__all__ = ["EncodingModelsTool", "EncodingModelsArgs", "EncodingModelsTools"]
