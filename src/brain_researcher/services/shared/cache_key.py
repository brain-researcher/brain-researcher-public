"""Cache key computation for deterministic result caching.

This module provides cache key computation with three modes:
- fast: Metadata-based (path + mtime + size) - default, very fast
- secure: First 1MB hash + size - good balance
- paranoid: Full file hash - slowest but most deterministic

The cache key captures:
- Tool name and version
- Canonical parameters (sorted)
- Input file fingerprints (based on mode)
- Container image fingerprint
- Git HEAD SHA (if available)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from brain_researcher.services.shared.provenance_helpers import (
    get_container_fingerprint,
    get_file_fingerprint,
    get_git_metadata,
)


def build_cache_key(
    tool: str,
    tool_version: str | None,
    canonical_params: dict[str, Any],
    input_paths: list[str],
    container_image: str,
    git_sha: str | None = None,
    mode: str | None = None,
) -> str:
    """Build deterministic cache key from tool execution parameters.

    Args:
        tool: Tool name (e.g., "fsl.bet", "afni.3dSkullStrip")
        tool_version: Tool version string (e.g., "6.0.7")
        canonical_params: Canonical parameters dict (will be sorted for determinism)
        input_paths: List of input file paths to fingerprint
        container_image: Path to container image
        git_sha: Optional git SHA (auto-detected if None)
        mode: Fingerprinting mode - "fast", "secure", or "paranoid".
              If None, falls back to BR_CACHE_MODE (default: fast).

    Returns:
        Cache key string in format "sha256:<hash>"

    Modes:
        fast: Metadata only (path + mtime + size) - ~1ms per file
        secure: First 1MB hash + size - ~50ms per file
        paranoid: Full file hash - seconds per GB

    Example:
        >>> key = build_cache_key(
        ...     tool="fsl.bet",
        ...     tool_version="6.0.7",
        ...     canonical_params={"f": 0.5, "input": "/data/brain.nii.gz"},
        ...     input_paths=["/data/brain.nii.gz"],
        ...     container_image="/cvmfs/fsl.simg",
        ...     mode="fast"
        ... )
        >>> key
        'sha256:a1b2c3...'
    """
    # Resolve mode: explicit argument wins; otherwise use environment (default fast)
    if mode is None:
        mode = os.getenv("BR_CACHE_MODE", "fast")

    # Validate mode
    if mode not in ("fast", "secure", "paranoid"):
        raise ValueError(
            f"Invalid cache mode: {mode}. Must be fast, secure, or paranoid"
        )

    # Build cache key components
    components = {
        "tool": tool,
        "tool_version": tool_version or "unknown",
        "params": _normalize_params(canonical_params),
        "inputs": _fingerprint_inputs(input_paths, mode),
        "container": get_container_fingerprint(container_image),
        "git_sha": git_sha or _get_git_sha(),
        "mode": mode,
    }

    # Serialize to deterministic JSON (sorted keys)
    serialized = json.dumps(components, sort_keys=True, ensure_ascii=False)

    # Hash the serialized components
    cache_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    return f"sha256:{cache_hash}"


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize parameters for deterministic comparison.

    - Sorts dict keys
    - Converts numeric values to canonical form
    - Handles nested dicts/lists

    Args:
        params: Raw parameters dict

    Returns:
        Normalized parameters dict
    """
    if not isinstance(params, dict):
        return params

    normalized = {}
    for key in sorted(params.keys()):
        value = params[key]

        # Recursively normalize nested dicts
        if isinstance(value, dict):
            normalized[key] = _normalize_params(value)
        # Sort lists of dicts
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                normalized[key] = [_normalize_params(item) for item in value]
            else:
                normalized[key] = value
        # Normalize floats to consistent precision
        elif isinstance(value, float):
            normalized[key] = round(value, 6)
        else:
            normalized[key] = value

    return normalized


