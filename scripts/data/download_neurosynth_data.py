#!/usr/bin/env python3.11
"""Download and verify the pinned public Neurosynth v0.7 source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

SOURCE_COMMIT = "209c33cd009d0b069398a802198b41b9c488b9b7"
DATASET_VERSION = "0.7"
BASE_URL = (
    "https://raw.githubusercontent.com/neurosynth/neurosynth-data/" f"{SOURCE_COMMIT}/"
)
LICENSE_SPDX = "ODbL-1.0"
LICENSE_URL = BASE_URL + "LICENSE.txt"
MANIFEST_FILENAME = "source_manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_DIR = REPO_ROOT / "data" / "neurosynth_nimare" / "neurosynth_v7"


@dataclass(frozen=True)
class SourceFile:
    filename: str
    size_bytes: int
    sha256: str

    @property
    def url(self) -> str:
        return BASE_URL + self.filename


SOURCE_FILES = (
    SourceFile(
        "data-neurosynth_version-7_coordinates.tsv.gz",
        3_587_167,
        "17135be3e08a0ab045896c77217e8463086543a0817d52a6a88c8e32c1161616",
    ),
    SourceFile(
        "data-neurosynth_version-7_metadata.tsv.gz",
        1_175_486,
        "8acde7de2a14ee2a12b406e50a8805e83288b0bc78924ddb36879d496dfb757b",
    ),
    SourceFile(
        "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz",
        9_896_293,
        "1b3359eebcbc8557340583788b3855031ea21361e87c265cb8fc540d9b6c4edd",
    ),
    SourceFile(
        "data-neurosynth_version-7_vocab-terms_vocabulary.txt",
        33_799,
        "71c1858c5eb1bcc79854198bbca234569731efdc382c6205a9e46495379614af",
    ),
)


def source_manifest() -> dict[str, Any]:
    """Return deterministic provenance for the only supported source bundle."""
    return {
        "schema_version": "brain-researcher.neurosynth-source-manifest.v1",
        "dataset": "Neurosynth",
        "release_version": DATASET_VERSION,
        "source_commit": SOURCE_COMMIT,
        "base_url": BASE_URL,
        "license": {
            "spdx": LICENSE_SPDX,
            "url": LICENSE_URL,
        },
        "output_directory": ".",
        "files": [
            {
                **asdict(spec),
                "url": spec.url,
            }
            for spec in SOURCE_FILES
        ],
    }


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, spec: SourceFile) -> tuple[bool, str]:
    """Verify both expected byte size and SHA-256 for one source asset."""
    if not path.is_file():
        return False, "missing"
    actual_size = path.stat().st_size
    if actual_size != spec.size_bytes:
        return False, f"size {actual_size} != {spec.size_bytes}"
    actual_hash = _sha256(path)
    if actual_hash != spec.sha256:
        return False, f"sha256 {actual_hash} != {spec.sha256}"
    return True, "verified"


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
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # A manifest is valid only when every current file passes both checks.
        # Remove prior provenance before verification so a failed run cannot
        # leave a stale success record behind.
        manifest_path.unlink(missing_ok=True)
        partial_manifest_path.unlink(missing_ok=True)
        for spec in SOURCE_FILES:
            if args.check_only:
                valid, reason = verify_file(target_dir / spec.filename, spec)
                if not valid:
                    raise ValueError(f"{spec.filename} failed verification: {reason}")
                outcome = "verified existing file"
            else:
                outcome = ensure_file(spec, target_dir)
            print(f"{spec.filename}: {outcome}")
        write_manifest(target_dir)
    except Exception as exc:
        manifest_path.unlink(missing_ok=True)
        partial_manifest_path.unlink(missing_ok=True)
        print(f"Neurosynth download failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Verified Neurosynth v{DATASET_VERSION} source commit {SOURCE_COMMIT} "
        f"under {LICENSE_SPDX} in {target_dir}"
    )
    print(f"Source manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
