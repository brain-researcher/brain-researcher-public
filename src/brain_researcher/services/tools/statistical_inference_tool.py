"""
Statistical inference tool wrapper.

Exposes bootstrap/Bayesian-style inference through the shared neurocore
pipeline with graceful fallbacks for environments lacking full scientific
stack support.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    StatisticalInferenceParameters,
    run_statistical_inference,
    statistical_inference_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class StatisticalInferenceArgs(BaseModel):
    """Agent-facing argument schema."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Path to samples × features numeric matrix")
    labels_file: str | None = Field(
        default=None, description="Optional labels/groups file"
    )
    covariates_file: str | None = Field(
        default=None, description="Optional covariates file"
    )
    method: str = Field(default="bootstrap", description="Inference approach")
    test_type: str = Field(default="mean_diff", description="Statistical test")
    n_bootstrap: int = Field(default=1000, description="Number of bootstrap samples")
    bootstrap_method: str = Field(
        default="percentile", description="Bootstrap CI method"
    )
    confidence_level: float = Field(
        default=0.95, description="Confidence level for intervals"
    )
    prior_type: str = Field(
        default="uninformative", description="Prior family for Bayesian modes"
    )
    n_mcmc: int = Field(
        default=5000, description="MCMC samples for Bayesian estimation"
    )
    burn_in: int = Field(default=1000, description="Burn-in samples for MCMC")
    robust_method: str = Field(
        default="trimmed_mean", description="Robust estimator variant"
    )
    trim_proportion: float = Field(
        default=0.1, description="Trim proportion for robust methods"
    )
    resampling_method: str = Field(
        default="permutation", description="Resampling approach"
    )
    n_resamples: int = Field(
        default=1000, description="Number of resamples for auxiliary metrics"
    )
    compute_effect_size: bool = Field(default=True, description="Compute effect sizes")
    effect_size_type: str = Field(default="cohen_d", description="Effect size metric")
    compute_power: bool = Field(default=False, description="Estimate statistical power")
    target_effect_size: float | None = Field(
        default=None, description="Target effect size for power estimation"
    )
    correct_multiple: bool = Field(
        default=True, description="Apply multiple testing correction"
    )
    correction_method: str = Field(default="fdr", description="Correction method")
    compute_confidence_regions: bool = Field(
        default=True, description="Generate multivariate confidence region"
    )
    region_method: str = Field(
        default="ellipse", description="Confidence region approach"
    )
    output_dir: str | None = Field(default=None, description="Directory for outputs")
    save_samples: bool = Field(default=True, description="Persist sampled statistics")
    save_intervals: bool = Field(default=True, description="Persist interval estimates")
    save_effect_sizes: bool = Field(default=True, description="Persist effect sizes")
    seed: int | None = Field(
        default=None, description="Random seed for reproducibility"
    )


class StatisticalInferenceTool(NeuroToolWrapper):
    """Agent tool entry point."""

    def get_tool_name(self) -> str:
        return "statistical_inference"

    def get_tool_description(self) -> str:
        return (
            "Bootstrap/Bayesian statistical inference for neuroimaging datasets with "
            "lightweight numpy-based fallbacks when advanced toolkits are unavailable."
        )

    def get_args_schema(self):
        return StatisticalInferenceArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = StatisticalInferenceArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "statistical_inference")

            params: StatisticalInferenceParameters = statistical_inference_from_payload(
                payload
            )
            results = run_statistical_inference(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Statistical inference failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class StatisticalInferenceTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [StatisticalInferenceTool()]


__all__ = ["StatisticalInferenceTool", "StatisticalInferenceTools"]
