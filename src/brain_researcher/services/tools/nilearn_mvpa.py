"""Nilearn MVPA/decoding wrappers."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    MVPADecodingParameters,
    mvpa_decoding_from_payload,
    run_mvpa_decoding,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class MVPADecodingArgs(BaseModel):
    """Arguments exposed to the agent for MVPA decoding."""

    model_config = ConfigDict(extra="ignore")

    img: str = Field(description="Input data matrix (.npy) or nifti path")
    labels: str | list[float] = Field(
        description="Labels vector or path to labels file"
    )
    mask_img: str | None = Field(default=None, description="Optional mask image")
    classifier: str = Field(default="svc", description="Classifier backend")
    cv_folds: int = Field(default=5, description="Number of cross-validation folds")
    standardize: bool = Field(default=True, description="Standardize features")
    smoothing_fwhm: float | None = Field(default=None, description="Smoothing kernel")
    feature_selection: str | None = Field(
        default=None, description="Feature selection strategy"
    )
    n_features: int | None = Field(
        default=None, description="Number of features to keep"
    )
    permutations: int = Field(default=0, description="Permutation test iterations")
    n_jobs: int = Field(default=-1, description="Parallel jobs (if backend supports)")
    output_dir: str | None = Field(default=None, description="Directory for outputs")
    seed: int | None = Field(default=None, description="Random seed")


class MVPADecodingTool(NeuroToolWrapper):
    """Delegates MVPA decoding to neurocore helper."""

    name = "decoding_classifier"
    description = "Perform MVPA decoding with optional permutation testing"
    category = "mvpa"

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self):
        return MVPADecodingArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = MVPADecodingArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params: MVPADecodingParameters = mvpa_decoding_from_payload(payload)
            results = run_mvpa_decoding(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("MVPA decoding failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


def register_mvpa_tools(registry):
    """Register MVPA tools with the agent registry."""
    tool = MVPADecodingTool()
    registry.register_tool(tool)
    logger.info("Registered MVPA tool: %s", tool.get_tool_name())
    return 1


__all__ = ["MVPADecodingTool", "register_mvpa_tools"]
