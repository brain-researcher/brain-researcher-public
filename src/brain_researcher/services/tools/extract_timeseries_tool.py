"""Timeseries extraction tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import gettempdir
from typing import Dict, Optional

import numpy as np
from nilearn.maskers import NiftiLabelsMasker
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_OUTPUT_ROOT = Path(os.getenv("BR_DEMO_ARTIFACT_DIR", Path(gettempdir()) / "br_demo"))


class ExtractTimeseriesArgs(BaseModel):
    img: str = Field(..., description="Input fMRI image")
    atlas: str = Field(..., description="Atlas path")
    output_dir: Optional[str] = Field(default=None, description="Output directory")
    standardize: bool = Field(default=True, description="Standardize signals")
    detrend: bool = Field(default=True, description="Detrend signals")
    tr: Optional[float] = Field(default=None, description="Repetition time (seconds)")
    low_pass: Optional[float] = Field(default=None, description="Low-pass filter (Hz)")
    high_pass: Optional[float] = Field(default=None, description="High-pass filter (Hz)")


class ExtractTimeseriesTool(NeuroToolWrapper):
    """Extract ROI time-series using Nilearn."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "extract_timeseries"

    def get_tool_description(self) -> str:
        return "Extract ROI mean time-series from 4D fMRI data using Nilearn."

    def get_args_schema(self):
        return ExtractTimeseriesArgs

    def _run(
        self,
        img: str,
        atlas: str,
        output_dir: Optional[str] = None,
        standardize: bool = True,
        detrend: bool = True,
        tr: Optional[float] = None,
        low_pass: Optional[float] = None,
        high_pass: Optional[float] = None,
        **kwargs,
    ) -> ToolResult:
        output_root = Path(output_dir) if output_dir else _OUTPUT_ROOT
        output_root.mkdir(parents=True, exist_ok=True)

        masker = NiftiLabelsMasker(
            labels_img=atlas,
            standardize=standardize,
            detrend=detrend,
            t_r=tr,
            low_pass=low_pass,
            high_pass=high_pass,
        )
        timeseries = masker.fit_transform(img)
        ts_array = np.asarray(timeseries, dtype=float)

        ts_file = output_root / "timeseries.npy"
        np.save(ts_file, ts_array)
        ts_csv = output_root / "timeseries.csv"
        np.savetxt(ts_csv, ts_array, delimiter=",")
        summary = {
            "img": img,
            "atlas": atlas,
            "n_timepoints": int(ts_array.shape[0]),
            "n_regions": int(ts_array.shape[1]) if ts_array.ndim > 1 else 1,
        }
        summary_file = output_root / "timeseries_summary.json"
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "timeseries": str(ts_file),
                    "timeseries_csv": str(ts_csv),
                    "summary": str(summary_file),
                },
                "summary": summary,
            },
        )


__all__ = ["ExtractTimeseriesTool"]
