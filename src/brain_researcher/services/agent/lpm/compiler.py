"""
LPM operation compiler - maps canonical ops to backend tools.

This module implements the core LPM compilation logic, which:
1. Parses and validates canonical operation parameters
2. Selects an appropriate backend (based on availability and preferences)
3. Compiles the operation to backend-specific parameters
4. Returns a CompiledOp with tool, params, and container image
"""

from __future__ import annotations

import logging
from typing import Any

from ..tool_catalog_loader import load_niwrap_containers
from .adapters import compile_smooth_afni, compile_smooth_fsl, compile_smooth_fsl_masked
from .specs import CompiledOp, SmoothParams

logger = logging.getLogger(__name__)


def compile_op(
    op_name: str,
    params: dict[str, Any],
    preferred: str | None = None,
) -> CompiledOp:
    """
    Compile a canonical operation to a backend-specific tool.

    This is the main entry point for LPM compilation. It:
    1. Validates the operation name and parameters
    2. Determines backend availability and preference
    3. Compiles to the best available backend
    4. Returns a CompiledOp with full execution details

    Args:
        op_name: Operation name (currently only "smooth" is supported)
        params: Canonical parameters for the operation
        preferred: Preferred backend (e.g., "afni", "fsl")

    Returns:
        CompiledOp with tool, params, container image, and explanation

    Raises:
        ValueError: If operation is unsupported or params are invalid
        RuntimeError: If no backend is available for the operation

    Example:
        >>> result = compile_op("smooth", {
        ...     "fwhm_mm": 6.0,
        ...     "input": "/data/brain.nii.gz",
        ...     "output": "/data/smoothed.nii.gz",
        ... })
        >>> print(result.tool)  # "afni.3dBlurInMask"
    """
    if op_name != "smooth":
        raise ValueError(
            f"Unsupported operation: {op_name}. Only 'smooth' is currently supported."
        )

    # Parse and validate parameters
    try:
        smooth_params = SmoothParams(**params)
    except Exception as e:
        raise ValueError(f"Invalid parameters for smooth operation: {e}") from e

    # Determine backend order based on preference
    backends = _determine_backend_order(preferred, smooth_params)

    # Load available containers
    containers = load_niwrap_containers()

    # Try each backend in order
    errors = []
    for backend in backends:
        try:
            compiled = _compile_smooth_backend(backend, smooth_params, containers)
            if compiled:
                logger.info(f"LPM compiled smooth to {backend}: {compiled.why}")
                return compiled
        except Exception as e:
            logger.debug(f"Backend {backend} failed: {e}")
            errors.append((backend, str(e)))

    # No backend succeeded
    error_msg = "No backend available for smooth operation. Tried: " + ", ".join(
        f"{backend} ({error})" for backend, error in errors
    )
    raise RuntimeError(error_msg)


def _determine_backend_order(preferred: str | None, params: SmoothParams) -> list[str]:
    """
    Determine the order in which to try backends.

    Logic:
    1. If preferred is specified and valid, try it first
    2. If mask is provided, prefer AFNI (native mask support)
    3. Otherwise, default order: AFNI, FSL

    Args:
        preferred: User-specified preferred backend
        params: Operation parameters (may influence order)

    Returns:
        List of backend names in priority order
    """
    # All available backends for smooth
    all_backends = ["afni", "fsl"]

    # If preferred specified, prioritize it
    if preferred and preferred in all_backends:
        backends = [preferred] + [b for b in all_backends if b != preferred]
    elif params.mask:
        # If mask provided, prefer AFNI (better mask support)
        backends = ["afni", "fsl"]
    else:
        # Default order
        backends = ["afni", "fsl"]

    return backends


def _compile_smooth_backend(
    backend: str, params: SmoothParams, containers: dict[str, Any]
) -> CompiledOp | None:
    """
    Compile smooth operation for a specific backend.

    Args:
        backend: Backend name ("afni" or "fsl")
        params: Canonical smooth parameters
        containers: Available container configurations

    Returns:
        CompiledOp if successful, None if backend not available

    Raises:
        ValueError: If backend is unknown
    """
    if backend == "afni":
        return _compile_smooth_afni(params, containers)
    elif backend == "fsl":
        return _compile_smooth_fsl(params, containers)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _compile_smooth_afni(
    params: SmoothParams, containers: dict[str, Any]
) -> CompiledOp | None:
    """Compile smooth operation for AFNI backend."""
    # Check if AFNI container is available
    if "afni" not in containers:
        logger.debug("AFNI container not available")
        return None

    container_info = containers["afni"]
    if not isinstance(container_info, dict) or "image" not in container_info:
        logger.debug("AFNI container info invalid")
        return None

    # Compile using AFNI adapter
    compiled = compile_smooth_afni(params)

    # Build explanation
    fwhm = params.to_fwhm()
    why = f"AFNI 3dBlurInMask (FWHM={fwhm:.2f}mm"
    if params.mask:
        why += ", with mask support"
    why += ")"

    return CompiledOp(
        tool="afni.3dBlurInMask",
        params=compiled["params"],
        container_image=container_info["image"],
        backend="afni",
        why=why,
        canonical_params=params.model_dump(),
        executable=compiled.get("executable"),
        multi_step=compiled.get("multi_step", False),
        steps=compiled.get("steps"),
    )


def _compile_smooth_fsl(
    params: SmoothParams, containers: dict[str, Any]
) -> CompiledOp | None:
    """Compile smooth operation for FSL backend."""
    # Check if FSL container is available
    if "fsl" not in containers:
        logger.debug("FSL container not available")
        return None

    container_info = containers["fsl"]
    if not isinstance(container_info, dict) or "image" not in container_info:
        logger.debug("FSL container info invalid")
        return None

    # Compile using FSL adapter
    # Use masked version if mask is provided
    if params.mask:
        compiled = compile_smooth_fsl_masked(params)
    else:
        compiled = compile_smooth_fsl(params)

    # Build explanation
    sigma = params.to_sigma()
    why = f"FSL fslmaths (sigma={sigma:.2f}mm"
    if params.mask:
        why += ", two-step with masking"
    why += ")"

    return CompiledOp(
        tool="fsl.fslmaths",
        params=compiled["params"],
        container_image=container_info["image"],
        backend="fsl",
        why=why,
        canonical_params=params.model_dump(),
        executable=compiled.get("executable"),
        multi_step=compiled.get("multi_step", False),
        steps=compiled.get("steps"),
    )


__all__ = ["compile_op"]
