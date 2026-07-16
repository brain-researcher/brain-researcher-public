"""Pinned-source contract for the public Neurosynth version-7 snapshot.

This module deliberately uses only the Python standard library so download,
conversion, ingestion, and reproducibility checks can share one provenance
contract without importing NiMARE or network clients.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "209c33cd009d0b069398a802198b41b9c488b9b7"
DATASET_VERSION = "0.7"
SOURCE_SNAPSHOT = "version-7"
BASE_URL = (
    f"https://raw.githubusercontent.com/neurosynth/neurosynth-data/{SOURCE_COMMIT}/"
)
LICENSE_SPDX = "ODbL-1.0"
LICENSE_URL = BASE_URL + "LICENSE.txt"
MANIFEST_FILENAME = "source_manifest.json"
CONVERTED_PROVENANCE_SUFFIX = ".provenance.json"

COORDINATES_FILENAME = "data-neurosynth_version-7_coordinates.tsv.gz"
METADATA_FILENAME = "data-neurosynth_version-7_metadata.tsv.gz"
FEATURES_FILENAME = (
    "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz"
)
VOCABULARY_FILENAME = "data-neurosynth_version-7_vocab-terms_vocabulary.txt"

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "neurosynth_nimare" / "neurosynth_v7"
DEFAULT_DATASET_PICKLE = (
    REPO_ROOT / "data" / "neurosynth_nimare" / "neurosynth_dataset_v7.pkl"
)


class NeurosynthSourceError(ValueError):
    """Raised when a local Neurosynth bundle does not match the pinned source."""


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
        COORDINATES_FILENAME,
        3_587_167,
        "17135be3e08a0ab045896c77217e8463086543a0817d52a6a88c8e32c1161616",
    ),
    SourceFile(
        METADATA_FILENAME,
        1_175_486,
        "8acde7de2a14ee2a12b406e50a8805e83288b0bc78924ddb36879d496dfb757b",
    ),
    SourceFile(
        FEATURES_FILENAME,
        9_896_293,
        "1b3359eebcbc8557340583788b3855031ea21361e87c265cb8fc540d9b6c4edd",
    ),
    SourceFile(
        VOCABULARY_FILENAME,
        33_799,
        "71c1858c5eb1bcc79854198bbca234569731efdc382c6205a9e46495379614af",
    ),
)


def build_source_manifest(
    source_files: tuple[SourceFile, ...] = SOURCE_FILES,
) -> dict[str, Any]:
    """Build the exact manifest accepted for a pinned source bundle."""
    return {
        "schema_version": "brain-researcher.neurosynth-source-manifest.v1",
        "dataset": "Neurosynth",
        "source_snapshot": SOURCE_SNAPSHOT,
        "source_commit": SOURCE_COMMIT,
        "base_url": BASE_URL,
        "license": {"spdx": LICENSE_SPDX, "url": LICENSE_URL},
        "output_directory": ".",
        "files": [{**asdict(spec), "url": spec.url} for spec in source_files],
    }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for ``path`` without loading it into memory."""
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
    actual_hash = sha256_file(path)
    if actual_hash != spec.sha256:
        return False, f"sha256 {actual_hash} != {spec.sha256}"
    return True, "verified"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NeurosynthSourceError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def verify_source_bundle(
    source_dir: str | Path,
    *,
    source_files: tuple[SourceFile, ...] = SOURCE_FILES,
) -> dict[str, Any]:
    """Verify the exact manifest plus every pinned file in ``source_dir``.

    A directory with the right filenames but no matching manifest is not an
    authoritative bundle. Extra or stale manifest fields also fail closed.
    """
    directory = Path(source_dir).expanduser().resolve()
    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise NeurosynthSourceError(
            f"missing Neurosynth source manifest: {manifest_path}; run "
            "python scripts/data/download_neurosynth_data.py"
        )
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except NeurosynthSourceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NeurosynthSourceError(
            f"invalid Neurosynth source manifest {manifest_path}: {exc}"
        ) from exc

    expected = build_source_manifest(source_files)
    if manifest != expected:
        raise NeurosynthSourceError(
            f"Neurosynth source manifest does not match the pinned {SOURCE_SNAPSHOT} "
            f"contract at commit {SOURCE_COMMIT}: {manifest_path}"
        )

    for spec in source_files:
        valid, reason = verify_file(directory / spec.filename, spec)
        if not valid:
            raise NeurosynthSourceError(
                f"Neurosynth source file {spec.filename} failed verification: {reason}"
            )
    return manifest


