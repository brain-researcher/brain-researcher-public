"""Marimo-aware display helpers for the Brain Researcher SDK.

Each function detects whether ``marimo`` is importable and renders
accordingly.  In non-Marimo environments (plain Python, Jupyter) the
functions fall back to matplotlib / plain ``DataFrame`` / pass-through.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HAS_MARIMO = importlib.util.find_spec("marimo") is not None


def nifti(path: str | Path, **plot_kwargs: Any) -> Any:
    """Render a NIfTI volume as an inline image.

    Uses ``nilearn.plotting.plot_anat`` (static matplotlib) and wraps the
    result in ``mo.as_html()`` when running inside Marimo.
    """
    path = str(path)
    try:
        from nilearn import plotting  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("nilearn not installed — returning path string")
        return path

    fig = plotting.plot_anat(path, **plot_kwargs)

    if _HAS_MARIMO:
        try:
            import marimo as mo  # type: ignore[import-untyped]

            return mo.as_html(fig)
        except Exception:
            pass
    return fig


def table(data: Any, **kwargs: Any) -> Any:
    """Render tabular data.

    *data* can be a list of dicts, a ``pandas.DataFrame``, or anything
    ``mo.ui.table()`` accepts.  Falls back to a plain ``DataFrame``.
    """
    if _HAS_MARIMO:
        try:
            import marimo as mo  # type: ignore[import-untyped]

            return mo.ui.table(data, **kwargs)
        except Exception:
            pass

    try:
        import pandas as pd  # type: ignore[import-untyped]

        if isinstance(data, pd.DataFrame):
            return data
        return pd.DataFrame(data)
    except ImportError:
        return data


def plot(fig: Any) -> Any:
    """Pass-through for matplotlib / plotly figures.

    Marimo renders these natively so no wrapping is needed.
    """
    return fig
