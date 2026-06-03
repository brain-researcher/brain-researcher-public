"""
Nilearn Preprocessing Tools

This module provides tools for data preprocessing, masking, and signal extraction.
"""

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    NiftiMaskerParameters,
    ROIExtractionParameters,
    nifti_masker_from_payload,
    roi_extraction_from_payload,
    run_nifti_masker,
    run_roi_extraction,
)
from brain_researcher.services.tools.spec import ToolExample
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

logger = logging.getLogger(__name__)


# =============================================================================
# 1. NiftiMasker Tool
# =============================================================================


class NiftiMaskerArgs(BaseModel):
    """Arguments for NiftiMasker brain extraction and signal processing."""

    img: str = Field(description="Path to 4D fMRI image")
    mask_img: str | None = Field(
        None, description="Path to mask image or 'compute' to generate"
    )
    mask_strategy: str = Field(
        default="epi", description="Strategy: 'epi', 'template', 'whole-brain-template'"
    )
    standardize: bool = Field(default=True, description="Z-score standardization")
    detrend: bool = Field(default=True, description="Detrend signals")
    smoothing_fwhm: float | None = Field(None, description="Smoothing kernel in mm")
    low_pass: float | None = Field(None, description="Low-pass filter cutoff in Hz")
    high_pass: float | None = Field(None, description="High-pass filter cutoff in Hz")
    t_r: float | None = Field(
        None, description="TR for filtering (required if filters used)"
    )
    confounds: str | None = Field(None, description="Path to confounds file")
    confound_strategy: list[str] = Field(
        default=["motion", "high_pass", "wm_csf"],
        description="Confound selection strategy",
    )
    output_file: str | None = Field(None, description="Save extracted signals")