def _fingerprint_inputs(
    input_paths: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Generate fingerprints for input files based on mode.

    Args:
        input_paths: List of file paths to fingerprint
        mode: Fingerprinting mode (fast, secure, paranoid)

    Returns:
        List of fingerprint dicts (one per input)
    """
    fingerprints = []

    for path_str in input_paths:
        path = Path(path_str)

        if not path.exists():
            # File doesn't exist - record as missing
            fingerprints.append(
                {
                    "path": str(path),
                    "status": "missing",
                }
            )
            continue

        if mode == "fast":
            # Fast mode: metadata only (no hashing)
            fingerprints.append(_fast_fingerprint(path))

        elif mode == "secure":
            # Secure mode: hash first 1MB + metadata
            fingerprints.append(_secure_fingerprint(path))

        elif mode == "paranoid":
            # Paranoid mode: full file hash
            fingerprints.append(_paranoid_fingerprint(path))

    return fingerprints


def _fast_fingerprint(path: Path) -> dict[str, Any]:
    """Fast fingerprint using metadata only.

    Returns:
        Dict with path, size, mtime (no hash)
    """
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "mode": "fast",
        }
    except (OSError, PermissionError) as e:
        return {
            "path": str(path),
            "error": str(e),
        }


def _secure_fingerprint(path: Path) -> dict[str, Any]:
    """Secure fingerprint using first 1MB hash + size.

    Good balance between speed and determinism.

    Returns:
        Dict with path, size, mtime, partial_hash
    """
    try:
        stat = path.stat()
        fingerprint = {
            "path": str(path),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "mode": "secure",
        }

        # Hash first 1MB
        chunk_size = 1024 * 1024  # 1MB
        hasher = hashlib.sha256()

        with path.open("rb") as f:
            chunk = f.read(chunk_size)
            hasher.update(chunk)

        fingerprint["partial_hash"] = hasher.hexdigest()[:16]  # First 16 chars

        return fingerprint

    except (OSError, PermissionError, MemoryError) as e:
        return {
            "path": str(path),
            "error": str(e),
        }


def _paranoid_fingerprint(path: Path) -> dict[str, Any]:
    """Paranoid fingerprint using full file hash.

    Slowest but most deterministic. Use for critical workloads.

    Returns:
        Dict with path, size, sha256
    """
    try:
        stat = path.stat()

        # Use provenance helper for full hash (with 128MB default limit)
        # For larger files, it will skip hash
        file_fp = get_file_fingerprint(path, max_hash_mb=128)

        return {
            "path": str(path),
            "size": stat.st_size,
            "sha256": file_fp.get("sha256", "skipped"),
            "mode": "paranoid",
        }

    except Exception as e:
        return {
            "path": str(path),
            "error": str(e),
        }


def _get_git_sha() -> str | None:
    """Get current git SHA (best-effort).

    Returns:
        Git SHA string or None if not available
    """
    git_metadata = get_git_metadata()
    return git_metadata.get("git_head")


def compute_cache_key_for_job(job: dict[str, Any]) -> str:
    """Convenience function to compute cache key from job dict.

    Args:
        job: Job dict with metadata, parameters, etc.

    Returns:
        Cache key string

    Example:
        >>> job = {
        ...     "metadata": {"tool": "fsl.bet", "tool_version": "6.0.7"},
        ...     "parameters": {"f": 0.5, "input": "/data/brain.nii.gz"},
        ...     "container_image": "/cvmfs/fsl.simg",
        ... }
        >>> compute_cache_key_for_job(job)
        'sha256:...'
    """
    metadata = job.get("metadata", {})
    parameters = job.get("parameters", {})

    # Extract tool and version
    tool = metadata.get("tool") or parameters.get("tool", "unknown")
    tool_version = metadata.get("tool_version")

    # Extract input paths (heuristic: look for common input param names)
    input_paths = []
    for key in ["input", "inputs", "in_file", "source", "image"]:
        if key in parameters:
            value = parameters[key]
            if isinstance(value, str):
                input_paths.append(value)
            elif isinstance(value, list):
                input_paths.extend([v for v in value if isinstance(v, str)])

    # Extract container image
    container_image = job.get("container_image") or metadata.get("container_image", "")

    # Get git SHA from metadata if available
    git_sha = metadata.get("git_sha")

    return build_cache_key(
        tool=tool,
        tool_version=tool_version,
        canonical_params=parameters,
        input_paths=input_paths,
        container_image=container_image,
        git_sha=git_sha,
    )
