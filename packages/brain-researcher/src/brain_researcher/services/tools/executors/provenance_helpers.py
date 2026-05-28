"""Best-effort provenance helpers for RunRecorder.

These helpers gather extended provenance information (git, host, container, file metadata)
in a fast, graceful way that doesn't block or fail if information is unavailable.

Following Codex recommendations:
- Fast operations only (< 2s timeouts)
- Graceful fallbacks (return {} or partial data)
- No sensitive information (no CPU serials, etc.)
- Lightweight for CVMFS (no tree walks)

Moved from: services/toolhub/common/provenance_helpers.py
"""

from __future__ import annotations

import platform
import socket
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any


def get_git_metadata(root: Path | None = None) -> dict[str, Any]:
    """Get git metadata (HEAD sha + dirty flag) with best-effort.

    Args:
        root: Repository root directory. If None, uses current working directory.

    Returns:
        Dict with git_head, git_dirty, git_branch (if available).
        Returns empty dict if not a git repo or on error.

    Performance: < 500ms typical, 2s timeout
    """
    if root is None:
        root = Path.cwd()

    try:
        # Check if .git exists
        if not (root / ".git").exists():
            return {}

        # Get HEAD sha
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return {}

        sha = result.stdout.strip()

        # Check if working tree is dirty
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        dirty = bool(result.stdout.strip()) if result.returncode == 0 else None

        # Try to get current branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        branch = result.stdout.strip() if result.returncode == 0 else None

        metadata = {
            "git_head": sha,
            "git_dirty": dirty,
        }
        if branch and branch != "HEAD":
            metadata["git_branch"] = branch

        return metadata

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return {}


def get_host_metadata() -> dict[str, Any]:
    """Get host metadata (no sensitive information).

    Returns:
        Dict with hostname, os, os_version, python_version, architecture.

    Performance: < 10ms
    """
    try:
        return {
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "os_version": platform.release(),
            "python_version": platform.python_version(),
            "architecture": platform.machine(),
            "platform": platform.platform(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_container_fingerprint(image_path: Path | str) -> dict[str, Any]:
    """Get container fingerprint (lightweight for CVMFS).

    For files (.sif): Returns path + mtime + size
    For directories (CVMFS): Returns path + type only (no tree walk)

    Args:
        image_path: Path to container image or directory

    Returns:
        Dict with path, type, size, mtime (for files)

    Performance: < 50ms for files, < 1ms for directories
    """
    try:
        if isinstance(image_path, str):
            image_path = Path(image_path)

        if not image_path.exists():
            return {
                "path": str(image_path),
                "status": "missing",
            }

        stat = image_path.stat()

        # For files (e.g., .sif images)
        if image_path.is_file():
            return {
                "path": str(image_path),
                "type": "file",
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }

        # For directories (e.g., CVMFS unpacked containers)
        # Don't walk tree - it's expensive on CVMFS
        if image_path.is_dir():
            return {
                "path": str(image_path),
                "type": "directory",
                "note": "CVMFS directory - no tree walk performed for performance",
            }

        return {
            "path": str(image_path),
            "status": "unknown_type",
        }

    except (OSError, PermissionError) as e:
        return {
            "path": str(image_path),
            "error": f"access_denied: {str(e)}",
        }
    except Exception as e:
        return {
            "path": str(image_path),
            "error": str(e),
        }


def get_file_fingerprint(
    file_path: Path | str,
    max_hash_mb: int = 128,
) -> dict[str, Any]:
    """Get file fingerprint (hash only if < max_hash_mb).

    For small files: Returns path + size + mtime + sha256
    For large files: Returns path + size + mtime only (no hash)

    Args:
        file_path: Path to file
        max_hash_mb: Maximum file size in MB to compute hash (default: 128MB)

    Returns:
        Dict with path, size, mtime, and optionally sha256

    Performance:
        < 100ms for files < 10MB
        < 1s for files < 128MB
        < 1ms for large files (no hash)
    """
    try:
        if isinstance(file_path, str):
            file_path = Path(file_path)

        if not file_path.exists():
            return {
                "path": str(file_path),
                "status": "missing",
            }

        stat = file_path.stat()
        max_bytes = max_hash_mb * 1024 * 1024

        fingerprint = {
            "path": str(file_path),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }

        # Only hash small files
        if stat.st_size <= max_bytes:
            try:
                content = file_path.read_bytes()
                fingerprint["sha256"] = sha256(content).hexdigest()
            except (OSError, MemoryError):
                fingerprint["sha256_error"] = "failed_to_read"
        else:
            fingerprint["sha256_skipped"] = f"file_too_large_>{max_hash_mb}MB"

        return fingerprint

    except (OSError, PermissionError) as e:
        return {
            "path": str(file_path),
            "error": f"access_denied: {str(e)}",
        }
    except Exception as e:
        return {
            "path": str(file_path),
            "error": str(e),
        }


def get_inputs_fingerprints(
    inputs: dict[str, Any],
    max_hash_mb: int = 128,
) -> dict[str, dict[str, Any]]:
    """Get fingerprints for multiple input files/values.

    Args:
        inputs: Dict of input parameters (may contain file paths or other values)
        max_hash_mb: Maximum file size in MB to compute hash

    Returns:
        Dict mapping input names to their fingerprints

    Performance: Depends on number and size of inputs
    """
    fingerprints = {}

    for key, value in inputs.items():
        # Try to interpret as file path
        try:
            path = Path(str(value))
            if path.exists() and path.is_file():
                fingerprints[key] = get_file_fingerprint(path, max_hash_mb)
            else:
                # Not a file, just record the value
                fingerprints[key] = {
                    "type": "value",
                    "value": str(value)[:200],  # Truncate long values
                }
        except Exception:
            # Invalid path or other error, record as value
            fingerprints[key] = {
                "type": "value",
                "value": str(value)[:200],
            }

    return fingerprints


# Schema version for provenance documents
# 1.0.0: Initial version with git, host, container, file fingerprints
# 1.1.0: Added pipeline executor support with multi-stage nesting
# 1.2.0: Added inputs_fingerprints and input_dataset_manifests (BIDS linkage)
PROVENANCE_SCHEMA_VERSION = "1.2.0"
