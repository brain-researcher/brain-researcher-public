"""Compatibility re-export for the shared failure-mode registry."""

from brain_researcher.services.shared.failure_mode_registry import (
    DEFAULT_REGISTRY_PATH,
    FailureModeRegistry,
    FailureModeRule,
    load_failure_mode_registry,
    render_failure_mode_registry_markdown,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "FailureModeRegistry",
    "FailureModeRule",
    "load_failure_mode_registry",
    "render_failure_mode_registry_markdown",
]
