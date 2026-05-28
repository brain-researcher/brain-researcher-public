"""Grandmaster (intent-based) tool surface.

This package provides YAML-driven wrappers that expose a curated set of
high-level tool IDs (the "Grandmaster" toolset) without requiring one Python
class per tool.
"""

from brain_researcher.services.tools.grandmaster.loader import (
    register_grandmaster_tools,
)

__all__ = ["register_grandmaster_tools"]

