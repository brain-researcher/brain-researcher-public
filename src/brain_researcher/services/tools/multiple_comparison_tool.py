"""
Multiple-comparison correction tool wrapper.

Delegates computation to the shared neurocore implementation that provides
fallback behaviour when scientific stacks (e.g., statsmodels) are absent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    MultipleComparisonParameters,
    multiple_comparison_from_payload,
    run_multiple_comparison,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class MultipleComparisonArgs(BaseModel):
    """Agent-facing arguments for multiple-comparison correction."""

    model_config = ConfigDict(extra="ignore")

    p_values_file: str | None = Field(
        default=None, description="Path to raw p-values array"
    )
    p_values_array: Any | None = Field(
        default=None, description="Inline p-values array"
    )
    statistic_file: str | None = Field(
        default=None, description="Optional statistic map for metadata"
    )
    method: str = Field(default="fdr_bh", description="Correction method")
    alpha: float = Field(default=0.05, description="Significance threshold")
    fdr_method: str = Field(default="indep", description="FDR dependency assumption")
    two_stage: bool = Field(default=False, description="Use two-stage FDR procedure")
    mask_file: str | None = Field(
        default=None, description="Mask limiting correction scope"
    )
    smoothness: float | None = Field(
        default=None, description="Smoothness estimate for RFT"
    )
    cluster_threshold: float | None = Field(
        default=None, description="Cluster-forming threshold"
    )
    connectivity: str = Field(default="faces", description="Neighbourhood definition")
    min_cluster_size: int = Field(default=1, description="Minimum cluster size")
    tfce_e: float = Field(default=0.5, description="TFCE extent parameter")
    tfce_h: float = Field(default=2.0, description="TFCE height parameter")
    output_dir: str | None = Field(default=None, description="Directory for outputs")
    save_corrected: bool = Field(default=True, description="Persist corrected values")
    save_mask: bool = Field(default=True, description="Persist significance mask")
    save_report: bool = Field(default=True, description="Persist summary report")
    return_arrays: bool = Field(
        default=False, description="Return numpy arrays in response"
    )


class MultipleComparisonTool(NeuroToolWrapper):
    """Agent tool entry point."""

    def get_tool_name(self) -> str:
        return "multiple_comparison_correction"

    def get_tool_description(self) -> str:
        return (
            "Apply multiple-comparison correction (FDR/FWE/TFCE fallbacks) with "
            "lightweight numpy-based implementations when high-end toolkits are unavailable."
        )

    def get_args_schema(self):
        return MultipleComparisonArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = MultipleComparisonArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "multiple_comparison")

            params: MultipleComparisonParameters = multiple_comparison_from_payload(
                payload
            )
            results = run_multiple_comparison(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Multiple-comparison correction failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class MultipleComparisonTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [MultipleComparisonTool()]


__all__ = ["MultipleComparisonTool", "MultipleComparisonTools"]
