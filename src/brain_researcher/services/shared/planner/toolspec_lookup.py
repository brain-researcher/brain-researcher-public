"""Dependency-inversion seam for tool-spec metadata used by planner handoff.

``services/shared`` is the lowest layer and must not import ``services/tools``.
Instead, the tools layer registers a lookup at import time (see
``services.tools.lookup_registry``) and ``shared/planner/handoff`` consumes it
through :func:`get_toolspec_lookup`. When no lookup is registered (e.g. a context
where the tools layer was never imported), handoff falls back to conservative
defaults, preserving the previous best-effort behaviour.

This breaks the ``shared -> tools`` back-edge (handoff no longer imports the
heavy ``tools.catalog_loader``).
"""

from __future__ import annotations

from collections.abc import Callable

# Given a tool_id, return (allowed_phases, approval_level) for a known spec, or
# None when no spec is available.
ToolSpecLookup = Callable[[str], tuple[list[str], str] | None]

_toolspec_lookup: ToolSpecLookup | None = None


def register_toolspec_lookup(lookup: ToolSpecLookup) -> None:
    """Register the tool-spec lookup (called by the tools layer at import)."""

    global _toolspec_lookup
    _toolspec_lookup = lookup


def get_toolspec_lookup() -> ToolSpecLookup | None:
    """Return the registered tool-spec lookup, or None if none is registered."""

    return _toolspec_lookup
