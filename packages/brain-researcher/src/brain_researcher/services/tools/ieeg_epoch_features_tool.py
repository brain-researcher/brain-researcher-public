"""Stub tool for extracting bandpower/epoch features from iEEG."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class IEEGEpochFeaturesArgs(BaseModel):
    """Arguments for epoch-based feature extraction."""

    clean_ieeg: str = Field(description="Path to clean iEEG recording")
    events: str = Field(description="Path to events TSV/JSON")
    bands: List[str] = Field(
        default_factory=lambda: ["delta", "theta", "alpha", "beta", "gamma"],
        description="Frequency bands to summarize",
    )
    epoch_length: float = Field(default=2.0, description="Epoch length in seconds")
    output_dir: Optional[str] = Field(
        default=None, description="Directory where features will be written"
    )


class IEEGEpochFeaturesTool(NeuroToolWrapper):
    """Generate synthetic feature tables for downstream classification."""

    def get_tool_name(self) -> str:
        return "ieeg_epoch_features"

    def get_tool_description(self) -> str:
        return "Compute simple bandpower/HFA features on epoched iEEG data."

    def get_args_schema(self):
        return IEEGEpochFeaturesArgs

    def _run(self, **kwargs) -> ToolResult:
        args = IEEGEpochFeaturesArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "ieeg_features")
        output_dir.mkdir(parents=True, exist_ok=True)
        features_path = output_dir / "features_table.parquet"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "features_table": str(features_path),
                    "bands": args.bands,
                    "epoch_length": args.epoch_length,
                },
                "summary": {"num_bands": len(args.bands)},
            },
        )


class IEEGEpochFeaturesTools:
    @staticmethod
    def get_all_tools():
        return [IEEGEpochFeaturesTool()]


__all__ = ["IEEGEpochFeaturesTool", "IEEGEpochFeaturesTools"]
