"""
GraphQL layer for BR-KG.

This package exposes `build_schema()` which returns a Strawberry `Schema`.
The import of Strawberry is deferred to runtime so other parts of the
application can import this package without requiring the dependency.
"""

from __future__ import annotations

from typing import Any


def build_schema() -> Any:
    from .schema import build_schema as _build

    return _build()
