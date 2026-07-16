#!/usr/bin/env python3.11
"""[supported-public] Download and verify pinned Neurosynth version-7 files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from brain_researcher.core.datasets import neurosynth_source as source_contract
from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_SOURCE_DIR,
    LICENSE_SPDX,
    MANIFEST_FILENAME,
    SOURCE_COMMIT,
    SOURCE_FILES,
    SOURCE_SNAPSHOT,
    SourceFile,
    build_source_manifest,
    sha256_file,
    verify_file,
    verify_source_bundle,
)

BASE_URL = source_contract.BASE_URL
LICENSE_URL = source_contract.LICENSE_URL
TARGET_DIR = DEFAULT_SOURCE_DIR
DOWNLOAD_STATUS = "supported-public"


def source_manifest() -> dict[str, Any]:
    """Return deterministic provenance for the only supported source bundle."""
    return build_source_manifest(SOURCE_FILES)


def write_manifest(target_dir: Path) -> Path:
    """Publish the source manifest atomically after every asset verifies."""
    manifest_path = target_dir / MANIFEST_FILENAME
    partial_path = manifest_path.with_name(manifest_path.name + ".part")
    partial_path.unlink(missing_ok=True)
    try:
        partial_path.write_text(
            json.dumps(source_manifest(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(partial_path, manifest_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return manifest_path


_sha256 = sha256_file


def download_file(
    spec: SourceFile,
    target_path: Path,
    *,
    request_get: Callable[..., Any] = requests.get,
) -> None:
    """Download to a temporary file, verify it, then publish atomically."""
    partial_path = target_path.with_name(target_path.name + ".part")
    partial_path.unlink(missing_ok=True)
    response = None
    try:
        response = request_get(spec.url, stream=True, timeout=30)
        response.raise_for_status()
        with partial_path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    stream.write(chunk)
        valid, reason = verify_file(partial_path, spec)
        if not valid:
            raise ValueError(f"downloaded file failed verification: {reason}")
        os.replace(partial_path, target_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    finally:
        if response is not None:
            response.close()


def ensure_file(
    spec: SourceFile,
    target_dir: Path,
    *,
    request_get: Callable[..., Any] = requests.get,
) -> str:
    """Reuse only a verified file; otherwise replace it with a verified download."""
    target_path = target_dir / spec.filename
    valid, reason = verify_file(target_path, spec)
    if valid:
        return "verified existing file"
    if target_path.exists():
        target_path.unlink()
    download_file(spec, target_path, request_get=request_get)
    valid, reason = verify_file(target_path, spec)
    if not valid:
        target_path.unlink(missing_ok=True)
        raise ValueError(f"published file failed verification: {reason}")
    return "downloaded and verified"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=TARGET_DIR,
        help="Destination for the four pinned Neurosynth files.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify the pinned files without making network requests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target_dir = args.target_dir.expanduser().resolve()
    manifest_path = target_dir / MANIFEST_FILENAME
    partial_manifest_path = manifest_path.with_name(manifest_path.name + ".part")
    if args.check_only:
        try:
            verify_source_bundle(target_dir, source_files=SOURCE_FILES)
            for spec in SOURCE_FILES:
                print(f"{spec.filename}: verified existing file")
        except Exception as exc:
            print(f"Neurosynth verification failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"Verified Neurosynth {SOURCE_SNAPSHOT} source commit {SOURCE_COMMIT} "
            f"under {LICENSE_SPDX} in {target_dir}"
        )
        print(f"Source manifest: {manifest_path}")
        return 0

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # A manifest is valid only when every current file passes both checks.
        # Remove prior provenance before verification so a failed run cannot
        # leave a stale success record behind.
        manifest_path.unlink(missing_ok=True)
        partial_manifest_path.unlink(missing_ok=True)
        for spec in SOURCE_FILES:
            outcome = ensure_file(spec, target_dir)
            print(f"{spec.filename}: {outcome}")
        write_manifest(target_dir)
    except Exception as exc:
        manifest_path.unlink(missing_ok=True)
        partial_manifest_path.unlink(missing_ok=True)
        print(f"Neurosynth download failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Verified Neurosynth {SOURCE_SNAPSHOT} source commit {SOURCE_COMMIT} "
        f"under {LICENSE_SPDX} in {target_dir}"
    )
    print(f"Source manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
