"""Compatibility shim for parameter helpers now hosted in ``services.shared``."""

from __future__ import annotations

from brain_researcher.services.shared.param_norm import (
    as_str_list,
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)

__all__ = ["enum_str", "coerce_enum", "as_str_list", "resolve_enum_or_error"]
