"""Statsmodels GLM agent wrapper using shared neurocore helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from brain_researcher.services.tools.params import (
    StatsmodelsGLMParameters,
    run_statsmodels_glm,
    statsmodels_glm_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class StatsmodelsGLMArgs(BaseModel):
    data_file: str
    design_matrix: str
    output_dir: str
    dependent_var: str | None = None
    mask_file: str | None = None
    formula: str | None = None
    family: str = "gaussian"
    link_function: str | None = None
    contrasts: dict[str, list[float]] | None = None
    contrast_names: list[str] | None = None
    alpha: float = 0.05
    correction_method: str = "fdr"
    fit_intercept: bool = True
    standardize: bool = False
    robust_covariance: bool = False
    regularization: str | None = None
    regularization_strength: float | None = None
    save_residuals: bool = True
    save_fitted: bool = True
    save_stats_maps: bool = True
    voxel_wise: bool = False
    smoothing_fwhm: float | None = None
    compute_diagnostics: bool = True
    plot_diagnostics: bool = True


class StatsmodelsGLMTool(NeuroToolWrapper):
    """Delegates Statsmodels GLM to neurocore placeholders or real backend."""

    def get_tool_name(self) -> str:
        return "statsmodels_glm"

    def get_tool_description(self) -> str:
        return "Statsmodels General Linear Model analysis with optional contrasts and diagnostics."

    def get_args_schema(self):  # noqa: D401
        return StatsmodelsGLMArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        args = StatsmodelsGLMArgs(**kwargs)
        payload = args.model_dump()
        payload.setdefault(
            "output_dir", args.output_dir or str(Path.cwd() / "statsmodels_glm")
        )
        params: StatsmodelsGLMParameters = statsmodels_glm_from_payload(payload)
        result = run_statsmodels_glm(params)
        return ToolResult(status="success", data=result)


class StatsmodelsGLMTools:
    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [StatsmodelsGLMTool()]


__all__ = ["StatsmodelsGLMTool", "StatsmodelsGLMTools"]
