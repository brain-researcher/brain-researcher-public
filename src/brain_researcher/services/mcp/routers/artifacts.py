"""Run-artifact access MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the
``artifact_list`` / ``artifact_read_text`` / ``artifact_get_metadata`` /
``artifact_read_bytes`` tools on the shared FastMCP instance via the
``@mcp.tool()`` decorator (an import side effect), so ``server.py`` imports
it for its effect.

The shared FastMCP instance, the ``_find_run_dir`` run-store helper, and the
``MAX_TEXT_BYTES`` / ``MAX_BINARY_BYTES`` limits are imported back from
``server`` rather than duplicated (they are used by other domains too).
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from typing import Any

from brain_researcher.services.mcp.server import (
    MAX_BINARY_BYTES,
    MAX_TEXT_BYTES,
    _find_run_dir,
    mcp,
)


@mcp.tool()
def artifact_list(run_id: str) -> dict[str, Any]:
    """List files under the run's artifacts directory."""
    try:
        run_dir = _find_run_dir(run_id)
        artifacts_dir = run_dir / "artifacts"
        if not artifacts_dir.exists():
            return {"ok": True, "items": []}
        items = []
        for p in sorted(artifacts_dir.rglob("*")):
            if p.is_dir():
                continue
            rel = str(p.relative_to(run_dir))
            items.append(
                {
                    "relpath": rel,
                    "size_bytes": p.stat().st_size,
                }
            )
        return {"ok": True, "items": items}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def artifact_read_text(
    run_id: str, relpath: str, max_bytes: int = 200000
) -> dict[str, Any]:
    """Read a small text artifact from a run (logs/json/tsv)."""
    try:
        run_dir = _find_run_dir(run_id)
        target = (run_dir / relpath).resolve()
        if not str(target).startswith(str(run_dir.resolve()) + os.sep):
            return {"ok": False, "error": "path_not_allowed"}
        limit = max(1, min(int(max_bytes), MAX_TEXT_BYTES))
        data = target.read_bytes()[:limit]
        return {"ok": True, "text": data.decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def artifact_get_metadata(
    run_id: str, relpath: str, include_sha256: bool = False
) -> dict[str, Any]:
    """Get metadata for an artifact/log file under a run."""
    try:
        run_dir = _find_run_dir(run_id)
        target = (run_dir / relpath).resolve()
        if not str(target).startswith(str(run_dir.resolve()) + os.sep):
            return {"ok": False, "error": "path_not_allowed"}
        stat = target.stat()
        sha256 = None
        sha256_status = None
        sha256_reason = None
        checksum = None
        if include_sha256:
            from brain_researcher.core.artifact_checksums import compute_file_sha256

            hexdigest, status, reason = compute_file_sha256(target)
            sha256_status = status
            sha256_reason = reason
            if status == "ok" and hexdigest:
                sha256 = hexdigest
                checksum = f"sha256:{hexdigest}"
        return {
            "ok": True,
            "metadata": {
                "relpath": relpath,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                "sha256": sha256,
                "sha256_status": sha256_status,
                "sha256_reason": sha256_reason,
                "checksum": checksum,
            },
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def artifact_read_bytes(
    run_id: str,
    relpath: str,
    max_bytes: int = 2000000,
    offset: int = 0,
    start: int | None = None,
    end: int | None = None,
) -> dict[str, Any]:
    """Read a small binary artifact from a run (base64-encoded)."""
    try:
        run_dir = _find_run_dir(run_id)
        target = (run_dir / relpath).resolve()
        if not str(target).startswith(str(run_dir.resolve()) + os.sep):
            return {"ok": False, "error": "path_not_allowed"}
        range_start = offset if start is None else start
        range_start = max(0, int(range_start))
        if end is not None:
            range_end = int(end)
            if range_end < range_start:
                return {"ok": False, "error": "invalid_range"}
            limit = max(0, range_end - range_start)
        else:
            range_end = None
            limit = int(max_bytes)
        limit = max(1, min(limit, MAX_BINARY_BYTES))
        with target.open("rb") as f:
            if range_start:
                f.seek(range_start)
            data = f.read(limit)
        truncated = False
        if range_end is None:
            try:
                file_size = target.stat().st_size
                truncated = range_start + len(data) < file_size and len(data) >= limit
            except Exception:
                truncated = len(data) >= limit
        return {
            "ok": True,
            "encoding": "base64",
            "offset": range_start,
            "truncated": truncated,
            "bytes": base64.b64encode(data).decode("ascii"),
            "range": {"start": range_start, "end": range_start + len(data)},
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
