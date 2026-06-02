"""Internal utilities for ingestion module."""

import subprocess
from collections.abc import Callable


def tool(func: Callable) -> Callable:
    """Simple tool decorator for backward compatibility."""
    # For now, just return the function as-is
    # In the future, this could add logging, metrics, etc.
    return func


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)
