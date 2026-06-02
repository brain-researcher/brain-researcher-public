"""Shared path validation helpers for service-layer callers."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_path(path: str, strict: bool = True) -> bool:
    """Validate path against traversal attacks and suspicious patterns."""

    if not path:
        raise ValueError("Empty path not allowed")

    if ".." in path:
        raise ValueError(f"Path contains '..' (directory traversal): {path}")

    if "\x00" in path:
        raise ValueError(f"Path contains null byte: {path}")

    if strict and path.startswith("/"):
        resolved = Path(path).expanduser().resolve(strict=False)
        cwd = Path.cwd().resolve()

        allowed_prefixes = [
            "/cvmfs",
            "/ref",
            "/data",
            "/tmp",
            "/var/tmp",
            "/outputs",
            "/inputs",
        ]

        if not any(
            str(resolved).startswith(prefix) for prefix in allowed_prefixes
        ) and not resolved.is_relative_to(cwd):
            raise ValueError(
                f"Absolute path outside allowed directories: {path}. "
                f"Allowed prefixes: {', '.join(allowed_prefixes)} "
                f"(or under cwd={cwd})"
            )

    suspicious_patterns = [
        "/etc/",
        "/root/",
        "/.ssh/",
        "/.aws/",
        "/proc/",
        "/sys/",
    ]

    for pattern in suspicious_patterns:
        if pattern in path:
            raise ValueError(f"Path contains suspicious pattern '{pattern}': {path}")

    logger.debug("Path validation passed: %s", path)
    return True


def validate_paths(paths: list[str], strict: bool = True) -> bool:
    """Validate multiple paths."""

    for path in paths:
        validate_path(path, strict=strict)
    return True


__all__ = ["validate_path", "validate_paths"]
