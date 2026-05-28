"""Shared utilities for code tools.

Provides common helpers without pulling heavy dependencies.
"""

from __future__ import annotations

from pathlib import Path


def validate_path(path: Path, repo_root: Path) -> bool:
    """Ensure path is under repo_root (no escape via ../etc).

    This is the canonical path validation function used by all code tools
    to prevent path traversal attacks.

    Args:
        path: The path to validate (can be relative or absolute)
        repo_root: The repository root that paths must stay within

    Returns:
        True if path is safely under repo_root, False otherwise

    Examples:
        >>> validate_path(Path("/repo/src/file.py"), Path("/repo"))
        True
        >>> validate_path(Path("/repo/../etc/passwd"), Path("/repo"))
        False
        >>> validate_path(Path("../outside"), Path("/repo"))
        False
    """
    try:
        resolved = path.resolve()
        root_resolved = repo_root.resolve()
        return resolved.is_relative_to(root_resolved)
    except (ValueError, RuntimeError):
        return False


__all__ = ["validate_path"]
