"""Python test shim for the Web UI AdvancedVisualizationControls module.

The real AdvancedVisualizationControls component is implemented in TypeScript
(`AdvancedVisualizationControls.tsx`). Some Python unit tests patch the Niivue
symbol at this import path to avoid importing browser-only code.
"""

from __future__ import annotations


class Niivue:  # pragma: no cover
    """Placeholder class for test-time patching."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
        raise RuntimeError("Niivue is browser-only; this is a Python test shim.")

