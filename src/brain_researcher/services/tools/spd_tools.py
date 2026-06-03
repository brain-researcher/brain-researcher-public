"""SPD (Symmetric Positive Definite) matrix tool wrappers for the agent layer.

Exposes 6 composable tools:
  - repr_spd_covariance_estimate: Timeseries → covariance matrix
  - repr_spd_project: Ensure SPD stability
  - geom_spd_logm: Matrix logarithm (tangent space)
  - geom_spd_geodesic_distance: Pairwise SPD distance
  - nn_spd_bimap: Learnable bilinear mapping
  - nn_spd_train_spdnet: Train SPDNet classifier
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params.spd_learn import (
    covariance_estimate_from_payload,
    run_covariance_estimate,
    run_spd_bimap,
    run_spd_geodesic_distance,
    run_spd_logm,
    run_spd_project,
    run_spdnet_train,
    spd_bimap_from_payload,
    spd_geodesic_distance_from_payload,
    spd_logm_from_payload,
    spd_project_from_payload,
    spdnet_train_from_payload,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Arg Schemas
# ============================================================================


class CovarianceEstimateArgs(BaseModel):
    """Arguments for covariance estimation from timeseries."""

    model_config = ConfigDict(extra="ignore")

    data_file: str = Field(description="Path to timeseries data (.npy/.npz)")
    output_file: str = Field(description="Output path for covariance matrix (.npz)")
    method: str = Field(
        default="empirical",
        description="Estimation method: empirical, ledoit_wolf, oas, shrinkage",
    )
    standardize: bool = Field(default=True, description="Z-score timeseries first")
    diagonal: bool = Field(
        default=False, description="Compute diagonal-only covariance"
    )


class SPDProjectArgs(BaseModel):
    """Arguments for SPD projection / regularization."""

    model_config = ConfigDict(extra="ignore")

    matrix_file: str = Field(description="Input matrix path (.npy/.npz)")
    output_file: str = Field(description="Output SPD matrix path (.npz)")
    epsilon: float = Field(default=1e-6, description="Minimum eigenvalue threshold")
    method: str = Field(
        default="eig_clamp",
        description="Projection method: eig_clamp, add_epsilon",
    )


class SPDLogmArgs(BaseModel):
    """Arguments for matrix logarithm on SPD manifold."""

    model_config = ConfigDict(extra="ignore")

    spd_matrix_file: str = Field(description="Input SPD matrix path (.npy/.npz)")
    output_file: str = Field(description="Output log-mapped matrix path (.npz)")
    reference: str = Field(
        default="identity",
        description="Reference point: 'identity' or path to reference SPD matrix",
    )


class SPDDistanceArgs(BaseModel):
    """Arguments for geodesic distance between SPD matrices."""

    model_config = ConfigDict(extra="ignore")

    matrix_a_file: str = Field(description="First SPD matrix path (.npy/.npz)")
    matrix_b_file: str = Field(description="Second SPD matrix path (.npy/.npz)")
    metric: str = Field(
        default="log_euclidean",
        description="Distance metric: log_euclidean, airm, euclidean",
    )
    output_file: str | None = Field(
        default=None, description="Optional output file for distance result JSON"
    )


class SPDBiMapArgs(BaseModel):
    """Arguments for BiMap dimensionality reduction."""

    model_config = ConfigDict(extra="ignore")

    data_files: list[str] = Field(description="List of SPD matrix file paths")
    labels_file: str | None = Field(default=None, description="Optional labels file")
    output_dim: int = Field(default=10, description="Target output dimension")
    output_dir: str = Field(default="spd_bimap_output", description="Output directory")
    epochs: int = Field(default=50, description="Training epochs")
    learning_rate: float = Field(default=0.01, description="Learning rate")


class SPDNetTrainArgs(BaseModel):
    """Arguments for SPDNet training."""

    model_config = ConfigDict(extra="ignore")

    data_files: list[str] = Field(description="List of SPD matrix file paths")
    output_dir: str = Field(default="spdnet_output", description="Output directory")
    architecture: str = Field(
        default="spdnet", description="Model architecture: spdnet, eeg_spdnet"
    )
    n_classes: int = Field(default=2, description="Number of classification classes")
    epochs: int = Field(default=100, description="Training epochs")
    batch_size: int = Field(default=32, description="Batch size")
    learning_rate: float = Field(default=0.001, description="Learning rate")
    val_split: float = Field(default=0.2, description="Validation split ratio")
    labels_file: str | None = Field(
        default=None, description="Optional labels file (.npy/.npz)"
    )


# ============================================================================
# Tool Wrappers
# ============================================================================


class CovarianceEstimateTool(NeuroToolWrapper):
    """Convert raw timeseries to SPD covariance matrices."""

    def get_tool_name(self) -> str:
        return "repr_spd_covariance_estimate"

    def get_tool_description(self) -> str:
        return (
            "Estimate covariance matrix from timeseries data. "
            "Supports empirical, Ledoit-Wolf, OAS, and shrinkage methods. "
            "Output is an SPD matrix suitable for geometric analysis."
        )

    def get_args_schema(self):
        return CovarianceEstimateArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = CovarianceEstimateArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = covariance_estimate_from_payload(payload)
            results = run_covariance_estimate(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("Covariance estimation failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SPDProjectTool(NeuroToolWrapper):
    """Ensure numerical SPD stability via eigenvalue clamping."""

    def get_tool_name(self) -> str:
        return "repr_spd_project"

    def get_tool_description(self) -> str:
        return (
            "Project a matrix onto the SPD cone by clamping eigenvalues "
            "or adding regularization. Ensures the matrix is numerically "
            "positive definite for downstream geometric operations."
        )

    def get_args_schema(self):
        return SPDProjectArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SPDProjectArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = spd_project_from_payload(payload)
            results = run_spd_project(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("SPD projection failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SPDLogmTool(NeuroToolWrapper):
    """Map SPD matrix to tangent space via matrix logarithm."""

    def get_tool_name(self) -> str:
        return "geom_spd_logm"

    def get_tool_description(self) -> str:
        return (
            "Compute the matrix logarithm of an SPD matrix, mapping it "
            "to the tangent space at a reference point (identity or custom). "
            "Useful for linearizing SPD data for Euclidean analysis."
        )

    def get_args_schema(self):
        return SPDLogmArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SPDLogmArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = spd_logm_from_payload(payload)
            results = run_spd_logm(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("SPD logm failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SPDDistanceTool(NeuroToolWrapper):
    """Compute geodesic distance between SPD matrices."""

    def get_tool_name(self) -> str:
        return "geom_spd_geodesic_distance"

    def get_tool_description(self) -> str:
        return (
            "Compute the geodesic distance between two SPD matrices using "
            "AIRM (Affine Invariant Riemannian Metric), Log-Euclidean, or "
            "Frobenius norm."
        )

    def get_args_schema(self):
        return SPDDistanceArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SPDDistanceArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = spd_geodesic_distance_from_payload(payload)
            results = run_spd_geodesic_distance(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("SPD distance failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SPDBiMapTool(NeuroToolWrapper):
    """Learnable bilinear mapping for SPD dimensionality reduction."""

    def get_tool_name(self) -> str:
        return "nn_spd_bimap"

    def get_tool_description(self) -> str:
        return (
            "Apply BiMap dimensionality reduction to SPD matrices. "
            "Learns a bilinear mapping W^T @ X @ W that reduces matrix "
            "dimension while preserving SPD structure."
        )

    def get_args_schema(self):
        return SPDBiMapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SPDBiMapArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = spd_bimap_from_payload(payload)
            results = run_spd_bimap(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("SPD BiMap failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class SPDNetTrainTool(NeuroToolWrapper):
    """Train SPDNet classifier on SPD/covariance data."""

    def get_tool_name(self) -> str:
        return "nn_spd_train_spdnet"

    def get_tool_description(self) -> str:
        return (
            "Train an SPDNet deep learning model for classification on "
            "SPD covariance matrices. Supports spdnet and eeg_spdnet "
            "architectures with train/validation split."
        )

    def get_args_schema(self):
        return SPDNetTrainArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = SPDNetTrainArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            params = spdnet_train_from_payload(payload)
            results = run_spdnet_train(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:
            logger.exception("SPDNet training failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


# ============================================================================
# Registry Helper
# ============================================================================


class SPDTools:
    """Registry helper for SPD tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [
            CovarianceEstimateTool(),
            SPDProjectTool(),
            SPDLogmTool(),
            SPDDistanceTool(),
            SPDBiMapTool(),
            SPDNetTrainTool(),
        ]


__all__ = [
    "CovarianceEstimateTool",
    "CovarianceEstimateArgs",
    "SPDProjectTool",
    "SPDProjectArgs",
    "SPDLogmTool",
    "SPDLogmArgs",
    "SPDDistanceTool",
    "SPDDistanceArgs",
    "SPDBiMapTool",
    "SPDBiMapArgs",
    "SPDNetTrainTool",
    "SPDNetTrainArgs",
    "SPDTools",
]
