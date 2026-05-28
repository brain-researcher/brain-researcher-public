"""Connectivity matrix tool using Nilearn."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import gettempdir
from typing import Any

import numpy as np
import pandas as pd
from nilearn.connectome import ConnectivityMeasure
from pydantic import BaseModel, Field

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    write_feature_contract,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_OUTPUT_ROOT = Path(os.getenv("BR_DEMO_ARTIFACT_DIR", Path(gettempdir()) / "br_demo"))


class ConnectivityMatrixArgs(BaseModel):
    timeseries: str = Field(..., description="Path to ROI time-series")
    method: str = Field(default="correlation", description="Connectivity method")
    output_dir: str | None = Field(default=None, description="Output directory")


class NilearnConnectivityMatrixTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "nilearn_connectivity_matrix"

    def get_tool_description(self) -> str:
        return "Compute a functional connectivity matrix using Nilearn."

    execution_backend = "python"

    def get_args_schema(self):
        return ConnectivityMatrixArgs

    def _load_timeseries(self, path: str) -> np.ndarray:
        ts_path = Path(path)
        if not ts_path.exists():
            raise FileNotFoundError(f"Timeseries file not found: {path}")

        suffix = ts_path.suffix.lower()
        if suffix == ".npy":
            data = np.load(ts_path)
        elif suffix == ".npz":
            loader = np.load(ts_path)
            if not loader.files:
                raise ValueError(f"No arrays found in {path}")
            data = loader[loader.files[0]]
        elif suffix in {".csv", ".tsv", ".txt"}:
            sep = "\t" if suffix == ".tsv" else ","
            data = pd.read_csv(ts_path, sep=sep, header=None).values
        elif suffix == ".json":
            payload: Any = json.loads(ts_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                keys = sorted(payload.keys())
                data = np.column_stack([payload[k] for k in keys])
            else:
                data = np.asarray(payload)
        else:
            raise ValueError(f"Unsupported timeseries file extension: {suffix}")

        data = np.asarray(data, dtype=float)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        return data

    def _run(
        self,
        timeseries: str,
        method: str = "correlation",
        output_dir: str | None = None,
        **kwargs,
    ) -> ToolResult:
        ts = self._load_timeseries(timeseries)
        measure = ConnectivityMeasure(kind=method, standardize="zscore_sample")
        matrix = measure.fit_transform([ts])[0]

        output_root = Path(output_dir) if output_dir else _OUTPUT_ROOT
        output_root.mkdir(parents=True, exist_ok=True)
        matrix_file = output_root / "connectivity_matrix.json"
        matrix_file.write_text(json.dumps(matrix.tolist(), indent=2), encoding="utf-8")
        matrix_npy = output_root / "connectivity_matrix.npy"
        np.save(matrix_npy, matrix)
        feature_contract = build_feature_contract(
            matrix,
            matrix_kind=method,
            source_level="roi_timeseries",
            n_rois=int(ts.shape[1]),
            n_timepoints=int(ts.shape[0]),
            effective_n_timepoints=int(ts.shape[0]),
            covariance_estimator=(
                type(getattr(measure, "cov_estimator_", None)).__name__
                if getattr(measure, "cov_estimator_", None) is not None
                else None
            ),
            extras={"tool": self.get_tool_name()},
        )
        feature_contract_path = write_feature_contract(feature_contract, output_root)
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "connectivity_matrix": str(matrix_npy),
                    "connectivity_matrix_json": str(matrix_file),
                    "feature_contract": str(feature_contract_path),
                },
                "summary": {
                    "method": method,
                    "timeseries": timeseries,
                    "n_timepoints": int(ts.shape[0]),
                    "n_regions": int(ts.shape[1]),
                },
            },
        )


__all__ = ["NilearnConnectivityMatrixTool"]
