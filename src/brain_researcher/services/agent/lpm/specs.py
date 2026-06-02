"""
Canonical operation specifications for LPM.

This module defines the canonical parameter schemas for neuroimaging operations.
Each operation has a specification that is tool-agnostic and can be compiled
to different backends (AFNI, FSL, ANTs, etc.).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SmoothParams(BaseModel):
    """
    Canonical parameters for smoothing/blurring operations.

    Smoothing can be specified using either FWHM (Full Width at Half Maximum)
    or sigma. The relationship is: FWHM = sigma * 2.3548 (where 2.3548 = sqrt(8*ln(2))).

    Attributes:
        fwhm_mm: Full Width at Half Maximum in millimeters
        sigma_mm: Gaussian kernel standard deviation in millimeters
        mask: Optional mask file to restrict smoothing
        input: Input file path
        output: Output file path
    """

    fwhm_mm: Optional[float] = Field(None, gt=0, description="FWHM in mm")
    sigma_mm: Optional[float] = Field(None, gt=0, description="Sigma in mm")
    mask: Optional[str] = Field(None, description="Mask file path")
    input: str = Field(..., description="Input file path")
    output: str = Field(..., description="Output file path")

    @model_validator(mode="after")
    def validate_smoothing_params(self) -> "SmoothParams":
        """Ensure exactly one of FWHM or sigma is provided."""
        has_fwhm = self.fwhm_mm is not None
        has_sigma = self.sigma_mm is not None

        if not (has_fwhm or has_sigma):
            raise ValueError("Must provide either fwhm_mm or sigma_mm")

        if has_fwhm and has_sigma:
            # Both provided - verify consistency
            computed_sigma = self.fwhm_mm / 2.3548
            if abs(computed_sigma - self.sigma_mm) > 0.01:
                raise ValueError(
                    f"Inconsistent FWHM ({self.fwhm_mm}) and sigma ({self.sigma_mm}). "
                    f"FWHM implies sigma={computed_sigma:.3f}"
                )

        return self

    def to_fwhm(self) -> float:
        """
        Convert to FWHM.

        Returns:
            FWHM in millimeters
        """
        if self.fwhm_mm is not None:
            return self.fwhm_mm
        return self.sigma_mm * 2.3548  # sqrt(8*ln(2))

    def to_sigma(self) -> float:
        """
        Convert to sigma.

        Returns:
            Sigma in millimeters
        """
        if self.sigma_mm is not None:
            return self.sigma_mm
        return self.fwhm_mm / 2.3548


class CompiledOp(BaseModel):
    """
    Result of compiling a canonical operation to a specific backend.

    Attributes:
        tool: Tool identifier (e.g., "afni.3dBlurInMask", "fsl.fslmaths")
        params: Backend-specific parameters
        container_image: Path to container image
        backend: Backend name (e.g., "afni", "fsl")
        why: Human-readable explanation of tool selection
        canonical_params: Original canonical parameters for reference
    """

    tool: str = Field(..., description="Tool identifier")
    params: Dict[str, Any] = Field(..., description="Backend-specific parameters")
    container_image: Optional[str] = Field(None, description="Container image path")
    backend: str = Field(..., description="Backend name")
    why: str = Field(default="", description="Selection explanation")
    canonical_params: Optional[Dict[str, Any]] = Field(
        None, description="Original canonical parameters"
    )
    executable: Optional[str] = Field(
        None, description="Backend executable used to perform the operation"
    )
    multi_step: bool = Field(
        default=False,
        description="Whether the backend execution requires multiple sequential steps",
    )
    steps: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Execution steps (if multi_step is true)",
    )


__all__ = ["SmoothParams", "CompiledOp"]
