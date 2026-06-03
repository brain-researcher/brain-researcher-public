"""
LPM (Language of Processing Methods) - Canonical operator specifications.

This module provides an abstraction layer for neuroimaging operations,
allowing users to specify operations in a tool-agnostic way. The LPM
compiler then selects the appropriate backend (AFNI, FSL, etc.) and
translates parameters accordingly.

Example:
    >>> from brain_researcher.services.agent.lpm import compile_op
    >>> compiled = compile_op("smooth", {"fwhm_mm": 6.0, "input": "brain.nii.gz", "output": "smoothed.nii.gz"})
    >>> print(compiled.tool)  # "afni.3dBlurInMask" or "fsl.fslmaths"
"""

from .compiler import compile_op
from .specs import SmoothParams, CompiledOp

__all__ = ["compile_op", "SmoothParams", "CompiledOp"]
