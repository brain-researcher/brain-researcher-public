"""API version constants shared across services."""

from __future__ import annotations

from typing import MutableMapping

API_VERSION = "v1"
API_VERSION_HEADER = "X-API-Version"


def set_api_version(headers: MutableMapping[str, str]) -> None:
    """Set the canonical API version header."""
    headers[API_VERSION_HEADER] = API_VERSION


__all__ = ["API_VERSION", "API_VERSION_HEADER", "set_api_version"]
