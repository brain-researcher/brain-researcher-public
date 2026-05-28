"""Compatibility exports for Gemini-safe tool schema generation."""

from __future__ import annotations

from brain_researcher.services.tools.tool_base import (  # noqa: F401
    _schema_for_type,
    generate_fixed_schema,
)

__all__ = ["_schema_for_type", "generate_fixed_schema"]
