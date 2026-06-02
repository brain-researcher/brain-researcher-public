"""Shared atlas output-path helpers used by the br_kg layer.

This module gives lower layers (notably ``services/br_kg``) a layer-clean home
for the small atlas-path helper they need, without importing the heavy
``services/tools`` atlas machinery (which pulls in nibabel/numpy and sits above
br_kg in the layering order).

The canonical implementation lives in :mod:`brain_researcher.config.paths`;
this module simply re-exports it under the name historically used by callers
(``default_atlas_output_root``).  ``services/tools.atlas_utils`` keeps its own
identically-named wrapper, so tool-side callers are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from brain_researcher.config.paths import get_default_atlas_output_root

__all__ = ["default_atlas_output_root"]


def default_atlas_output_root() -> Path:
    """Return the default root directory for atlas outputs.

    Thin wrapper over
    :func:`brain_researcher.config.paths.get_default_atlas_output_root` kept
    here so br_kg modules can depend on a same-or-lower layer instead of
    ``services/tools``.
    """

    return get_default_atlas_output_root()
