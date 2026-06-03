"""
Backend adapters for LPM canonical operations.

This module provides adapters that translate canonical operation specifications
into backend-specific tool invocations. Each adapter handles parameter conversion,
command construction, and backend-specific quirks.
"""

from __future__ import annotations

from typing import Any

from .specs import SmoothParams


def compile_smooth_afni(params: SmoothParams) -> dict[str, Any]:
    """
    Compile smooth operation for AFNI's 3dBlurInMask.

    AFNI Command:
        3dBlurInMask -FWHM <fwhm> -input <input> -prefix <output> [-mask <mask>]

    Features:
        - Uses FWHM directly (no conversion needed)
        - Supports masking natively
        - Handles 3D and 4D datasets

    Args:
        params: Canonical smooth parameters

    Returns:
        Dictionary with executable, args, and params
    """
    fwhm = params.to_fwhm()

    args: list[str] = [
        "-FWHM",
        f"{fwhm:.4f}",
        "-input",
        params.input,
        "-prefix",
        params.output,
    ]

    cmd_params = {
        "FWHM": fwhm,
        "input": params.input,
        "prefix": params.output,
    }

    # Add mask if provided
    if params.mask:
        args.extend(["-mask", params.mask])
        cmd_params["mask"] = params.mask

    return {
        "executable": "3dBlurInMask",
        "args": args,
        "params": cmd_params,
    }


def compile_smooth_fsl(params: SmoothParams) -> dict[str, Any]:
    """
    Compile smooth operation for FSL's fslmaths.

    FSL Command:
        fslmaths <input> -s <sigma> <output>

    Features:
        - Uses sigma (not FWHM) - conversion performed automatically
        - Does NOT support masking natively in the smooth operation
        - Mask must be applied separately if needed

    Note:
        If a mask is provided, the operation should be:
        1. fslmaths <input> -mas <mask> <temp>
        2. fslmaths <temp> -s <sigma> <output>

    Args:
        params: Canonical smooth parameters

    Returns:
        Dictionary with executable, args, and params
    """
    sigma = params.to_sigma()

    args: list[str] = [params.input, "-s", f"{sigma:.5f}", params.output]

    cmd_params = {
        "input": params.input,
        "sigma": sigma,
        "output": params.output,
    }

    # Note about masking limitation
    if params.mask:
        cmd_params["_note"] = (
            "FSL fslmaths smooth doesn't support masking directly. "
            "To apply mask, use: fslmaths input -mas mask temp && "
            "fslmaths temp -s sigma output"
        )
        cmd_params["mask"] = params.mask
        cmd_params["requires_preprocessing"] = True

    return {
        "executable": "fslmaths",
        "args": args,
        "params": cmd_params,
    }


def compile_smooth_fsl_masked(params: SmoothParams) -> dict[str, Any]:
    """
    Compile smooth operation for FSL with masking support.

    This creates a two-step process:
    1. Apply mask: fslmaths <input> -mas <mask> <temp>
    2. Smooth: fslmaths <temp> -s <sigma> <output>

    Args:
        params: Canonical smooth parameters (must include mask)

    Returns:
        Dictionary with multi-step command specification
    """
    if not params.mask:
        raise ValueError("compile_smooth_fsl_masked requires a mask")

    sigma = params.to_sigma()
    temp_file = f"{params.output}_temp.nii.gz"

    return {
        "executable": "fslmaths",
        "multi_step": True,
        "steps": [
            {
                "name": "apply_mask",
                "args": [params.input, "-mas", params.mask, temp_file],
            },
            {
                "name": "smooth",
                "args": [temp_file, "-s", f"{sigma:.5f}", params.output],
            },
        ],
        "params": {
            "input": params.input,
            "mask": params.mask,
            "sigma": sigma,
            "output": params.output,
            "temp_file": temp_file,
        },
    }


__all__ = [
    "compile_smooth_afni",
    "compile_smooth_fsl",
    "compile_smooth_fsl_masked",
]