def converted_provenance_path(dataset_path: str | Path) -> Path:
    """Return the sidecar path for a converted NiMARE dataset pickle."""
    path = Path(dataset_path).expanduser().resolve()
    return path.with_name(path.name + CONVERTED_PROVENANCE_SUFFIX)


def build_converted_dataset_provenance(
    dataset_path: str | Path,
    source_dir: str | Path,
    *,
    source_files: tuple[SourceFile, ...] = SOURCE_FILES,
) -> dict[str, Any]:
    """Build clone-independent provenance binding a pickle to its raw bundle."""
    artifact = Path(dataset_path).expanduser().resolve()
    if not artifact.is_file() or artifact.stat().st_size <= 0:
        raise NeurosynthSourceError(
            f"missing or empty converted Neurosynth dataset: {artifact}"
        )
    directory = Path(source_dir).expanduser().resolve()
    manifest = verify_source_bundle(directory, source_files=source_files)
    manifest_path = directory / MANIFEST_FILENAME
    return {
        "schema_version": "brain-researcher.neurosynth-converted-provenance.v1",
        "dataset": "Neurosynth",
        "source_snapshot": manifest["source_snapshot"],
        "source_commit": manifest["source_commit"],
        "source_manifest": {
            "filename": MANIFEST_FILENAME,
            "sha256": sha256_file(manifest_path),
        },
        "artifact": {
            "filename": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
    }


def publish_converted_dataset_provenance(
    dataset_path: str | Path,
    source_dir: str | Path,
    *,
    source_files: tuple[SourceFile, ...] = SOURCE_FILES,
) -> Path:
    """Atomically publish the provenance sidecar for a converted dataset."""
    sidecar = converted_provenance_path(dataset_path)
    partial = sidecar.with_name(sidecar.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        payload = build_converted_dataset_provenance(
            dataset_path, source_dir, source_files=source_files
        )
        partial.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(partial, sidecar)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return sidecar


def verify_converted_dataset(
    dataset_path: str | Path,
    source_dir: str | Path,
    *,
    source_files: tuple[SourceFile, ...] = SOURCE_FILES,
) -> dict[str, Any]:
    """Verify a converted pickle and its exact binding to a verified raw bundle."""
    artifact = Path(dataset_path).expanduser().resolve()
    sidecar = converted_provenance_path(artifact)
    if not sidecar.is_file():
        raise NeurosynthSourceError(
            f"missing Neurosynth converted-dataset provenance: {sidecar}; run "
            "python scripts/data/convert_neurosynth.py"
        )
    try:
        actual = json.loads(
            sidecar.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except NeurosynthSourceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NeurosynthSourceError(
            f"invalid Neurosynth converted-dataset provenance {sidecar}: {exc}"
        ) from exc
    expected = build_converted_dataset_provenance(
        artifact, source_dir, source_files=source_files
    )
    if actual != expected:
        raise NeurosynthSourceError(
            f"Neurosynth converted dataset or source binding failed verification: "
            f"{sidecar}"
        )
    return actual


__all__ = [
    "BASE_URL",
    "COORDINATES_FILENAME",
    "CONVERTED_PROVENANCE_SUFFIX",
    "DATASET_VERSION",
    "DEFAULT_DATASET_PICKLE",
    "DEFAULT_SOURCE_DIR",
    "FEATURES_FILENAME",
    "LICENSE_SPDX",
    "LICENSE_URL",
    "MANIFEST_FILENAME",
    "METADATA_FILENAME",
    "NeurosynthSourceError",
    "REPO_ROOT",
    "SOURCE_COMMIT",
    "SOURCE_FILES",
    "SOURCE_SNAPSHOT",
    "SourceFile",
    "VOCABULARY_FILENAME",
    "build_source_manifest",
    "build_converted_dataset_provenance",
    "converted_provenance_path",
    "publish_converted_dataset_provenance",
    "sha256_file",
    "verify_file",
    "verify_converted_dataset",
    "verify_source_bundle",
]
