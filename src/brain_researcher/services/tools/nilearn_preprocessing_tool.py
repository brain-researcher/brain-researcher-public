"""Nilearn preprocessing tool for the BR-KG LangGraph system.

Implements CONN-style preprocessing pipeline using Nilearn for fMRI
connectivity analysis preparation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from nilearn.image import clean_img
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.tools.spec import ToolSpec

logger = logging.getLogger(__name__)


def _nilearn_standardize_arg(enabled: bool) -> str | bool:
    return "zscore_sample" if enabled else False


def _sample_standardize_columns(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, np.newaxis]
    mean = array.mean(axis=0, keepdims=True)
    std = array.std(axis=0, ddof=1, keepdims=True)
    std[~np.isfinite(std) | (std < 1e-6)] = 1.0
    return (array - mean) / std


class NilearnPreprocessingArgs(BaseModel):
    """Arguments for Nilearn preprocessing pipeline."""

    input_file: str = Field(
        description="Path to 4D NIfTI file for preprocessing"
    )
    output_dir: str = Field(
        description="Output directory for preprocessed data"
    )
    confounds_file: Optional[str] = Field(
        default=None,
        description="Path to confounds TSV file (fMRIPrep format)"
    )
    tr: Optional[float] = Field(
        default=None,
        description="Repetition time in seconds"
    )
    high_pass: float = Field(
        default=0.01,
        description="High-pass filter cutoff in Hz"
    )
    low_pass: Optional[float] = Field(
        default=None,
        description="Low-pass filter cutoff in Hz (optional)"
    )
    smoothing_fwhm: Optional[float] = Field(
        default=None,
        description="Smoothing FWHM in mm (optional)"
    )
    standardize: bool = Field(
        default=True,
        description="Whether to standardize the data"
    )
    detrend: bool = Field(
        default=True,
        description="Whether to detrend the data"
    )
    confound_columns: Optional[List[str]] = Field(
        default=None,
        description="List of confound columns to regress out"
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _NILEARN_PREPROC_SCHEMA = NilearnPreprocessingArgs.model_json_schema()
except AttributeError:
    _NILEARN_PREPROC_SCHEMA = NilearnPreprocessingArgs.schema()


TOOL_SPEC = ToolSpec(
    name="nilearn_preprocessing",
    description="Nilearn preprocessing pipeline for fMRI connectivity analysis.",
    json_schema=_NILEARN_PREPROC_SCHEMA,
    required=_model_required(NilearnPreprocessingArgs),
    defaults=_model_defaults(NilearnPreprocessingArgs),
    category="nilearn",
)


class NilearnPreprocessingTool(NeuroToolWrapper):
    """Nilearn preprocessing tool for CONN-style connectivity analysis.
    """

    def __init__(self):
        """Initialize Nilearn preprocessing tool."""
        super().__init__()

    def get_tool_name(self) -> str:
        return "nilearn_preprocessing"

    def get_tool_description(self) -> str:
        return (
            "Run CONN-style preprocessing pipeline using Nilearn for fMRI "
            "connectivity analysis. Includes filtering, confound regression, "
            "and standardization."
        )

    def get_args_schema(self):
        return NilearnPreprocessingArgs

    def _run(
        self,
        input_file: str,
        output_dir: str,
        confounds_file: Optional[str] = None,
        tr: Optional[float] = None,
        high_pass: float = 0.01,
        low_pass: Optional[float] = None,
        smoothing_fwhm: Optional[float] = None,
        standardize: bool = True,
        detrend: bool = True,
        confound_columns: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """Execute Nilearn preprocessing pipeline."""
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            if tr is None and (high_pass is not None or low_pass is not None):
                raise ValueError("tr must be provided when using temporal filters")

            confounds = None
            confounds_path = None
            if confounds_file:
                df = pd.read_csv(confounds_file, sep="\t")
                if confound_columns:
                    missing = [c for c in confound_columns if c not in df.columns]
                    if missing:
                        raise ValueError(f"Missing confound columns: {missing}")
                    df = df[confound_columns]
                confounds = _sample_standardize_columns(
                    df.select_dtypes(include=["number"]).fillna(0.0).to_numpy()
                )
                confounds_path = output_path / "confounds_used.tsv"
                df.to_csv(confounds_path, sep="\t", index=False)

            cleaned_img = clean_img(
                input_file,
                confounds=confounds,
                t_r=tr,
                high_pass=high_pass,
                low_pass=low_pass,
                detrend=detrend,
                standardize=_nilearn_standardize_arg(standardize),
                clean__standardize_confounds=False,
                smoothing_fwhm=smoothing_fwhm,
            )

            output_file = output_path / "preprocessed_bold.nii.gz"
            cleaned_img.to_filename(output_file)

            n_dims = len(cleaned_img.shape)
            summary = {
                "input_file": input_file,
                "output_file": str(output_file),
                "confounds_file": confounds_file,
                "n_volumes": int(cleaned_img.shape[-1]) if n_dims == 4 else 1,
            }

            summary_path = output_path / "preprocessing_summary.json"
            summary_path.write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "preprocessed_file": str(output_file),
                        "confounds_used": str(confounds_path) if confounds_path else None,
                        "summary": str(summary_path),
                    },
                    "summary": summary,
                    "message": "Nilearn preprocessing completed",
                },
            )
        except Exception as exc:
            logger.exception("Nilearn preprocessing failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})
