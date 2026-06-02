"""
Permutation testing tool wrapper.

Provides a lightweight interface that delegates execution to the shared
neurocore permutation testing implementation with graceful fallbacks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    PermutationTestParameters,
    permutation_test_from_payload,
    run_permutation_test,
)
from brain_researcher.services.tools.params.permutation_testing import (
    LabelPermutationNullParameters,
    label_permutation_null_from_payload,
    run_label_permutation_null,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PermutationTestingArgs(BaseModel):
    """Arguments exposed to the agent for permutation testing."""

    model_config = ConfigDict(extra="ignore")

    data_file: str | None = Field(
        default=None, description="Path to primary data array"
    )
    group1_files: list[str] | None = Field(
        default=None, description="Group 1 data files"
    )
    group2_files: list[str] | None = Field(
        default=None, description="Group 2 data files"
    )
    test_type: str = Field(default="ttest_1samp", description="Permutation test type")
    n_permutations: int = Field(
        default=1000, description="Number of permutations to run"
    )
    alpha: float = Field(default=0.05, description="Significance threshold")
    tail: int = Field(default=0, description="Tail selection (0=two-tailed)")
    correction_method: str = Field(
        default="none", description="Multiple-comparison correction method"
    )
    cluster_threshold: float | None = Field(
        default=None, description="Cluster-forming threshold"
    )
    tfce_e: float = Field(default=0.5, description="TFCE extent parameter")
    tfce_h: float = Field(default=2.0, description="TFCE height parameter")
    mask_file: str | None = Field(
        default=None, description="Mask file for spatial data"
    )
    design_matrix: Any | None = Field(
        default=None, description="Design matrix or covariates"
    )
    contrast: Any | None = Field(default=None, description="Contrast vector")
    output_dir: str | None = Field(default=None, description="Directory for outputs")
    save_stats: bool = Field(
        default=True, description="Persist observed statistics to disk"
    )
    save_clusters: bool = Field(default=True, description="Persist cluster metadata")
    save_null: bool = Field(default=False, description="Persist null distribution")
    seed: int | None = Field(default=None, description="Random seed")
    probe: str | None = Field(
        default=None,
        description=(
            "Optional probe mode. Use 'label_permutation_null' for a "
            "feature-matrix label-null probe; only trusted harness outputs "
            "qualify as full-pipeline review evidence."
        ),
    )
    estimator_factory_path: str | None = Field(
        default=None,
        description="Import path for an estimator factory used by the label-permutation-null probe",
    )
    X_path: str | None = Field(
        default=None,
        description="Feature matrix path for the label-permutation-null probe",
    )
    y_path: str | None = Field(
        default=None,
        description="Target vector path for the label-permutation-null probe",
    )
    split_manifest_path: str | None = Field(
        default=None,
        description="Train/test split manifest path for the label-permutation-null probe",
    )
    cv_scope: str = Field(
        default="nested_outer_cv", description="CV scope label for review probe output"
    )
    exchangeability_unit: str = Field(
        default="row", description="Permutation exchangeability unit"
    )
    metric: str = Field(default="r2", description="Label-null scoring metric")
    config_sha256: str | None = Field(
        default=None, description="Optional config digest for probe provenance"
    )
    groups_path: str | None = Field(
        default=None, description="Optional group labels path for grouped shuffling"
    )
    null_indistinguishable_threshold: float = Field(
        default=0.05, description="Empirical p-value threshold for signal detection"
    )


class PermutationTestingTool(NeuroToolWrapper):
    """Agent-visible permutation testing tool."""

    def get_tool_name(self) -> str:
        return "permutation_testing"

    def get_tool_description(self) -> str:
        return (
            "Permutation-based statistical testing with optional multiple-comparison "
            "correction. Falls back to lightweight analytic approximations when "
            "specialised dependencies are unavailable."
        )

    def get_args_schema(self):
        return PermutationTestingArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = PermutationTestingArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "permutation_test")

            if _is_label_permutation_null_payload(payload):
                params: LabelPermutationNullParameters = (
                    label_permutation_null_from_payload(payload)
                )
                results = run_label_permutation_null(params)
                return ToolResult(status="success", data=results)

            params: PermutationTestParameters = permutation_test_from_payload(payload)
            results = run_permutation_test(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Permutation testing failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class PermutationTestingTools:
    """Collection helper used by registry discovery."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [PermutationTestingTool()]


__all__ = ["PermutationTestingTool", "PermutationTestingTools"]


def _is_label_permutation_null_payload(payload: dict[str, Any]) -> bool:
    probe = str(payload.get("probe", "")).lower()
    if probe in {"label_permutation_null", "label-permutation-null"}:
        return True
    required = {"estimator_factory_path", "X_path", "y_path", "split_manifest_path"}
    return required.issubset(payload)
