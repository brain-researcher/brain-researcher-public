"""EEG connectivity computation tool using MNE-Connectivity."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)
from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ConnectivityMeasuresArgs(BaseModel):
    epochs: str = Field(description="Epochs file")
    method: str = Field(default="pli")
    fmin: float | None = Field(default=8.0)
    fmax: float | None = Field(default=13.0)
    output_dir: str | None = Field(default=None)


class ConnectivityMeasuresTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "connectivity_measures"

    def get_tool_description(self) -> str:
        return "Compute sensor-space connectivity metrics (PLI/WPLI/PLV)."

    def get_args_schema(self):
        return ConnectivityMeasuresArgs

    def _run(self, epochs: str, method: str = "pli", **kwargs) -> ToolResult:
        configure_mne_environment()
        try:
            import mne
            from mne_connectivity import spectral_connectivity_epochs
        except ImportError as exc:
            return ToolResult(
                status="error",
                error=f"MNE connectivity dependencies not available: {exc}",
                data={},
            )
        args = ConnectivityMeasuresArgs(
            epochs=epochs,
            method=method,
            fmin=kwargs.get("fmin", 8.0),
            fmax=kwargs.get("fmax", 13.0),
            output_dir=kwargs.get("output_dir"),
        )

        epochs_path = Path(args.epochs)
        if not epochs_path.exists():
            return ToolResult(status="error", error="epochs file not found", data={})

        epochs_obj = mne.read_epochs(epochs_path, preload=True, verbose=False)
        conn = spectral_connectivity_epochs(
            epochs_obj,
            method=args.method,
            mode="multitaper",
            sfreq=epochs_obj.info["sfreq"],
            fmin=args.fmin,
            fmax=args.fmax,
            faverage=True,
            verbose=False,
        )
        matrix = conn.get_data(output="dense")[:, :, 0]

        output_dir = Path(args.output_dir) if args.output_dir else epochs_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = output_dir / f"{epochs_path.stem}_{args.method}_conn.npy"
        np.save(matrix_path, matrix)
        data = epochs_obj.get_data()
        feature_contract = FeatureContract(
            matrix_kind=f"eeg_sensor_{args.method}",
            source_level="eeg_epochs",
            n_rois=int(matrix.shape[0]),
            n_timepoints=int(data.shape[-1]) if data.ndim >= 3 else None,
            effective_n_timepoints=int(data.shape[-1]) if data.ndim >= 3 else None,
            transform_state="sensor_connectivity",
            extras={
                "n_epochs": int(data.shape[0]) if data.ndim >= 3 else None,
                "fmin": float(args.fmin),
                "fmax": float(args.fmax),
                "tool": self.get_tool_name(),
            },
        )
        feature_contract_path = write_feature_contract(feature_contract, output_dir)

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "connectivity_matrix": str(matrix_path),
                    "feature_contract": str(feature_contract_path),
                },
                "summary": {
                    "method": args.method,
                    "fmin": args.fmin,
                    "fmax": args.fmax,
                    "n_channels": matrix.shape[0],
                },
            },
        )


__all__ = ["ConnectivityMeasuresTool"]