class NiftiMaskerTool(NeuroToolWrapper):
    """Extract and clean time series from brain regions."""

    name = "nifti_masker"
    description = "Extract, filter, and clean time series from fMRI data with automatic confound handling"
    category = "preprocessing"

    ARG_SYNONYMS = {
        "standardize": ["zscore", "normalize", "z_score"],
        "smoothing_fwhm": ["fwhm", "smooth", "kernel"],
        "low_pass": ["lp", "lowpass"],
        "high_pass": ["hp", "highpass"],
        "t_r": ["TR", "repetition_time", "tr"],
    }

    EXAMPLES = [
        ToolExample(
            user_query="Extract cleaned time series from fMRI",
            params={
                "img": "sub-01_task-rest_bold.nii.gz",
                "mask_img": "compute",
                "standardize": True,
                "high_pass": 0.01,
                "t_r": 2.0,
                "confounds": "sub-01_task-rest_confounds.tsv",
            },
            notes="Automatic masking with filtering and confounds",
        ),
        ToolExample(
            user_query="Apply smoothing and extract signals",
            params={
                "img": "bold.nii.gz",
                "smoothing_fwhm": 6.0,
                "mask_strategy": "template",
                "detrend": True,
            },
            notes="Template-based masking with smoothing",
        ),
    ]

    args_model = NiftiMaskerArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> dict[str, Any]:
        return self._invoke(**kwargs)

    def _invoke(self, **kwargs) -> dict[str, Any]:
        """Apply NiftiMasker for signal extraction."""
        args = NiftiMaskerArgs(**kwargs)
        payload = args.model_dump()
        params: NiftiMaskerParameters = nifti_masker_from_payload(payload)
        result = run_nifti_masker(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# 2. ROI Extraction Tool
# =============================================================================


class ROIExtractionArgs(BaseModel):
    """Arguments for ROI-based signal extraction."""

    img: str = Field(description="Path to 4D fMRI data")
    atlas: str = Field(
        description="Atlas name or path: 'AAL', 'Harvard-Oxford', 'Schaefer2018', 'Yeo', custom path"
    )
    n_parcels: int | None = Field(
        None, description="Number of parcels (for parametric atlases)"
    )
    extract_type: str = Field(
        default="mean", description="Extraction: 'mean', 'median', 'sum', 'min', 'max'"
    )
    confounds: str | None = Field(None, description="Confounds file path")
    standardize: bool = Field(default=True, description="Standardize signals")
    detrend: bool = Field(default=True, description="Detrend signals")
    low_pass: float | None = Field(None, description="Low-pass filter")
    high_pass: float | None = Field(None, description="High-pass filter")
    t_r: float | None = Field(None, description="TR for filtering")
    output_file: str | None = Field(None, description="Save ROI signals")
    labels_file: str | None = Field(None, description="Save ROI labels")


class ROIExtractionTool(NeuroToolWrapper):
    """Extract time series from atlas-defined ROIs."""

    name = "roi_extraction"
    description = "Extract signals from brain regions using standard atlases (AAL, Schaefer, Harvard-Oxford)"
    category = "preprocessing"

    ARG_SYNONYMS = {
        "atlas": ["parcellation", "roi_atlas", "template"],
        "extract_type": ["aggregation", "summary_method", "extraction_method"],
        "n_parcels": ["n_rois", "n_regions", "resolution"],
    }

    EXAMPLES = [
        ToolExample(
            user_query="Extract signals from Schaefer atlas",
            params={
                "img": "preprocessed_bold.nii.gz",
                "atlas": "Schaefer2018",
                "n_parcels": 400,
                "extract_type": "mean",
                "standardize": True,
            },
            notes="400-parcel Schaefer atlas extraction",
        ),
        ToolExample(
            user_query="Get AAL region time series",
            params={
                "img": "sub-01_bold.nii.gz",
                "atlas": "AAL",
                "confounds": "confounds.tsv",
                "high_pass": 0.01,
                "t_r": 2.0,
            },
            notes="AAL atlas with confound regression",
        ),
    ]

    args_model = ROIExtractionArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> dict[str, Any]:
        return self._invoke(**kwargs)

    def _invoke(self, **kwargs) -> dict[str, Any]:
        """Extract ROI signals."""
        args = ROIExtractionArgs(**kwargs)
        payload = args.model_dump()
        params: ROIExtractionParameters = roi_extraction_from_payload(payload)
        result = run_roi_extraction(params)
        return {
            "status": "success",
            **result,
        }


# =============================================================================
# 3. Confounds Cleaning Tool
# =============================================================================


class ConfoundsCleanArgs(BaseModel):
    """Arguments for comprehensive confound removal."""

    img: str = Field(description="Path to 4D fMRI image")
    confounds: str = Field(description="Path to confounds file (TSV or CSV)")
    strategy: str | list[str] = Field(
        default="minimal",
        description="Strategy: 'minimal', 'motion', 'compcor', 'scrubbing', 'ica-aroma', or list of column patterns",
    )
    motion_params: bool = Field(default=True, description="Include motion parameters")
    wm_csf: bool = Field(default=True, description="Include WM/CSF signals")
    global_signal: bool = Field(default=False, description="Include global signal")
    compcor: str | None = Field(
        None, description="CompCor type: 'anat', 'temp', 'combined'"
    )
    n_compcor: int = Field(default=5, description="Number of CompCor components")
    high_pass: float = Field(default=0.01, description="High-pass filter cutoff")
    low_pass: float | None = Field(None, description="Low-pass filter cutoff")
    t_r: float | None = Field(None, description="TR in seconds")
    scrub_threshold: float = Field(
        default=0.5, description="FD threshold for scrubbing"
    )
    output_file: str | None = Field(None, description="Save cleaned image")
    save_confounds: str | None = Field(None, description="Save selected confounds")


class ConfoundsCleanTool(NeuroToolWrapper):
    """Remove confounds from fMRI data."""

    name = "clean_confounds"
    description = "Comprehensive confound removal with motion, CompCor, scrubbing, and filtering strategies"
    category = "preprocessing"

    ARG_SYNONYMS = {
        "strategy": ["cleaning_strategy", "confound_strategy", "pipeline"],
        "motion_params": ["motion", "movement", "realignment_params"],
        "wm_csf": ["white_matter_csf", "tissue_signals"],
        "global_signal": ["global", "gs", "global_mean"],
    }

    EXAMPLES = [
        ToolExample(
            user_query="Clean fMRI with minimal preprocessing",
            params={
                "img": "sub-01_bold.nii.gz",
                "confounds": "sub-01_confounds.tsv",
                "strategy": "minimal",
                "high_pass": 0.008,
                "t_r": 2.0,
            },
            notes="Minimal cleaning strategy",
        ),
        ToolExample(
            user_query="Apply CompCor and scrubbing",
            params={
                "img": "bold.nii.gz",
                "confounds": "confounds.tsv",
                "compcor": "anat",
                "n_compcor": 10,
                "scrub_threshold": 0.3,
                "motion_params": True,
            },
            notes="Advanced cleaning with aCompCor",
        ),
    ]

    args_model = ConfoundsCleanArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> dict[str, Any]:
        return self._invoke(**kwargs)

    def _invoke(self, **kwargs) -> dict[str, Any]:
        """Clean confounds from fMRI data."""
        import nibabel as nib
        import pandas as pd
        from nilearn.image import clean_img, load_img

        args = ConfoundsCleanArgs(**kwargs)

        # Load confounds
        confounds_df = pd.read_csv(args.confounds, sep="\t")

        # Select confounds based on strategy
        selected_confounds = []

        if isinstance(args.strategy, str):
            if args.strategy == "minimal":
                # Basic motion parameters
                motion_cols = [
                    c
                    for c in confounds_df.columns
                    if any(x in c for x in ["trans", "rot"])
                ]
                selected_confounds.extend(motion_cols[:6])  # Basic 6 params

            elif args.strategy == "motion":
                # Motion + derivatives
                motion_cols = [
                    c
                    for c in confounds_df.columns
                    if any(x in c for x in ["trans", "rot"])
                ]
                selected_confounds.extend(motion_cols)

            elif args.strategy == "compcor":
                # CompCor components
                if args.compcor == "anat":
                    compcor_cols = [
                        c for c in confounds_df.columns if "a_comp_cor" in c.lower()
                    ]
                elif args.compcor == "temp":
                    compcor_cols = [
                        c for c in confounds_df.columns if "t_comp_cor" in c.lower()
                    ]
                else:
                    compcor_cols = [
                        c for c in confounds_df.columns if "comp_cor" in c.lower()
                    ]
                selected_confounds.extend(compcor_cols[: args.n_compcor])

        else:
            # Custom list of patterns
            for pattern in args.strategy:
                cols = [c for c in confounds_df.columns if pattern in c]
                selected_confounds.extend(cols)

        # Add additional confounds
        if args.motion_params:
            motion_cols = [
                c for c in confounds_df.columns if any(x in c for x in ["trans", "rot"])
            ]
            selected_confounds.extend(
                [c for c in motion_cols if c not in selected_confounds]
            )

        if args.wm_csf:
            tissue_cols = [
                c
                for c in confounds_df.columns
                if any(x in c.lower() for x in ["white_matter", "csf", "wm", "cerebro"])
            ]
            selected_confounds.extend(
                [c for c in tissue_cols if c not in selected_confounds]
            )

        if args.global_signal:
            global_cols = [c for c in confounds_df.columns if "global" in c.lower()]
            selected_confounds.extend(
                [c for c in global_cols if c not in selected_confounds]
            )

        # Keep confound selection order stable for reproducible runs and logs.
        selected_confounds = list(dict.fromkeys(selected_confounds))
        selected_confounds_df = None
        sanitized_confounds = []
        n_sanitized_values = 0
        confounds_array = None
        if selected_confounds:
            selected_confounds_df = confounds_df[selected_confounds].apply(
                pd.to_numeric, errors="coerce"
            )
            invalid_mask = ~np.isfinite(
                selected_confounds_df.to_numpy(dtype=float, copy=False)
            )
            n_sanitized_values = int(invalid_mask.sum())
            if n_sanitized_values:
                sanitized_confounds = selected_confounds_df.columns[
                    invalid_mask.any(axis=0)
                ].tolist()
                logger.warning(
                    "Sanitizing %s non-finite confound values across %s columns",
                    n_sanitized_values,
                    len(sanitized_confounds),
                )
                selected_confounds_df = selected_confounds_df.replace(
                    [np.inf, -np.inf], np.nan
                ).fillna(0.0)
            confounds_array = selected_confounds_df.to_numpy(dtype=float, copy=False)
            if not np.isfinite(confounds_array).all():
                raise ValueError(
                    "Selected confounds still contain NaN/Inf after sanitation"
                )

        # Clean image
        img = load_img(args.img)
        t_r = args.t_r
        if t_r is None and (args.high_pass is not None or args.low_pass is not None):
            zooms = img.header.get_zooms()
            if len(zooms) > 3:
                t_r = float(zooms[3])
        cleaned_img = clean_img(
            img,
            confounds=confounds_array,
            high_pass=args.high_pass,
            low_pass=args.low_pass,
            t_r=t_r,
            standardize="zscore_sample",
            clean__standardize_confounds=False,
            detrend=True,
        )

        # Apply scrubbing if requested
        if args.scrub_threshold and "framewise_displacement" in confounds_df.columns:
            fd = confounds_df["framewise_displacement"].values
            fd[np.isnan(fd)] = 0
            good_volumes = fd < args.scrub_threshold

            if good_volumes.sum() < len(fd):
                # Extract good volumes
                data = cleaned_img.get_fdata()
                data_scrubbed = data[..., good_volumes]
                cleaned_img = nib.Nifti1Image(
                    data_scrubbed, cleaned_img.affine, cleaned_img.header
                )
                logger.info(f"Scrubbed {(~good_volumes).sum()} volumes")

        # Save outputs
        if args.output_file:
            cleaned_img.to_filename(args.output_file)

        if args.save_confounds and selected_confounds_df is not None:
            selected_confounds_df.to_csv(args.save_confounds, sep="\t", index=False)

        return {
            "status": "success",
            "n_confounds": len(selected_confounds),
            "confounds_used": selected_confounds,
            "n_sanitized_values": n_sanitized_values,
            "sanitized_confounds": sanitized_confounds,
            "output_file": args.output_file,
        }


# =============================================================================
# Tool Registration
# =============================================================================


def register_preprocessing_tools(registry):
    """Register all preprocessing tools."""
    tools = [
        NiftiMaskerTool(),
        ROIExtractionTool(),
        ConfoundsCleanTool(),
    ]

    for tool in tools:
        registry.register_tool(tool)
        logger.info(f"Registered preprocessing tool: {tool.name}")

    return len(tools)
