from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from ._utils import tool

logger = logging.getLogger(__name__)

# Default BIDS dataset manifest schema version
BIDS_MANIFEST_SCHEMA_VERSION = "bids-dataset-manifest-v1"


def build_bids_dataset_manifest(
    bids_dir: Path | str,
    mode: Literal["fast", "secure", "paranoid"] = "fast",
    include_derivatives: bool = False,
    max_hash_mb: int | None = None,
) -> dict[str, Any]:
    """Build a BIDS dataset manifest with file hashes and metadata.

    Args:
        bids_dir: Path to BIDS dataset root
        mode: Hash strategy - "fast" (path+size only), "secure" (first 1MB SHA-256),
              "paranoid" (full SHA-256, cap with max_hash_mb)
        include_derivatives: Include derivatives/ directory
        max_hash_mb: For "paranoid" mode, cap files at this size (MB) before hashing

    Returns:
        Dict with manifest schema including:
        - schema_version: BIDS manifest schema version
        - manifest_sha256: SHA-256 of the manifest JSON (for dataset identity)
        - summary: {n_files, total_bytes, hash_mode}
        - config: {mode, include_derivatives, max_hash_mb}
        - files: list of {path, size, sha256, sha256_mode, sha256_bytes} entries
    """
    bids_root = Path(bids_dir).expanduser().resolve()
    if not bids_root.exists():
        raise FileNotFoundError(f"BIDS directory not found: {bids_root}")

    # Collect files
    files_data = []
    total_bytes = 0
    max_read_bytes = (max_hash_mb * 1024 * 1024) if max_hash_mb is not None else None

    for item in _iter_bids_files(bids_root, include_derivatives=include_derivatives):
        rel_path = item.relative_to(bids_root)
        file_size = item.stat().st_size
        total_bytes += file_size

        file_entry: dict[str, Any] = {
            "path": str(rel_path).replace("\\", "/"),
            "size": file_size,
        }

        if mode == "fast":
            file_entry.update(
                {"sha256": None, "sha256_mode": "none", "sha256_bytes": 0}
            )
        elif mode == "secure":
            prefix_bytes = 1024 * 1024
            digest = _hash_file_prefix(item, prefix_bytes=prefix_bytes)
            if digest == "<error>":
                file_entry.update(
                    {"sha256": None, "sha256_mode": "error", "sha256_bytes": 0}
                )
            else:
                file_entry.update(
                    {
                        "sha256": digest,
                        "sha256_mode": "prefix",
                        "sha256_bytes": min(file_size, prefix_bytes),
                    }
                )
        elif mode == "paranoid":
            digest = _hash_file_full(item, max_bytes=max_read_bytes)
            if digest == "<error>":
                file_entry.update(
                    {"sha256": None, "sha256_mode": "error", "sha256_bytes": 0}
                )
            else:
                capped = max_read_bytes is not None and file_size > max_read_bytes
                file_entry.update(
                    {
                        "sha256": digest,
                        "sha256_mode": "capped" if capped else "full",
                        "sha256_bytes": (
                            min(file_size, max_read_bytes) if capped else file_size
                        ),
                    }
                )
        else:
            raise ValueError(f"Invalid mode: {mode}")

        files_data.append(file_entry)

    files_data.sort(key=lambda x: x.get("path", ""))

    manifest = {
        "schema_version": BIDS_MANIFEST_SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "summary": {
            "n_files": len(files_data),
            "total_bytes": total_bytes,
            "hash_mode": mode,
        },
        "config": {
            "mode": mode,
            "include_derivatives": include_derivatives,
            "max_hash_mb": max_hash_mb,
        },
        "files": files_data,
    }

    # Compute manifest SHA-256 (for dataset identity checking)
    manifest_for_hash = {k: v for k, v in manifest.items() if k not in {"generated_at"}}
    manifest_json = json.dumps(
        manifest_for_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    manifest["manifest_sha256"] = hashlib.sha256(
        manifest_json.encode("utf-8")
    ).hexdigest()

    return manifest


def write_bids_dataset_manifest(
    bids_dir: Path | str,
    mode: Literal["fast", "secure", "paranoid"] = "fast",
    include_derivatives: bool = False,
    max_hash_mb: int | None = None,
) -> dict[str, Any]:
    """Build and write dataset_manifest.json to a BIDS dataset.

    Args:
        bids_dir: Path to BIDS dataset root
        mode: Hash strategy (see build_bids_dataset_manifest)
        include_derivatives: Include derivatives/ directory
        max_hash_mb: Cap file size for paranoid hashing

    Returns:
        The manifest dict (same as build_bids_dataset_manifest)
        with an additional "path" key pointing to the written file.
    """
    bids_root = Path(bids_dir).resolve()
    manifest = build_bids_dataset_manifest(
        bids_root,
        mode=mode,
        include_derivatives=include_derivatives,
        max_hash_mb=max_hash_mb,
    )

    out_path = bids_root / "dataset_manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(tmp_path, out_path)
    manifest["path"] = str(out_path)

    return manifest


def _iter_bids_files(bids_root: Path, include_derivatives: bool) -> list[Path]:
    """Iterate dataset files under bids_root (excluding VCS and optional derivatives)."""
    skip_dirnames = {".git", ".datalad", "__pycache__"}
    if not include_derivatives:
        skip_dirnames.add("derivatives")

    files: list[Path] = []
    for root, dirnames, filenames in os.walk(bids_root, followlinks=False):
        root_path = Path(root)
        rel_parts = root_path.relative_to(bids_root).parts

        # Prune directories early
        pruned = []
        for d in list(dirnames):
            if d in skip_dirnames:
                continue
            if d.startswith(".") and d not in {".bidsignore"}:
                continue
            pruned.append(d)
        dirnames[:] = pruned

        # Skip if we're already under a pruned directory (defensive)
        if any(part in skip_dirnames for part in rel_parts):
            continue
        if not include_derivatives and "derivatives" in rel_parts:
            continue

        for fname in filenames:
            if fname in {".DS_Store", "Thumbs.db"}:
                continue
            if fname == "dataset_manifest.json":
                continue
            if fname.startswith(".") and fname not in {".bidsignore"}:
                continue
            files.append(root_path / fname)

    return files


def _hash_file_prefix(path: Path, prefix_bytes: int = 1024 * 1024) -> str:
    """Hash the first N bytes of a file."""
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as f:
            chunk = f.read(prefix_bytes)
            hasher.update(chunk)
    except (OSError, PermissionError):
        return "<error>"
    return hasher.hexdigest()


def _hash_file_full(path: Path, max_bytes: int | None = None) -> str:
    """Hash a file, optionally capping at N bytes."""
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as f:
            if max_bytes:
                remaining = max_bytes
                while remaining > 0:
                    chunk = f.read(min(remaining, 65536))
                    if not chunk:
                        break
                    hasher.update(chunk)
                    remaining -= len(chunk)
            else:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
    except (OSError, PermissionError):
        return "<error>"
    return hasher.hexdigest()


def _iso_now() -> str:
    """Get current timestamp in ISO format."""
    from datetime import datetime

    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@tool
def load_bids_dataset(bids_dir: str) -> Any:
    """Load a BIDS dataset."""
    try:
        from bids.layout import BIDSLayout
    except Exception as e:
        raise NotImplementedError("pybids required") from e
    layout = BIDSLayout(Path(bids_dir).resolve().as_posix())
    return layout


@tool
def validate_bids_dataset(
    bids_dir: str, strict: bool = True, timeout_s: float = 30.0
) -> dict[str, Any]:
    """Validate a BIDS dataset."""
    cmd = ["bids-validator", "--json"]
    if not strict:
        cmd.append("--ignoreWarnings")
    cmd.append(Path(bids_dir).resolve().as_posix())
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        logger.warning("bids-validator not found; returning validation error")
        return {
            "is_valid": False,
            "errors": [{"reason": "bids-validator-not-found"}],
        }
    except subprocess.TimeoutExpired:
        logger.warning("bids-validator timed out after %.1fs", timeout_s)
        return {
            "is_valid": False,
            "errors": [{"reason": "bids-validator-timeout"}],
        }
    if proc.returncode != 0 and strict:
        logger.warning(
            "BIDS validation reported errors: %s", proc.stderr or proc.stdout
        )
    try:
        import json

        result = json.loads(proc.stdout or "{}")
    except Exception:
        result = {}
    return {
        "is_valid": result.get("valid", proc.returncode == 0),
        "errors": result.get("issues", []),
    }


@tool
def query_bids_files(
    layout: Any,
    suffix: str,
    subject: str | None = None,
    scope: str = "raw",
) -> list[str]:
    """Query BIDS files."""
    files = layout.get(suffix=suffix, subject=subject, scope=scope, return_type="file")
    return [Path(f).resolve().as_posix() for f in files]


@tool
def heudiconv_convert(dicom_dir: str, bids_dir: str, heuristic: str) -> dict[str, str]:
    """Convert DICOMs using HeuDiConv."""
    cmd = [
        "heudiconv",
        "-d",
        Path(dicom_dir).resolve().as_posix(),
        "-o",
        Path(bids_dir).resolve().as_posix(),
        "-f",
        heuristic,
        "-c",
        "dcm2niix",
        "-b",
    ]
    log = Path(tempfile.mkstemp(suffix=".log")[1]).resolve()
    with log.open("w") as lf:
        proc = subprocess.run(
            cmd, stdout=lf, stderr=subprocess.STDOUT, text=True, check=False
        )
    if proc.returncode != 0:
        raise RuntimeError(f"heudiconv failed: {log}")
    return {"log": log.as_posix(), "bids_dir": Path(bids_dir).resolve().as_posix()}
