"""Stable namespace: HTTP client wrappers."""

from brain_researcher.cli.utils.http_client import (
    api_get_sync,
    api_post_sync,
    format_http_error,
    get_orchestrator_url,
)

__all__ = [
    "api_get_sync",
    "api_post_sync",
    "format_http_error",
    "get_orchestrator_url",
]
