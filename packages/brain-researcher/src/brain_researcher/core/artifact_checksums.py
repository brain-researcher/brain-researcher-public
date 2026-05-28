"""Artifact checksum helpers.

This module provides a single place to compute per-artifact checksums for
run outputs. The primary consumer is the canonical `observation.json`, but the
helpers are also safe to use from MCP metadata endpoints.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


def _max_hash_mb() -> int:
    raw = os.getenv("BR_ARTIFACT_SHA256_MAX_MB", "128").strip()
    try:
        value = int(raw)
    except ValueError:
        return 128
    return max(0, value)


def compute_file_sha256(
    path: Path,
    *,
    max_hash_mb: int | None = None,
    chunk_bytes: int = 1024 * 1024,
) -> tuple[str | None, str, str | None]:
    """Compute a SHA256 digest for `path` (streaming), with an optional size cap.

    Returns: (hexdigest|None, status, reason|None)
      - status: "ok" | "missing" | "skipped" | "error"
    """
    try:
        if not path.exists():
            return None, "missing", "file_not_found"
        if not path.is_file():
            return None, "error", "not_a_file"

        stat = path.stat()
        limit_mb = _max_hash_mb() if max_hash_mb is None else max_hash_mb
        if limit_mb > 0 and stat.st_size > limit_mb * 1024 * 1024:
            return None, "skipped", f"file_too_large_>{limit_mb}MB"

        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(chunk_bytes), b""):
                hasher.update(chunk)
        return hasher.hexdigest(), "ok", None
    except Exception as exc:  # pragma: no cover - best effort
        return None, "error", str(exc)


def _resolve_artifact_path(
    artifact: dict[str, Any], run_dir: Path
) -> tuple[Path | None, str | None]:
    raw_path = artifact.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        try:
            resolved = candidate.resolve()
            run_root = run_dir.resolve()
            if not resolved.is_relative_to(run_root):
                return None, "path_outside_run_dir"
            return resolved, None
        except Exception:
            return None, "path_resolution_failed"

    name = artifact.get("name")
    if isinstance(name, str) and name.strip():
        candidate = run_dir / name
        try:
            resolved = candidate.resolve()
            run_root = run_dir.resolve()
            if not resolved.is_relative_to(run_root):
                return None, "path_outside_run_dir"
            return resolved, None
        except Exception:
            return None, "path_resolution_failed"

    return None, "no_local_path"


def fill_artifact_checksums(
    artifacts: list[dict[str, Any]],
    *,
    run_dir: Path,
    max_hash_mb: int | None = None,
) -> list[dict[str, Any]]:
    """Fill `checksum` for artifacts with local files under `run_dir`.

    Mutates the artifact dicts in place and returns them for convenience.
    """
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue

        checksum = artifact.get("checksum")
        if isinstance(checksum, str) and checksum.startswith("sha256:"):
            artifact.setdefault("checksum_status", "ok")
            artifact.setdefault("checksum_reason", None)
            continue

        path, reason = _resolve_artifact_path(artifact, run_dir)
        if path is None:
            artifact.setdefault("checksum_status", "skipped")
            artifact.setdefault("checksum_reason", reason or "no_local_path")
            continue

        hexdigest, status, reason = compute_file_sha256(path, max_hash_mb=max_hash_mb)
        if hexdigest:
            artifact["checksum"] = f"sha256:{hexdigest}"
        artifact["checksum_status"] = status
        if reason:
            artifact["checksum_reason"] = reason

    # Ensure every artifact has a status, even if path/checksum missing
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if "checksum_status" not in artifact:
            artifact["checksum_status"] = "skipped"
            artifact.setdefault("checksum_reason", "not_computed")

    return artifacts


__all__ = ["compute_file_sha256", "fill_artifact_checksums"]
