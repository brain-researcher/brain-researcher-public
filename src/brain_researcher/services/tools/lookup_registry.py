"""Register the tools-layer tool-spec lookup with the shared planner seam.

Breaks the ``services/shared -> services/tools`` back-edge: instead of
``shared/planner/handoff`` importing the heavy ``tools.catalog_loader``, the
tools layer pushes a lookup *down* to ``shared`` at import time. The catalog
load itself stays lazy (inside :func:`_lookup`), so registration is cheap.
"""

from __future__ import annotations


def _lookup(tool_id: str) -> tuple[list[str], str] | None:
    from brain_researcher.services.tools.catalog_loader import get_toolspec_by_name

    spec = get_toolspec_by_name(tool_id)
    if spec is None:
        return None
    return list(spec.allowed_phases or []), str(spec.approval_level or "none")


def register_tools_lookup() -> None:
    """Register :func:`_lookup` as the shared planner tool-spec lookup."""

    from brain_researcher.services.shared.planner.toolspec_lookup import (
        register_toolspec_lookup,
    )

    register_toolspec_lookup(_lookup)
