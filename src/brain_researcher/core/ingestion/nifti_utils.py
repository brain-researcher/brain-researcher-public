from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._utils import tool

logger = logging.getLogger(__name__)


@tool
def load_nifti(path: str) -> Any:
    """Load a NIfTI file."""
    try:
        import nibabel as nib
    except Exception as e:
        raise NotImplementedError("nibabel required") from e
    return nib.load(Path(path).resolve().as_posix())


@tool
def save_nifti(img: Any, path: str) -> str:
    """Save a NIfTI file."""
    try:
        import nibabel as nib
    except Exception as e:
        raise NotImplementedError("nibabel required") from e
    nib.save(img, Path(path).resolve().as_posix())
    return Path(path).resolve().as_posix()


@tool
def nifti_header(path: str) -> dict[str, Any]:
    """Get NIfTI header."""
    try:
        import nibabel as nib
    except Exception as e:
        raise NotImplementedError("nibabel required") from e
    img = nib.load(Path(path).resolve().as_posix())
    return dict(img.header)


@tool
def nifti_to_png(path: str, out_png: str, slice_index: int | None = None) -> str:
    """Convert NIfTI to PNG."""
    try:
        import nibabel as nib
        import numpy as np
        from PIL import Image
    except Exception as e:
        raise NotImplementedError("nibabel and pillow required") from e
    img = nib.load(Path(path).resolve().as_posix())
    data = img.get_fdata()
    if slice_index is None:
        slice_index = data.shape[2] // 2
    slice_img = data[:, :, slice_index]
    slice_norm = (slice_img - np.min(slice_img)) / (np.ptp(slice_img) or 1)
    png = Image.fromarray((slice_norm * 255).astype("uint8"))
    png.save(Path(out_png).resolve().as_posix())
    return Path(out_png).resolve().as_posix()
