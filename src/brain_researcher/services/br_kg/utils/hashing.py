from __future__ import annotations

import hashlib
from pathlib import Path


def sha1sum(path: Path) -> str:
    """Return SHA-1 checksum of a file."""
    return hashlib.sha1(path.read_bytes()).hexdigest()
