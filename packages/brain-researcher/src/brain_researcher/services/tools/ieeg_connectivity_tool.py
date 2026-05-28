"""Stub connectivity computation for iEEG pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class IEEGConnectivityArgs(BaseModel):
    """Arguments for connectivity metrics."""

    features_table: str = Field(description="Path to epoch features table")
    metric: Literal["pli", "plv", "coh", "gc"] = Field(
        default="plv", description="Connectivity metric"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class IEEGConnectivityTool(NeuroToolWrapper):
    """Produce stubbed connectivity matrices from features."""

    def get_tool_name(self) -> str:
        return "ieeg_connectivity"

    def get_tool_description(self) -> str:
        return "Estimate functional connectivity matrices from iEEG features."

    def get_args_schema(self):
        return IEEGConnectivityArgs

    @staticmethod
    def _infer_channel_count(features_table: str) -> int:
        source = Path(features_table)
        if not source.exists():
            return 4
        try:
            if source.suffix == ".npy":
                data = np.load(source)
                if data.ndim >= 2:
                    return max(1, int(data.shape[-1]))
            if source.suffix in {".csv", ".tsv", ".txt"}:
                delimiter = "\t" if source.suffix == ".tsv" else ","
                data = np.loadtxt(source, delimiter=delimiter)
                if data.ndim >= 2:
                    return max(1, int(data.shape[-1]))
        except Exception:
            return 4
        return 4

    def _run(self, **kwargs) -> ToolResult:
        args = IEEGConnectivityArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "ieeg_connectivity")
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = output_dir / f"connectivity_{args.metric}.npy"
        n_channels = self._infer_channel_count(args.features_table)
        if args.metric == "gc":
            matrix = np.zeros((n_channels, n_channels), dtype=float)
            if n_channels > 1:
                matrix[np.triu_indices(n_channels, k=1)] = 0.1
        else:
            matrix = np.eye(n_channels, dtype=float)
        np.save(matrix_path, matrix)

        contract = FeatureContract(
            matrix_kind=f"ieeg_{args.metric}",
            source_level="ieeg_features",
            n_rois=int(n_channels),
            transform_state="sensor_connectivity",
            extras={
                "source": args.features_table,
                "tool": self.get_tool_name(),
            },
        )
        feature_contract_path = write_feature_contract(contract, output_dir)

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "connectivity_matrix": str(matrix_path),
                    "feature_contract": str(feature_contract_path),
                    "metric": args.metric,
                },
                "summary": {
                    "metric": args.metric,
                    "source": args.features_table,
                    "n_channels": n_channels,
                },
            },
        )


class IEEGConnectivityTools:
    @staticmethod
    def get_all_tools():
        return [IEEGConnectivityTool()]


__all__ = ["IEEGConnectivityTool", "IEEGConnectivityTools"]
