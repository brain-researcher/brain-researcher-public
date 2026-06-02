"""Nilearn ICA decomposition tool for the BR-KG LangGraph system.

Implements Independent Component Analysis using Nilearn for fMRI data
decomposition and component extraction.
"""

import json
import logging
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import nibabel as nib
import numpy as np
from nilearn.decomposition import CanICA
from nilearn.image import concat_imgs, load_img
from nilearn.masking import compute_epi_mask
from pydantic import BaseModel, Field

from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class NilearnICAArgs(BaseModel):
    """Arguments for Nilearn ICA decomposition."""

    input_files: List[str] = Field(
        description="List of 4D NIfTI files for ICA decomposition"
    )
    output_dir: str = Field(description="Output directory for ICA results")
    n_components: int = Field(
        default=20, description="Number of ICA components to extract"
    )
    mask: Optional[str] = Field(default=None, description="Brain mask file (optional)")
    smoothing_fwhm: Optional[float] = Field(
        default=None, description="Smoothing FWHM in mm (optional)"
    )
    standardize: bool = Field(
        default=True, description="Whether to standardize the data"
    )
    random_state: int = Field(default=0, description="Random state for reproducibility")


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
    _NILEARN_ICA_SCHEMA = NilearnICAArgs.model_json_schema()
except AttributeError:
    _NILEARN_ICA_SCHEMA = NilearnICAArgs.schema()


TOOL_SPEC = ToolSpec(
    name="nilearn_ica",
    description="Nilearn ICA decomposition for fMRI data analysis.",
    json_schema=_NILEARN_ICA_SCHEMA,
    required=_model_required(NilearnICAArgs),
    defaults=_model_defaults(NilearnICAArgs),
    category="nilearn",
)


class NilearnICATool(NeuroToolWrapper):
    """Nilearn ICA decomposition tool."""

    def __init__(self):
        """Initialize Nilearn ICA tool."""
        super().__init__()

    def get_tool_name(self) -> str:
        return "nilearn_ica"

    def get_tool_description(self) -> str:
        return (
            "Run Independent Component Analysis using Nilearn for fMRI data. "
            "Extracts spatially independent components from 4D fMRI data."
        )

    def get_args_schema(self):
        return NilearnICAArgs

    def _run(
        self,
        input_files: List[str],
        output_dir: str,
        n_components: int = 20,
        mask: Optional[str] = None,
        smoothing_fwhm: Optional[float] = None,
        standardize: bool = True,
        random_state: int = 0,
        **kwargs,
    ) -> ToolResult:
        """Execute Nilearn ICA decomposition."""
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            imgs = [load_img(path) for path in input_files]
            if len(imgs) == 1:
                data_img = imgs[0]
            else:
                data_img = concat_imgs(imgs)

            if mask:
                mask_img = load_img(mask)
            else:
                try:
                    from nilearn.masking import _MaskWarning  # type: ignore
                except Exception:  # pragma: no cover - fallback for nilearn versions
                    _MaskWarning = UserWarning
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=_MaskWarning)
                    mask_img = compute_epi_mask(data_img)

                if not np.any(mask_img.get_fdata()):
                    mask_data = np.ones(data_img.shape[:3], dtype="uint8")
                    mask_img = nib.Nifti1Image(mask_data, data_img.affine)
            canica = CanICA(
                n_components=n_components,
                mask=mask_img,
                smoothing_fwhm=smoothing_fwhm,
                standardize=standardize,
                random_state=random_state,
            )
            canica.fit(data_img)

            components_img = canica.components_img_
            components_path = output_path / "ica_components.nii.gz"
            components_img.to_filename(components_path)

            time_series = canica.transform(data_img)
            if isinstance(time_series, list):
                time_series_array = np.asarray(time_series[0])
            else:
                time_series_array = np.asarray(time_series)
            ts_path = output_path / "ica_time_series.npy"
            np.save(ts_path, time_series_array)

            summary = {
                "n_components": int(n_components),
                "n_files": int(len(input_files)),
                "time_series_shape": list(time_series_array.shape),
            }
            summary_path = output_path / "ica_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "components": str(components_path),
                        "time_series": str(ts_path),
                        "summary": str(summary_path),
                    },
                    "summary": summary,
                    "message": "Nilearn ICA completed",
                },
            )
        except Exception as exc:
            logger.exception("Nilearn ICA failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})
